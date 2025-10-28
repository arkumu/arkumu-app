from django.contrib import admin
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _
from django.utils.safestring import mark_safe
from django.contrib.admin import SimpleListFilter
from django.db.models import Count, Q, Exists, OuterRef
from django.urls import reverse
from django.utils import timezone
from django.contrib import messages

from arkumu.metadata.models.resource import Resource, ResourceType, PublicAccessLevel
from arkumu.metadata.models.triples import Triple


class ResourceTypeFilter(SimpleListFilter):
    """Filter resources by type groups."""
    title = _('resource type group')
    parameter_name = 'type_group'
    
    def lookups(self, request, model_admin):
        return (
            ('identifiers', _('Identifiers (IRI, Class, Property)')),
            ('literals', _('Literals Only')),
            ('placeholders', _('Placeholder Resources')),
        )
    
    def queryset(self, request, queryset):
        if self.value() == 'identifiers':
            return queryset.exclude(resource_type=ResourceType.LITERAL)
        if self.value() == 'literals':
            return queryset.filter(resource_type=ResourceType.LITERAL)
        if self.value() == 'placeholders':
            return queryset.filter(is_placeholder=True)
        return queryset


class PublicAccessFilter(SimpleListFilter):
    """Filter resources by public access status."""
    title = _('public access status')
    parameter_name = 'public_status'
    
    def lookups(self, request, model_admin):
        return (
            ('public_approved', _('Public & Approved')),
            ('public_pending', _('Public but Not Approved')),
            ('restricted', _('Restricted Access')),
            ('private', _('Private Only')),
            ('externally_linked', _('Externally Linked')),
        )
    
    def queryset(self, request, queryset):
        if self.value() == 'public_approved':
            return queryset.filter(
                public_access_level=PublicAccessLevel.PUBLIC,
                is_public_approved=True
            )
        if self.value() == 'public_pending':
            return queryset.filter(
                public_access_level=PublicAccessLevel.PUBLIC,
                is_public_approved=False
            )
        if self.value() == 'restricted':
            return queryset.filter(public_access_level=PublicAccessLevel.RESTRICTED)
        if self.value() == 'private':
            return queryset.filter(public_access_level=PublicAccessLevel.PRIVATE)
        if self.value() == 'externally_linked':
            return queryset.filter(is_externally_linked=True)
        return queryset


class HasTriplesFilter(SimpleListFilter):
    """Filter resources by triple relationships."""
    title = _('has triples')
    parameter_name = 'has_triples'
    
    def lookups(self, request, model_admin):
        return (
            ('as_subject', _('Used as Subject')),
            ('as_predicate', _('Used as Predicate')),
            ('as_object', _('Used as Object')),
            ('no_triples', _('No Triple References')),
        )
    
    def queryset(self, request, queryset):
        if self.value() == 'as_subject':
            return queryset.filter(
                Exists(Triple.objects.filter(subject=OuterRef('pk')))
            )
        if self.value() == 'as_predicate':
            return queryset.filter(
                Exists(Triple.objects.filter(predicate=OuterRef('pk')))
            )
        if self.value() == 'as_object':
            return queryset.filter(
                Exists(Triple.objects.filter(object=OuterRef('pk')))
            )
        if self.value() == 'no_triples':
            return queryset.filter(
                ~Exists(Triple.objects.filter(
                    Q(subject=OuterRef('pk')) |
                    Q(predicate=OuterRef('pk')) |
                    Q(object=OuterRef('pk'))
                ))
            )
        return queryset


class CanonicalUriFilter(SimpleListFilter):
    """Filter resources by canonical URI status."""
    title = _('canonical URI status')
    parameter_name = 'canonical_status'
    
    def lookups(self, request, model_admin):
        return (
            ('has_canonical', _('Has Canonical URI')),
            ('no_canonical', _('No Canonical URI')),
            ('arkumu_compliant', _('Arkumu Compliant (rsh, det, fuk)')),
        )
    
    def queryset(self, request, queryset):
        if self.value() == 'has_canonical':
            return queryset.filter(canonical_uri__isnull=False)
        if self.value() == 'no_canonical':
            return queryset.filter(canonical_uri__isnull=True)
        if self.value() == 'arkumu_compliant':
            # Filter for Arkumu-compliant institutions
            return queryset.filter(
                Q(organization__code__iexact='rsh') |
                Q(organization__code__iexact='det') |
                Q(organization__code__iexact='fuk')
            )
        return queryset




