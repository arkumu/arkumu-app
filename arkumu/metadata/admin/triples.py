from django.contrib import admin
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _
from django.utils.safestring import mark_safe
from django.contrib.admin import SimpleListFilter
from django.db.models import Q, Count, F
from django.db import models
from django.urls import reverse
from django.contrib import messages
from django.core.exceptions import ValidationError

from arkumu.metadata.models.triples import Triple
from arkumu.metadata.models.resource import Resource, ResourceType


class ResourceTypeInTripleFilter(SimpleListFilter):
    """Filter triples by resource types used."""
    title = _('resource types')
    parameter_name = 'resource_types'

    def lookups(self, request, model_admin):
        return (
            ('literal_objects', _('Has Literal Objects')),
            ('class_subjects', _('Has Class Subjects')),
            ('property_predicates', _('Valid Property Predicates')),
            ('invalid_predicates', _('Invalid Predicates')),
        )

    def queryset(self, request, queryset):
        if self.value() == 'literal_objects':
            return queryset.filter(object__resource_type=ResourceType.LITERAL)
        if self.value() == 'class_subjects':
            return queryset.filter(subject__resource_type=ResourceType.CLASS)
        if self.value() == 'property_predicates':
            return queryset.filter(predicate__resource_type=ResourceType.PROPERTY)
        if self.value() == 'invalid_predicates':
            return queryset.exclude(predicate__resource_type=ResourceType.PROPERTY)
        return queryset


class SourceFilter(SimpleListFilter):
    """Filter triples by organization consistency and triple source."""
    title = _('source consistency')
    parameter_name = 'source_consistency'

    def lookups(self, request, model_admin):
        return (
            ('same_org', _('All Same Organization')),
            ('cross_org', _('Cross-Organization')),
            ('derived_triples', _('System-Derived Triples')),
            ('archival_triples', _('Archival Triples')),
        )

    def queryset(self, request, queryset):
        if self.value() == 'same_org':
            # Triples where all resources have the same organization
            return queryset.filter(
                subject__organization=models.F('object__organization'),
                predicate__organization=models.F('object__organization')
            ).exclude(subject__organization__isnull=True)
        if self.value() == 'cross_org':
            # Triples crossing organization boundaries
            return queryset.filter(
                ~models.Q(subject__organization=models.F('object__organization'))
            ).exclude(
                subject__organization__isnull=True,
                object__organization__isnull=True
            )
        if self.value() == 'derived_triples':
            # System-derived triples (no source)
            return queryset.filter(source__isnull=True, is_derived=True)
        if self.value() == 'archival_triples':
            # Archival triples (have source)
            return queryset.filter(source__isnull=False, is_derived=False)
        return queryset


class TripleInline(admin.TabularInline):
    """Inline for showing related triples in Resource admin."""
    model = Triple
    fk_name = 'subject'  # Default to subject relationship
    fields = ('predicate', 'object', 'created_at')
    readonly_fields = ('created_at',)
    extra = 0
    can_delete = True
    show_change_link = True

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.select_related('predicate', 'object')


