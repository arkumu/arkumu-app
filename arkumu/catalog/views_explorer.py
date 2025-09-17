"""
Catalog Explorer View for graph-based data exploration.

This view provides a graph search interface where users can search
for specific property values and explore connected data relationships.
"""

from typing import Dict, Any, Optional, List
import logging
from django.views.generic import TemplateView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse, HttpResponse
from django.template.loader import render_to_string
from django.core.paginator import Paginator

from arkumu.catalog.services.graph_search_service import GraphSearchService
from arkumu.cache.services import CatalogCacheService, SchemaMapCacheService
from arkumu.metadata.views.csv_mapping.mixins.template_helpers import CSVMappingTemplateHelperMixin


class CatalogExplorerView(LoginRequiredMixin, TemplateView, CSVMappingTemplateHelperMixin):
    """Graph-based data exploration view."""

    template_name = 'catalog/explorer_sidebar.html'
    logger = logging.getLogger(__name__)

    def get(self, request, *args, **kwargs):
        """Handle GET requests, including HTMX requests."""
        # For HTMX requests, handle them directly
        if request.headers.get('HX-Request'):
            return self._handle_htmx_request(request)

        # For normal requests, use the standard template rendering
        return super().get(request, *args, **kwargs)

    def _handle_htmx_request(self, request):
        """Handle HTMX requests for dynamic content updates using OOB."""
        hx_target = request.headers.get('HX-Target', '')
        selected_organization = request.GET.get('organization', '')

        self.logger.info(f"HTMX Request - Target: '{hx_target}', Organization: '{selected_organization}'")

        # Get context data
        context = self._get_context_data()

        # For organization changes, use OOB to update multiple sections
        if hx_target in ['classes-section', '#classes-section']:
            self.logger.info(f"Returning OOB updates for organization: {selected_organization}")

            # Render the main classes content
            classes_html = render_to_string('catalog/partials/classes_list.html', context, request=request)

            # Also clear the properties section since organization changed
            properties_html = ""  # Empty content to clear properties

            # Build manual OOB response using outerHTML to replace entire sections
            oob_classes = f'<div id="classes-section" hx-swap-oob="outerHTML">{classes_html}</div>'
            oob_properties = f'<div id="properties-section" hx-swap-oob="outerHTML">{properties_html}</div>'

            response_html = f"{oob_classes}{oob_properties}"
            self.logger.info(f"Manual OOB response length: {len(response_html)}")

            return HttpResponse(response_html)
        else:
            # Return full explorer content for other HTMX requests
            self.logger.info(f"Returning full explorer content for target: {hx_target}")
            content_html = render_to_string('catalog/partials/explorer_content.html', context, request=request)
            return HttpResponse(content_html)

    def _get_context_data(self) -> Dict[str, Any]:
        """Get context data for both normal and HTMX requests."""
        # Initialize services
        schema_cache = SchemaMapCacheService()

        # Get query parameters
        query = self.request.GET.get('q', '')
        property_name = self.request.GET.get('property', 'title')
        selected_class = self.request.GET.get('class', '')
        selected_organization = self.request.GET.get('organization', '')
        page = self.request.GET.get('page', 1)

        # Get comprehensive schema map (cached for 10 minutes)
        schema_map = schema_cache.get_complete_schema_map(selected_organization)

        # Extract data from schema map for faster access
        available_organizations = schema_map.get('organizations', {})
        available_types = list(schema_map.get('classes', {}).values())

        # Get properties for selected class from cache
        available_properties = []
        if selected_class and selected_class in schema_map.get('classes', {}):
            class_info = schema_map['classes'][selected_class]
            available_properties = list(class_info.get('properties', {}).values())

        # Log cache performance
        self.logger.debug(f"Schema map cache: {len(available_types)} classes, "
                         f"{len(available_properties)} properties for class {selected_class}")

        return {
            'available_classes': {item['uri']: {'name': item['name'], 'entity_count': item['entity_count']}
                                 for item in available_types},
            'available_properties': {item['uri']: {'name': item.get('name', item['uri']), 'usage_count': item.get('usage_count', 0)}
                                   for item in available_properties},
            'available_organizations': available_organizations,
            'selected_class': selected_class,
            'selected_property': property_name,
            'selected_organization': selected_organization,
            'schema_meta': schema_map.get('meta', {}),
            'has_results': False,
            'show_initial_message': True
        }

    def get_context_data(self, **kwargs) -> Dict[str, Any]:
        """Get context with graph search results using comprehensive schema map."""
        context = super().get_context_data(**kwargs)
        context.update(self._get_context_data())
        return context




