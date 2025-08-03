from allauth.account.decorators import secure_admin_login
from django.conf import settings
from django.contrib import admin
from django.contrib.auth import admin as auth_admin
from django.utils.translation import gettext_lazy as _
from django.utils.html import format_html
from django.db.models import Count, Q
from django.urls import reverse
from django.utils.safestring import mark_safe
from django.contrib import messages
from django.contrib.admin import SimpleListFilter

from .forms import UserAdminChangeForm
from .forms import UserAdminCreationForm
from .models import User, Organization

if settings.DJANGO_ADMIN_FORCE_ALLAUTH:
    # Force the `admin` sign in process to go through the `django-allauth` workflow:
    # https://docs.allauth.org/en/latest/common/admin.html#admin
    admin.autodiscover()
    admin.site.login = secure_admin_login(admin.site.login)  # type: ignore[method-assign]


class HasUsersFilter(SimpleListFilter):
    """Filter organizations by whether they have users."""
    title = _('has users')
    parameter_name = 'has_users'
    
    def lookups(self, request, model_admin):
        return (
            ('yes', _('Has users')),
            ('no', _('No users')),
        )
    
    def queryset(self, request, queryset):
        if self.value() == 'yes':
            return queryset.filter(users__isnull=False).distinct()
        if self.value() == 'no':
            return queryset.filter(users__isnull=True)
        return queryset


class UserRoleFilter(SimpleListFilter):
    """Filter users by role groups."""
    title = _('role group')
    parameter_name = 'role_group'
    
    def lookups(self, request, model_admin):
        return (
            ('admin', _('Administrators (Manager+')),
            ('staff', _('Staff (Archivist+)')),
            ('basic', _('Basic Users (Researcher)')),
        )
    
    def queryset(self, request, queryset):
        if self.value() == 'admin':
            return queryset.filter(role__in=['manager', 'super_manager', 'system_admin'])
        if self.value() == 'staff':
            return queryset.filter(role__in=['archivist', 'manager', 'super_manager', 'system_admin'])
        if self.value() == 'basic':
            return queryset.filter(role='researcher')
        return queryset


class LoginActivityFilter(SimpleListFilter):
    """Filter users by their login activity."""
    title = _('login activity')
    parameter_name = 'login_activity'
    
    def lookups(self, request, model_admin):
        return (
            ('never', _('Never logged in')),
            ('active', _('Active (within 7 days)')),
            ('recent', _('Recent (within 30 days)')),
            ('inactive', _('Inactive (over 30 days)')),
            ('shibboleth_only', _('Shibboleth login only')),
            ('regular_only', _('Regular login only')),
        )
    
    def queryset(self, request, queryset):
        from django.utils import timezone
        from datetime import timedelta
        
        now = timezone.now()
        seven_days_ago = now - timedelta(days=7)
        thirty_days_ago = now - timedelta(days=30)
        
        if self.value() == 'never':
            return queryset.filter(last_login__isnull=True, last_shibboleth_login__isnull=True)
        elif self.value() == 'active':
            from django.db.models import Q
            return queryset.filter(
                Q(last_login__gte=seven_days_ago) | Q(last_shibboleth_login__gte=seven_days_ago)
            )
        elif self.value() == 'recent':
            from django.db.models import Q
            return queryset.filter(
                Q(last_login__gte=thirty_days_ago) | Q(last_shibboleth_login__gte=thirty_days_ago)
            ).exclude(
                Q(last_login__gte=seven_days_ago) | Q(last_shibboleth_login__gte=seven_days_ago)
            )
        elif self.value() == 'inactive':
            from django.db.models import Q
            return queryset.exclude(
                Q(last_login__gte=thirty_days_ago) | Q(last_shibboleth_login__gte=thirty_days_ago)
            ).exclude(last_login__isnull=True, last_shibboleth_login__isnull=True)
        elif self.value() == 'shibboleth_only':
            return queryset.filter(last_shibboleth_login__isnull=False, last_login__isnull=True)
        elif self.value() == 'regular_only':
            return queryset.filter(last_login__isnull=False, last_shibboleth_login__isnull=True)
        
        return queryset


