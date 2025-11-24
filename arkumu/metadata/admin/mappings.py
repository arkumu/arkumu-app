import json
from typing import Dict, List, Optional

from django.contrib import admin, messages
from django.contrib.admin import SimpleListFilter
from django.db import transaction
from django.db.models import Count, Q
from django.http import HttpRequest, HttpResponse
from django.template.response import TemplateResponse
from django.shortcuts import redirect
from django.urls import path, reverse
from django.utils import timezone
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from django.utils.translation import gettext_lazy as _

from arkumu.metadata.models.mappings import Mapping, MappingSelectionAudit
from arkumu.metadata.tasks import (
    create_promoted_manifest_task,
    promote_legacy_junctions_task,
)
from arkumu.metadata.derivations.kreuz_config import (
    DerivationPattern,
    iter_applicable_patterns,
)
from arkumu.metadata.services.derived_relationship_service import DerivedRelationshipService
from arkumu.metadata.services.junction_pattern_service import JunctionPatternService


class ValidationStatusFilter(SimpleListFilter):
    """Filter mappings by validation status groups."""
    title = _('status group')
    parameter_name = 'status_group'
    
    def lookups(self, request, model_admin):
        return (
            ('ready', _('Ready to Execute')),
            ('not_ready', _('Not Ready')),
            ('recently_executed', _('Recently Executed')),
        )
    
    def queryset(self, request, queryset):
        if self.value() == 'ready':
            return queryset.filter(
                validation_status__in=['validated', 'active'],
                mapping_config__isnull=False,
                source_datasets__isnull=False
            )
        if self.value() == 'not_ready':
            return queryset.filter(
                Q(validation_status='draft') | 
                Q(mapping_config={}) | 
                Q(source_datasets=[])
            )
        if self.value() == 'recently_executed':
            # Executed in the last 7 days
            from datetime import timedelta
            cutoff = timezone.now() - timedelta(days=7)
            return queryset.filter(last_executed__gte=cutoff)
        return queryset


class HasExecutionStatsFilter(SimpleListFilter):
    """Filter mappings by whether they have execution statistics."""
    title = _('has execution stats')
    parameter_name = 'has_stats'
    
    def lookups(self, request, model_admin):
        return (
            ('yes', _('Has statistics')),
            ('no', _('No statistics')),
        )
    
    def queryset(self, request, queryset):
        if self.value() == 'yes':
            return queryset.exclude(execution_stats={})
        if self.value() == 'no':
            return queryset.filter(execution_stats={})
        return queryset


