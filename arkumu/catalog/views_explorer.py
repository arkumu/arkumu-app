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


class CatalogExplorerView(LoginRequiredMixin, TemplateView):
    """Graph-based data exploration view."""

    template_name = 'catalog/explorer_sidebar.html'
    logger = logging.getLogger(__name__)

    def get_context_data(self, **kwargs) -> Dict[str, Any]:
        """Get context with graph search results."""
        context = super().get_context_data(**kwargs)

        # Initialize graph search service
        graph_service = GraphSearchService(user=self.request.user)

        # Get query parameters
        query = self.request.GET.get('q', '')
        property_name = self.request.GET.get('property', 'title')  # Default to title search
        selected_class = self.request.GET.get('class', '')
        page = self.request.GET.get('page', 1)

        # Get available types and properties for the UI
        available_types = graph_service.get_available_types()
        available_properties = graph_service.get_available_properties(selected_class)

        context.update({
            'available_classes': {item['uri']: {'name': item['display_name'], 'entity_count': item['count']}
                                 for item in available_types},
            'available_properties': {item['uri']: {'name': item['display_name'], 'usage_count': item['usage_count']}
                                   for item in available_properties},
            'selected_class': selected_class,
            'selected_property': property_name,
        })

        # Show initial message - this is for browsing literal values by class/property
        context.update({
            'has_results': False,
            'show_initial_message': True
        })

        # For HTMX requests, return just the explorer content section
        if self.request.headers.get('HX-Request'):
            content_html = render_to_string('catalog/partials/explorer_content.html', context, request=self.request)
            return HttpResponse(content_html)

        return context


class CatalogExplorerPropertiesView(LoginRequiredMixin, TemplateView):
    """HTMX endpoint for loading properties of a selected class."""

    def get(self, request, *args, **kwargs):
        """Return properties HTML for the selected class."""
        selected_class = request.GET.get('class', '')

        if not selected_class:
            return HttpResponse("")

        # Get properties for this class
        graph_service = GraphSearchService(user=request.user)
        available_properties = graph_service.get_available_properties(selected_class)

        context = {
            'available_properties': {item['uri']: {'name': item['display_name'], 'usage_count': item['usage_count']}
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
        search_term = request.GET.get('search', '')
        page = int(request.GET.get('page', 1))
        per_page = 20  # Show 20 items per page with proper pagination

        if not property_uri:
            return HttpResponse("")

        # Get literal values for this property
        graph_service = GraphSearchService(user=request.user)

        try:
            # Calculate offset for database-level pagination
            offset = (page - 1) * per_page

            literals_data = graph_service.browse_property_values(
                property_uri=property_uri,
                class_uri=class_uri if class_uri else None,
                search_term=search_term if search_term else None,
                offset=offset,
                limit=per_page
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
                header_html = f'<h2 class="text-xl font-semibold">{literals_data["property_name"].title()} Values</h2><span class="badge badge-primary badge-lg font-mono">{literals_data["total_values"]} entities</span>'

                # OOB update for header counts
                oob_html = f'<div id="literals-header" hx-swap-oob="innerHTML"><div class="flex justify-between items-center mb-4">{header_html}</div></div>'

                return HttpResponse(f'{results_html}{oob_html}')

        except Exception as e:
            self.logger.error(f"Error browsing literals: {e}")
            return HttpResponse(f"<p class='text-red-500'>Error loading literals: {str(e)}</p>")

    def _render_literals_results(self, context, request):
        """Render just the results section (grid + pagination) for OOB updates."""
        return render_to_string('catalog/partials/literals_results_section.html', context, request=request)