@admin.register(Resource)
class ResourceAdmin(admin.ModelAdmin):
    list_display = [
        'id_short',
        'resource_type_badge',
        'display_uri',
        'display_canonical_uri',
        'display_name',
        'display_value_truncated',
        'organization_link',
        'public_access_badge',
        'display_language_datatype',
        'is_placeholder_badge',
        'triple_usage_display',
        'created_at'
    ]
    
    list_filter = [
        'resource_type',  # Indexed through constraints
        ResourceTypeFilter,
        'public_access_level',  # Has composite index with is_public_approved
        PublicAccessFilter,
        CanonicalUriFilter,  # New canonical URI filter
        'is_placeholder',
        'is_public',
        'is_externally_linked',
        HasTriplesFilter,
        'organization',  # Has index
        'created_at',
        ('public_approved_by', admin.RelatedOnlyFieldListFilter),
        ('language', admin.AllValuesFieldListFilter),  # For literal filtering
        ('datatype', admin.AllValuesFieldListFilter),  # For literal filtering
    ]
    
    # Simple search fields using Django's default search
    search_fields = [
        'uri',
        'canonical_uri',  # Add canonical URI to search
        'name', 
        'value',
        'organization__name',
        'organization__code',
    ]
    
    readonly_fields = [
        'id',
        'created_at',
        'updated_at',
        'value_hash',
        'resource_display',
        'triple_relationships',
        'public_access_info',
        'literal_info',
        'literal_source_breakdown',
    ]
    
    fieldsets = (
        (_('Basic Information'), {
            'fields': (
                'id',
                'resource_type',
                'is_placeholder',
            ),
            'description': 'Core resource identification and type.'
        }),
        (_('Resource Content'), {
            'fields': (
                'uri',
                'canonical_uri',
                'name', 
                'value',
                'value_hash',
            ),
            'description': 'The actual content of the resource - URI for identified resources, canonical URI for unified catalog, value for literals.'
        }),
        (_('Literal-Specific Properties'), {
            'fields': (
                'datatype',
                'language',
                'literal_info',
                'literal_source_breakdown'
            ),
            'description': 'Properties that only apply to LITERAL type resources.',
        }),
        (_('Organization & Ownership'), {
            'fields': (
                'organization',
            ),
            'description': 'Organization that owns this resource.',
        }),
        (_('Public Access Control'), {
            'fields': (
                'public_access_level',
                'is_public',
                'is_public_approved',
                'is_externally_linked',
                'public_approved_at',
                'public_approved_by',
                'public_access_info'
            ),
            'description': 'Controls who can see and use this resource across organizations.',
        }),
        (_('Timestamps'), {
            'fields': (
                'created_at',
                'updated_at',
            ),
            'classes': ('collapse',),
        }),
        (_('Triple Relationships'), {
            'fields': ('triple_relationships',),
            'classes': ('collapse',),
            'description': 'How this resource is used in triple statements.',
        }),
        (_('Summary View'), {
            'fields': ('resource_display',),
            'classes': ('collapse',),
            'description': 'Formatted summary of all resource information.',
        }),
    )
    
    def get_queryset(self, request):
        """Optimize queries with annotations."""
        qs = super().get_queryset(request)
        return qs.select_related('organization', 'public_approved_by')

    def changelist_view(self, request, extra_context=None):
        response = super().changelist_view(request, extra_context=extra_context)
        try:
            cl = response.context_data['cl']
            result_list = list(cl.result_list)
        except (AttributeError, KeyError, TypeError):
            return response

        if not result_list:
            return response

        resource_ids = [obj.id for obj in result_list]

        subject_counts = {
            row['subject_id']: row['count']
            for row in Triple.objects.filter(subject_id__in=resource_ids)
            .values('subject_id')
            .annotate(count=Count('id'))
        }
        predicate_counts = {
            row['predicate_id']: row['count']
            for row in Triple.objects.filter(predicate_id__in=resource_ids)
            .values('predicate_id')
            .annotate(count=Count('id'))
        }
        object_counts = {
            row['object_id']: row['count']
            for row in Triple.objects.filter(object_id__in=resource_ids)
            .values('object_id')
            .annotate(count=Count('id'))
        }

        for obj in result_list:
            obj.subject_count = subject_counts.get(obj.id, 0)
            obj.predicate_count = predicate_counts.get(obj.id, 0)
            obj.object_count = object_counts.get(obj.id, 0)

        cl.result_list = result_list
        response.context_data['cl'] = cl
        return response
    
    def display_value(self, obj):
        """Display the resource value with appropriate formatting."""
        if obj.resource_type == ResourceType.LITERAL:
            # Format literal with datatype/language
            value = f'"{obj.value}"'
            if obj.language:
                value += f'@{obj.language}'
            elif obj.datatype:
                value += f'^^{obj.datatype}'
            return format_html(
                '<code style="background: #f8f9fa; padding: 2px 4px; '
                'border-radius: 3px;">{}</code>',
                value
            )
        elif obj.uri:
            # Truncate long URIs
            display_uri = obj.uri
            if len(display_uri) > 60:
                display_uri = display_uri[:57] + '...'
            return format_html(
                '<a href="{}" target="_blank" title="{}">{}</a>',
                obj.uri,
                obj.uri,
                display_uri
            )
        elif obj.name:
            return format_html('<strong>{}</strong>', obj.name)
        else:
            return format_html('<em style="color: #6c757d;">Resource {}</em>', obj.id)
    display_value.short_description = _('Resource')
    display_value.admin_order_field = 'uri'
    
    def resource_type_badge(self, obj):
        """Display resource type with icon and color."""
        icons = {
            ResourceType.IRI: '🔗',
            ResourceType.CLASS: '📦',
            ResourceType.PROPERTY: '🔧',
            ResourceType.LITERAL: '📝',
        }
        colors = {
            ResourceType.IRI: '#17a2b8',      # info blue
            ResourceType.CLASS: '#6610f2',     # indigo
            ResourceType.PROPERTY: '#e83e8c',  # pink
            ResourceType.LITERAL: '#28a745',   # green
        }
        
        icon = icons.get(obj.resource_type, '❓')
        color = colors.get(obj.resource_type, '#6c757d')
        
        return format_html(
            '<span style="color: {}; font-size: 14px;" title="{}">{} {}</span>',
            color,
            obj.get_resource_type_display(),
            icon,
            obj.get_resource_type_display()
        )
    resource_type_badge.short_description = _('Type')
    resource_type_badge.admin_order_field = 'resource_type'
    
    
    def organization_link(self, obj):
        """Display organization as a link."""
        if obj.organization:
            url = reverse('admin:users_organization_change', args=[obj.organization.pk])
            return format_html('<a href="{}">{}</a>', url, obj.organization.name)
        return '-'
    organization_link.short_description = _('Organization')
    organization_link.admin_order_field = 'organization__name'
    
    def public_access_badge(self, obj):
        """Display public access status with badges."""
        badges = []
        
        # Access level
        level_colors = {
            PublicAccessLevel.PRIVATE: '#6c757d',     # gray
            PublicAccessLevel.RESTRICTED: '#ffc107',  # yellow
            PublicAccessLevel.PUBLIC: '#28a745',      # green
        }
        color = level_colors.get(obj.public_access_level, '#6c757d')
        
        badges.append(format_html(
            '<span style="background: {}; color: white; padding: 2px 6px; '
            'border-radius: 3px; font-size: 11px; margin-right: 4px;">{}</span>',
            color,
            obj.get_public_access_level_display()
        ))
        
        # Approval status
        if obj.public_access_level == PublicAccessLevel.PUBLIC:
            if obj.is_public_approved:
                badges.append(format_html(
                    '<span style="background: #28a745; color: white; padding: 2px 6px; '
                    'border-radius: 3px; font-size: 11px;">✓ Approved</span>'
                ))
            else:
                badges.append(format_html(
                    '<span style="background: #dc3545; color: white; padding: 2px 6px; '
                    'border-radius: 3px; font-size: 11px;">⏳ Pending</span>'
                ))
        
        # External linking
        if obj.is_externally_linked:
            badges.append(format_html(
                '<span style="background: #17a2b8; color: white; padding: 2px 6px; '
                'border-radius: 3px; font-size: 11px;" title="Linked by other organizations">🔗 External</span>'
            ))
        
        return format_html(' '.join(badges))
    public_access_badge.short_description = _('Access')
    
    def triple_usage_display(self, obj):
        """Display how this resource is used in triples."""
        counts = []
        
        subject_count = getattr(obj, 'subject_count', 0)
        predicate_count = getattr(obj, 'predicate_count', 0)
        object_count = getattr(obj, 'object_count', 0)
        
        if subject_count:
            url = reverse('admin:metadata_triple_changelist') + f'?subject__id__exact={obj.pk}'
            counts.append(format_html(
                '<a href="{}" title="View as subject">S:{}</a>',
                url, subject_count
            ))
        
        if predicate_count:
            url = reverse('admin:metadata_triple_changelist') + f'?predicate__id__exact={obj.pk}'
            counts.append(format_html(
                '<a href="{}" title="View as predicate">P:{}</a>',
                url, predicate_count
            ))
        
        if object_count:
            url = reverse('admin:metadata_triple_changelist') + f'?object__id__exact={obj.pk}'
            counts.append(format_html(
                '<a href="{}" title="View as object">O:{}</a>',
                url, object_count
            ))
        
        if counts:
            return format_html(' | '.join(counts))
        return format_html('<span style="color: #6c757d;">No triples</span>')
    triple_usage_display.short_description = _('Triple Usage')
    
    def is_placeholder_badge(self, obj):
        """Display placeholder status."""
        if obj.is_placeholder:
            return format_html(
                '<span style="background: #ffc107; color: #000; padding: 2px 6px; '
                'border-radius: 3px; font-size: 11px;">⚠️ Placeholder</span>'
            )
        return ''
    is_placeholder_badge.short_description = _('Status')
    is_placeholder_badge.admin_order_field = 'is_placeholder'
    
    def resource_display(self, obj):
        """Comprehensive resource display showing ALL fields."""
        html = '<div style="line-height: 2; background: #f8f9fa; padding: 15px; border-radius: 5px;">'    
        html += '<h4 style="margin-top: 0; color: #495057;">Complete Resource Information</h4>'
        
        # Basic Info
        html += '<div style="margin-bottom: 15px;">'
        html += '<strong style="color: #007bff;">BASIC INFORMATION</strong><br>'
        html += f'<strong>ID:</strong> <code>{obj.id}</code><br>'
        html += f'<strong>Type:</strong> {obj.get_resource_type_display()} ({obj.resource_type})<br>'
        html += f'<strong>Is Placeholder:</strong> {"Yes ⚠️" if obj.is_placeholder else "No"}<br>'
        html += '</div>'
        
        # Content Fields
        html += '<div style="margin-bottom: 15px;">'
        html += '<strong style="color: #28a745;">CONTENT FIELDS</strong><br>'
        html += f'<strong>URI:</strong> {f"<a href='{obj.uri}' target='_blank'>{obj.uri}</a>" if obj.uri else "<em>None</em>"}<br>'
        html += f'<strong>Name:</strong> {obj.name if obj.name else "<em>None</em>"}<br>'
        html += f'<strong>Value:</strong> <code>{obj.value}</code><br>' if obj.value else '<strong>Value:</strong> <em>None</em><br>'
        html += f'<strong>Value Hash:</strong> <code style="font-size: 10px; word-break: break-all;">{obj.value_hash}</code><br>' if obj.value_hash else '<strong>Value Hash:</strong> <em>None</em><br>'
        html += '</div>'
        
        # Literal Properties
        if obj.resource_type == ResourceType.LITERAL:
            html += '<div style="margin-bottom: 15px;">'
            html += '<strong style="color: #e83e8c;">LITERAL PROPERTIES</strong><br>'
            html += f'<strong>Language:</strong> {obj.language if obj.language else "<em>None</em>"}<br>'
            html += f'<strong>Datatype:</strong> <code>{obj.datatype}</code><br>' if obj.datatype else '<strong>Datatype:</strong> <em>None (plain string)</em><br>'
            html += f'<strong>Full Representation:</strong> <code>{str(obj)}</code><br>'
            html += '</div>'
        
        # Organization
        html += '<div style="margin-bottom: 15px;">'
        html += '<strong style="color: #ffc107;">ORGANIZATION</strong><br>'
        if obj.organization:
            org_url = reverse('admin:users_organization_change', args=[obj.organization.pk])
            html += f'<strong>Organization:</strong> <a href="{org_url}">{obj.organization.name} ({obj.organization.code})</a><br>'
        else:
            html += '<strong>Organization:</strong> <em>None</em><br>'
        html += '</div>'
        
        # Public Access
        html += '<div style="margin-bottom: 15px;">'
        html += '<strong style="color: #17a2b8;">PUBLIC ACCESS SETTINGS</strong><br>'
        html += f'<strong>Access Level:</strong> {obj.get_public_access_level_display()} ({obj.public_access_level})<br>'
        html += f'<strong>Is Public:</strong> {"Yes" if obj.is_public else "No"}<br>'
        html += f'<strong>Is Approved:</strong> {"Yes ✓" if obj.is_public_approved else "No ✗"}<br>'
        html += f'<strong>Externally Linked:</strong> {"Yes 🔗" if obj.is_externally_linked else "No"}<br>'
        if obj.public_approved_at and obj.public_approved_by:
            approver_url = reverse('admin:users_user_change', args=[obj.public_approved_by.pk])
            html += f'<strong>Approved By:</strong> <a href="{approver_url}">{obj.public_approved_by.get_display_name()}</a><br>'
            html += f'<strong>Approved At:</strong> {obj.public_approved_at.strftime("%Y-%m-%d %H:%M:%S")}<br>'
        html += '</div>'
        
        # Timestamps
        html += '<div style="margin-bottom: 15px;">'
        html += '<strong style="color: #6c757d;">TIMESTAMPS</strong><br>'
        html += f'<strong>Created:</strong> {obj.created_at.strftime("%Y-%m-%d %H:%M:%S") if obj.created_at else "Unknown"}<br>'
        html += f'<strong>Updated:</strong> {obj.updated_at.strftime("%Y-%m-%d %H:%M:%S") if obj.updated_at else "Unknown"}<br>'
        html += '</div>'
        
        html += '</div>'
        return mark_safe(html)
    resource_display.short_description = _('Complete Resource Details')
    
    def display_value(self, obj):
        """Display the resource value with appropriate formatting - LEGACY method for compatibility."""
        if obj.resource_type == ResourceType.LITERAL:
            value = f'"{obj.value}"'
            if obj.language:
                value += f'@{obj.language}'
            elif obj.datatype:
                value += f'^^{obj.datatype}'
            return format_html(
                '<code style="background: #f8f9fa; padding: 2px 4px; '
                'border-radius: 3px;">{}</code>',
                value
            )
        elif obj.uri:
            display_uri = obj.uri
            if len(display_uri) > 60:
                display_uri = display_uri[:57] + '...'
            return format_html(
                '<a href="{}" target="_blank" title="{}">{}</a>',
                obj.uri,
                obj.uri,
                display_uri
            )
        elif obj.name:
            return format_html('<strong>{}</strong>', obj.name)
        else:
            return format_html('<em style="color: #6c757d;">Resource {}</em>', obj.id)
    display_value.short_description = _('Resource')
    display_value.admin_order_field = 'uri'
    
    def triple_relationships(self, obj):
        """Show detailed triple relationships."""
        if not obj.pk:
            return '-'
        
        html = '<div style="line-height: 1.8;">'
        
        # As subject
        subject_triples = Triple.objects.filter(subject=obj).select_related('predicate', 'object')[:5]
        if subject_triples:
            html += '<strong>As Subject:</strong><br>'
            for triple in subject_triples:
                pred_url = reverse('admin:metadata_resource_change', args=[triple.predicate.pk])
                obj_url = reverse('admin:metadata_resource_change', args=[triple.object.pk])
                html += f'  → <a href="{pred_url}">{triple.predicate}</a> → <a href="{obj_url}">{triple.object}</a><br>'
            
            total_subject = obj.subject_triples.count()
            if total_subject > 5:
                list_url = reverse('admin:metadata_triple_changelist') + f'?subject__id__exact={obj.pk}'
                html += f'  <a href="{list_url}">... and {total_subject - 5} more</a><br>'
        
        # As predicate
        predicate_triples = Triple.objects.filter(predicate=obj).select_related('subject', 'object')[:5]
        if predicate_triples:
            html += '<br><strong>As Predicate:</strong><br>'
            for triple in predicate_triples:
                subj_url = reverse('admin:metadata_resource_change', args=[triple.subject.pk])
                obj_url = reverse('admin:metadata_resource_change', args=[triple.object.pk])
                html += f'  <a href="{subj_url}">{triple.subject}</a> → <a href="{obj_url}">{triple.object}</a><br>'
            
            total_predicate = obj.predicate_triples.count()
            if total_predicate > 5:
                list_url = reverse('admin:metadata_triple_changelist') + f'?predicate__id__exact={obj.pk}'
                html += f'  <a href="{list_url}">... and {total_predicate - 5} more</a><br>'
        
        # As object
        object_triples = Triple.objects.filter(object=obj).select_related('subject', 'predicate')[:5]
        if object_triples:
            html += '<br><strong>As Object:</strong><br>'
            for triple in object_triples:
                subj_url = reverse('admin:metadata_resource_change', args=[triple.subject.pk])
                pred_url = reverse('admin:metadata_resource_change', args=[triple.predicate.pk])
                html += f'  <a href="{subj_url}">{triple.subject}</a> → <a href="{pred_url}">{triple.predicate}</a><br>'
            
            total_object = obj.object_triples.count()
            if total_object > 5:
                list_url = reverse('admin:metadata_triple_changelist') + f'?object__id__exact={obj.pk}'
                html += f'  <a href="{list_url}">... and {total_object - 5} more</a><br>'
        
        if not (subject_triples or predicate_triples or object_triples):
            html += '<em style="color: #6c757d;">No triple relationships</em>'
        
        html += '</div>'
        return mark_safe(html)
    triple_relationships.short_description = _('Triple Relationships')
    
    def public_access_info(self, obj):
        """Display detailed public access information."""
        if not obj.pk:
            return '-'
        
        html = '<div style="line-height: 1.8;">'
        
        html += f'<strong>Access Level:</strong> {obj.get_public_access_level_display()}<br>'
        html += f'<strong>Is Approved:</strong> {"Yes ✓" if obj.is_public_approved else "No ✗"}<br>'
        html += f'<strong>Is Public:</strong> {"Yes" if obj.is_public else "No"}<br>'
        html += f'<strong>Externally Linked:</strong> {"Yes 🔗" if obj.is_externally_linked else "No"}<br>'
        
        if obj.public_approved_at and obj.public_approved_by:
            approver_url = reverse('admin:users_user_change', args=[obj.public_approved_by.pk])
            html += f'<br><strong>Approved By:</strong> <a href="{approver_url}">{obj.public_approved_by.get_display_name()}</a><br>'
            html += f'<strong>Approved At:</strong> {obj.public_approved_at.strftime("%Y-%m-%d %H:%M")}<br>'
        
        html += '</div>'
        return mark_safe(html)
    public_access_info.short_description = _('Public Access Details')
    
    def literal_info(self, obj):
        """Display literal-specific information."""
        if obj.resource_type != ResourceType.LITERAL:
            return format_html('<em style="color: #6c757d;">Not a literal resource</em>')
        
        html = '<div style="line-height: 1.8;">'
        html += f'<strong>Value:</strong> <code>{obj.value}</code><br>'
        
        if obj.value_hash:
            html += f'<strong>Value Hash (SHA-256):</strong><br>'
            html += f'<code style="font-size: 11px; word-break: break-all;">{obj.value_hash}</code><br>'
        
        if obj.language:
            html += f'<br><strong>Language Tag:</strong> <code>{obj.language}</code><br>'
        
        if obj.datatype:
            html += f'<strong>Datatype URI:</strong> <code>{obj.datatype}</code><br>'
        else:
            html += '<strong>Datatype:</strong> <em>Plain string</em><br>'
        
        # Show the full literal representation
        html += f'<br><strong>Full Representation:</strong><br><code>{str(obj)}</code>'
        
        html += '</div>'
        return mark_safe(html)
    literal_info.short_description = _('Literal Information')
    
    def literal_source_breakdown(self, obj):
        """Display which organizations are using this literal."""
        if obj.resource_type != ResourceType.LITERAL:
            return format_html('<em style="color: #6c757d;">Not a literal resource</em>')
        
        if not obj.pk:
            return '-'
        
        # Get all triples where this literal is used as object
        from django.db.models import Count
        from arkumu.users.models import Organization
        
        # Query organizations that have triples using this resource as object
        # Use the Triple model directly to avoid related_name issues
        from arkumu.metadata.models import Triple
        
        triple_counts = (
            Triple.objects
            .filter(object=obj)
            .values('source__name', 'source__id')
            .annotate(usage_count=Count('id'))
            .order_by('-usage_count', 'source__name')
        )
        
        org_usage = []
        for item in triple_counts:
            if item['source__id']:
                try:
                    org = Organization.objects.get(id=item['source__id'])
                    org.usage_count = item['usage_count']
                    org_usage.append(org)
                except Organization.DoesNotExist:
                    continue
        
        if not org_usage:
            return format_html('<em style="color: #6c757d;">No organization usage found</em>')
        
        html = '<div style="line-height: 1.8;">'
        html += '<strong>Used by Organizations:</strong><br>'
        
        for org in org_usage:
            org_url = reverse('admin:users_organization_change', args=[org.pk])
            triple_url = reverse('admin:metadata_triple_changelist') + f'?object__id__exact={obj.pk}&source__id__exact={org.pk}'
            html += f'  • <a href="{org_url}">{org.name}</a>: <a href="{triple_url}" title="View triples">{org.usage_count} triple{"s" if org.usage_count != 1 else ""}</a><br>'
        
        total_triples = sum(org.usage_count for org in org_usage)
        html += f'<br><strong>Total Usage:</strong> {total_triples} triple{"s" if total_triples != 1 else ""} across {len(org_usage)} organization{"s" if len(org_usage) != 1 else ""}'
        
        html += '</div>'
        return mark_safe(html)
    literal_source_breakdown.short_description = _('Source Organizations')
    
    actions = [
        'approve_public_access',
        'revoke_public_access',
        'mark_as_placeholder',
        'unmark_as_placeholder',
        'set_public_level',
        'set_restricted_level',
        'set_private_level'
    ]
    
    def approve_public_access(self, request, queryset):
        """Approve selected resources for public access."""
        # Only approve resources that are set to public level
        eligible = queryset.filter(
            public_access_level=PublicAccessLevel.PUBLIC,
            is_public_approved=False
        )
        
        count = eligible.update(
            is_public_approved=True,
            public_approved_at=timezone.now(),
            public_approved_by=request.user
        )
        
        if count < queryset.count():
            self.message_user(
                request,
                f"Approved {count} resource(s) for public access. "
                f"{queryset.count() - count} were not eligible (not set to public level or already approved).",
                messages.WARNING
            )
        else:
            self.message_user(
                request,
                f"Successfully approved {count} resource(s) for public access.",
                messages.SUCCESS
            )
    approve_public_access.short_description = _("Approve for public access")
    
    def revoke_public_access(self, request, queryset):
        """Revoke public access approval."""
        count = queryset.update(
            is_public_approved=False,
            public_approved_at=None,
            public_approved_by=None
        )
        self.message_user(
            request,
            f"Revoked public access approval for {count} resource(s).",
            messages.INFO
        )
    revoke_public_access.short_description = _("Revoke public access approval")
    
    def mark_as_placeholder(self, request, queryset):
        """Mark resources as placeholders."""
        count = queryset.update(is_placeholder=True)
        self.message_user(
            request,
            f"Marked {count} resource(s) as placeholder.",
            messages.SUCCESS
        )
    mark_as_placeholder.short_description = _("Mark as placeholder")
    
    def unmark_as_placeholder(self, request, queryset):
        """Remove placeholder status."""
        count = queryset.update(is_placeholder=False)
        self.message_user(
            request,
            f"Removed placeholder status from {count} resource(s).",
            messages.SUCCESS
        )
    unmark_as_placeholder.short_description = _("Remove placeholder status")
    
    def set_public_level(self, request, queryset):
        """Set resources to public access level."""
        count = queryset.update(public_access_level=PublicAccessLevel.PUBLIC)
        self.message_user(
            request,
            f"Set {count} resource(s) to public access level. "
            "Remember to approve them for public display.",
            messages.SUCCESS
        )
    set_public_level.short_description = _("Set to public level")
    
    def set_restricted_level(self, request, queryset):
        """Set resources to restricted access level."""
        count = queryset.update(public_access_level=PublicAccessLevel.RESTRICTED)
        self.message_user(
            request,
            f"Set {count} resource(s) to restricted access level.",
            messages.SUCCESS
        )
    set_restricted_level.short_description = _("Set to restricted level")
    
    def set_private_level(self, request, queryset):
        """Set resources to private access level."""
        count = queryset.update(
            public_access_level=PublicAccessLevel.PRIVATE,
            is_public_approved=False,
            public_approved_at=None,
            public_approved_by=None
        )
        self.message_user(
            request,
            f"Set {count} resource(s) to private access level.",
            messages.SUCCESS
        )
    set_private_level.short_description = _("Set to private level")
    
    def has_value_hash(self, obj):
        """Display whether resource has a value hash."""
        if obj.value_hash:
            return format_html(
                '<span style="color: #28a745; font-size: 11px;" '
                'title="{}">✓ Hash</span>',
                obj.value_hash[:16] + '...'
            )
        return ''
    has_value_hash.short_description = _('Hash')
    has_value_hash.admin_order_field = 'value_hash'
    
    def id_short(self, obj):
        """Display shortened UUID."""
        return format_html(
            '<code style="font-size: 10px; color: #6c757d;" title="{}">{}</code>',
            str(obj.id),
            str(obj.id)[:8]
        )
    id_short.short_description = _('ID')
    id_short.admin_order_field = 'id'
    
    def display_uri(self, obj):
        """Display URI for non-literal resources."""
        if obj.resource_type == ResourceType.LITERAL:
            return format_html('<span style="color: #6c757d;">—</span>')
        
        if obj.uri:
            display_uri = obj.uri
            if len(display_uri) > 40:
                display_uri = display_uri[:37] + '...'
            return format_html(
                '<a href="{}" target="_blank" title="{}" '
                'style="text-decoration: none; color: #007bff;">{}</a>',
                obj.uri,
                obj.uri,
                display_uri
            )
        return format_html('<span style="color: #dc3545;">⚠️ No URI</span>')
    display_uri.short_description = _('URI')
    display_uri.admin_order_field = 'uri'
    
    def display_canonical_uri(self, obj):
        """Display canonical URI with special styling."""
        if obj.canonical_uri:
            display_uri = obj.canonical_uri
            if len(display_uri) > 35:
                display_uri = display_uri[:32] + '...'
            return format_html(
                '<a href="{}" target="_blank" title="{}" '
                'style="text-decoration: none; color: #28a745; font-weight: bold;">{}</a> '
                '<span style="background: #28a745; color: white; padding: 1px 3px; '
                'border-radius: 3px; font-size: 9px;">UNIFIED</span>',
                obj.canonical_uri,
                obj.canonical_uri,
                display_uri
            )
        elif obj.organization and obj.organization.code.lower() in ['rsh', 'det', 'fuk']:
            return format_html(
                '<span style="color: #ffc107; font-style: italic;">⚠️ Missing canonical URI</span>'
            )
        return format_html('<span style="color: #6c757d;">—</span>')
    display_canonical_uri.short_description = _('Canonical URI')
    display_canonical_uri.admin_order_field = 'canonical_uri'
    
    def display_name(self, obj):
        """Display the name field."""
        if obj.name:
            if len(obj.name) > 30:
                return format_html(
                    '<span title="{}">{}</span>',
                    obj.name,
                    obj.name[:27] + '...'
                )
            return obj.name
        return format_html('<span style="color: #6c757d;">—</span>')
    display_name.short_description = _('Name')
    display_name.admin_order_field = 'name'
    
    def display_value_truncated(self, obj):
        """Display truncated value for literals."""
        if obj.resource_type != ResourceType.LITERAL:
            return format_html('<span style="color: #6c757d;">—</span>')
        
        if obj.value:
            value = obj.value
            if len(value) > 50:
                value = value[:47] + '...'
            return format_html(
                '<code style="background: #f8f9fa; padding: 2px 4px; '
                'border-radius: 3px; font-size: 11px;" title="{}">{}</code>',
                obj.value[:500],  # Show more in tooltip
                value
            )
        return format_html('<span style="color: #dc3545;">⚠️ No value</span>')
    display_value_truncated.short_description = _('Value')
    display_value_truncated.admin_order_field = 'value'
    
    def display_language_datatype(self, obj):
        """Display language and datatype for literals."""
        if obj.resource_type != ResourceType.LITERAL:
            return ''
        
        badges = []
        if obj.language:
            badges.append(format_html(
                '<span style="background: #17a2b8; color: white; padding: 1px 4px; '
                'border-radius: 3px; font-size: 10px;">@{}</span>',
                obj.language
            ))
        if obj.datatype:
            # Shorten common datatypes
            display_dt = obj.datatype
            if 'XMLSchema#' in display_dt:
                display_dt = 'xsd:' + display_dt.split('#')[-1]
            elif '/' in display_dt:
                display_dt = '...' + display_dt.split('/')[-1]
            
            badges.append(format_html(
                '<span style="background: #6610f2; color: white; padding: 1px 4px; '
                'border-radius: 3px; font-size: 10px;" title="{}">^^{}</span>',
                obj.datatype,
                display_dt if len(display_dt) < 20 else display_dt[:17] + '...'
            ))
        
        return format_html(' '.join(badges)) if badges else ''
    display_language_datatype.short_description = _('Lang/Type')
    
    def get_actions(self, request):
        """Only show public access actions to users with permission."""
        actions = super().get_actions(request)
        
        if not request.user.has_perm('metadata.can_approve_public_access'):
            # Remove public access related actions
            actions.pop('approve_public_access', None)
            actions.pop('revoke_public_access', None)
        
        return actions
    
    
    
    class Media:
        css = {
            'all': ('admin/css/resource_admin.css',)
        }
