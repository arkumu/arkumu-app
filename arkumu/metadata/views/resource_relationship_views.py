from django.shortcuts import get_object_or_404
from django.http import HttpResponse
from django.views import View
from django.views.generic import TemplateView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.paginator import Paginator
from django.db.models import Q
from django.utils.decorators import method_decorator
from django.views.decorators.cache import cache_page
from django.views.decorators.vary import vary_on_headers
from django.core.exceptions import PermissionDenied
from django.template.loader import render_to_string
from django.middleware.csrf import get_token
import logging

from arkumu.metadata.models.resource import Resource, ResourceType
from arkumu.metadata.models.triples import Triple
from arkumu.metadata.models.mappings import Mapping
from arkumu.metadata.services.resource_relationship_service import ResourceRelationshipService
from arkumu.users.mixins import GeneralLoginRequiredMixin
from arkumu.metadata.views.csv_mapping.mixins.template_helpers import CSVMappingTemplateHelperMixin

logger = logging.getLogger(__name__)


class ResourceRelationshipExplorerView(GeneralLoginRequiredMixin, CSVMappingTemplateHelperMixin, TemplateView):
    """
    Main relationship explorer page.
    GET /metadata/resources/<uuid:resource_id>/relationships/
    """
    template_name = 'metadata/relationships/explorer.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        resource_id = kwargs.get('resource_id')
        
        try:
            # Get the resource
            resource = get_object_or_404(Resource, id=resource_id)
            
            # Check permissions
            if not self._can_access_resource(self.request.user, resource):
                raise PermissionDenied("You don't have permission to access this resource")
            
            # Get organization filter
            organization = self._get_organization_filter(self.request.user, resource)
            
            # Use the service to get initial relationships
            service = ResourceRelationshipService()
            relationships = service.get_related_resources(
                resource.uri,
                max_depth=1,  # Start with depth 1 for initial load
                organization=None  # Don't filter by organization - this was the problem!
            )
            
            # Extract the related resources from the relationships structure
            related_resources = []
            if relationships and 'relationships' in relationships:
                outgoing = relationships['relationships'].get('outgoing', [])
                incoming = relationships['relationships'].get('incoming', [])
                
                # Transform the relationship objects to match template expectations
                for rel in outgoing:
                    target = rel.get('target', {}).copy()  # Create a copy to avoid modifying original
                    target['relationship_type'] = rel.get('relationship_type', 'Connected')
                    target['direction'] = 'outgoing'
                    related_resources.append(target)
                
                for rel in incoming:
                    # For incoming relationships, the related resource is in 'source', not 'target'
                    source = rel.get('source', {}).copy()  # Create a copy to avoid modifying original
                    source['relationship_type'] = rel.get('relationship_type', 'Connected')
                    source['direction'] = 'incoming'
                    related_resources.append(source)
            
            context.update({
                'resource': resource,
                'relationships': relationships,
                'related_resources': related_resources,
                'organization_id': organization or (resource.organization.code if resource.organization else None),
                'max_depth_options': [1, 2, 3],
                'current_depth': 1,
            })
            
        except Resource.DoesNotExist:
            raise PermissionDenied("Resource not found")
        except Exception as e:
            logger.error(f"Error loading relationship explorer for resource {resource_id}: {str(e)}")
            raise
        
        return context
    
    def _can_access_resource(self, user, resource):
        """Check if user can access the resource."""
        # Django superusers can access everything
        if user.is_superuser:
            return True
        
        # System admins can access everything
        if getattr(user, 'role', None) == 'system_admin':
            return True
        
        # Users can access their organization's resources
        if user.organization:
            # Check both organization field and source field
            if resource.organization_id == user.organization.id:
                return True
            if resource.organization and resource.organization.code == user.organization.code:
                return True
        
        # Users can access public resources
        if hasattr(resource, 'is_publicly_accessible') and resource.is_publicly_accessible:
            return True
        
        # Users can access restricted resources if authenticated
        if hasattr(resource, 'public_access_level') and resource.public_access_level == 'restricted':
            return True
        
        # Users can access public resources
        if hasattr(resource, 'public_access_level') and resource.public_access_level == 'public':
            return True
        
        return False
    
    def _get_organization_filter(self, user, resource):
        """Get organization filter for the user."""
        # System admins see everything
        if getattr(user, 'role', None) == 'system_admin':
            return None
        
        # Regular users see their organization's data
        if user.organization:
            return user.organization.code
        
        return None


