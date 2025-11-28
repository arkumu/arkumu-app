"""Advanced search view using indexed ProjectIndex for fast queries."""

import random
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
        actors = request.GET.getlist('aktuer')

        logger.info(
            "ADVANCED_SEARCH: query=%s, institutions=%s, categories=%s, actors=%s",
            query, institutions, categories, actors
        )

        try:
            index_service = ProjectIndexService(backend="db")

            # Determine if we have any filters
            has_filters = query or institutions or categories or actors

            if not has_filters:
                # No filters: show random sample of projects
                all_cards = index_service.get_cards()
                total_results = len(all_cards)
                filtered_cards = random.sample(all_cards, k=min(self.ITEMS_PER_PAGE, total_results))
            else:
                # Apply filters via indexed query
                # Map institution labels to org_codes for filtering
                org_code = None
                if institutions:
                    # For now, use the first institution's org code
                    org_code = self._institution_label_to_org_code(institutions[0])

                filtered_cards = index_service.get_cards(
                    query=query,
                    organ_code=org_code,
                    categories=categories if categories else None,
                    actors=actors if actors else None,
                )
                total_results = len(filtered_cards)

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
            active_filters = self._build_active_filters(request, institutions, categories, actors)

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
            }

            processing_time = time.time() - start_time
            logger.info("ADVANCED_SEARCH_COMPLETE: %d results in %.3fs", len(filtered_cards), processing_time)

            return render(request, 'catalog/advanced_search.html', context)

        except Exception as e:
            logger.exception("ADVANCED_SEARCH_ERROR: %s", e)
            return render(request, 'catalog/error.html', {'error': str(e)})

    def _institution_label_to_org_code(self, label: str) -> str:
        """Map institution label to org code."""
        mapping = {
            "Folkwang Universität der Künste": "fuk",
            "Robert Schumann Hochschule Düsseldorf": "rsh",
            "Kunsthochschule für Medien Köln": "khm",
            "Hochschule für Musik Detmold": "det",
            "Hochschule für Musik und Tanz Köln": "hmt",
        }
        return mapping.get(label, label.lower()[:3])

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
            )

            # Get unique institution labels
            all_institutions = sorted(set(
                base_qs.exclude(institution_label='')
                .values_list('institution_label', flat=True)
                .distinct()
            ))

            # Get unique categories (flatten ArrayField) - already human-readable labels
            all_categories_raw = set()
            for cats in base_qs.values_list('categories', flat=True):
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
            q.setlist('aktuer', [a for a in actors if a != act])
            active_filters.append({
                'type': 'aktuer',
                'value': act,
                'display_name': act,
                'remove_url': f"{request.path}?{q.urlencode()}"
            })

        return active_filters
