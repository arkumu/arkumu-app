"""
Catalog views using harmonization rules for unified resource browsing.
"""

from django.views.generic import ListView, DetailView, TemplateView, View
from django.shortcuts import get_object_or_404
from django.db.models import Q
from django.core.cache import cache
from django.http import Http404, HttpResponse
from django.template.loader import render_to_string
from django.middleware.csrf import get_token

from arkumu.users.mixins import GeneralLoginRequiredMixin
from arkumu.metadata.services.catalog_navigation_service import CatalogNavigationService
from arkumu.metadata.services.faceted_search_service import FacetedSearchService
from arkumu.metadata.models import Resource


class CatalogSearchMixin:
    """Mixin for live search updates using HTMX."""
    
    def build_oob_response(self, main_html, oob_updates=None):
        """Build response with out-of-band updates."""
        if not oob_updates:
            return main_html
        
        oob_html = ""
        for target_id, content in oob_updates.items():
            oob_html += f'<div id="{target_id}" hx-swap-oob="innerHTML">{content}</div>'
        
        return f'{main_html}{oob_html}'
    
    def render_search_results_template(self, request, results, result_count, search_query, selected_type, selected_facets):
        """Render search results template."""
        context = {
            'results': results,
            'result_count': result_count,
            'search_query': search_query,
            'selected_type': selected_type,
            'selected_facets': selected_facets,
            'csrf_token': get_token(request),
        }
        
        return render_to_string(
            'catalog/partials/search_results_list.html',
            context,
            request=request
        )
    
    def render_search_sidebar_template(self, request, resource_type, all_properties, searchable_properties, facets, selected_facets, selected_search_property, available_types):
        """Render search sidebar template with dynamic properties and facets."""
        context = {
            'selected_type': resource_type,
            'all_properties': all_properties,
            'searchable_properties': searchable_properties,
            'facets': facets,
            'selected_facets': selected_facets,
            'selected_search_property': selected_search_property,
            'available_types': available_types,
            'csrf_token': get_token(request),
        }
        
        return render_to_string(
            'catalog/partials/search_sidebar.html',
            context,
            request=request
        )


class CatalogOverviewView(GeneralLoginRequiredMixin, TemplateView):
    """Dashboard showing harmonized resource counts and navigation."""
    
    template_name = 'catalog/overview.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # Use caching for expensive operations
        cache_key = f'catalog_overview_{self.request.user.id}'
        cached_data = cache.get(cache_key)
        
        if cached_data:
            context.update(cached_data)
        else:
            service = CatalogNavigationService(self.request.user)
            
            # Get resource counts by type
            resource_counts = service.get_resource_counts_by_type()
            
            # Get recent projects for quick access
            recent_projects = service.get_all_projects(
                include_events=False,
                include_participants=False,
                include_documents=False
            )[:5]  # Limit to 5 for overview
            
            data = {
                'resource_counts': resource_counts,
                'recent_projects': recent_projects,
                'total_resources': sum(resource_counts.values()),
            }
            
            # Cache for 30 minutes
            cache.set(cache_key, data, 30 * 60)
            context.update(data)
        
        return context


class HarmonizedResourceListView(GeneralLoginRequiredMixin, ListView):
    """List view for harmonized resources with filtering."""
    
    template_name = 'catalog/resource_list.html'
    context_object_name = 'resources'
    paginate_by = 20
    
    def get_queryset(self):
        service = CatalogNavigationService(self.request.user)
        resource_type = self.kwargs.get('resource_type') or self.request.GET.get('type')
        org_code = self.kwargs.get('org_code') or self.request.GET.get('org')
        search_query = self.request.GET.get('q')
        
        # Handle search
        if search_query:
            # Determine resource types to search
            search_types = []
            if resource_type:
                type_mapping = {
                    'Project': service.ARKUMU_PROJECT,
                    'Event': service.ARKUMU_EVENT,
                    'Person': service.ARKUMU_PERSON,
                    'Organization': service.ARKUMU_ORGANIZATION,
                    'Document': service.ARKUMU_DOCUMENT,
                }
                search_types = [type_mapping.get(resource_type)]
            
            return service.search_resources(
                query=search_query,
                resource_types=search_types,
                limit=self.paginate_by * 10  # Allow for pagination
            )
        
        # Handle specific resource type requests
        if resource_type == 'Project':
            return service.get_all_projects(
                include_events=True,
                include_participants=True,
                include_documents=False
            )
        elif resource_type == 'Event':
            return service.get_all_events() if hasattr(service, 'get_all_events') else Resource.objects.none()
        elif resource_type == 'Person':
            return service.get_all_persons() if hasattr(service, 'get_all_persons') else Resource.objects.none()
        elif resource_type == 'Organization':
            return Resource.objects.none()  # Not implemented in original service
        elif resource_type == 'Document':
            return Resource.objects.none()  # Not implemented in original service
        
        # Default: get all projects as the primary resource type
        return service.get_all_projects(
            include_events=True,
            include_participants=True,
            include_documents=False
        )
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        service = CatalogNavigationService(self.request.user)
        
        # Add filter context
        context['current_type'] = self.kwargs.get('resource_type') or self.request.GET.get('type')
        context['current_org'] = self.kwargs.get('org_code') or self.request.GET.get('org')
        context['search_query'] = self.request.GET.get('q')
        
        # Add resource counts for navigation
        context['resource_counts'] = service.get_resource_counts_by_type()
        
        # Add available resource types
        context['resource_types'] = [
            {'key': 'Project', 'label': 'Projects', 'count': context['resource_counts'].get('projects', 0)},
            {'key': 'Event', 'label': 'Events', 'count': context['resource_counts'].get('events', 0)},
            {'key': 'Person', 'label': 'Persons', 'count': context['resource_counts'].get('persons', 0)},
            {'key': 'Organization', 'label': 'Organizations', 'count': context['resource_counts'].get('organizations', 0)},
            {'key': 'Document', 'label': 'Documents', 'count': context['resource_counts'].get('documents', 0)},
        ]
        
        return context