@admin.register(Mapping)
class MappingAdmin(admin.ModelAdmin):
    list_display = [
        'name',
        'id_display',
        'organization_link',
        'active_status_badge',
        'dataset_count_display',
        'column_count_display',
        'relationship_count_display',
        'promoted_manifest_status',
        'created_by_link',
        'created_at'
    ]
    
    list_filter = [
        'created_at',
        ('created_by', admin.RelatedOnlyFieldListFilter),
    ]
    
    search_fields = [
        'name',
        'description',
        'organization_id',
        'source_datasets',
    ]
    
    readonly_fields = [
        'id',
        'created_at',
        'updated_at',
        'dataset_count_display',
        'column_count_display',
        'relationship_count_display',
        'promoted_manifest_status',
        'mapping_preview',
        'schema_manifest_preview',
        'last_executed_display',
        'execution_stats_display',
        'junction_patterns_link',
    ]
    
    fieldsets = (
        (None, {
            'fields': ('name', 'description', 'organization_id', 'validation_status')
        }),
        (_('Source Configuration'), {
            'fields': ('source_datasets',),
            'description': 'List of datasets this mapping applies to.',
        }),
        (_('Mapping Configuration'), {
            'fields': ('mapping_config', 'mapping_preview', 'schema_manifest_preview'),
            'description': 'JSON configuration that defines the mapping rules.',
            'classes': ('wide',),
        }),
        (_('Execution Information'), {
            'fields': (
                'last_executed_display',
                'execution_stats',
                'execution_stats_display'
            ),
            'classes': ('collapse',),
        }),
        (_('Metadata'), {
            'fields': ('created_by', 'created_at', 'updated_at', 'id'),
            'classes': ('collapse',),
        }),
        (_('Statistics'), {
            'fields': (
                'dataset_count_display',
                'column_count_display',
                'relationship_count_display',
                'promoted_manifest_status',
            ),
            'classes': ('collapse',),
        }),
        (_('Derivation helpers'), {
            'fields': ('junction_patterns_link',),
        }),
    )

    def get_urls(self):
        urls = super().get_urls()
        custom = [
            path(
                '<path:object_id>/junction-patterns/',
                self.admin_site.admin_view(self.junction_patterns_view),
                name='metadata_mapping_junction_patterns',
            ),
        ]
        return custom + urls
    
    def get_queryset(self, request):
        """Optimize queries with select_related."""
        return super().get_queryset(request).select_related('created_by')
    
    def organization_link(self, obj):
        """Display organization as a link to organization admin."""
        if obj.organization_id:
            # Try to link to organization if it exists
            try:
                from arkumu.users.models import Organization
                org = Organization.objects.get(code=obj.organization_id)
                url = reverse('admin:users_organization_change', args=[org.pk])
                return format_html('<a href="{}">{}</a>', url, obj.organization_id)
            except:
                return obj.organization_id
        return '-'
    organization_link.short_description = _('Organization')
    organization_link.admin_order_field = 'organization_id'
    
    def validation_status_badge(self, obj):
        """Display validation status with color-coded badge."""
        colors = {
            'draft': '#6c757d',      # gray
            'validated': '#17a2b8',  # info blue
            'active': '#28a745',     # success green
        }
        color = colors.get(obj.validation_status, '#6c757d')
        
        icon = ''
        if obj.validation_status == 'active':
            icon = '✓ '
        elif obj.validation_status == 'validated':
            icon = '⚡ '
        
        return format_html(
            '<span style="background-color: {}; color: white; padding: 3px 8px; '
            'border-radius: 3px; font-size: 11px; font-weight: bold;">{}{}</span>',
            color,
            icon,
            obj.get_validation_status_display()
        )
    validation_status_badge.short_description = _('Status')
    validation_status_badge.admin_order_field = 'validation_status'

    def active_status_badge(self, obj):
        """Display whether the mapping is active for its organization."""
        if obj.is_active:
            return format_html(
                '<span style="background-color:#198754;color:white;padding:3px 8px;'
                'border-radius:3px;font-size:11px;font-weight:bold;">Active</span>'
            )
        return format_html(
            '<span style="background-color:#adb5bd;color:white;padding:3px 8px;'
            'border-radius:3px;font-size:11px;">Inactive</span>'
        )
    active_status_badge.short_description = _('Active?')
    active_status_badge.admin_order_field = 'is_active'
    
    def dataset_count_display(self, obj):
        """Display number of datasets."""
        count = obj.get_dataset_count()
        if count > 0:
            return format_html(
                '<span style="font-weight: bold;">{}</span> dataset{}',
                count,
                's' if count != 1 else ''
            )
        return format_html('<span style="color: #dc3545;">No datasets</span>')
    dataset_count_display.short_description = _('Datasets')
    
    def column_count_display(self, obj):
        """Display number of columns in workspace."""
        count = obj.get_column_count()
        return format_html(
            '<span style="font-weight: bold;">{}</span> column{}',
            count,
            's' if count != 1 else ''
        )
    column_count_display.short_description = _('Columns')
    
    def relationship_count_display(self, obj):
        """Display number of FK relationships."""
        count = obj.get_relationship_count()
        if count > 0:
            return format_html(
                '<span style="font-weight: bold; color: #17a2b8;">{}</span> relationship{}',
                count,
                's' if count != 1 else ''
            )
        return format_html('<span style="color: #6c757d;">No relationships</span>')
    relationship_count_display.short_description = _('Relationships')

    def promoted_manifest_status(self, obj):
        config = obj.mapping_config or {}
        manifest = config.get('promoted_manifest') or {}
        created_at = manifest.get('created_at')

        if manifest:
            timestamp = f" – {created_at}" if created_at else ""
            return format_html(
                '<span style="color:#198754;font-weight:bold;">Ready{}</span>',
                timestamp,
            )

        return format_html('<span style="color:#b02a37;">Missing</span>')
    promoted_manifest_status.short_description = _('Promoted manifest')

    @admin.action(description=_("Set selected mapping as active"))
    def action_set_active_mapping(self, request, queryset):
        if queryset.count() != 1:
            self.message_user(
                request,
                "Select exactly one mapping to mark as active.",
                level=messages.ERROR,
            )
            return

        mapping = queryset.first()
        if not mapping.organization_id:
            self.message_user(
                request,
                "Selected mapping does not have an organization_id set.",
                level=messages.ERROR,
            )
            return

        with transaction.atomic():
            Mapping.objects.filter(
                organization_id=mapping.organization_id,
                is_active=True,
            ).exclude(id=mapping.id).update(is_active=False)

            Mapping.objects.filter(id=mapping.id).update(is_active=True)
            mapping.is_active = True

            MappingSelectionAudit.objects.create(
                user=request.user if request.user.is_authenticated else None,
                organization_id=mapping.organization_id,
                mapping=mapping,
                mapping_name=mapping.name,
                action='set',
                ip_address=request.META.get('REMOTE_ADDR'),
            )

        self.message_user(
            request,
            f"Mapping '{mapping.name}' is now active for organization {mapping.organization_id}.",
            level=messages.SUCCESS,
        )

    @admin.action(description=_("Queue promote_legacy_junctions (Huey)"))
    def action_promote_legacy_junctions(self, request, queryset):
        scheduled = []
        seen_orgs = set()
        for mapping in queryset:
            org_code = (mapping.organization_id or "").lower()
            if not org_code or org_code in seen_orgs:
                continue
            task = promote_legacy_junctions_task.schedule(
                kwargs={
                    "mapping_id": str(mapping.id),
                    "dry_run": False,
                },
                delay=0,
            )
            scheduled.append((mapping, task.id))
            seen_orgs.add(org_code)

        if not scheduled:
            self.message_user(
                request,
                "No tasks queued. Ensure mappings have unique organizations selected.",
                level=messages.WARNING,
            )
            return

        preview = self._build_task_preview(scheduled)
        self.message_user(
            request,
            f"Queued {len(scheduled)} promote_legacy_junctions task(s): {preview}",
            level=messages.SUCCESS,
        )

    @admin.action(description=_("Queue create_promoted_schema_manifest (Huey)"))
    def action_generate_promoted_manifest(self, request, queryset):
        scheduled = []
        for mapping in queryset:
            if not mapping.organization_id:
                continue
            task = create_promoted_manifest_task.schedule(
                kwargs={
                    "mapping_id": str(mapping.id),
                    "output_key": "promoted_manifest",
                },
                delay=0,
            )
            scheduled.append((mapping, task.id))

        if not scheduled:
            self.message_user(
                request,
                "No tasks queued. Ensure the selected mappings have an organization configured.",
                level=messages.WARNING,
            )
            return

        preview = self._build_task_preview(scheduled)
        self.message_user(
            request,
            f"Queued {len(scheduled)} create_promoted_schema_manifest task(s): {preview}",
            level=messages.SUCCESS,
        )

    # ------------------------------------------------------------------
    # Junction pattern admin views
    # ------------------------------------------------------------------
    def junction_patterns_view(self, request: HttpRequest, object_id: str) -> HttpResponse:
        mapping = self.get_object(request, object_id)
        if not mapping:
            self.message_user(request, _("Mapping not found."), level=messages.ERROR)
            return redirect('admin:metadata_mapping_changelist')

        if request.method == "POST":
            return self._handle_junction_patterns_post(request, mapping)

        context = self._build_junction_patterns_context(request, mapping)
        return TemplateResponse(
            request,
            "admin/metadata/mapping/junction_patterns.html",
            context,
        )

    def _handle_junction_patterns_post(self, request: HttpRequest, mapping: Mapping) -> HttpResponse:
        action = request.POST.get("action")
        dataset_name = request.POST.get("dataset_name")

        dataset_required_actions = {"remove_pattern", "adopt_pattern"}
        if action in dataset_required_actions and not dataset_name:
            self.message_user(request, _("Dataset missing."), level=messages.ERROR)
            return redirect(reverse('admin:metadata_mapping_junction_patterns', args=[mapping.pk]))

        if action == "remove_pattern":
            pattern_name = request.POST.get("pattern_name")
            if pattern_name and self._remove_manifest_pattern(mapping, dataset_name, pattern_name):
                self.message_user(
                    request,
                    _("Removed pattern %(pattern)s from %(dataset)s") % {"pattern": pattern_name, "dataset": dataset_name},
                    level=messages.SUCCESS,
                )
            else:
                self.message_user(request, _("Pattern not found."), level=messages.WARNING)

        elif action == "adopt_pattern":
            pattern_name = request.POST.get("pattern_name")
            pattern = self._find_proposed_pattern(mapping, dataset_name, pattern_name)
            if pattern and self._add_manifest_pattern(mapping, dataset_name, pattern):
                self.message_user(
                    request,
                    _("Added pattern %(pattern)s to %(dataset)s") % {"pattern": pattern_name, "dataset": dataset_name},
                    level=messages.SUCCESS,
                )
            else:
                self.message_user(request, _("Could not add pattern."), level=messages.ERROR)
        elif action == "run_derivation":
            dry_run = request.POST.get("dry_run") == "1"
            stats = self._run_derivation(mapping, dry_run=dry_run)
            if stats:
                msg = _("Derivation complete: processed %(processed)d, created %(created)d")
                self.message_user(
                    request,
                    msg % {"processed": stats.processed, "created": stats.created},
                    level=messages.SUCCESS,
                )
        else:
            self.message_user(request, _("Unsupported action."), level=messages.WARNING)

        return redirect(reverse('admin:metadata_mapping_junction_patterns', args=[mapping.pk]))

    def _build_junction_patterns_context(self, request: HttpRequest, mapping: Mapping) -> Dict[str, object]:
        dataset_rows = self._dataset_rows(mapping, include_proposals=True)
        return {
            **self.admin_site.each_context(request),
            "title": _("Junction patterns for %(mapping)s") % {"mapping": mapping.name},
            "mapping": mapping,
            "datasets": dataset_rows,
            "opts": self.model._meta,
            "change_url": reverse('admin:metadata_mapping_change', args=[mapping.pk]),
        }

    def _run_derivation(self, mapping: Mapping, *, dry_run: bool):
        service = DerivedRelationshipService(
            mapping.organization_id or "",
            mapping_config=mapping.mapping_config,
        )
        return service.derive(dry_run=dry_run)

    def _dataset_rows(self, mapping: Mapping, *, include_proposals: bool) -> List[Dict[str, object]]:
        manifest = (mapping.mapping_config or {}).get("schema_manifest") or {}
        service = JunctionPatternService(
            mapping_config=mapping.mapping_config,
            organization_code=mapping.organization_id,
            include_static_patterns=False,
        )
        rows: List[Dict[str, object]] = []
        for dataset_name in sorted(manifest.keys()):
            dataset_entry = manifest[dataset_name]
            canonical_predicates = sorted(self._collect_canonical_predicates(dataset_entry))
            manifest_patterns = service.get_manifest_patterns(dataset_name)
            proposals: List[DerivationPattern] = []
            if include_proposals:
                manifest_names = {pattern.name for pattern in manifest_patterns}
                static_patterns = iter_applicable_patterns(
                    mapping.organization_id or "",
                    dataset_name,
                    canonical_predicates,
                )
                proposals = [pattern for pattern in static_patterns if pattern.name not in manifest_names]

            rows.append(
                {
                    "name": dataset_name,
                    "canonical_predicates": canonical_predicates,
                    "existing_patterns": manifest_patterns,
                    "proposed_patterns": proposals,
                }
            )
        return rows

    def _find_proposed_pattern(self, mapping: Mapping, dataset_name: str, pattern_name: str) -> Optional[DerivationPattern]:
        rows = self._dataset_rows(mapping, include_proposals=True)
        for row in rows:
            if row["name"] != dataset_name:
                continue
            for pattern in row["proposed_patterns"]:
                if pattern.name == pattern_name:
                    return pattern
        return None

    def _collect_canonical_predicates(self, dataset_entry: Dict[str, object]) -> set[str]:
        predicates: set[str] = set()
        properties = dataset_entry.get("properties") or {}
        if isinstance(properties, dict):
            for prop in properties.values():
                if isinstance(prop, dict):
                    canonical_uri = prop.get("canonical_uri")
                    if canonical_uri:
                        predicates.add(canonical_uri)
        return predicates

    def _add_manifest_pattern(self, mapping: Mapping, dataset_name: str, pattern: DerivationPattern) -> bool:
        serialized = self._serialize_pattern(pattern)
        config = mapping.mapping_config or {}
        junction_config = config.setdefault("junction_patterns", {})
        dataset_entry = junction_config.setdefault(dataset_name, {"patterns": []})
        if isinstance(dataset_entry, list):
            dataset_entry = {"patterns": dataset_entry}
            junction_config[dataset_name] = dataset_entry

        patterns = dataset_entry.setdefault("patterns", [])
        if any(existing.get("name") == serialized["name"] for existing in patterns):
            return False
        patterns.append(serialized)
        mapping.mapping_config = config
        mapping.save(update_fields=["mapping_config"])
        return True

    def _remove_manifest_pattern(self, mapping: Mapping, dataset_name: str, pattern_name: str) -> bool:
        config = mapping.mapping_config or {}
        junction_config = config.get("junction_patterns") or {}
        dataset_entry = junction_config.get(dataset_name)
        patterns = None
        if isinstance(dataset_entry, dict):
            patterns = dataset_entry.get("patterns")
        elif isinstance(dataset_entry, list):
            patterns = dataset_entry

        if not isinstance(patterns, list):
            return False

        initial_len = len(patterns)
        patterns[:] = [pattern for pattern in patterns if pattern.get("name") != pattern_name]
        if len(patterns) == initial_len:
            return False

        mapping.mapping_config = config
        mapping.save(update_fields=["mapping_config"])
        return True

    def _serialize_pattern(self, pattern: DerivationPattern) -> Dict[str, object]:
        return {
            "name": pattern.name,
            "description": pattern.description,
            "required_properties": list(pattern.required_properties),
            "recipes": [
                {
                    "subject_property": recipe.subject_property,
                    "object_property": recipe.object_property,
                    "predicate_uri": recipe.predicate_uri,
                    "description": recipe.description,
                }
                for recipe in pattern.recipes
            ],
        }

    def _build_task_preview(self, scheduled_tasks):
        if not scheduled_tasks:
            return ""
        preview_items = [
            f"{mapping.organization_id}:{mapping.name} → {task_id}"
            for mapping, task_id in scheduled_tasks[:3]
        ]
        remainder = len(scheduled_tasks) - len(preview_items)
        if remainder > 0:
            preview_items.append(f"+{remainder} more")
        return ", ".join(preview_items)
    
    def last_executed_display(self, obj):
        """Display last execution time with relative format."""
        if not obj.last_executed:
            return format_html('<span style="color: #6c757d;">Never executed</span>')
        
        from django.utils.timesince import timesince
        time_since = timesince(obj.last_executed, timezone.now())
        
        # Check if recently executed
        from datetime import timedelta
        if timezone.now() - obj.last_executed < timedelta(hours=24):
            color = '#28a745'  # green for recent
        elif timezone.now() - obj.last_executed < timedelta(days=7):
            color = '#ffc107'  # yellow for this week
        else:
            color = '#6c757d'  # gray for older
        
        return format_html(
            '<span style="color: {};">{}<br><small>{} ago</small></span>',
            color,
            obj.last_executed.strftime('%Y-%m-%d %H:%M'),
            time_since
        )
    last_executed_display.short_description = _('Last Executed')
    last_executed_display.admin_order_field = 'last_executed'
    
    def created_by_link(self, obj):
        """Display creator as a link."""
        if obj.created_by:
            url = reverse('admin:users_user_change', args=[obj.created_by.pk])
            return format_html('<a href="{}">{}</a>', url, obj.created_by.get_display_name())
        return '-'
    created_by_link.short_description = _('Created By')
    created_by_link.admin_order_field = 'created_by'

    def id_display(self, obj):
        """Expose UUID for quick copy/use in management commands."""
        return str(obj.id)
    id_display.short_description = _('UUID')
    id_display.admin_order_field = 'id'
    
    def mapping_preview(self, obj):
        """Display a formatted preview of the mapping configuration."""
        if not obj.mapping_config:
            return format_html('<span style="color: #6c757d;">No configuration</span>')
        
        try:
            config = obj.mapping_config
            
            # Count various elements
            workspace_cols = config.get('workspace_columns', {})
            fk_relationships = config.get('fk_relationships', {})
            junction_tables = config.get('junction_tables', {})
            
            preview_html = '<div style="font-family: monospace; line-height: 1.6;">'
            
            # Version
            version = config.get('version', 'Unknown')
            preview_html += f'<strong>Version:</strong> {version}<br>'
            
            # Workspace columns
            if workspace_cols:
                preview_html += f'<strong>Workspace Columns:</strong> {len(workspace_cols)}<br>'
                # Show first 3 datasets
                for i, (dataset, cols) in enumerate(list(workspace_cols.items())[:3]):
                    col_count = len(cols) if isinstance(cols, dict) else 0
                    preview_html += f'  • {dataset}: {col_count} columns<br>'
                if len(workspace_cols) > 3:
                    preview_html += f'  <em>... and {len(workspace_cols) - 3} more datasets</em><br>'
            
            # FK Relationships
            if fk_relationships:
                preview_html += f'<br><strong>FK Relationships:</strong> {len(fk_relationships)}<br>'
                for i, (rel_name, rel_config) in enumerate(list(fk_relationships.items())[:2]):
                    source = rel_config.get('source', {}).get('dataset', 'Unknown')
                    target = rel_config.get('target', {}).get('dataset', 'Unknown')
                    preview_html += f'  • {source} → {target}<br>'
                if len(fk_relationships) > 2:
                    preview_html += f'  <em>... and {len(fk_relationships) - 2} more relationships</em><br>'
            
            # Junction tables
            if junction_tables:
                preview_html += f'<br><strong>Junction Tables:</strong> {len(junction_tables)}<br>'
            
            preview_html += '</div>'
            
            # Add a collapsible full JSON view
            json_str = json.dumps(config, indent=2, sort_keys=True)
            preview_html += f'''
            <details style="margin-top: 10px;">
                <summary style="cursor: pointer; color: #0066cc;">View Full JSON</summary>
                <pre style="background: #f8f9fa; padding: 10px; margin-top: 5px; 
                           border: 1px solid #dee2e6; border-radius: 4px; 
                           overflow-x: auto; max-height: 400px;">{json_str}</pre>
            </details>
            '''
            
            return mark_safe(preview_html)
            
        except Exception as e:
            return format_html(
                '<span style="color: #dc3545;">Error parsing configuration: {}</span>',
                str(e)
            )
    mapping_preview.short_description = _('Configuration Preview')

    def schema_manifest_preview(self, obj):
        """Display a formatted preview of the schema manifest."""
        manifest = (obj.mapping_config or {}).get('schema_manifest')
        if not manifest:
            return format_html('<span style="color: #6c757d;">No schema manifest stored</span>')

        try:
            dataset_count = len(manifest)
            summary_html = '<div style="font-family: monospace; line-height: 1.6;">'
            summary_html += f'<strong>Datasets:</strong> {dataset_count}<br>'

            # List first 3 datasets with property counts
            for dataset_name in list(manifest.keys())[:3]:
                dataset_info = manifest[dataset_name]
                prop_count = len(dataset_info.get('properties', {}))
                fk_count = len(dataset_info.get('fk_relationships', []))
                summary_html += (
                    f'  • {dataset_name}: '
                    f'{prop_count} properties, {fk_count} FKs<br>'
                )
            if dataset_count > 3:
                summary_html += f'  <em>... and {dataset_count - 3} more datasets</em><br>'

            summary_html += '</div>'

            json_str = json.dumps(manifest, indent=2, sort_keys=True)
            summary_html += f'''
            <details style="margin-top: 10px;">
                <summary style="cursor: pointer; color: #0066cc;">View Full Schema Manifest</summary>
                <pre style="background: #f8f9fa; padding: 10px; margin-top: 5px;
                           border: 1px solid #dee2e6; border-radius: 4px;
                           overflow-x: auto; max-height: 400px;">{json_str}</pre>
            </details>
            '''

            return mark_safe(summary_html)

        except Exception as exc:
            return format_html(
                '<span style="color: #dc3545;">Error rendering schema manifest: {}</span>',
                str(exc)
            )
    schema_manifest_preview.short_description = _('Schema Manifest')

    def junction_patterns_link(self, obj):
        if not obj or not obj.pk:
            return _("Save mapping to manage junction patterns.")
        url = reverse('admin:metadata_mapping_junction_patterns', args=[obj.pk])
        return format_html('<a class="button" href="{}">{}</a>', url, _("Manage junction patterns"))

    junction_patterns_link.short_description = _("Junction patterns")

    def execution_stats_display(self, obj):
        """Display execution statistics in a formatted way."""
        if not obj.execution_stats:
            return format_html('<span style="color: #6c757d;">No execution statistics</span>')

        try:
            stats = obj.execution_stats
            
            html = '<div style="line-height: 1.6;">'
            
            # Common stats
            if 'rows_processed' in stats:
                html += f'<strong>Rows Processed:</strong> {stats["rows_processed"]:,}<br>'
            if 'resources_created' in stats:
                html += f'<strong>Resources Created:</strong> {stats["resources_created"]:,}<br>'
            if 'triples_created' in stats:
                html += f'<strong>Triples Created:</strong> {stats["triples_created"]:,}<br>'
            if 'errors' in stats:
                html += f'<strong>Errors:</strong> <span style="color: #dc3545;">{stats["errors"]:,}</span><br>'
            if 'warnings' in stats:
                html += f'<strong>Warnings:</strong> <span style="color: #ffc107;">{stats["warnings"]:,}</span><br>'
            if 'execution_time' in stats:
                html += f'<strong>Execution Time:</strong> {stats["execution_time"]:.2f}s<br>'
            
            # Show any additional stats
            known_keys = {'rows_processed', 'resources_created', 'triples_created', 
                         'errors', 'warnings', 'execution_time'}
            other_stats = {k: v for k, v in stats.items() if k not in known_keys}
            
            if other_stats:
                html += '<br><strong>Additional Stats:</strong><br>'
                for key, value in other_stats.items():
                    html += f'  • {key}: {value}<br>'
            
            html += '</div>'
            
            # Add full JSON view
            json_str = json.dumps(stats, indent=2, sort_keys=True)
            html += f'''
            <details style="margin-top: 10px;">
                <summary style="cursor: pointer; color: #0066cc;">View Raw Statistics</summary>
                <pre style="background: #f8f9fa; padding: 10px; margin-top: 5px; 
                           border: 1px solid #dee2e6; border-radius: 4px; 
                           overflow-x: auto; max-height: 200px;">{json_str}</pre>
            </details>
            '''
            
            return mark_safe(html)
            
        except Exception as e:
            return format_html(
                '<span style="color: #dc3545;">Error parsing statistics: {}</span>',
                str(e)
            )
    execution_stats_display.short_description = _('Execution Statistics')
    
    def save_model(self, request, obj, form, change):
        """Set created_by when creating new mapping."""
        if not change and not obj.created_by:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)
    
    actions = [
        'action_set_active_mapping',
        'action_promote_legacy_junctions',
        'action_generate_promoted_manifest',
        'mark_as_validated',
        'mark_as_active',
        'reset_to_draft',
        'clear_execution_stats',
    ]
    
    def mark_as_validated(self, request, queryset):
        """Mark selected mappings as validated."""
        count = queryset.update(validation_status='validated')
        self.message_user(
            request,
            f"{count} mapping(s) marked as validated.",
            level='SUCCESS'
        )
    mark_as_validated.short_description = _("Mark as validated")
    
    def mark_as_active(self, request, queryset):
        """Mark selected mappings as active."""
        # Only mark validated mappings as active
        validated = queryset.filter(validation_status='validated')
        count = validated.update(validation_status='active')
        
        if count < queryset.count():
            self.message_user(
                request,
                f"Only {count} validated mapping(s) were marked as active. "
                f"{queryset.count() - count} mapping(s) must be validated first.",
                level='WARNING'
            )
        else:
            self.message_user(
                request,
                f"{count} mapping(s) marked as active.",
                level='SUCCESS'
            )
    mark_as_active.short_description = _("Mark as active")
    
    def reset_to_draft(self, request, queryset):
        """Reset selected mappings to draft status."""
        count = queryset.update(validation_status='draft')
        self.message_user(
            request,
            f"{count} mapping(s) reset to draft.",
            level='INFO'
        )
    reset_to_draft.short_description = _("Reset to draft")
    
    def clear_execution_stats(self, request, queryset):
        """Clear execution statistics for selected mappings."""
        count = queryset.update(execution_stats={}, last_executed=None)
        self.message_user(
            request,
            f"Cleared execution statistics for {count} mapping(s).",
            level='INFO'
        )
    clear_execution_stats.short_description = _("Clear execution statistics")
