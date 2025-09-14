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

        # Perform graph search if query exists
        if query.strip():
            try:
                search_results = graph_service.search_by_property_with_graph(
                    query=query,
                    property_name=property_name,
                    resource_type=selected_class if selected_class else None,
                    limit=20
                )

                # Format results for template (same as API)
                formatted_results = []
                for result in search_results:
                    # Extract display title from properties
                    title = (result['properties'].get('title') or
                            result['properties'].get('name') or
                            result['properties'].get('deutsches_wikidata_label') or
                            'Untitled')

                    formatted_results.append({
                        'entity_uri': result['entity_uri'],
                        'entity_type': result['entity_type'],
                        'title': title,
                        'properties': result['properties'],
                        'outgoing_relations': result['outgoing_relations'],
                        'incoming_relations': result['incoming_relations'],
                        'connected_count': len(result['connected_entities'])
                    })

                # Paginate results
                paginator = Paginator(formatted_results, 10)
                page_obj = paginator.get_page(page)

                context.update({
                    'query': query,
                    'results': page_obj,
                    'total_count': len(formatted_results),
                    'has_results': len(formatted_results) > 0
                })

                self.logger.info(f"Graph search: '{query}' in '{property_name}' found {len(formatted_results)} results")

            except Exception as e:
                self.logger.error(f"Graph search failed: {e}")
                context.update({
                    'query': query,
                    'search_error': f"Search failed: {str(e)}",
                    'has_results': False
                })
        else:
            context.update({
                'has_results': False,
                'show_initial_message': True
            })

        # For HTMX requests, return just the results section
        if self.request.headers.get('HX-Request'):
            results_html = render_to_string('catalog/partials/explorer_results.html', context, request=self.request)
            return HttpResponse(results_html)

        return context