class RelatedResourcesHTMXView(GeneralLoginRequiredMixin, CSVMappingTemplateHelperMixin, View):
    """
    HTMX view for getting related resources.
    GET /metadata/resources/<uuid:resource_id>/related/
    """
    
    def get(self, request, resource_id):
        try:
            # Get the resource
            resource = get_object_or_404(Resource, id=resource_id)
            
            # Check permissions
            if not self._can_access_resource(request.user, resource):
                raise PermissionDenied("You don't have permission to access this resource")
            
            # Get query parameters
            relationship_type = request.GET.get('relationship_type', '')
            page = int(request.GET.get('page', 1))
            per_page = int(request.GET.get('per_page', 20))
            organization = self._get_organization_filter(request.user, resource)
            
            # Use the service to get related resources
            service = ResourceRelationshipService()
            
            if relationship_type:
                related_resources = service.find_resources_by_relationship(
                    resource.uri,
                    relationship_type=relationship_type,
                    organization=organization
                )
            else:
                relationships = service.get_bidirectional_relationships(
                    resource.uri,
                    organization=organization
                )
                related_resources = relationships.get('outgoing', []) + relationships.get('incoming', [])
            
            # Paginate results
            paginator = Paginator(related_resources, per_page)
            page_obj = paginator.get_page(page)
            
            # Render the template
            html = self.render_related_resources_template(
                request, resource, page_obj, paginator, organization
            )
            
            return HttpResponse(html)
            
        except Resource.DoesNotExist:
            return HttpResponse(
                '<div class="alert alert-error">Resource not found</div>',
                status=404
            )
        except PermissionDenied as e:
            return HttpResponse(
                f'<div class="alert alert-error">{str(e)}</div>',
                status=403
            )
        except Exception as e:
            logger.error(f"Error getting related resources for {resource_id}: {str(e)}")
            return HttpResponse(
                '<div class="alert alert-error">An error occurred while loading related resources</div>',
                status=500
            )
    
    def render_related_resources_template(self, request, resource, page_obj, paginator, organization):
        """Render related resources template using template helper pattern."""
        context = {
            'resource': resource,
            'related_resources': page_obj,
            'paginator': paginator,
            'organization_id': organization or (resource.organization.code if resource.organization else None),
            'csrf_token': get_token(request),
        }
        
        return render_to_string(
            'metadata/relationships/partials/related_resources.html',
            context,
            request=request
        )
    
    def _can_access_resource(self, user, resource):
        """Check if user can access the resource."""
        # Django superusers can access everything
        if user.is_superuser:
            return True
        
        # System admins can access everything
        if getattr(user, 'role', None) == 'system_admin':
            return True
        
        # Users can access their organization's resources
        if user.organization:
            # Check both organization field and source field
            if resource.organization_id == user.organization.id:
                return True
            if resource.organization and resource.organization.code == user.organization.code:
                return True
        
        # Users can access public resources
        if hasattr(resource, 'is_publicly_accessible') and resource.is_publicly_accessible:
            return True
        
        # Users can access restricted resources if authenticated
        if hasattr(resource, 'public_access_level') and resource.public_access_level == 'restricted':
            return True
        
        # Users can access public resources
        if hasattr(resource, 'public_access_level') and resource.public_access_level == 'public':
            return True
        
        return False
    
    def _get_organization_filter(self, user, resource):
        """Get organization filter for the user."""
        # System admins see everything
        if getattr(user, 'role', None) == 'system_admin':
            return None
        
        # Regular users see their organization's data
        if user.organization:
            return user.organization.code
        
        return None


class RelationshipChainHTMXView(GeneralLoginRequiredMixin, CSVMappingTemplateHelperMixin, View):
    """
    HTMX view for getting relationship chain between two resources.
    GET /metadata/resources/<uuid:resource_id>/chain/<uuid:target_id>/
    """
    
    def get(self, request, resource_id, target_id):
        try:
            # Get both resources
            resource = get_object_or_404(Resource, id=resource_id)
            target_resource = get_object_or_404(Resource, id=target_id)
            
            # Check permissions for both resources
            if not (self._can_access_resource(request.user, resource) and 
                    self._can_access_resource(request.user, target_resource)):
                raise PermissionDenied("You don't have permission to access one or both resources")
            
            # Get organization filter
            organization = self._get_organization_filter(request.user, resource)
            
            # Use the service to get the chain
            service = ResourceRelationshipService()
            chain = service.get_relationship_chain(
                resource.uri,
                target_resource.uri,
                organization=organization
            )
            
            # Render the template
            html = self.render_chain_template(request, resource, target_resource, chain, organization)
            
            return HttpResponse(html)
            
        except Resource.DoesNotExist:
            return HttpResponse(
                '<div class="alert alert-error">Resource not found</div>',
                status=404
            )
        except PermissionDenied as e:
            return HttpResponse(
                f'<div class="alert alert-error">{str(e)}</div>',
                status=403
            )
        except Exception as e:
            logger.error(f"Error getting chain from {resource_id} to {target_id}: {str(e)}")
            return HttpResponse(
                '<div class="alert alert-error">An error occurred while loading the relationship chain</div>',
                status=500
            )
    
    def render_chain_template(self, request, resource, target_resource, chain, organization):
        """Render chain template using template helper pattern."""
        context = {
            'source': resource,
            'target': target_resource,
            'chain': chain,
            'organization_id': organization or (resource.organization.code if resource.organization else None),
            'csrf_token': get_token(request),
        }
        
        return render_to_string(
            'metadata/relationships/partials/relationship_chain.html',
            context,
            request=request
        )
    
    def _can_access_resource(self, user, resource):
        """Check if user can access the resource."""
        # Django superusers can access everything
        if user.is_superuser:
            return True
        
        # System admins can access everything
        if getattr(user, 'role', None) == 'system_admin':
            return True
        
        # Users can access their organization's resources
        if user.organization:
            # Check both organization field and source field
            if resource.organization_id == user.organization.id:
                return True
            if resource.organization and resource.organization.code == user.organization.code:
                return True
        
        # Users can access public resources
        if hasattr(resource, 'is_publicly_accessible') and resource.is_publicly_accessible:
            return True
        
        # Users can access restricted resources if authenticated
        if hasattr(resource, 'public_access_level') and resource.public_access_level == 'restricted':
            return True
        
        # Users can access public resources
        if hasattr(resource, 'public_access_level') and resource.public_access_level == 'public':
            return True
        
        return False
    
    def _get_organization_filter(self, user, resource):
        """Get organization filter for the user."""
        # System admins see everything
        if getattr(user, 'role', None) == 'system_admin':
            return None
        
        # Regular users see their organization's data
        if user.organization:
            return user.organization.code
        
        return None


