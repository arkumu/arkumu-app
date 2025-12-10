from django.contrib.auth.mixins import UserPassesTestMixin, LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from functools import wraps


class RoleRequiredMixin(UserPassesTestMixin):
    """Mixin to require specific roles for view access."""
    required_roles = []
    required_permissions = []
    
    def test_func(self):
        if not self.request.user.is_authenticated:
            return False
        
        # Check roles
        if self.required_roles and self.request.user.role not in self.required_roles:
            return False
        
        # Check permissions  
        if self.required_permissions:
            for permission in self.required_permissions:
                if not self.request.user.has_role_permission(permission):
                    return False
        
        return True


class AdminRequiredMixin(LoginRequiredMixin):
    """
    Mixin requiring admin backend access.
    This is a USER-level permission check.
    """
    
    def dispatch(self, request, *args, **kwargs):
        if not request.user.has_role_permission('can_access_admin_backend'):
            raise PermissionDenied("Administrative access required.")
        return super().dispatch(request, *args, **kwargs)


class PublicApprovalMixin(AdminRequiredMixin):
    """
    Mixin for views that handle public approval workflow.
    Only managers and above can approve resources for public catalog.
    """
    
    def dispatch(self, request, *args, **kwargs):
        if not request.user.has_role_permission('can_approve_public_access'):
            raise PermissionDenied("You don't have permission to approve resources for public access.")
        return super().dispatch(request, *args, **kwargs)


class SystemAdminRequiredMixin(LoginRequiredMixin):
    """Mixin requiring system admin role."""
    
    def dispatch(self, request, *args, **kwargs):
        if request.user.role != 'system_admin':
            raise PermissionDenied("System administrator access required.")
        return super().dispatch(request, *args, **kwargs)


class ManagerRequiredMixin(LoginRequiredMixin):
    """Mixin requiring manager role or above."""
    
    def dispatch(self, request, *args, **kwargs):
        if request.user.role not in ['manager', 'super_manager', 'system_admin']:
            raise PermissionDenied("Manager access required.")
        return super().dispatch(request, *args, **kwargs)


class ArchivistRequiredMixin(LoginRequiredMixin):
    """Mixin requiring archivist role or above."""
    
    def dispatch(self, request, *args, **kwargs):
        if request.user.role not in ['archivist', 'manager', 'super_manager', 'system_admin']:
            raise PermissionDenied("Archivist access required.")
        return super().dispatch(request, *args, **kwargs)


class GeneralLoginRequiredMixin(LoginRequiredMixin):
    """
    General-purpose login required mixin for views that need authentication
    but don't require specific role checks. This provides a base level of 
    security for most application views.
    """
    pass


# ============================================================================
# FEATURE-SPECIFIC PERMISSION MIXINS
# ============================================================================

class DataManagementMixin(LoginRequiredMixin):
    """
    Mixin for views that handle data management operations.
    Requires archivist role or above.
    """
    def dispatch(self, request, *args, **kwargs):
        if request.user.role not in ['archivist', 'manager', 'super_manager', 'system_admin']:
            raise PermissionDenied("Data management access requires archivist role or above.")
        return super().dispatch(request, *args, **kwargs)


class FileUploadMixin(LoginRequiredMixin):
    """
    Mixin for file upload operations.
    Any authenticated user can upload, but we can restrict this later.
    """
    def dispatch(self, request, *args, **kwargs):
        # Currently allows any authenticated user
        # Can be enhanced with specific upload permissions
        return super().dispatch(request, *args, **kwargs)


class MetadataEditorMixin(LoginRequiredMixin):
    """
    Mixin for metadata editing operations.
    Requires archivist role or above.
    """
    def dispatch(self, request, *args, **kwargs):
        if request.user.role not in ['archivist', 'manager', 'super_manager', 'system_admin']:
            raise PermissionDenied("Metadata editing requires archivist role or above.")
        return super().dispatch(request, *args, **kwargs)


