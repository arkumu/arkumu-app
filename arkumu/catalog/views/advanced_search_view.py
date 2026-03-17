"""Advanced search view using indexed ProjectIndex for fast queries."""

import time

from django.views.generic import View
from django.shortcuts import render
from django.middleware.csrf import get_token
from django.core.cache import cache
import logging
from typing import List

from .catalog_template_helpers import CatalogTemplateHelperMixin
from arkumu.users.mixins import GeneralLoginRequiredMixin
from arkumu.catalog.models import ProjectIndex
from arkumu.catalog.services.project_index_service import ProjectIndexService
from arkumu.metadata.models import PublicAccessLevel

logger = logging.getLogger(__name__)


class AdvancedSearchView(GeneralLoginRequiredMixin, View, CatalogTemplateHelperMixin):
    """Advanced search with filtering by institution, category, and actor using indexed queries."""

    ITEMS_PER_PAGE = 15
    DROPDOWN_CACHE_TTL = 3600  # 1 hour

    def get(self, request, *args, **kwargs):
        start_time = time.time()

        # Extract search parameters
        view = request.GET.get('view', 'card').strip()
        query = request.GET.get('query', '').strip() or None
        institutions = request.GET.getlist('hochschule')
        categories = request.GET.getlist('kategorie')
        actors = request.GET.getlist('akteur')
        schlagworte = request.GET.getlist('schlagwort')
        jahr_von = request.GET.get('jahr_von', '').strip()
        jahr_bis = request.GET.get('jahr_bis', '').strip()
        year_from = int(jahr_von) if jahr_von.isdigit() else None
        year_to = int(jahr_bis) if jahr_bis.isdigit() else None
        try:
            page = max(int(request.GET.get('page', 1)), 1)
        except ValueError:
            page = 1

        logger.info(
            "ADVANCED_SEARCH: query=%s, institutions=%s, categories=%s, actors=%s, schlagworte=%s, year_from=%s, year_to=%s",
            query, institutions, categories, actors, schlagworte, year_from, year_to
        )

        try:
            index_service = ProjectIndexService(backend="db")

            # Determine if we have any filters
            has_filters = query or institutions or categories or actors or schlagworte or year_from or year_to

            if not has_filters:
                # No filters: show random sample of projects
                filtered_cards, total_results = index_service.get_random_cards_sample(
                    limit=self.ITEMS_PER_PAGE,
                )
                pagination_context = {
                    'current_page': 1,
                    'total_pages': 1,
                    'has_previous': False,
                    'has_next': False,
                    'previous_page': None,
                    'next_page': None,
                    'page_range': [],
                }
            else:
                # Apply filters via indexed query
                # Map institution labels to org_codes for filtering
                org_codes = None
                if institutions:
                    org_codes = [
                        ProjectIndex.label_to_org_code(label)
                        for label in institutions
                        if ProjectIndex.label_to_org_code(label)
                    ]

                filtered_cards, total_results = index_service.get_cards_page(
                    query=query,
                    org_codes=org_codes if org_codes else None,
                    page=page,
                    page_size=self.ITEMS_PER_PAGE,
                    categories=categories if categories else None,
                    actors=actors if actors else None,
                    catchphrases=schlagworte if schlagworte else None,
                    year_from=year_from,
                    year_to=year_to,
                )
                total_pages = (total_results + self.ITEMS_PER_PAGE - 1) // self.ITEMS_PER_PAGE if total_results else 0
                pagination_context = {
                    'current_page': page,
                    'total_pages': total_pages,
                    'has_previous': page > 1,
                    'has_next': total_pages > page,
                    'previous_page': page - 1 if page > 1 else None,
                    'next_page': page + 1 if total_pages > page else None,
                    'page_range': self._get_page_range(page, total_pages) if total_pages else [],
                }

            # Categories are already human-readable labels in ProjectIndex
            # Just copy category labels to category{N}_name for template
            for card in filtered_cards:
                card_categories = card.get("categories", [])
                for idx, cat_label in enumerate(card_categories[:3]):
                    if cat_label:
                        card[f"category{idx+1}_name"] = cat_label

            # Build dropdown options from indexed data (no Wikidata needed)
            dropdown_options = self._get_dropdown_options(institutions, categories, actors)

            # Build active filters for display
            active_filters = self._build_active_filters(request, institutions, categories, actors, schlagworte)

            query_params = request.GET.copy()
            query_params.pop('view', None)
            request_path = f"{request.path}?{query_params.urlencode()}"

            context = {
                'institution': institutions,
                'active_filters': active_filters,
                'actor': actors,
                'category': categories,
                'results': filtered_cards,
                'total_results': total_results,
                'csrf_token': get_token(request),
                'dropdown_option': dropdown_options,
                'query': query or '',
                'view': view,
                'request_path': request_path,
                'current_page': pagination_context['current_page'],
                'total_pages': pagination_context['total_pages'],
                'has_previous': pagination_context['has_previous'],
                'has_next': pagination_context['has_next'],
                'previous_page': pagination_context['previous_page'],
                'next_page': pagination_context['next_page'],
                'page_range': pagination_context['page_range'],
            }

            processing_time = time.time() - start_time
            logger.info("ADVANCED_SEARCH_COMPLETE: %d results in %.3fs", len(filtered_cards), processing_time)

            return render(request, 'catalog/advanced_search.html', context)

        except Exception as e:
            logger.exception("ADVANCED_SEARCH_ERROR: %s", e)
            return render(request, 'catalog/error.html', {'error': str(e)})

    def _get_dropdown_options(
        self,
        selected_institutions: List[str],
        selected_categories: List[str],
        selected_actors: List[str],
    ) -> dict:
        """Get dropdown options from indexed data with caching."""
        cache_key = "arkumu:advanced_search:dropdown_options"
        cached = cache.get(cache_key)

        if cached:
            all_institutions, all_categories, all_actors = cached
        else:
            # Query indexed data for unique values
            base_qs = ProjectIndex.objects.filter(
                public_access_level=PublicAccessLevel.PUBLIC,
                is_public_approved=True,
            ).exclude(title__isnull=True).exclude(title='')

            # Get institutions from centralized model mapping
            all_institutions = ProjectIndex.get_all_institution_labels()

            # Get unique categories (flatten ArrayField) - already human-readable labels
            all_categories_raw = set()
            for cats in base_qs.values_list('category_labels', flat=True):
                if cats:
                    all_categories_raw.update(cats)

            # Categories are already labels, use them directly
            all_categories = [
                {"id": cat, "name": cat}
                for cat in sorted(all_categories_raw)
                if cat
            ]

            # Get unique actor names (flatten ArrayField)
            all_actors = set()
            for names in base_qs.values_list('actor_names', flat=True):
                if names:
                    all_actors.update(names)
            all_actors = sorted(all_actors)

            # Cache the results
            cache.set(cache_key, (all_institutions, all_categories, all_actors), self.DROPDOWN_CACHE_TTL)

        # Filter out already selected values
        available_institutions = [i for i in all_institutions if i not in selected_institutions]
        available_categories = [c for c in all_categories if c["id"] not in selected_categories]
        available_actors = [a for a in all_actors if a not in selected_actors]

        return {
            "hochschulen": available_institutions,
            "kategorien": available_categories,
            "akteur": available_actors,
        }

    def _build_active_filters(
        self,
        request,
        institutions: List[str],
        categories: List[str],
        actors: List[str],
        schlagworte: List[str],
    ) -> List[dict]:
        """Build list of active filters with remove URLs."""
        active_filters = []

        # Institution filters
        for inst in institutions:
            q = request.GET.copy()
            q.setlist('hochschule', [i for i in institutions if i != inst])
            active_filters.append({
                'type': 'hochschule',
                'value': inst,
                'display_name': inst,
                'remove_url': f"{request.path}?{q.urlencode()}"
            })

        # Category filters - categories are already human-readable labels
        for cat in categories:
            q = request.GET.copy()
            q.setlist('kategorie', [c for c in categories if c != cat])
            active_filters.append({
                'type': 'kategorie',
                'value': cat,
                'display_name': cat,
                'remove_url': f"{request.path}?{q.urlencode()}"
            })

        # Actor filters
        for act in actors:
            q = request.GET.copy()
            q.setlist('akteur', [a for a in actors if a != act])
            active_filters.append({
                'type': 'akteur',
                'value': act,
                'display_name': act,
                'remove_url': f"{request.path}?{q.urlencode()}"
            })

        # Schlagwort filters
        for sw in schlagworte:
            q = request.GET.copy()
            q.setlist('schlagwort', [s for s in schlagworte if s != sw])
            active_filters.append({
                'type': 'schlagwort',
                'value': sw,
                'display_name': sw,
                'remove_url': f"{request.path}?{q.urlencode()}"
            })

        return active_filters

    def _get_page_range(self, current: int, total: int) -> List[int]:
        """Get list of page numbers to display in pagination."""
        if total <= 7:
            return list(range(1, total + 1))

        if current <= 3:
            return list(range(1, min(6, total + 1))) + ([total] if total > 6 else [])
        if current >= total - 2:
            return [1] + list(range(max(total - 4, 2), total + 1))
        return [1] + list(range(current - 1, min(current + 2, total + 1))) + ([total] if current + 2 < total else [])