class UserInline(admin.TabularInline):
    """Inline for displaying users in Organization admin"""
    model = User
    fields = ('username', 'name', 'role', 'auth_source', 'is_active')
    readonly_fields = ('username', 'name', 'role', 'auth_source')
    extra = 0
    can_delete = False
    show_change_link = True
    
    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = [
        'name', 
        'code_badge',
        'domain', 
        'user_count',
        'active_user_count',
        'is_active',
        'created_at'
    ]
    list_filter = [
        'is_active',
        HasUsersFilter,
        'created_at',
        ('users', admin.EmptyFieldListFilter),
    ]
    search_fields = ['name', 'code', 'domain', 'shibboleth_entity_id']
    readonly_fields = ['created_at', 'updated_at', 'user_statistics']
    prepopulated_fields = {"code": ["name"]}
    ordering = ['-created_at']
    
    fieldsets = (
        (None, {
            'fields': ('name', 'code', 'is_active')
        }),
        (_('Contact Information'), {
            'fields': ('contact_name', 'contact_email', 'description'),
            'description': 'Organization contact details and internal notes.'
        }),
        (_('Domain Configuration'), {
            'fields': ('domain', 'shibboleth_entity_id'),
            'description': 'Configure domain and authentication settings for this organization.'
        }),
        (_('Statistics'), {
            'fields': ('user_statistics',),
            'classes': ('collapse',),
        }),
        (_('Timestamps'), {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',),
        }),
    )
    
    inlines = [UserInline]
    
    def get_queryset(self, request):
        """Optimize queries by annotating user counts."""
        return super().get_queryset(request).annotate(
            total_users=Count('users'),
            active_users=Count('users', filter=Q(users__is_active=True))
        )
    
    def user_count(self, obj):
        """Display total number of users."""
        count = getattr(obj, 'total_users', 0)
        url = reverse('admin:users_user_changelist') + f'?organization__id__exact={obj.pk}'
        return format_html('<a href="{}">{}</a>', url, count)
    user_count.short_description = _('Total Users')
    user_count.admin_order_field = 'total_users'
    
    def active_user_count(self, obj):
        """Display number of active users."""
        count = getattr(obj, 'active_users', 0)
        url = reverse('admin:users_user_changelist') + f'?organization__id__exact={obj.pk}&is_active__exact=1'
        return format_html('<a href="{}">{}</a>', url, count)
    active_user_count.short_description = _('Active Users')
    active_user_count.admin_order_field = 'active_users'
    
    def code_badge(self, obj):
        """Display organization code as a colored badge."""
        if not obj.code:
            return format_html('<span style="color: #6c757d;">-</span>')
        
        # Color coding for different institution codes
        colors = {
            'rsh': '#dc3545',    # red
            'khm': '#6610f2',    # indigo  
            'fuk': '#20c997',    # teal
            'hmt': '#fd7e14',    # orange
            'det': '#6f42c1',    # purple
            'other': '#6c757d',  # gray
        }
        
        color = colors.get(obj.code, '#6c757d')
        display_name = obj.get_organization_type_display_name() or obj.code
        
        return format_html(
            '<span style="background-color: {}; color: white; padding: 2px 6px; '
            'border-radius: 3px; font-size: 11px; font-weight: bold;" title="{}">{}</span>',
            color,
            display_name,
            obj.code.upper()
        )
    code_badge.short_description = _('Code')
    code_badge.admin_order_field = 'code'
    
    def user_statistics(self, obj):
        """Display detailed user statistics."""
        if not obj.pk:
            return '-'
        
        stats = User.objects.filter(organization=obj).aggregate(
            total=Count('id'),
            active=Count('id', filter=Q(is_active=True)),
            researchers=Count('id', filter=Q(role='researcher')),
            archivists=Count('id', filter=Q(role='archivist')),
            managers=Count('id', filter=Q(role='manager')),
            super_managers=Count('id', filter=Q(role='super_manager')),
            system_admins=Count('id', filter=Q(role='system_admin')),
            shibboleth=Count('id', filter=Q(auth_source='shibboleth')),
            local=Count('id', filter=Q(auth_source='local')),
        )
        
        return format_html(
            '<div style="line-height: 1.5;">'
            '<strong>Total Users:</strong> {}<br>'
            '<strong>Active:</strong> {} | <strong>Inactive:</strong> {}<br>'
            '<hr style="margin: 8px 0;">'
            '<strong>By Role:</strong><br>'
            '• Researchers: {}<br>'
            '• Archivists: {}<br>'
            '• Managers: {}<br>'
            '• Super Managers: {}<br>'
            '• System Admins: {}<br>'
            '<hr style="margin: 8px 0;">'
            '<strong>By Auth Source:</strong><br>'
            '• Shibboleth: {}<br>'
            '• Local: {}<br>'
            '</div>',
            stats['total'],
            stats['active'],
            stats['total'] - stats['active'],
            stats['researchers'],
            stats['archivists'],
            stats['managers'],
            stats['super_managers'],
            stats['system_admins'],
            stats['shibboleth'],
            stats['local']
        )
    user_statistics.short_description = _('User Statistics')
    
    def save_model(self, request, obj, form, change):
        """Log organization changes."""
        if change:
            original = Organization.objects.get(pk=obj.pk)
            if original.is_active and not obj.is_active:
                self.message_user(
                    request, 
                    f"Organization '{obj.name}' has been deactivated. All users will lose access.",
                    level='WARNING'
                )
        super().save_model(request, obj, form, change)
    
    actions = ['activate_organizations', 'deactivate_organizations', 'populate_from_type']
    
    def activate_organizations(self, request, queryset):
        """Activate selected organizations."""
        count = queryset.update(is_active=True)
        self.message_user(
            request,
            f"{count} organization(s) were successfully activated.",
            messages.SUCCESS
        )
    activate_organizations.short_description = _("Activate selected organizations")
    
    def deactivate_organizations(self, request, queryset):
        """Deactivate selected organizations."""
        # Warn about user impact
        total_users = User.objects.filter(organization__in=queryset).count()
        count = queryset.update(is_active=False)
        self.message_user(
            request,
            f"{count} organization(s) were deactivated. This affects {total_users} user(s).",
            messages.WARNING
        )
    deactivate_organizations.short_description = _("Deactivate selected organizations")
    
    def populate_from_type(self, request, queryset):
        """Auto-populate name from code if it matches a known OrganizationType."""
        updated_count = 0
        
        for org in queryset:
            if org.code and org.code != 'other':
                old_name = org.name
                
                org.populate_from_type()
                
                if org.name != old_name:
                    org.save()
                    updated_count += 1
        
        if updated_count > 0:
            self.message_user(
                request,
                f"Updated {updated_count} organization(s) names from their codes.",
                messages.SUCCESS
            )
        else:
            self.message_user(
                request,
                "No organizations were updated. They either have unknown codes or already have matching names.",
                messages.INFO
            )
    populate_from_type.short_description = _("Populate name from organization code")


