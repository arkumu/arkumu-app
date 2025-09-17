"""
Catalog Template Helpers

This mixin provides common template rendering and OOB update methods
for catalog views to improve search performance and UX.
"""

import logging
from django.template.loader import render_to_string
from django.middleware.csrf import get_token
from django.http import HttpResponse
import json
from typing import Dict, List, Any, Optional

logger = logging.getLogger(__name__)


class CatalogTemplateHelperMixin:
    """
    Mixin providing template rendering methods for catalog views.

    Implements OOB (Out-of-Band) updates for fast search results
    without full page reloads.
    """

    def render_search_results_template(self, request, results: List[Dict], query: str = "") -> str:
        """
        Render search results card grid template.

        Args:
            request: Django request object
            results: List of project cards
            query: Search query string

        Returns:
            Rendered HTML string for card grid
        """
        context = {
            'results': results,
            'query': query,
            'csrf_token': get_token(request)
        }

        return render_to_string(
            'catalog/partials/card_grid.html',
            context,
            request=request
        )

    def render_pagination_template(self, request, pagination_context: Dict) -> str:
        """
        Render pagination component template.

        Args:
            request: Django request object
            pagination_context: Pagination data dict

        Returns:
            Rendered HTML string for pagination
        """
        return render_to_string(
            'catalog/partials/pagination_htmx.html',
            pagination_context,
            request=request
        )

    def render_results_count_template(self, start: int, end: int, total: int) -> str:
        """
        Render results count display.

        Args:
            start: Start result number
            end: End result number
            total: Total results count

        Returns:
            HTML string for results count
        """
        if total == 0:
            return "Keine Ergebnisse gefunden"

        return f"Ergebnisse {start}-{end} von {total}"

    def render_search_status_template(self, query: str, total_results: int) -> str:
        """
        Render search status message.

        Args:
            query: Search query string
            total_results: Number of results found

        Returns:
            HTML string for search status
        """
        if not query:
            return ""

        if total_results == 0:
            return f'<div class="text-center py-8 text-arkumu-dark theme-dark:text-arkumu-light">Keine Projekte gefunden für "{query}"</div>'

        return f'<div class="text-center py-4 text-arkumu-dark theme-dark:text-arkumu-light">Suche nach "{query}" - {total_results} Projekte gefunden</div>'

    def build_search_oob_response(self, request, main_html: str, pagination_context: Dict,
                                query: str = "", total_results: int = 0) -> HttpResponse:
        """
        Build complete search response with OOB updates using proven CSV mapping pattern.

        Updates multiple page elements simultaneously:
        - Main search results
        - Pagination controls
        - Results counter
        - Search status

        Args:
            request: Django request object
            main_html: Main search results HTML
            pagination_context: Pagination data
            query: Search query string
            total_results: Total number of results

        Returns:
            HttpResponse with OOB updates
        """
        # Render pagination
        pagination_html = self.render_pagination_template(request, pagination_context)

        # Render results count
        start = pagination_context.get('start_result', 0)
        end = pagination_context.get('end_result', 0)
        results_count_html = self.render_results_count_template(start, end, total_results)

        # Render search status
        search_status_html = self.render_search_status_template(query, total_results)

        # Build OOB updates using proven CSV mapping pattern
        oob_updates = {}

        # Only add OOB updates with actual content
        if pagination_html.strip():
            oob_updates['pagination-container'] = pagination_html

        if results_count_html.strip():
            oob_updates['results-count'] = results_count_html

        if search_status_html.strip():
            oob_updates['search-status'] = search_status_html

        logger.info(f"🔍 OOB_CONTENT DEBUG: pagination_html length: {len(pagination_html)}")
        logger.info(f"🔍 OOB_CONTENT DEBUG: results_count_html length: {len(results_count_html)}")
        logger.info(f"🔍 OOB_CONTENT DEBUG: search_status_html length: {len(search_status_html)}")
        logger.info(f"🔍 OOB_CONTENT DEBUG: Final oob_updates keys: {list(oob_updates.keys())}")

        # Use the proven build_oob_response method from CSV mapping
        response_html = self.build_oob_response(main_html, oob_updates)

        logger.info(f"🚀 CATALOG_OOB: Built response with {len(oob_updates)} OOB updates for query '{query}'")

        # Create HttpResponse with URL push for search queries
        response = HttpResponse(response_html)

        # Add URL push using HX-Push header (more reliable than OOB)
        if query:
            response['HX-Push-Url'] = f"/catalog/design/?query={query}"
        else:
            response['HX-Push-Url'] = "/catalog/design/"

        return response

    def build_oob_response(self, main_html, oob_updates=None):
        """
        Build response with out-of-band updates using proven CSV mapping pattern.

        Consolidates the repeated pattern:
        response = f'{main_html}<div id="target" hx-swap-oob="innerHTML">{content}</div>'

        Args:
            main_html (str): The main response HTML
            oob_updates (dict): Dict of {target_id: content} for OOB updates

        Returns:
            str: Complete HTML response with OOB updates
        """
        logger.info(f"🔍 BUILD_OOB DEBUG: main_html length: {len(main_html)}")
        logger.info(f"🔍 BUILD_OOB DEBUG: oob_updates: {list(oob_updates.keys()) if oob_updates else 'None'}")

        if not oob_updates:
            logger.info(f"🔍 BUILD_OOB DEBUG: No OOB updates, returning main_html only")
            return main_html

        oob_html = ""
        for target_id, content in oob_updates.items():
            oob_element = f'<div id="{target_id}" hx-swap-oob="innerHTML">{content}</div>'
            oob_html += oob_element
            logger.info(f"🔍 BUILD_OOB DEBUG: Added OOB element for '{target_id}', content length: {len(content)}")

        final_response = f'{main_html}{oob_html}'
        logger.info(f"🔍 BUILD_OOB DEBUG: Final combined response length: {len(final_response)}")
        return final_response

    def build_empty_search_response(self, request, query: str = "") -> HttpResponse:
        """
        Build response for empty search results.

        Args:
            request: Django request object
            query: Search query string

        Returns:
            HttpResponse with empty results and OOB updates
        """
        # Empty results template
        main_html = self.render_search_results_template(request, [], query)

        # Empty pagination context
        pagination_context = {
            'current_page': 1,
            'total_pages': 0,
            'total_results': 0,
            'start_result': 0,
            'end_result': 0,
            'has_previous': False,
            'has_next': False,
            'previous_page': None,
            'next_page': None,
            'page_range': []
        }

        return self.build_search_oob_response(
            request=request,
            main_html=main_html,
            pagination_context=pagination_context,
            query=query,
            total_results=0
        )

    def add_search_performance_headers(self, response: HttpResponse, query: str,
                                     results_count: int, processing_time: float = None) -> HttpResponse:
        """
        Add performance and search metadata headers.

        Args:
            response: HttpResponse object
            query: Search query string
            results_count: Number of results
            processing_time: Optional processing time in seconds

        Returns:
            HttpResponse with additional headers
        """
        # Add search metadata headers
        response['X-Search-Query'] = query
        response['X-Search-Results'] = str(results_count)

        if processing_time:
            response['X-Search-Time'] = f"{processing_time:.3f}s"

        # Add cache headers for better performance
        if query:
            # Cache search results for 5 minutes
            response['Cache-Control'] = 'public, max-age=300'
        else:
            # Don't cache empty search pages
            response['Cache-Control'] = 'no-cache'

        return response

    def render_loading_placeholder_template(self, request) -> str:
        """
        Render loading placeholder for search results.

        Args:
            request: Django request object

        Returns:
            HTML string for loading placeholder
        """
        return '''
        <div class="flex items-center justify-center py-16">
            <div class="inline-flex items-center px-4 py-2 text-lg font-medium text-arkumu-dark theme-dark:text-arkumu-light">
                <svg class="animate-spin -ml-1 mr-3 h-6 w-6" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                    <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                    <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                </svg>
                Projekte werden geladen...
            </div>
        </div>
        '''

    def create_htmx_trigger_response(self, html_content: str, triggers: Dict = None) -> HttpResponse:
        """
        Create HttpResponse with HX-Trigger header for event firing.

        Args:
            html_content: HTML content for response
            triggers: Dictionary of trigger events

        Returns:
            HttpResponse with HX-Trigger header
        """
        response = HttpResponse(html_content)

        if triggers:
            response['HX-Trigger'] = json.dumps(triggers)

        return response