class MappingRelationshipsHTMXView(GeneralLoginRequiredMixin, CSVMappingTemplateHelperMixin, View):
    """
    HTMX view for getting relationships defined in a mapping.
    GET /metadata/mappings/<mapping_id>/relationships/
    """
    
    def get(self, request, mapping_id):
        try:
            # Get the mapping
            mapping = get_object_or_404(Mapping, id=mapping_id)
            
            # Check permissions
            if not self._can_access_mapping(request.user, mapping):
                raise PermissionDenied("You don't have permission to access this mapping")
            
            # Use the service to get mapping relationships
            service = ResourceRelationshipService()
            relationships = service.get_mapping_relationships(str(mapping.id))
            
            # Render the template
            html = self.render_mapping_relationships_template(request, mapping, relationships)
            
            return HttpResponse(html)
            
        except Mapping.DoesNotExist:
            return HttpResponse(
                '<div class="alert alert-error">Mapping not found</div>',
                status=404
            )
        except PermissionDenied as e:
            return HttpResponse(
                f'<div class="alert alert-error">{str(e)}</div>',
                status=403
            )
        except Exception as e:
            logger.error(f"Error getting mapping relationships for {mapping_id}: {str(e)}")
            return HttpResponse(
                '<div class="alert alert-error">An error occurred while loading mapping relationships</div>',
                status=500
            )
    
    def render_mapping_relationships_template(self, request, mapping, relationships):
        """Render mapping relationships template using template helper pattern."""
        context = {
            'mapping': mapping,
            'relationships': relationships,
            'organization_id': mapping.organization_id,
            'csrf_token': get_token(request),
        }
        
        return render_to_string(
            'metadata/relationships/partials/mapping_relationships.html',
            context,
            request=request
        )
    
    def _can_access_mapping(self, user, mapping):
        """Check if user can access the mapping."""
        # System admins can access everything
        if getattr(user, 'role', None) == 'system_admin':
            return True
        
        # Users can access their organization's mappings
        if user.organization and mapping.organization_id == user.organization.code:
            return True
        
        return False


class OrganizationRelationshipTypesHTMXView(GeneralLoginRequiredMixin, CSVMappingTemplateHelperMixin, View):
    """
    HTMX view for getting all relationship types used by an organization.
    GET /metadata/organizations/<str:org_code>/relationship-types/
    """
    
    def get(self, request, org_code):
        try:
            # Check permissions
            if not self._can_access_organization(request.user, org_code):
                raise PermissionDenied("You don't have permission to access this organization's data")
            
            # Use the service to get relationship types
            service = ResourceRelationshipService()
            relationship_types = service.get_organization_relationship_types(org_code)
            
            # Render the template
            html = self.render_relationship_types_template(request, org_code, relationship_types)
            
            return HttpResponse(html)
            
        except PermissionDenied as e:
            return HttpResponse(
                f'<div class="alert alert-error">{str(e)}</div>',
                status=403
            )
        except Exception as e:
            logger.error(f"Error getting relationship types for organization {org_code}: {str(e)}")
            return HttpResponse(
                '<div class="alert alert-error">An error occurred while loading relationship types</div>',
                status=500
            )
    
    def render_relationship_types_template(self, request, org_code, relationship_types):
        """Render relationship types template using template helper pattern."""
        context = {
            'organization': org_code,
            'relationship_types': relationship_types,
            'organization_id': org_code,
            'csrf_token': get_token(request),
        }
        
        return render_to_string(
            'metadata/relationships/partials/relationship_types.html',
            context,
            request=request
        )
    
    def _can_access_organization(self, user, org_code):
        """Check if user can access the organization's data."""
        # System admins can access everything
        if getattr(user, 'role', None) == 'system_admin':
            return True
        
        # Users can access their own organization's data
        if user.organization and user.organization.code == org_code:
            return True
        
        return False