@admin.register(User)
class UserAdmin(auth_admin.UserAdmin):
    form = UserAdminChangeForm
    add_form = UserAdminCreationForm
    fieldsets = (
        (None, {"fields": ("username", "password")}),
        (_("Personal info"), {"fields": ("name", "email")}),
        (_("Organization & Role"), {
            "fields": ("organization", "role"),
            "description": "Assign user to an organization and set their role."
        }),
        (_("Shibboleth Integration"), {
            "fields": (
                "auth_source", 
                "shibboleth_eppn", 
                "shibboleth_persistent_id",
                "shibboleth_affiliation",
                "is_federated_user",
                "last_shibboleth_login"
            ),
            "classes": ("collapse",),
        }),
        (
            _("Permissions"),
            {
                "fields": (
                    "is_active",
                    "is_staff",
                    "is_superuser",
                    "groups",
                    "user_permissions",
                    "calculated_permissions",
                ),
            },
        ),
        (_("Login Activity"), {
            "fields": ("login_activity_display",),
            "description": "User login history and authentication activity."
        }),
        (_("Important dates"), {"fields": ("last_login", "date_joined")}),
    )
    list_display = [
        "username", 
        "name", 
        "email",
        "organization_link", 
        "role_badge", 
        "auth_source_badge",
        "login_status",
        "is_active", 
        "is_staff", 
        "is_superuser"
    ]
    list_filter = [
        "is_active", 
        "is_staff", 
        "is_superuser", 
        "role",
        UserRoleFilter,
        LoginActivityFilter,
        "organization",
        "auth_source",
        "is_federated_user",
        "date_joined",
        "last_login"
    ]
    search_fields = ["name", "username", "email", "shibboleth_eppn"]
    autocomplete_fields = ["organization"]
    readonly_fields = ["calculated_permissions", "login_activity_display"]
    ordering = ['-date_joined']
    
    def get_queryset(self, request):
        """Optimize queries by selecting related organization."""
        return super().get_queryset(request).select_related('organization')
    
    def organization_link(self, obj):
        """Display organization as a link."""
        if obj.organization:
            url = reverse('admin:users_organization_change', args=[obj.organization.pk])
            return format_html('<a href="{}">{}</a>', url, obj.organization.name)
        return '-'
    organization_link.short_description = _('Organization')
    organization_link.admin_order_field = 'organization__name'
    
    def role_badge(self, obj):
        """Display role with color-coded badge."""
        colors = {
            'researcher': '#17a2b8',      # info blue
            'archivist': '#28a745',       # success green
            'manager': '#ffc107',         # warning yellow
            'super_manager': '#fd7e14',   # orange
            'system_admin': '#dc3545',    # danger red
        }
        color = colors.get(obj.role, '#6c757d')  # default gray
        return format_html(
            '<span style="background-color: {}; color: white; padding: 3px 8px; '
            'border-radius: 3px; font-size: 11px; font-weight: bold;">{}</span>',
            color,
            obj.get_role_display()
        )
    role_badge.short_description = _('Role')
    role_badge.admin_order_field = 'role'
    
    def auth_source_badge(self, obj):
        """Display authentication source as badge."""
        if obj.auth_source == 'shibboleth':
            icon = '🔐'
            color = '#28a745'
        else:
            icon = '🔑'
            color = '#6c757d'
        
        return format_html(
            '<span style="color: {};">{} {}</span>',
            color,
            icon,
            obj.get_auth_source_display()
        )
    auth_source_badge.short_description = _('Auth Source')
    auth_source_badge.admin_order_field = 'auth_source'
    
    def login_status(self, obj):
        """Display comprehensive login status with both regular and Shibboleth logins."""
        from django.utils import timezone
        from django.utils.timesince import timesince
        
        regular_login = obj.last_login
        shib_login = obj.last_shibboleth_login
        
        # Determine the most recent login
        most_recent = None
        login_type = None
        
        if regular_login and shib_login:
            if regular_login > shib_login:
                most_recent = regular_login
                login_type = "Regular"
            else:
                most_recent = shib_login
                login_type = "Shibboleth"
        elif regular_login:
            most_recent = regular_login
            login_type = "Regular"
        elif shib_login:
            most_recent = shib_login
            login_type = "Shibboleth"
        
        if not most_recent:
            return format_html('<span style="color: #dc3545;">Never logged in</span>')
        
        time_since = timesince(most_recent, timezone.now())
        
        # Color coding based on how recent the login is
        now = timezone.now()
        days_since = (now - most_recent).days
        
        if days_since <= 1:
            color = '#28a745'  # Green - very recent
            status = 'Active'
        elif days_since <= 7:
            color = '#17a2b8'  # Blue - recent
            status = 'Recent'
        elif days_since <= 30:
            color = '#ffc107'  # Yellow - moderate
            status = 'Moderate'
        else:
            color = '#dc3545'  # Red - old
            status = 'Inactive'
        
        return format_html(
            '<div>'
            '<span style="color: {}; font-weight: bold;">{}</span><br>'
            '<small style="color: #666;">{} via {}<br>{} ago</small>'
            '</div>',
            color,
            status,
            most_recent.strftime('%Y-%m-%d %H:%M'),
            login_type,
            time_since
        )
    login_status.short_description = _('Login Status')
    login_status.admin_order_field = 'last_login'
    
    def login_activity_display(self, obj):
        """Display detailed login activity in the admin form."""
        from django.utils import timezone
        from django.utils.timesince import timesince
        
        if not obj.pk:
            return '-'
        
        regular_login = obj.last_login
        shib_login = obj.last_shibboleth_login
        
        activity_html = []
        
        # Regular login info
        if regular_login:
            time_since = timesince(regular_login, timezone.now())
            activity_html.append(
                f'<div style="margin-bottom: 10px;">'
                f'<strong>🔑 Regular Login:</strong><br>'
                f'<span style="color: #28a745;">{regular_login.strftime("%Y-%m-%d %H:%M:%S")}</span><br>'
                f'<small style="color: #666;">({time_since} ago)</small>'
                f'</div>'
            )
        else:
            activity_html.append(
                f'<div style="margin-bottom: 10px;">'
                f'<strong>🔑 Regular Login:</strong><br>'
                f'<span style="color: #dc3545;">Never</span>'
                f'</div>'
            )
        
        # Shibboleth login info
        if shib_login:
            time_since = timesince(shib_login, timezone.now())
            activity_html.append(
                f'<div style="margin-bottom: 10px;">'
                f'<strong>🔐 Shibboleth Login:</strong><br>'
                f'<span style="color: #28a745;">{shib_login.strftime("%Y-%m-%d %H:%M:%S")}</span><br>'
                f'<small style="color: #666;">({time_since} ago)</small>'
                f'</div>'
            )
        else:
            activity_html.append(
                f'<div style="margin-bottom: 10px;">'
                f'<strong>🔐 Shibboleth Login:</strong><br>'
                f'<span style="color: #dc3545;">Never</span>'
                f'</div>'
            )
        
        # Account age
        account_age = timesince(obj.date_joined, timezone.now())
        activity_html.append(
            f'<div style="margin-bottom: 10px; padding-top: 10px; border-top: 1px solid #ddd;">'
            f'<strong>📅 Account Created:</strong><br>'
            f'{obj.date_joined.strftime("%Y-%m-%d %H:%M:%S")}<br>'
            f'<small style="color: #666;">({account_age} ago)</small>'
            f'</div>'
        )
        
        # Login frequency estimate
        if regular_login or shib_login:
            most_recent = max(filter(None, [regular_login, shib_login]))
            days_since_joined = (timezone.now() - obj.date_joined).days
            days_since_last_login = (timezone.now() - most_recent).days
            
            if days_since_joined > 0:
                activity_level = "Active" if days_since_last_login <= 7 else "Moderate" if days_since_last_login <= 30 else "Inactive"
                activity_html.append(
                    f'<div style="margin-top: 10px; padding-top: 10px; border-top: 1px solid #ddd;">'
                    f'<strong>Activity Level:</strong> '
                    f'<span style="color: {"#28a745" if activity_level == "Active" else "#ffc107" if activity_level == "Moderate" else "#dc3545"};">'
                    f'{activity_level}</span>'
                    f'</div>'
                )
        
        return mark_safe(''.join(activity_html))
    login_activity_display.short_description = _('Login Activity')
    
    def calculated_permissions(self, obj):
        """Display calculated permissions based on role."""
        if not obj.pk:
            return '-'
        
        permissions = []
        role_perms = {
            'researcher': [
                'can_access_admin_backend',
                'can_view_cross_university_public',
                'can_link_cross_university'
            ],
            'archivist': [
                'can_access_admin_backend',
                'can_view_cross_university_public',
                'can_link_cross_university',
                'can_manage_metadata'
            ],
            'manager': [
                'can_access_admin_backend',
                'can_view_cross_university_public',
                'can_link_cross_university',
                'can_manage_metadata',
                'can_transfer_to_public',
                'can_approve_public_access',
                'can_import_universal'
            ],
            'super_manager': [
                'can_access_admin_backend',
                'can_view_cross_university_public',
                'can_link_cross_university',
                'can_manage_metadata',
                'can_transfer_to_public',
                'can_approve_public_access',
                'can_import_universal',
                'can_manage_org_users'
            ],
            'system_admin': [
                'can_access_admin_backend',
                'can_view_cross_university_public',
                'can_link_cross_university',
                'can_manage_metadata',
                'can_transfer_to_public',
                'can_approve_public_access',
                'can_import_universal',
                'can_manage_org_users',
                'can_reset_database'
            ],
        }
        
        user_perms = role_perms.get(obj.role, [])
        
        perm_display = []
        for perm in user_perms:
            # Format permission name nicely
            display_name = perm.replace('can_', '').replace('_', ' ').title()
            perm_display.append(f'✓ {display_name}')
        
        if obj.is_superuser:
            perm_display.insert(0, '<strong style="color: #dc3545;">⚡ Django Superuser (All Permissions)</strong>')
        
        return mark_safe('<br>'.join(perm_display) if perm_display else 'No permissions')
    calculated_permissions.short_description = _('Calculated Permissions')
    
    def save_model(self, request, obj, form, change):
        """Add logging and validation when saving users."""
        if change:
            original = User.objects.get(pk=obj.pk)
            # Log role changes
            if original.role != obj.role:
                self.message_user(
                    request,
                    f"User '{obj.username}' role changed from '{original.get_role_display()}' "
                    f"to '{obj.get_role_display()}'",
                    level='INFO'
                )
            # Warn about organization changes
            if original.organization != obj.organization:
                self.message_user(
                    request,
                    f"User '{obj.username}' moved from '{original.organization}' "
                    f"to '{obj.organization}'",
                    level='WARNING'
                )
        super().save_model(request, obj, form, change)
    
    actions = ['activate_users', 'deactivate_users', 'promote_to_archivist', 'promote_to_manager']
    
    def activate_users(self, request, queryset):
        """Activate selected users."""
        count = queryset.update(is_active=True)
        self.message_user(
            request,
            f"{count} user(s) were successfully activated.",
            messages.SUCCESS
        )
    activate_users.short_description = _("Activate selected users")
    
    def deactivate_users(self, request, queryset):
        """Deactivate selected users."""
        # Don't allow deactivating superusers
        superuser_count = queryset.filter(is_superuser=True).count()
        if superuser_count > 0:
            self.message_user(
                request,
                f"Cannot deactivate {superuser_count} superuser(s). Operation cancelled.",
                messages.ERROR
            )
            return
        
        count = queryset.update(is_active=False)
        self.message_user(
            request,
            f"{count} user(s) were successfully deactivated.",
            messages.WARNING
        )
    deactivate_users.short_description = _("Deactivate selected users")
    
    def promote_to_archivist(self, request, queryset):
        """Promote selected researchers to archivists."""
        # Only promote researchers
        eligible = queryset.filter(role='researcher')
        count = eligible.update(role='archivist')
        
        if count > 0:
            self.message_user(
                request,
                f"{count} researcher(s) were promoted to archivist.",
                messages.SUCCESS
            )
        else:
            self.message_user(
                request,
                "No researchers were selected for promotion.",
                messages.WARNING
            )
    promote_to_archivist.short_description = _("Promote researchers to archivists")
    
    def promote_to_manager(self, request, queryset):
        """Promote selected users to managers."""
        # Only promote archivists
        eligible = queryset.filter(role='archivist')
        count = eligible.update(role='manager')
        
        if count > 0:
            self.message_user(
                request,
                f"{count} archivist(s) were promoted to manager.",
                messages.SUCCESS
            )
        else:
            self.message_user(
                request,
                "No archivists were selected for promotion.",
                messages.WARNING
            )
    promote_to_manager.short_description = _("Promote archivists to managers")
    
    def get_form(self, request, obj=None, **kwargs):
        """Customize form based on user permissions."""
        form = super().get_form(request, obj, **kwargs)
        
        # Only system admins can set system_admin role
        if not request.user.is_superuser and not request.user.role == 'system_admin':
            if 'role' in form.base_fields:
                choices = [c for c in form.base_fields['role'].choices if c[0] != 'system_admin']
                form.base_fields['role'].choices = choices
        
        return form