class CatalogExplorerPropertiesView(LoginRequiredMixin, TemplateView):
    """HTMX endpoint for loading properties of a selected class."""

    def get(self, request, *args, **kwargs):
        """Return properties HTML for the selected class using cached schema map."""
        selected_class = request.GET.get('class', '')
        selected_organization = request.GET.get('organization', '')

        if not selected_class:
            return HttpResponse("")

        # Get properties from cached schema map or load them on demand
        schema_cache = SchemaMapCacheService()
        schema_map = schema_cache.get_complete_schema_map(selected_organization)

        available_properties = []
        if selected_class in schema_map.get('classes', {}):
            class_info = schema_map['classes'][selected_class]
            cached_properties = class_info.get('properties', {})

            if cached_properties:
                # Properties are cached, use them
                available_properties = list(cached_properties.values())
            else:
                # Properties not cached, load them on demand
                properties_map = schema_cache._get_properties_for_class_with_orgs(selected_class)
                available_properties = list(properties_map.values())

        context = {
            'available_properties': {item['uri']: {'name': item.get('name', item['uri']), 'usage_count': item.get('usage_count', 0)}
                                   for item in available_properties},
            'selected_class': selected_class,
            'selected_property': request.GET.get('property', ''),
        }

        html = render_to_string('catalog/partials/properties_list.html', context, request=request)
        return HttpResponse(html)


class CatalogExplorerLiteralsView(LoginRequiredMixin, TemplateView):
    """HTMX endpoint for browsing literal values of a selected property."""
    logger = logging.getLogger(__name__)

    def get(self, request, *args, **kwargs):
        """Return literal values HTML for the selected property."""
        property_uri = request.GET.get('property', '')
        class_uri = request.GET.get('class', '')
        organization_code = request.GET.get('organization', '')
        search_term = request.GET.get('search', '')
        page = int(request.GET.get('page', 1))
        per_page = 20  # Show 20 items per page with proper pagination

        if not property_uri:
            return HttpResponse("")

        # Get literal values for this property
        graph_service = GraphSearchService(user=request.user)
        catalog_cache = CatalogCacheService()

        # Get user organization for cache scoping
        user_org = request.user.organization.code if hasattr(request.user, 'organization') and request.user.organization else None

        try:
            # Calculate offset for database-level pagination
            offset = (page - 1) * per_page

            # Try to get cached search results first
            cache_key_params = f"{property_uri}_{class_uri}_{organization_code}_{search_term}_{offset}_{per_page}"
            cached_results = catalog_cache.get_cached_search_results(
                query=cache_key_params,
                property_name=property_uri,
                selected_class=class_uri or '',
                user_org=user_org
            )

            if cached_results:
                self.logger.debug(f"Using cached search results for {property_uri}")
                literals_data = cached_results['results']
            else:
                # Cache miss - get from graph service
                self.logger.debug(f"Cache miss - fetching search results for {property_uri}")
                literals_data = graph_service.browse_property_values(
                    property_uri=property_uri,
                    class_uri=class_uri if class_uri else None,
                    organization_code=organization_code if organization_code else None,
                    search_term=search_term if search_term else None,
                    offset=offset,
                    limit=per_page
                )

                # Cache the results
                catalog_cache.cache_search_results(
                    query=cache_key_params,
                    property_name=property_uri,
                    results=literals_data,
                    selected_class=class_uri or '',
                    user_org=user_org
                )

            # Calculate total pages from unique values count
            total_pages = (literals_data['unique_values'] + per_page - 1) // per_page

            # Create a simple page object for template
            page_obj = type('PageObj', (), {
                'number': page,
                'has_previous': page > 1,
                'has_next': page < total_pages,
                'previous_page_number': page - 1 if page > 1 else None,
                'next_page_number': page + 1 if page < total_pages else None,
                'paginator': type('Paginator', (), {'num_pages': total_pages})()
            })()

            literals_data['page_obj'] = page_obj

            context = {
                'literals_data': literals_data,
                'property_uri': property_uri,
                'class_uri': class_uri,
                'search_term': search_term,
                'page_obj': page_obj,
                'current_page': page,
            }

            # For first load (property selection), return complete interface
            # For search/pagination, return content with OOB header update
            if not search_term and page == 1:
                # Initial property load - return complete interface
                html = render_to_string('catalog/partials/literals_list.html', context, request=request)
                return HttpResponse(html)
            else:
                # Search/pagination - return results section with OOB header update
                results_html = self._render_literals_results(context, request)
                header_html = f'<h2 class="text-xl font-semibold">{literals_data["property_name"].title()} Values</h2><span class="badge badge-primary badge-lg font-mono ml-8">{literals_data["total_values"]} usages</span>'

                # OOB update for header counts
                oob_html = f'<div id="literals-header" hx-swap-oob="innerHTML"><div class="flex justify-between items-center mb-4">{header_html}</div></div>'

                return HttpResponse(f'{results_html}{oob_html}')

        except Exception as e:
            self.logger.error(f"Error browsing literals: {e}")
            return HttpResponse(f"<p class='text-red-500'>Error loading literals: {str(e)}</p>")

    def _render_literals_results(self, context, request):
        """Render just the results section (grid + pagination) for OOB updates."""
        return render_to_string('catalog/partials/literals_results_section.html', context, request=request)