class HarmonizedResourceDetailView(GeneralLoginRequiredMixin, DetailView):
    """Detail view showing full resource graph."""
    
    template_name = 'catalog/resource_detail.html'
    context_object_name = 'resource'
    
    def get_object(self):
        # Get resource URI from URL path
        resource_uri = self.kwargs.get('resource_uri')
        if not resource_uri:
            raise Http404("Resource URI not provided")
        
        # Decode if needed (URLs might encode special characters)
        import urllib.parse
        resource_uri = urllib.parse.unquote(resource_uri)
        
        # Get resource with access control
        try:
            if not self.request.user.is_authenticated:
                resource = Resource.objects.filter(
                    uri=resource_uri,
                    public_access_level='PUBLIC',
                    is_public_approved=True
                ).first()
            else:
                # Use proper access control logic
                from django.db.models import Q
                q = Q(uri=resource_uri)
                
                # Add organization filter if user has organization
                if hasattr(self.request.user, 'organization') and self.request.user.organization:
                    org_filter = Q(organization=self.request.user.organization)
                else:
                    org_filter = Q()
                
                public_filter = Q(
                    public_access_level__in=['PUBLIC', 'RESTRICTED'],
                    is_public_approved=True
                )
                
                resource = Resource.objects.filter(q & (org_filter | public_filter)).first()
            
            if not resource:
                raise Http404(f"Resource not found: {resource_uri}")
                
            return resource
            
        except Exception as e:
            raise Http404(f"Error retrieving resource: {str(e)}")
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        service = CatalogNavigationService(self.request.user)
        
        # Get full resource graph
        resource_graph = service.get_project_with_full_graph(
            self.object.uri, 
            depth=2
        )
        
        if resource_graph:
            context['resource_graph'] = resource_graph
            context['relationships'] = resource_graph.get('project', {}).get('relationships', {})
            context['related_resources'] = resource_graph.get('related_resources', {})
        
        # Add breadcrumb information
        context['breadcrumbs'] = [
            {'label': 'Catalog', 'url': '/catalog/'},
            {'label': 'Resources', 'url': '/catalog/resources/'},
            {'label': self.object.uri, 'url': None},  # Current page
        ]
        
        return context


