"""
Catalog view with pagination and caching.
"""

from django.views.generic import View
from django.shortcuts import render
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.middleware.csrf import get_token
import logging
from typing import Any, Dict, List, Optional

from arkumu.cache.services import CacheManager
from arkumu.projects.services import ProjectSnapshotService
from .catalog_template_helpers import CatalogTemplateHelperMixin

logger = logging.getLogger(__name__)


class CatalogView(LoginRequiredMixin, View, CatalogTemplateHelperMixin):
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
        page = request.GET.get('page', 1)
        is_htmx = request.headers.get('HX-Request') is not None

        # Get user's organization (optional for cross-institutional queries)
        org_code = None
        if hasattr(request.user, 'organization') and request.user.organization:
            org_code = request.user.organization.code

        logger.info(f"🔍 CATALOG_SEARCH: Query: '{query}', Page: {page}, Org: {org_code}, HTMX: {is_htmx}")

        try:
            # For HTMX requests without query, return empty results immediately
            if is_htmx and not query:
                logger.info("🚀 FAST_PATH: Empty HTMX request, returning empty results")
                return self.build_empty_search_response(request, query)

            # Only load projects when there's a search query
            if query:
                projects = self._get_all_projects(query, request)
                logger.info(f"📊 SEARCH_RESULTS: Found {len(projects)} projects for '{query}'")
            else:
                # Empty results when no query - lazy loading
                projects = []

            # Paginate results
            paginator = Paginator(projects, self.ITEMS_PER_PAGE)

            try:
                page_obj = paginator.page(page)
            except PageNotAnInteger:
                page_obj = paginator.page(1)
            except EmptyPage:
                page_obj = paginator.page(paginator.num_pages)

            # Calculate result range for display
            total_results = paginator.count
            start_result = (page_obj.number - 1) * self.ITEMS_PER_PAGE + 1 if total_results > 0 else 0
            end_result = min(page_obj.number * self.ITEMS_PER_PAGE, total_results)

            # Build pagination context
            pagination_context = {
                'current_page': page_obj.number,
                'total_pages': paginator.num_pages,
                'total_results': total_results,
                'start_result': start_result,
                'end_result': end_result,
                'has_previous': page_obj.has_previous(),
                'has_next': page_obj.has_next(),
                'previous_page': page_obj.previous_page_number() if page_obj.has_previous() else None,
                'next_page': page_obj.next_page_number() if page_obj.has_next() else None,
                'page_range': self._get_page_range(page_obj.number, paginator.num_pages)
            }

            processing_time = time.time() - start_time

            # For HTMX requests, return unified results container
            if is_htmx:
                logger.info(f"⚡ HTMX_RESPONSE: Returning unified results container in {processing_time:.3f}s")
                response = self.build_search_response(
                    request=request,
                    results=page_obj.object_list,
                    pagination_context=pagination_context,
                    query=query,
                    total_results=total_results
                )
                return self.add_search_performance_headers(response, query, total_results, processing_time)

            # For regular requests, return full page
            context = {
                'query': query,
                'results': page_obj.object_list,
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
            return render(request, 'catalog/design.html', context)

        except Exception as e:
            logger.error(f"❌ CATALOG_ERROR: {e}")
            if is_htmx:
                return self.build_empty_search_response(request, query)
            return self._render_error(request, f"Error loading catalog: {str(e)}")

    def _get_all_projects(
        self,
        query: str,
        request=None,
    ) -> List[Dict[str, Any]]:
        """Return project cards, using cached snapshot and query cache."""
        cache_manager = CacheManager()
        skip_cache = bool(request and request.GET.get('nocache') == '1')

        if query and not skip_cache:
            cached_search = cache_manager.catalog.get_cached_search_results(
                query=query,
                property_name="cross_institutional_search",
                selected_class="projekt",
                user_org="global",
            )
            if cached_search and cached_search.get('results'):
                logger.info("✅ CATALOG_CACHE_HIT: Using cached search results for '%s'", query)
                return cached_search['results'].get('entities', [])

        if skip_cache:
            logger.info("🔄 CACHE_BYPASS: nocache=1 forcing snapshot refresh")

        snapshot_service = ProjectSnapshotService()
        snapshot = snapshot_service.get_cross_institutional_snapshot(force_refresh=skip_cache)
        records = snapshot.projects
        logger.info(
            "CATALOG_SNAPSHOT: generated %s with %d total projects (force_refresh=%s)",
            snapshot.generated_at.isoformat(),
            len(records),
            skip_cache,
        )

        if query:
            matching_records = [record for record in records if record.matches_query(query)]
            logger.info("🔍 FILTERED: %d projects match '%s'", len(matching_records), query)
            logger.debug(
                "🔍 FILTERED_CODES: institutions=%s categories=%s",
                sorted({code for record in matching_records for code in record.institution_codes}),
                sorted({slug for record in matching_records for slug in record.category_slugs}),
            )
        else:
            matching_records = records

        cards = [record.to_card_dict() for record in matching_records]

        if query and not skip_cache:
            cache_manager.catalog.cache_search_results(
                query=query,
                property_name="cross_institutional_search",
                results={'entities': cards},
                selected_class="projekt",
                user_org="global",
            )
            logger.info("💾 CATALOG_CACHED: Stored search results for '%s'", query)

        return cards


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
