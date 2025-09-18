"""
Service for catalog insights including popular keywords and random projects.

This service provides reusable methods for REST API endpoints and UI views.
"""

import logging
import random
from typing import Any, Dict, List, Optional, Set

from django.db.models import Count, Q

from arkumu.cache.services import CatalogCacheService
from arkumu.catalog.services.project_views import CardURIs, CardView, ProjectURIs
from arkumu.metadata.models import Resource, ResourceType, Triple

logger = logging.getLogger(__name__)

RDF_TYPE_URI = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"


class CatalogInsightsService:
    """Service for catalog insights and data aggregation."""

    POPULAR_KEYWORDS_CACHE_TYPE = 'popular_keywords'
    POPULAR_KEYWORDS_TTL = 'catalog_statistics'
    RANDOM_PROJECTS_CACHE_TYPE = 'random_project_candidates'
    RANDOM_PROJECTS_TTL = 'catalog_search'

    def __init__(self, user=None):
        self.catalog_cache = CatalogCacheService()
        self.user = user

    # ------------------------------------------------------------------
    # Popular keywords
    # ------------------------------------------------------------------
    def get_popular_keywords(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Return popular keyword/category statistics."""
        limit = max(1, min(limit, 200))
        cache_params = {'limit': limit}

        cached = self.catalog_cache.get_cached(
            self.POPULAR_KEYWORDS_CACHE_TYPE,
            **cache_params
        )
        if cached is not None:
            return cached

        category_predicate_ids = self._get_resource_ids_by_canonical(CardURIs.CATEGORY)
        if not category_predicate_ids:
            logger.warning("No project category predicate found; returning empty keyword list")
            return []

        try:
            most_used_categories = (
                Triple.objects
                .filter(
                    predicate_id__in=category_predicate_ids,
                    object__resource_type__in=[ResourceType.IRI, ResourceType.ENTITY]
                )
                .values('object__id', 'object__uri', 'object__canonical_uri')
                .annotate(count=Count('object_id'))
                .order_by('-count')[:limit]
            )
        except Exception as exc:
            logger.error("Failed to aggregate popular keywords: %s", exc, exc_info=True)
            return []

        results: List[Dict[str, Any]] = []
        for category_data in most_used_categories:
            object_id = category_data['object__id']
            try:
                category_resource = Resource.objects.get(id=object_id)
            except Resource.DoesNotExist:
                logger.debug("Skipping missing category resource id=%s", object_id)
                continue

            label = self._get_category_label(category_resource)
            if not label:
                continue

            canonical_uri = category_data.get('object__canonical_uri') or category_data.get('object__uri')
            category_id = self._resource_slug(canonical_uri or category_resource.uri)
            if not category_id:
                continue

            results.append({
                'id': category_id,
                'label': label,
                'count': int(category_data['count'])
            })

        results.sort(key=lambda item: item['count'], reverse=True)
        self.catalog_cache.set_cached(
            self.POPULAR_KEYWORDS_CACHE_TYPE,
            results,
            self.POPULAR_KEYWORDS_TTL,
            **cache_params
        )
        return results

    # ------------------------------------------------------------------
    # Random projects
    # ------------------------------------------------------------------
    def get_random_projects(
        self,
        limit: int = 10,
        keyword_id: Optional[str] = None,
        category: Optional[str] = None,
        university: Optional[str] = None,
        year: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """Return randomised project previews with optional filters."""
        limit = max(1, min(limit, 50))

        cache_params = {
            'keyword': (keyword_id or '').strip() or 'ALL',
            'category': (category or '').strip() or 'ALL',
            'university': (university or '').strip() or 'ALL',
            'year': year or 'ALL'
        }

        candidate_uris: Optional[List[str]] = self.catalog_cache.get_cached(
            self.RANDOM_PROJECTS_CACHE_TYPE,
            **cache_params
        )

        if candidate_uris is None:
            subject_ids = self._get_project_subject_ids()
            if not subject_ids:
                self.catalog_cache.set_cached(
                    self.RANDOM_PROJECTS_CACHE_TYPE,
                    [],
                    self.RANDOM_PROJECTS_TTL,
                    **cache_params
                )
                return []

            filtered_ids = subject_ids
            if keyword_id or category:
                filtered_ids &= self._filter_projects_by_category(subject_ids, keyword_id, category)
                if not filtered_ids:
                    self.catalog_cache.set_cached(
                        self.RANDOM_PROJECTS_CACHE_TYPE,
                        [],
                        self.RANDOM_PROJECTS_TTL,
                        **cache_params
                    )
                    return []

            if university:
                filtered_ids &= self._filter_projects_by_university(filtered_ids, university)
                if not filtered_ids:
                    self.catalog_cache.set_cached(
                        self.RANDOM_PROJECTS_CACHE_TYPE,
                        [],
                        self.RANDOM_PROJECTS_TTL,
                        **cache_params
                    )
                    return []

            if year:
                filtered_ids &= self._filter_projects_by_year(filtered_ids, year)
                if not filtered_ids:
                    self.catalog_cache.set_cached(
                        self.RANDOM_PROJECTS_CACHE_TYPE,
                        [],
                        self.RANDOM_PROJECTS_TTL,
                        **cache_params
                    )
                    return []

            candidate_uris = list(
                Resource.objects.filter(id__in=filtered_ids).values_list('uri', flat=True)
            )
            candidate_uris = [uri for uri in candidate_uris if uri]

            self.catalog_cache.set_cached(
                self.RANDOM_PROJECTS_CACHE_TYPE,
                candidate_uris,
                self.RANDOM_PROJECTS_TTL,
                **cache_params
            )

        if not candidate_uris:
            return []

        if len(candidate_uris) <= limit:
            selected_uris = candidate_uris[:]
            random.shuffle(selected_uris)
        else:
            selected_uris = random.sample(candidate_uris, limit)

        projects: List[Dict[str, Any]] = []
        for project_uri in selected_uris:
            try:
                card_view = CardView(project_uri)
                card_data = card_view.get_card_data()
                if not card_data:
                    continue

                project_year = self._extract_year(card_data.event_start)
                project_slug = self._resource_slug(project_uri)
                projects.append({
                    'id': project_slug or project_uri,
                    'year': project_year,
                    'university': card_data.institution or "",
                    'title': card_data.title or "",
                    'project_type': self._get_project_type(project_uri),
                    'actors': card_data.actors,
                    'categories': card_data.categories,
                    'preview_image_url': card_data.image,
                    'detail_url': f"/projekt/{project_slug}" if project_slug else f"/projekt/{project_uri}",
                })
            except Exception as exc:
                logger.error("Error building project preview for %s: %s", project_uri, exc, exc_info=True)

        return projects

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _get_project_subject_ids(self) -> Set[int]:
        """Return subject IDs for resources that are projects."""
        project_type_uris = [CardURIs.PROJECT_TYPE, ProjectURIs.PROJECT_TYPE_FUK]

        predicate_ids = self._get_resource_ids_by_canonical(RDF_TYPE_URI)
        if not predicate_ids:
            logger.warning("rdf:type predicate not harmonized; unable to locate projects")
            return set()

        project_type_ids: List[int] = []
        for uri in project_type_uris:
            project_type_ids.extend(self._get_resource_ids_by_canonical(uri))

        project_triples = Triple.objects.filter(
            predicate_id__in=predicate_ids
        ).filter(
            Q(object__canonical_uri__in=project_type_uris) |
            Q(object__uri__in=project_type_uris) |
            Q(object_id__in=project_type_ids)
        )

        return set(project_triples.values_list('subject_id', flat=True))

    def _filter_projects_by_category(
        self,
        subject_ids: Set[int],
        keyword_id: Optional[str],
        category: Optional[str]
    ) -> Set[int]:
        if not subject_ids:
            return set()

        predicate_ids = self._get_resource_ids_by_canonical(CardURIs.CATEGORY)
        if not predicate_ids:
            return set()

        category_qs = Triple.objects.filter(
            predicate_id__in=predicate_ids,
            subject_id__in=subject_ids
        )

        if keyword_id:
            slug = keyword_id.strip()
            category_qs = category_qs.filter(
                Q(object__uri__iendswith=f'/{slug}') |
                Q(object__canonical_uri__iendswith=f'/{slug}')
            )

        if category:
            matching_category_ids = self._match_category_ids_by_label(category)
            if not matching_category_ids:
                return set()
            category_qs = category_qs.filter(object_id__in=matching_category_ids)

        return set(category_qs.values_list('subject_id', flat=True))

    def _filter_projects_by_university(self, subject_ids: Set[int], university: str) -> Set[int]:
        if not subject_ids:
            return set()

        predicate_ids = self._get_resource_ids_by_canonical(CardURIs.INSTITUTION)
        if not predicate_ids:
            return set()

        normalized = university.strip()
        institution_qs = Triple.objects.filter(
            predicate_id__in=predicate_ids,
            subject_id__in=subject_ids
        ).filter(
            Q(object__uri__icontains=normalized) |
            Q(object__canonical_uri__icontains=normalized)
        )

        if not institution_qs.exists():
            institution_ids = self._match_institution_ids_by_label(normalized)
            if not institution_ids:
                return set()

            institution_qs = Triple.objects.filter(
                predicate_id__in=predicate_ids,
                subject_id__in=subject_ids,
                object_id__in=institution_ids
            )

        return set(institution_qs.values_list('subject_id', flat=True))

    def _filter_projects_by_year(self, subject_ids: Set[int], year: int) -> Set[int]:
        if not subject_ids:
            return set()

        event_predicate_ids = self._get_resource_ids_by_canonical(CardURIs.EVENT)
        start_predicate_ids = self._get_resource_ids_by_canonical(CardURIs.EVENT_START)
        if not event_predicate_ids or not start_predicate_ids:
            return set()

        project_events = Triple.objects.filter(
            predicate_id__in=event_predicate_ids,
            subject_id__in=subject_ids
        )

        event_ids = list(project_events.values_list('object_id', flat=True))
        if not event_ids:
            return set()

        matching_event_ids = Triple.objects.filter(
            predicate_id__in=start_predicate_ids,
            subject_id__in=event_ids,
            object__resource_type=ResourceType.LITERAL,
            object__value__startswith=str(year)
        ).values_list('subject_id', flat=True)

        if not matching_event_ids:
            return set()

        return set(
            project_events.filter(object_id__in=matching_event_ids).values_list('subject_id', flat=True)
        )

    def _match_category_ids_by_label(self, label: str) -> List[int]:
        predicate_ids = self._get_resource_ids_by_canonical(CardURIs.CATEGORY_GERMAN_NAME)
        if not predicate_ids:
            return []

        return list(
            Triple.objects.filter(
                predicate_id__in=predicate_ids,
                object__resource_type=ResourceType.LITERAL,
                object__value__icontains=label.strip()
            ).values_list('subject_id', flat=True)
        )

    def _match_institution_ids_by_label(self, label: str) -> List[int]:
        predicate_ids = self._get_resource_ids_by_canonical(CardURIs.INSTITUTION_GERMAN_NAME)
        if not predicate_ids:
            return []

        return list(
            Triple.objects.filter(
                predicate_id__in=predicate_ids,
                object__resource_type=ResourceType.LITERAL,
                object__value__icontains=label.strip()
            ).values_list('subject_id', flat=True)
        )

    def _get_resource_ids_by_canonical(self, canonical_uri: str) -> List[int]:
        ids = list(
            Resource.objects.filter(canonical_uri=canonical_uri).values_list('id', flat=True)
        )
        if ids:
            return ids
        return list(Resource.objects.filter(uri=canonical_uri).values_list('id', flat=True))

    def _get_category_label(self, category_resource: Resource) -> Optional[str]:
        if not category_resource:
            return None

        cache_params = {
            'category': category_resource.canonical_uri or category_resource.uri or category_resource.id
        }
        cached_label = self.catalog_cache.get_cached('category_label', **cache_params)
        if cached_label:
            return cached_label

        label_triple = Triple.objects.filter(
            subject=category_resource,
            predicate__canonical_uri=CardURIs.CATEGORY_GERMAN_NAME,
            object__resource_type=ResourceType.LITERAL
        ).first()

        label = label_triple.object.literal_value if label_triple and label_triple.object else None

        if not label:
            label = category_resource.name or category_resource.value
        if not label and category_resource.uri:
            label = self._resource_slug(category_resource.uri)

        if label:
            self.catalog_cache.set_cached('category_label', label, self.POPULAR_KEYWORDS_TTL, **cache_params)

        return label

    def _get_project_type(self, project_uri: str) -> Optional[str]:
        project = Resource.objects.filter(uri=project_uri).first()
        if not project:
            return None

        project_type_triple = Triple.objects.filter(
            subject=project,
            predicate__canonical_uri=ProjectURIs.PROJECT_TYPE_FIELD,
            object__resource_type=ResourceType.LITERAL
        ).first()

        if project_type_triple and project_type_triple.object:
            return project_type_triple.object.literal_value

        return None

    @staticmethod
    def _resource_slug(uri: Optional[str]) -> Optional[str]:
        if not uri:
            return None
        return uri.rstrip('/').split('/')[-1]

    @staticmethod
    def _extract_year(value: Optional[str]) -> Optional[int]:
        if not value:
            return None
        try:
            return int(str(value)[:4])
        except (TypeError, ValueError):
            return None