class HarmonizedSearchView(GeneralLoginRequiredMixin, ListView):
    """Faceted search across harmonized resources."""
    
    template_name = 'catalog/search_results.html'
    context_object_name = 'results'
    paginate_by = 20
    
    def get_queryset(self):
        query = self.request.GET.get('q', '').strip()
        resource_type = self.request.GET.get('type', '').strip()
        
        service = FacetedSearchService(self.request.user)
        
        # Get facet filters
        facet_filters = {}
        for facet_key in ['projektart-calc', 'faechergruppe', 'rechtsstatus', 'originaltitel-sprache', 'eventname']:
            values = self.request.GET.getlist(facet_key)
            if values:
                facet_filters[facet_key] = values
        
        # Perform faceted search
        return service.search_with_facets(
            query=query,
            resource_type=resource_type,
            facet_filters=facet_filters,
            limit=self.paginate_by * 10  # Allow for pagination
        )
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        service = FacetedSearchService(self.request.user)
        
        # Add search context
        context['search_query'] = self.request.GET.get('q', '')
        context['selected_type'] = self.request.GET.get('type', '')
        
        # Add basic type selection
        base_service = CatalogNavigationService(self.request.user)
        context['resource_counts'] = base_service.get_resource_counts_by_type()
        context['available_types'] = [
            {'key': 'projects', 'label': 'Projects', 'count': context['resource_counts'].get('projects', 0)},
            {'key': 'events', 'label': 'Events', 'count': context['resource_counts'].get('events', 0)},
        ]
        
        # Add dynamic property data based on selected type
        selected_type = context['selected_type']
        if selected_type in ['projects', 'events']:
            # Get all properties and separate into searchable vs facetable
            all_properties = service.discover_and_cache_properties(selected_type)
            
            context['all_properties'] = all_properties  # For template access to labels
            context['searchable_properties'] = {
                key: prop_config for key, prop_config in all_properties.items()
                if prop_config['is_searchable']
            }
            
            context['facets'] = service.get_all_facet_values(selected_type)
            
            # Add currently selected search property
            context['selected_search_property'] = self.request.GET.get('search_property', 'all_properties')
            
            # Add currently selected facet values
            context['selected_facets'] = {}
            for prop_key, prop_config in all_properties.items():
                if prop_config['is_facetable']:
                    selected_values = self.request.GET.getlist(prop_key)
                    if selected_values:
                        context['selected_facets'][prop_key] = selected_values
        else:
            context['all_properties'] = {}
            context['searchable_properties'] = {}
            context['facets'] = {}
            context['selected_facets'] = {}
            context['selected_search_property'] = 'all_properties'
        
        # Add result statistics
        if hasattr(self, 'object_list') and self.object_list is not None:
            context['result_count'] = self.object_list.count() if hasattr(self.object_list, 'count') else len(self.object_list)
        else:
            context['result_count'] = 0
        
        return context


class LiveSearchFilterView(GeneralLoginRequiredMixin, CatalogSearchMixin, View):
    """HTMX endpoint for live search filtering."""
    
    def get(self, request, *args, **kwargs):
        """Handle live filter updates."""
        query = request.GET.get('q', '').strip()
        resource_type = request.GET.get('type', '').strip()
        search_property = request.GET.get('search_property', '').strip()
        
        service = FacetedSearchService(request.user)
        
        # Get all properties dynamically
        all_properties = service.discover_and_cache_properties(resource_type) if resource_type else {}
        
        # Get facet filters - only from facetable properties
        facet_filters = {}
        selected_facets = {}
        for prop_key, prop_config in all_properties.items():
            if prop_config['is_facetable']:
                values = request.GET.getlist(prop_key)
                if values:
                    facet_filters[prop_key] = values
                    selected_facets[prop_key] = values
        
        # Perform search
        results = service.search_with_facets(
            query=query,
            resource_type=resource_type,
            search_property=search_property,
            facet_filters=facet_filters,
            limit=50
        )
        
        # Get updated facets based on current filters
        facets = {}
        if resource_type in ['projects', 'events']:
            facets = service.get_all_facet_values(resource_type)
        
        # Get available types (for sidebar)
        base_service = CatalogNavigationService(request.user)
        resource_counts = base_service.get_resource_counts_by_type()
        available_types = [
            {'key': 'projects', 'label': 'Projects', 'count': resource_counts.get('projects', 0)},
            {'key': 'events', 'label': 'Events', 'count': resource_counts.get('events', 0)},
        ]
        
        # Prepare searchable properties
        searchable_properties = {
            key: prop_config for key, prop_config in all_properties.items()
            if prop_config['is_searchable']
        }
        
        # Render templates
        results_html = self.render_search_results_template(
            request, results, results.count(), query, resource_type, selected_facets
        )
        
        # Render sidebar with updated facets
        sidebar_html = self.render_search_sidebar_template(
            request, resource_type, all_properties, searchable_properties, 
            facets, selected_facets, search_property or 'all_properties', available_types
        )
        
        # Update the result count in the header
        count_html = f"""
        <div>
            <h2 class="text-xl font-semibold">
                {results.count()} result{'s' if results.count() != 1 else ''}
            </h2>
            {'<p class="text-sm text-base-content/60">Showing ' + resource_type + '</p>' if resource_type else ''}
        </div>
        """
        
        # Build OOB response with sidebar updates
        oob_updates = {
            'search-results': results_html,
            'result-count': count_html,
            'search-sidebar': sidebar_html,
        }
        
        return HttpResponse(self.build_oob_response("", oob_updates))