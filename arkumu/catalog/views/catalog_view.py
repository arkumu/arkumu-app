"""
Catalog view with pagination and caching.
"""

from django.views.generic import View
from django.shortcuts import render
from django.middleware.csrf import get_token
import logging
from typing import List

from .catalog_template_helpers import CatalogTemplateHelperMixin
from arkumu.users.mixins import GeneralLoginRequiredMixin
from ..services.wikidata_service import WikidataService
from ..services.project_card_search_service import ProjectCardSearchService

logger = logging.getLogger(__name__)


class CatalogView(GeneralLoginRequiredMixin, View, CatalogTemplateHelperMixin):
    """
    Catalog view with pagination and caching.
    """

    ITEMS_PER_PAGE = 10
    CACHE_TIMEOUT = 3600

    def get(self, request, *args, **kwargs):
        """Handle catalog page with fast HTMX search and OOB updates."""
        import time
        start_time = time.time()

        query = request.GET.get('query', '').strip()
        orga_code = request.GET.get('orga_code', "").strip().lower() or None
        query = query or None

        # Mapping der Kürzel zu vollständigen Namen
        orga_mapping = {
            "fuk": "Folkwang Universität der Künste",
            "rsh": "Robert Schumann Hochschule Düsseldorf",
            "khm": "Kunsthochschule für Medien Köln",
            "det": "Hochschule für Musik Detmold",
            "hmt": "Hochschule für Musik und Tanz Köln"
        }

        orga_display = orga_mapping.get(orga_code) if orga_code else None

        try:
            page = max(int(request.GET.get('page', 1)), 1)
        except ValueError:
            page = 1
        is_htmx = request.headers.get('HX-Request') is not None

        # Get user's organization (optional for cross-institutional queries)
        org_code = None
        if hasattr(request.user, 'organization') and request.user.organization:
            org_code = request.user.organization.code

        logger.info(f"🔍 CATALOG_SEARCH: Query: '{query}', Page: {page}, Org: {org_code}, HTMX: {is_htmx}")

        try:
            # For requests without query, return empty results immediately
            if not query and not orga_code:
                logger.info("FAST_PATH: No query provided, returning empty results")
                if is_htmx:
                    return self.build_empty_search_response(request, query)
                # For initial page load without query, return empty page
                context = {
                    'query': None,
                    'orga_code': None,
                    'results': [],
                    'pagination': {},
                    'total_results': 0,
                    'csrf_token': get_token(request)
                }
                return render(request, 'catalog/design.html', context)

            search_service = ProjectCardSearchService()
            cards, total_results = search_service.search_cards(
                query,
                org_code=orga_code,
                page=page,
                page_size=self.ITEMS_PER_PAGE,
            )

            # Categories are already labels from ProjectIndex (db backend).
            # Only do Wikidata lookup if value looks like a Wikidata ID (Q followed by digits).
            def _is_wikidata_id(val: str) -> bool:
                return val and val.startswith("Q") and val[1:].isdigit()

            for card in cards:
                # category1-4 fields: use as-is if already a label
                for i in range(1, 5):
                    key = f"category{i}"
                    val = card.get(key)
                    if val:
                        if _is_wikidata_id(val):
                            card[f"{key}_name"] = WikidataService().get_entity_label(wikidata_id=val)
                        else:
                            card[f"{key}_name"] = val  # Already a label

                # categories array: convert to {id, name} format
                if card.get("categories"):
                    card["categories"] = [
                        {"id": cat, "name": cat} if not _is_wikidata_id(cat)
                        else {"id": cat, "name": WikidataService().get_entity_label(wikidata_id=cat)}
                        for cat in card.get("categories")
                    ]


            # Calculate result range for display
            total_pages = (total_results + self.ITEMS_PER_PAGE - 1) // self.ITEMS_PER_PAGE if total_results else 0
            start_result = (page - 1) * self.ITEMS_PER_PAGE + 1 if total_results > 0 else 0
            end_result = min(page * self.ITEMS_PER_PAGE, total_results)

            pagination_context = {
                'current_page': page,
                'total_pages': total_pages,
                'total_results': total_results,
                'start_result': start_result,
                'end_result': end_result,
                'has_previous': page > 1,
                'has_next': total_pages > page,
                'previous_page': page - 1 if page > 1 else None,
                'next_page': page + 1 if total_pages > page else None,
                'page_range': self._get_page_range(page, total_pages) if total_pages else [],
            }

            processing_time = time.time() - start_time

            # For HTMX requests, return unified results container
            if is_htmx:
                logger.info(f"⚡ HTMX_RESPONSE: Returning unified results container in {processing_time:.3f}s")
                response = self.build_search_response(
                    request=request,
                    results=cards,
                    pagination_context=pagination_context,
                    query=query,
                    total_results=total_results,
                    orga_code=orga_code,
                )
                return self.add_search_performance_headers(response, query, total_results, processing_time)

            # For regular requests, return full page
            context = {
                'query': query,
                'orga_code': orga_display or orga_code,
                'results': cards,
                'pagination': pagination_context,
                # Also include individual pagination values for template
                'total_results': total_results,
                'start_result': pagination_context['start_result'],
                'end_result': pagination_context['end_result'],
                'current_page': pagination_context['current_page'],
                'total_pages': pagination_context['total_pages'],
                'has_previous': pagination_context['has_previous'],
                'has_next': pagination_context['has_next'],
                'previous_page': pagination_context['previous_page'],
                'next_page': pagination_context['next_page'],
                'page_range': pagination_context['page_range'],
                'csrf_token': get_token(request)
            }

            logger.info(f"📄 FULL_PAGE: Returning full page in {processing_time:.3f}s")
            if orga_display == "Folkwang Universität der Künste":
                return render(request, 'catalog/university_pages/university_page_FUK.html', context)
            if orga_display == "Robert Schumann Hochschule Düsseldorf":
                return render(request, 'catalog/university_pages/university_page_RSH.html', context)
            if orga_display == "Kunsthochschule für Medien Köln":
                return render(request, 'catalog/university_pages/university_page_KHM.html', context)
            if orga_display == "Hochschule für Musik Detmold":
                return render(request, 'catalog/university_pages/university_page_DET.html', context)
            if orga_display == "Hochschule für Musik und Tanz Köln":
                return render(request, 'catalog/university_pages/university_page_HMT.html', context)
            return render(request, 'catalog/design.html', context)

        except Exception as e:
            logger.error(f"❌ CATALOG_ERROR: {e}")
            if is_htmx:
                return self.build_empty_search_response(request, query)
            return self._render_error(request, f"Error loading catalog: {str(e)}")

    def _get_page_range(self, current: int, total: int) -> List[int]:
        """Get list of page numbers to display in pagination."""
        if total <= 7:
            return list(range(1, total + 1))

        if current <= 3:
            return list(range(1, min(6, total + 1))) + ([total] if total > 6 else [])
        elif current >= total - 2:
            return [1] + list(range(max(total - 4, 2), total + 1))
        else:
            return [1] + list(range(current - 1, min(current + 2, total + 1))) + ([total] if current + 2 < total else [])


    def _render_error(self, request, error_message: str):
        """Render error page."""
        context = {
            'error': error_message
        }
        return render(request, 'catalog/design_error.html', context)