class BulkOperationsMixin(LoginRequiredMixin):
    """
    Mixin for bulk data operations (imports, transformations).
    Requires manager role or above.
    """
    def dispatch(self, request, *args, **kwargs):
        if request.user.role not in ['manager', 'super_manager', 'system_admin']:
            raise PermissionDenied("Bulk operations require manager role or above.")
        return super().dispatch(request, *args, **kwargs)


class DangerousOperationsMixin(LoginRequiredMixin):
    """
    Mixin for potentially dangerous operations (database resets, deletions).
    Requires system admin role.
    """
    def dispatch(self, request, *args, **kwargs):
        if request.user.role != 'system_admin':
            raise PermissionDenied("Dangerous operations require system administrator access.")
        return super().dispatch(request, *args, **kwargs)


class ReadOnlyMixin(LoginRequiredMixin):
    """
    Mixin for read-only views (dashboards, viewing data).
    Any authenticated user can access.
    """
    pass  # Just requires login, no additional restrictions


# ============================================================================
# DYNAMIC PERMISSION MIXIN
# ============================================================================

class PermissionRequiredMixin(LoginRequiredMixin):
    """
    Dynamic mixin that checks for specific permissions.
    Set required_permissions as a class attribute or override get_required_permissions().
    """
    required_permissions = []
    
    def get_required_permissions(self):
        """Override this method to dynamically determine required permissions."""
        return self.required_permissions
    
    def dispatch(self, request, *args, **kwargs):
        permissions = self.get_required_permissions()
        for permission in permissions:
            if not request.user.has_role_permission(permission):
                raise PermissionDenied(f"Permission '{permission}' required.")
        return super().dispatch(request, *args, **kwargs)


# ============================================================================
# DECORATORS FOR FUNCTION-BASED VIEWS
# ============================================================================

# Decorators for function-based views
def role_required(roles=None, permissions=None):
    """Decorator for function-based views requiring specific roles/permissions."""
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            if not request.user.is_authenticated:
                raise PermissionDenied("Authentication required")
            
            if roles and request.user.role not in roles:
                raise PermissionDenied(f"Role {request.user.role} not authorized")
            
            if permissions:
                for permission in permissions:
                    if not request.user.has_role_permission(permission):
                        raise PermissionDenied(f"Permission {permission} required")
            
            return view_func(request, *args, **kwargs)
        return wrapper
    return decorator


def admin_required(view_func):
    """Decorator requiring admin backend access."""
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            raise PermissionDenied("Authentication required")
        
        if not request.user.has_role_permission('can_access_admin_backend'):
            raise PermissionDenied("Administrative access required")
        
        return view_func(request, *args, **kwargs)
    return wrapper


def manager_required(view_func):
    """Decorator requiring manager role or above."""
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            raise PermissionDenied("Authentication required")
        
        if request.user.role not in ['manager', 'super_manager', 'system_admin']:
            raise PermissionDenied("Manager access required")
        
        return view_func(request, *args, **kwargs)
    return wrapper


