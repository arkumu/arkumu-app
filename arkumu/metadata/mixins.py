from django.core.exceptions import PermissionDenied
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import Http404
from arkumu.users.mixins import AdminRequiredMixin, PublicApprovalMixin
from .models.resource import Resource
from .utils import get_public_catalog_queryset, get_user_accessible_resources


class PublicCatalogMixin(LoginRequiredMixin):
    """
    Mixin for catalog views requiring authentication.
    Shows publicly approved resources to authenticated users only.
    """
    
    def get_queryset(self):
        """Return publicly accessible resources for authenticated users only."""
        if hasattr(super(), 'get_queryset'):
            base_queryset = super().get_queryset()
        else:
            base_queryset = Resource.objects.all()
            
        # Only authenticated users can access catalog
        return get_user_accessible_resources(self.request.user)
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['is_public_catalog'] = True
        context['show_edit_controls'] = (
            self.request.user.has_role_permission('can_edit_org_data')
        )
        return context


class RestrictedCatalogMixin(LoginRequiredMixin):
    """
    Mixin for authenticated-only catalog views.
    Shows public + restricted + organization resources.
    """
    
    def get_queryset(self):
        if hasattr(super(), 'get_queryset'):
            base_queryset = super().get_queryset()
        else:
            base_queryset = Resource.objects.all()
            
        return get_user_accessible_resources(self.request.user)


class OrganizationResourceMixin(LoginRequiredMixin):
    """
    Mixin for organization-scoped resource access.
    Users can only see resources from their organization.
    """
    
    def get_queryset(self):
        if hasattr(super(), 'get_queryset'):
            base_queryset = super().get_queryset()
        else:
            base_queryset = Resource.objects.all()
        
        user = self.request.user
        
        # System admins see everything
        if user.role == 'system_admin':
            return base_queryset
        
        # Users see only their organization's resources
        if user.organization:
            return base_queryset.filter(source=user.organization.code)
        
        return base_queryset.none()


class ResourceOwnershipMixin:
    """
    Mixin that ensures users can only access resources they have permissions for.
    Automatically filters based on user role and organization.
    """
    
    def get_object(self, queryset=None):
        """Override to check resource-level permissions."""
        obj = super().get_object(queryset)
        
        # Check if user can view this specific resource
        if not obj.can_user_view(self.request.user):
            raise Http404("Resource not found or access denied.")
        
        return obj


class EditPermissionMixin(ResourceOwnershipMixin):
    """
    Mixin that ensures users can only edit resources they have permission for.
    """
    
    def get_object(self, queryset=None):
        """Override to check edit permissions."""
        obj = super().get_object(queryset)
        
        # Check if user can edit this specific resource
        if not obj.can_user_edit(self.request.user):
            raise PermissionDenied("You don't have permission to edit this resource.")
        
        return obj


class DeletePermissionMixin(ResourceOwnershipMixin):
    """
    Mixin that ensures users can only delete resources they have permission for.
    """
    
    def get_object(self, queryset=None):
        """Override to check delete permissions."""
        obj = super().get_object(queryset)
        
        # Check if user can delete this specific resource
        if not obj.can_user_delete(self.request.user):
            raise PermissionDenied("You don't have permission to delete this resource.")
        
        return obj


class BulkActionMixin:
    """
    Mixin for views that perform bulk actions on resources.
    Ensures bulk operations respect permission boundaries.
    """
    
    def get_actionable_queryset(self, resource_ids):
        """Get resources that the current user can perform actions on."""
        queryset = self.get_queryset().filter(id__in=resource_ids)
        
        # Filter to only resources the user can edit
        actionable_resources = []
        for resource in queryset:
            if resource.can_user_edit(self.request.user):
                actionable_resources.append(resource.id)
        
        return Resource.objects.filter(id__in=actionable_resources)


# Composed mixins for common patterns
class PublicCatalogDetailMixin(PublicCatalogMixin, ResourceOwnershipMixin):
    """
    Combined mixin for catalog detail views.
    Requires authentication and respects resource permissions.
    """
    pass


class AdminResourceListMixin(AdminRequiredMixin, OrganizationResourceMixin):
    """
    Combined mixin for admin resource list views.
    Requires admin access and filters to organization resources.
    """
    pass


class AdminResourceDetailMixin(AdminRequiredMixin, OrganizationResourceMixin, EditPermissionMixin):
    """
    Combined mixin for admin resource detail views with edit capabilities.
    """
    pass


class AdminResourceDeleteMixin(AdminRequiredMixin, OrganizationResourceMixin, DeletePermissionMixin):
    """
    Combined mixin for admin resource delete views.
    """
    pass


class PublicApprovalWorkflowMixin(PublicApprovalMixin, OrganizationResourceMixin, BulkActionMixin):
    """
    Combined mixin for public approval workflow views.
    Allows managers to bulk approve resources for public catalog.
    """
    pass 