@admin.register(Triple)
class TripleAdmin(admin.ModelAdmin):
    list_display = [
        'id_short',
        'subject_display',
        'predicate_display',
        'object_display',
        'source_info',
        'is_derived_badge',
        'validation_status',
        'created_at'
    ]

    list_filter = [
        ResourceTypeInTripleFilter,
        SourceFilter,
        'is_derived',
        'created_at',
        ('source', admin.RelatedOnlyFieldListFilter),
        ('subject__organization', admin.RelatedOnlyFieldListFilter),
        ('predicate__resource_type', admin.ChoicesFieldListFilter),
        ('object__resource_type', admin.ChoicesFieldListFilter),
    ]

    search_fields = [
        'subject__uri',
        'subject__name',
        'predicate__uri',
        'predicate__canonical_uri',
        'predicate__name',
        'object__uri',
        'object__name',
        'object__value',
    ]

    readonly_fields = [
        'id',
        'created_at',
        'updated_at',
        'triple_visualization',
        'validation_details',
        'source_analysis',
    ]

    autocomplete_fields = ['subject', 'predicate', 'object']

    fieldsets = (
        (None, {
            'fields': ('subject', 'predicate', 'object', 'triple_visualization')
        }),
        (_('Source & Type'), {
            'fields': ('source', 'is_derived'),
            'description': 'Triple source organization and derivation status.',
        }),
        (_('Validation & Analysis'), {
            'fields': ('validation_details', 'source_analysis'),
            'classes': ('collapse',),
        }),
        (_('Metadata'), {
            'fields': ('created_at', 'updated_at', 'id'),
            'classes': ('collapse',),
        }),
    )

    def get_queryset(self, request):
        """Optimize queries with select_related."""
        return super().get_queryset(request).select_related(
            'source',
            'subject__organization',
            'predicate',
            'object__organization'
        )

    def id_short(self, obj):
        """Display shortened ID."""
        return format_html(
            '<code style="font-size: 11px;">{}</code>',
            str(obj.id)[:8]
        )
    id_short.short_description = _('ID')

    def subject_display(self, obj):
        """Display subject with link and type indicator."""
        if not obj.subject:
            return '-'

        url = reverse('admin:metadata_resource_change', args=[obj.subject.pk])

        # Type indicator
        type_icon = {
            ResourceType.IRI: '🔗',
            ResourceType.CLASS: '📦',
            ResourceType.PROPERTY: '🔧',
        }.get(obj.subject.resource_type, '❓')

        # Display value
        if obj.subject.uri:
            display = obj.subject.uri
            if len(display) > 40:
                display = display[:37] + '...'
        else:
            display = obj.subject.name or f'Resource {obj.subject.id[:8]}'

        return format_html(
            '{} <a href="{}" title="{}">{}</a>',
            type_icon,
            url,
            obj.subject.uri or obj.subject.name or '',
            display
        )
    subject_display.short_description = _('Subject')
    subject_display.admin_order_field = 'subject__uri'

    def predicate_display(self, obj):
        """Display predicate with validation indicator."""
        if not obj.predicate:
            return '-'

        url = reverse('admin:metadata_resource_change', args=[obj.predicate.pk])

        # Validation indicator
        if obj.predicate.resource_type == ResourceType.PROPERTY:
            icon = '✓'
            color = '#28a745'
        else:
            icon = '⚠️'
            color = '#dc3545'

        # Display value
        if obj.predicate.uri:
            display = obj.predicate.uri
            if len(display) > 40:
                display = display[:37] + '...'
        else:
            display = obj.predicate.name or f'Property {obj.predicate.id[:8]}'

        return format_html(
            '<span style="color: {};">{}</span> '
            '<a href="{}" title="{}">{}</a>',
            color,
            icon,
            url,
            obj.predicate.uri or obj.predicate.name or '',
            display
        )
    predicate_display.short_description = _('Predicate')
    predicate_display.admin_order_field = 'predicate__uri'

    def object_display(self, obj):
        """Display object with appropriate formatting."""
        if not obj.object:
            return '-'

        url = reverse('admin:metadata_resource_change', args=[obj.object.pk])

        # Type indicator
        type_icon = {
            ResourceType.IRI: '🔗',
            ResourceType.CLASS: '📦',
            ResourceType.PROPERTY: '🔧',
            ResourceType.LITERAL: '📝',
        }.get(obj.object.resource_type, '❓')

        # Display value
        if obj.object.resource_type == ResourceType.LITERAL:
            value = f'"{obj.object.value}"'
            if obj.object.language:
                value += f'@{obj.object.language}'
            elif obj.object.datatype:
                value += f'^^{obj.object.datatype}'

            return format_html(
                '{} <a href="{}" title="Literal value">'
                '<code style="background: #f8f9fa; padding: 2px 4px; '
                'border-radius: 3px;">{}</code></a>',
                type_icon,
                url,
                value if len(value) <= 50 else value[:47] + '...'
            )
        else:
            if obj.object.uri:
                display = obj.object.uri
                if len(display) > 40:
                    display = display[:37] + '...'
            else:
                display = obj.object.name or f'Resource {obj.object.id[:8]}'

            return format_html(
                '{} <a href="{}" title="{}">{}</a>',
                type_icon,
                url,
                obj.object.uri or obj.object.name or '',
                display
            )
    object_display.short_description = _('Object')
    object_display.admin_order_field = 'object__uri'

    def source_info(self, obj):
        """Display source/organization information."""
        badges = []

        # Triple source (from Triple model)
        if obj.source:
            badges.append(format_html(
                '<span style="background: #17a2b8; color: white; padding: 2px 6px; '
                'border-radius: 3px; font-size: 11px;" title="Source organization">{}</span>',
                obj.source.name
            ))
        elif obj.is_derived:
            badges.append(format_html(
                '<span style="background: #6610f2; color: white; padding: 2px 6px; '
                'border-radius: 3px; font-size: 11px;">Derived</span>'
            ))

        # Check if resources are from different organizations
        orgs = set()
        if obj.subject.organization:
            orgs.add(obj.subject.organization.code)
        if obj.object.organization:
            orgs.add(obj.object.organization.code)

        if len(orgs) > 1:
            badges.append(format_html(
                '<span style="background: #dc3545; color: white; padding: 2px 6px; '
                'border-radius: 3px; font-size: 11px;" title="{}">Cross-org</span>',
                ', '.join(orgs)
            ))
        elif len(orgs) == 1:
            badges.append(format_html(
                '<span style="background: #28a745; color: white; padding: 2px 6px; '
                'border-radius: 3px; font-size: 11px;">{}</span>',
                list(orgs)[0]
            ))

        return format_html(' '.join(badges)) if badges else '-'
    source_info.short_description = _('Source')

    def validation_status(self, obj):
        """Display validation status of the triple."""
        issues = []

        # Check subject
        if obj.subject.resource_type == ResourceType.LITERAL:
            issues.append('Subject is literal')

        # Check predicate
        if obj.predicate.resource_type != ResourceType.PROPERTY:
            issues.append('Predicate not a property')

        # Check cross-references
        if obj.subject.is_placeholder:
            issues.append('Subject is placeholder')
        if obj.object.is_placeholder:
            issues.append('Object is placeholder')

        if not issues:
            return format_html(
                '<span style="color: #28a745;">✓ Valid</span>'
            )
        else:
            return format_html(
                '<span style="color: #dc3545;" title="{}">⚠️ Issues</span>',
                '; '.join(issues)
            )
    validation_status.short_description = _('Valid')

    def is_derived_badge(self, obj):
        """Display whether triple is derived or archival."""
        if obj.is_derived:
            return format_html(
                '<span style="background: #6610f2; color: white; padding: 2px 6px; '
                'border-radius: 3px; font-size: 11px;">📊 Derived</span>'
            )
        else:
            return format_html(
                '<span style="background: #6c757d; color: white; padding: 2px 6px; '
                'border-radius: 3px; font-size: 11px;">🏛️ Archival</span>'
            )
    is_derived_badge.short_description = _('Type')
    is_derived_badge.admin_order_field = 'is_derived'

    def triple_visualization(self, obj):
        """Visual representation of the triple."""
        if not obj.pk:
            return '-'

        html = '<div style="font-family: monospace; font-size: 14px; line-height: 2; '
        html += 'background: #f8f9fa; padding: 15px; border-radius: 5px; margin: 10px 0;">'

        # Subject
        subj_url = reverse('admin:metadata_resource_change', args=[obj.subject.pk])
        if obj.subject.uri:
            subj_display = f'&lt;{obj.subject.uri}&gt;'
        else:
            subj_display = f'[{obj.subject.name or obj.subject.id[:8]}]'
        html += f'<a href="{subj_url}" style="color: #0066cc; text-decoration: none;">{subj_display}</a><br>'

        # Predicate (indented)
        pred_url = reverse('admin:metadata_resource_change', args=[obj.predicate.pk])
        if obj.predicate.uri:
            pred_display = f'&lt;{obj.predicate.uri}&gt;'
        else:
            pred_display = f'[{obj.predicate.name or obj.predicate.id[:8]}]'
        html += f'&nbsp;&nbsp;&nbsp;&nbsp;<a href="{pred_url}" style="color: #e83e8c; text-decoration: none;">{pred_display}</a><br>'

        # Object (further indented)
        obj_url = reverse('admin:metadata_resource_change', args=[obj.object.pk])
        if obj.object.resource_type == ResourceType.LITERAL:
            obj_display = str(obj.object)
            html += f'&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;<a href="{obj_url}" style="color: #28a745; text-decoration: none;">{obj_display}</a>'
        else:
            if obj.object.uri:
                obj_display = f'&lt;{obj.object.uri}&gt;'
            else:
                obj_display = f'[{obj.object.name or obj.object.id[:8]}]'
            html += f'&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;<a href="{obj_url}" style="color: #17a2b8; text-decoration: none;">{obj_display}</a>'

        html += ' .'
        html += '</div>'

        return mark_safe(html)
    triple_visualization.short_description = _('Triple Visualization')

    def validation_details(self, obj):
        """Detailed validation information."""
        if not obj.pk:
            return '-'

        html = '<div style="line-height: 1.8;">'

        # Subject validation
        html += '<strong>Subject Validation:</strong><br>'
        if obj.subject.resource_type == ResourceType.LITERAL:
            html += '&nbsp;&nbsp;<span style="color: #dc3545;">✗ Literal cannot be subject</span><br>'
        else:
            html += '&nbsp;&nbsp;<span style="color: #28a745;">✓ Valid subject type</span><br>'

        if obj.subject.is_placeholder:
            html += '&nbsp;&nbsp;<span style="color: #ffc107;">⚠️ Placeholder resource</span><br>'

        # Predicate validation
        html += '<br><strong>Predicate Validation:</strong><br>'
        if obj.predicate.resource_type == ResourceType.PROPERTY:
            html += '&nbsp;&nbsp;<span style="color: #28a745;">✓ Valid property type</span><br>'
        else:
            html += f'&nbsp;&nbsp;<span style="color: #dc3545;">✗ Invalid type: {obj.predicate.get_resource_type_display()}</span><br>'

        # Object validation
        html += '<br><strong>Object Validation:</strong><br>'
        html += f'&nbsp;&nbsp;Type: {obj.object.get_resource_type_display()}<br>'
        if obj.object.is_placeholder:
            html += '&nbsp;&nbsp;<span style="color: #ffc107;">⚠️ Placeholder resource</span><br>'

        # Overall status
        try:
            obj.clean()
            html += '<br><strong>Overall Status:</strong> <span style="color: #28a745;">✓ Valid triple</span>'
        except ValidationError as e:
            html += f'<br><strong>Overall Status:</strong> <span style="color: #dc3545;">✗ {e.message}</span>'

        html += '</div>'
        return mark_safe(html)
    validation_details.short_description = _('Validation Details')

    def source_analysis(self, obj):
        """Analyze source and organization relationships."""
        if not obj.pk:
            return '-'

        html = '<div style="line-height: 1.8;">'

        # Triple source
        html += '<strong>Triple Source:</strong><br>'
        if obj.source:
            org_url = reverse('admin:users_organization_change', args=[obj.source.pk])
            html += f'&nbsp;&nbsp;Organization: <a href="{org_url}">{obj.source.name}</a><br>'
            html += f'&nbsp;&nbsp;Type: Archival<br>'
        elif obj.is_derived:
            html += '&nbsp;&nbsp;Type: System-Derived<br>'
        else:
            html += '&nbsp;&nbsp;<em>No source specified</em><br>'

        # Subject source
        html += '<br><strong>Subject Resource:</strong><br>'
        if obj.subject.organization:
            org_url = reverse('admin:users_organization_change', args=[obj.subject.organization.pk])
            html += f'&nbsp;&nbsp;Organization: <a href="{org_url}">{obj.subject.organization.name}</a><br>'
        else:
            html += '&nbsp;&nbsp;Organization: <em>None</em><br>'

        # Predicate source
        html += '<br><strong>Predicate Resource:</strong><br>'
        if obj.predicate.organization:
            org_url = reverse('admin:users_organization_change', args=[obj.predicate.organization.pk])
            html += f'&nbsp;&nbsp;Organization: <a href="{org_url}">{obj.predicate.organization.name}</a><br>'
        else:
            html += '&nbsp;&nbsp;Organization: <em>None</em><br>'

        # Object source
        html += '<br><strong>Object Resource:</strong><br>'
        if obj.object.organization:
            org_url = reverse('admin:users_organization_change', args=[obj.object.organization.pk])
            html += f'&nbsp;&nbsp;Organization: <a href="{org_url}">{obj.object.organization.name}</a><br>'
        else:
            html += '&nbsp;&nbsp;Organization: <em>None</em><br>'

        # Analysis
        orgs = {
            obj.subject.organization.code if obj.subject.organization else None,
            obj.predicate.organization.code if obj.predicate.organization else None,
            obj.object.organization.code if obj.object.organization else None
        } - {None}

        html += '<br><strong>Analysis:</strong><br>'

        if obj.is_derived:
            html += '&nbsp;&nbsp;<span style="color: #6610f2;">📊 System-derived triple</span><br>'
        elif obj.source:
            html += f'&nbsp;&nbsp;<span style="color: #17a2b8;">🏛️ Archival triple from {obj.source.name}</span><br>'

        if len(orgs) <= 1:
            html += '&nbsp;&nbsp;<span style="color: #28a745;">✓ Same organization resources</span><br>'
        else:
            html += f'&nbsp;&nbsp;<span style="color: #dc3545;">⚠️ Cross-organization resources: {", ".join(orgs)}</span><br>'

        html += '</div>'
        return mark_safe(html)
    source_analysis.short_description = _('Source Analysis')

    actions = ['validate_triples', 'delete_invalid_triples']

    def validate_triples(self, request, queryset):
        """Validate selected triples and report issues."""
        valid_count = 0
        invalid_count = 0
        issues = []

        for triple in queryset:
            try:
                triple.clean()
                valid_count += 1
            except ValidationError as e:
                invalid_count += 1
                issues.append(f"Triple {triple.id[:8]}: {e.message}")

        if invalid_count > 0:
            # Show first 5 issues
            issue_list = '<br>'.join(issues[:5])
            if len(issues) > 5:
                issue_list += f'<br>... and {len(issues) - 5} more issues'

            self.message_user(
                request,
                mark_safe(
                    f"Validation complete: {valid_count} valid, "
                    f"{invalid_count} invalid.<br><br>{issue_list}"
                ),
                messages.WARNING
            )
        else:
            self.message_user(
                request,
                f"All {valid_count} triple(s) are valid!",
                messages.SUCCESS
            )
    validate_triples.short_description = _("Validate selected triples")

    def delete_invalid_triples(self, request, queryset):
        """Delete triples that fail validation."""
        deleted_count = 0

        for triple in queryset:
            try:
                triple.clean()
            except ValidationError:
                triple.delete()
                deleted_count += 1

        if deleted_count > 0:
            self.message_user(
                request,
                f"Deleted {deleted_count} invalid triple(s).",
                messages.WARNING
            )
        else:
            self.message_user(
                request,
                "No invalid triples found to delete.",
                messages.INFO
            )
    delete_invalid_triples.short_description = _("Delete invalid triples")

    def save_model(self, request, obj, form, change):
        """Validate triple before saving."""
        try:
            obj.clean()
        except ValidationError as e:
            messages.error(request, f"Validation error: {e.message}")
            return

        super().save_model(request, obj, form, change)