def general_login_required(view_func):
    """
    General-purpose login required decorator for function-based views.
    Use this instead of @login_required for consistent error handling.
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            raise PermissionDenied("Authentication required")
        
        return view_func(request, *args, **kwargs)
    return wrapper


# ============================================================================
# FEATURE-SPECIFIC DECORATORS
# ============================================================================

def data_management_required(view_func):
    """Decorator for data management operations requiring archivist role or above."""
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            raise PermissionDenied("Authentication required")
        
        if request.user.role not in ['archivist', 'manager', 'super_manager', 'system_admin']:
            raise PermissionDenied("Data management access requires archivist role or above.")
        
        return view_func(request, *args, **kwargs)
    return wrapper


def metadata_editor_required(view_func):
    """Decorator for metadata editing operations requiring archivist role or above."""
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            raise PermissionDenied("Authentication required")
        
        if request.user.role not in ['archivist', 'manager', 'super_manager', 'system_admin']:
            raise PermissionDenied("Metadata editing requires archivist role or above.")
        
        return view_func(request, *args, **kwargs)
    return wrapper


def bulk_operations_required(view_func):
    """Decorator for bulk operations requiring manager role or above."""
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            raise PermissionDenied("Authentication required")
        
        if request.user.role not in ['manager', 'super_manager', 'system_admin']:
            raise PermissionDenied("Bulk operations require manager role or above.")
        
        return view_func(request, *args, **kwargs)
    return wrapper


def dangerous_operations_required(view_func):
    """Decorator for dangerous operations requiring system admin role."""
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            raise PermissionDenied("Authentication required")

        if request.user.role != 'system_admin':
            raise PermissionDenied("Dangerous operations require system administrator access.")

        return view_func(request, *args, **kwargs)
    return wrapper


# ============================================================================
# ORGANIZATION ACCESS CONTROL
# ============================================================================

def can_access_organization(user, organization_code: str) -> bool:
    """
    Check if user can access the given organization's bucket.

    Rules:
    - Superusers can access any organization
    - Regular users can only access their own organization's bucket

    Args:
        user: The authenticated user
        organization_code: The organization code (e.g., 'rsh', 'fuk', 'khm')

    Returns:
        True if user can access the organization, False otherwise
    """
    if not user.is_authenticated:
        return False

    if user.is_superuser:
        return True

    user_org = getattr(user, 'organization', None)
    if user_org and user_org.code == organization_code:
        return True

    return False


def get_accessible_organizations(user):
    """
    Get list of organizations the user can access.

    Rules:
    - Superusers can access all active organizations
    - Regular users can only access their own organization

    Args:
        user: The authenticated user

    Returns:
        QuerySet of Organization objects the user can access
    """
    from arkumu.users.models import Organization

    if not user.is_authenticated:
        return Organization.objects.none()

    if user.is_superuser:
        return Organization.objects.filter(is_active=True)

    user_org = getattr(user, 'organization', None)
    if user_org:
        return Organization.objects.filter(id=user_org.id, is_active=True)

    return Organization.objects.none()


def organization_access_required(view_func):
    """
    Decorator that checks if user can access the organization specified in the request.

    Looks for organization in:
    - URL kwargs: 'organization'
    - GET params: 'organization' or 'org'
    - POST params: 'organization' or 'org'
    - bucket_type URL kwarg starting with 'org-'
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            raise PermissionDenied("Authentication required")

        # Try to find organization code from various sources
        org_code = None

        # Check URL kwargs
        if 'organization' in kwargs:
            org_code = kwargs['organization']
        elif 'bucket_type' in kwargs and kwargs['bucket_type'].startswith('org-'):
            org_code = kwargs['bucket_type'][4:]  # Remove 'org-' prefix

        # Check GET params
        if not org_code:
            org_code = request.GET.get('organization') or request.GET.get('org')

        # Check POST params
        if not org_code:
            org_code = request.POST.get('organization') or request.POST.get('org')

        # If no organization specified, allow (view will handle it)
        if not org_code:
            return view_func(request, *args, **kwargs)

        # Check access
        if not can_access_organization(request.user, org_code):
            raise PermissionDenied(f"You don't have permission to access organization '{org_code}'")

        return view_func(request, *args, **kwargs)
    return wrapper


class OrganizationAccessMixin(LoginRequiredMixin):
    """
    Mixin that checks if user can access the organization specified in the request.
    """

    def get_organization_code(self):
        """Get organization code from request. Override in subclass if needed."""
        # Check URL kwargs
        if 'organization' in self.kwargs:
            return self.kwargs['organization']
        if 'bucket_type' in self.kwargs and self.kwargs['bucket_type'].startswith('org-'):
            return self.kwargs['bucket_type'][4:]

        # Check GET/POST params
        return (
            self.request.GET.get('organization') or
            self.request.GET.get('org') or
            self.request.POST.get('organization') or
            self.request.POST.get('org')
        )

    def dispatch(self, request, *args, **kwargs):
        org_code = self.get_organization_code()

        if org_code and not can_access_organization(request.user, org_code):
            raise PermissionDenied(f"You don't have permission to access organization '{org_code}'")

        return super().dispatch(request, *args, **kwargs)
 