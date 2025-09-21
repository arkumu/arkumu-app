"""Service for catalog insights including popular keywords and random projects."""

from collections import defaultdict
import logging
import random
from typing import Any, Dict, List, Optional, Set

from django.db.models import Count, Q
from django.utils.text import slugify

from arkumu.cache.services import CatalogCacheService
from arkumu.catalog.services.project_views import CardURIs, CardView, ProjectURIs
from arkumu.metadata.models import Resource, ResourceType, Triple
from arkumu.projects import ProjectRecord
from arkumu.projects.services import ProjectSnapshotService

logger = logging.getLogger(__name__)

RDF_TYPE_URI = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"


class CatalogInsightsService:
    """Service for catalog insights and data aggregation."""

    POPULAR_KEYWORDS_CACHE_TYPE = 'popular_keywords'
    POPULAR_KEYWORDS_TTL = 'catalog_statistics'
    RANDOM_PROJECTS_CACHE_TYPE = 'random_project_candidates'
    RANDOM_PROJECTS_TTL = 'catalog_search'
    PROJECT_PREVIEW_SEARCH_CACHE_TYPE = 'project_preview_search'

    def __init__(self, user=None):
        self.catalog_cache = CatalogCacheService()
        self.user = user
        self._project_info_cache: Optional[Dict[str, Dict[str, Any]]] = None
        self._records_cache: Optional[List[ProjectRecord]] = None

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

        # Prefer snapshot data so keyword cloud reflects the cached project snapshot.
        info_map = self._load_project_info_from_graph()
        if info_map:
            counts: Dict[str, int] = defaultdict(int)
            labels: Dict[str, str] = {}

            for info in info_map.values():
                category_labels = info.get('category_labels', [])
                category_slugs = info.get('category_slugs', [])
                max_len = max(len(category_labels), len(category_slugs))

                for idx in range(max_len):
                    slug = category_slugs[idx] if idx < len(category_slugs) else ''
                    label = category_labels[idx] if idx < len(category_labels) else ''

                    if not slug:
                        slug = slugify(label) if label else ''

                    if not slug:
                        continue

                    counts[slug] += 1
                    if slug not in labels and label:
                        labels[slug] = label

            if counts:
                sorted_items = sorted(counts.items(), key=lambda item: item[1], reverse=True)
                results = []
                for slug, count in sorted_items[:limit]:
                    label = labels.get(slug)
                    if not label:
                        label = slug.replace('-', ' ').title()
                    results.append({'id': slug, 'label': label, 'count': count})

                self.catalog_cache.set_cached(
                    self.POPULAR_KEYWORDS_CACHE_TYPE,
                    results,
                    self.POPULAR_KEYWORDS_TTL,
                    **cache_params
                )
                return results

        # Snapshot data missing or empty: fall back to database aggregation.
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

        project_info_map = self._load_project_info_from_graph()
        if project_info_map:
            graph_projects = self._get_random_projects_from_graph(
                limit=limit,
                cache_params=cache_params,
                project_info_map=project_info_map,
                keyword_id=keyword_id,
                category=category,
                university=university,
                year=year,
            )
            if graph_projects is not None:
                return graph_projects

        return self._get_random_projects_from_db(
            limit=limit,
            cache_params=cache_params,
            keyword_id=keyword_id,
            category=category,
            university=university,
            year=year,
        )

    def search_project_previews(self, query: str, limit: int = 25) -> List[Dict[str, Any]]:
        """Return project preview cards matching a free-text query."""
        if not query:
            return []

        limit = max(1, min(limit, 50))
        normalized_query = query.strip().lower()
        if not normalized_query:
            return []

        cache_params = {
            'query': normalized_query,
            'limit': limit,
        }

        cached = self.catalog_cache.get_cached(
            self.PROJECT_PREVIEW_SEARCH_CACHE_TYPE,
            **cache_params,
        )
        if cached is not None:
            return cached

        records = self._get_snapshot_records()
        matches: List[ProjectRecord] = []
        for record in records:
            try:
                if record.matches_query(normalized_query):
                    matches.append(record)
            except Exception as exc:  # pragma: no cover - defensive
                logger.debug("Failed to evaluate search for %s: %s", record.uri, exc)

        previews = [self._record_to_preview(record) for record in matches[:limit]]

        self.catalog_cache.set_cached(
            self.PROJECT_PREVIEW_SEARCH_CACHE_TYPE,
            previews,
            self.RANDOM_PROJECTS_TTL,
            **cache_params,
        )

        return previews

    def _get_random_projects_from_graph(
        self,
        *,
        limit: int,
        cache_params: Dict[str, Any],
        project_info_map: Dict[str, Dict[str, Any]],
        keyword_id: Optional[str],
        category: Optional[str],
        university: Optional[str],
        year: Optional[int],
    ) -> Optional[List[Dict[str, Any]]]:
        """Return random projects using pre-built graph/card cache with proper relationship enrichment."""

        if not project_info_map:
            return None

        candidate_uris = self.catalog_cache.get_cached(
            self.RANDOM_PROJECTS_CACHE_TYPE,
            **cache_params
        )

        if candidate_uris in (None, []):
            candidate_uris = self._filter_project_uris_from_info(
                project_info_map,
                keyword_id=keyword_id,
                category=category,
                university=university,
                year=year,
            )

            if candidate_uris:
                self.catalog_cache.set_cached(
                    self.RANDOM_PROJECTS_CACHE_TYPE,
                    candidate_uris,
                    self.RANDOM_PROJECTS_TTL,
                    **cache_params
                )
            else:
                # Avoid reusing stale empty cache entries; surface empty list to caller.
                self.catalog_cache.invalidate(
                    self.RANDOM_PROJECTS_CACHE_TYPE,
                    **cache_params
                )
                return []

        if not candidate_uris:
            return None

        available_uris = [uri for uri in candidate_uris if uri in project_info_map]
        if not available_uris:
            return None

        if len(available_uris) <= limit:
            selected_uris = available_uris[:]
            random.shuffle(selected_uris)
        else:
            selected_uris = random.sample(available_uris, limit)

        # Use the same enrichment approach as CatalogView
        projects = self._enrich_projects_with_relationships(selected_uris, project_info_map)

        return projects or None

    def _enrich_projects_with_relationships(
        self,
        selected_uris: List[str],
        project_info_map: Dict[str, Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Build random project previews directly from snapshot records."""

        projects: List[Dict[str, Any]] = []

        for uri in selected_uris:
            info = project_info_map.get(uri)
            if not info:
                continue

            record: Optional[ProjectRecord] = info.get('record')
            if not record:
                continue

            preview = self._record_to_preview(record)
            if not preview.get('preview_image_url'):
                preview['preview_image_url'] = info['image']
            projects.append(preview)

        return projects

    def _get_random_projects_from_db(
        self,
        *,
        limit: int,
        cache_params: Dict[str, Any],
        keyword_id: Optional[str],
        category: Optional[str],
        university: Optional[str],
        year: Optional[int],
    ) -> List[Dict[str, Any]]:
        """Fallback implementation using database lookups."""

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
    # Graph-backed helpers
    # ------------------------------------------------------------------

    def _filter_project_uris_from_info(
        self,
        project_info_map: Dict[str, Dict[str, Any]],
        *,
        keyword_id: Optional[str],
        category: Optional[str],
        university: Optional[str],
        year: Optional[int]
    ) -> List[str]:
        keyword_slug = (keyword_id or '').strip().lower()
        category_filter = (category or '').strip().lower()
        university_filter = (university or '').strip().lower()

        results: List[str] = []
        for uri, info in project_info_map.items():
            if keyword_slug and keyword_slug not in info['category_slugs']:
                continue

            if category_filter and not any(category_filter in label.lower() for label in info['category_labels']):
                continue

            if university_filter:
                codes = {code.lower() for code in info['institution_codes']}
                label_matches = any(university_filter in label.lower() for label in info['institution_labels'])
                if university_filter not in codes and not label_matches:
                    continue

            if year and year not in info['year_values']:
                continue

            results.append(uri)

        return results

    def _get_snapshot_records(self) -> List[ProjectRecord]:
        if self._records_cache is not None:
            return self._records_cache

        try:
            snapshot = ProjectSnapshotService().get_cross_institutional_snapshot()
            self._records_cache = snapshot.projects
        except Exception as exc:
            logger.warning("Failed to load project snapshot for insights: %s", exc)
            self._records_cache = []

        return self._records_cache

    def _load_project_info_from_graph(self) -> Dict[str, Dict[str, Any]]:
        if self._project_info_cache is not None:
            return self._project_info_cache

        records = self._get_snapshot_records()
        if not records:
            self._project_info_cache = {}
            return self._project_info_cache

        info_map = {
            record.uri: self._build_info_from_record(record)
            for record in records
            if record.uri
        }

        self._project_info_cache = info_map
        return self._project_info_cache

    def _build_info_from_record(self, record: ProjectRecord) -> Dict[str, Any]:
        image = record.image
        if not image and record.digital_objects:
            image = record.digital_objects[0].path

        institution_label = record.institution.label if record.institution and record.institution.label else ''
        institution_codes = list(record.institution_codes)
        if record.institution and record.institution.code and record.institution.code not in institution_codes:
            institution_codes.append(record.institution.code.lower())

        category_labels = [cat.label for cat in record.categories if cat.label]
        year_values = self._extract_years_from_record(record)

        return {
            'uri': record.uri,
            'subject_id': record.subject_id,
            'slug': record.slug,
            'title': record.title or '',
            'image': image or '',
            'university_label': institution_label,
            'institution_labels': [institution_label] if institution_label else [],
            'institution_codes': [code.lower() for code in institution_codes],
            'category_labels': category_labels,
            'category_slugs': record.category_slugs,
            'year_values': year_values,
            'project_type': record.project_type.label if record.project_type and record.project_type.label else '',
            'record': record,
        }

    @staticmethod
    def _extract_years_from_record(record: ProjectRecord) -> Set[int]:
        years: Set[int] = set()

        for event in record.events:
            for value in (event.start, event.end):
                if not value:
                    continue
                try:
                    years.add(int(value.split('-')[0]))
                except (ValueError, TypeError):
                    continue

        if record.year_range:
            parts = [part.strip() for part in record.year_range.split('bis')]
            for part in parts:
                if not part:
                    continue
                try:
                    years.add(int(part.split('-')[0]))
                except (ValueError, TypeError):
                    continue

        return years

    def _record_to_preview(self, record: ProjectRecord) -> Dict[str, Any]:
        slug = record.slug
        image = record.image
        if not image and record.digital_objects:
            image = record.digital_objects[0].path

        preview = {
            'id': slug,
            'title': record.title or '',
            'university': record.institution.label if record.institution and record.institution.label else '',
            'year': self._primary_year(record),
            'project_type': record.project_type.label if record.project_type and record.project_type.label else None,
            'actors': [
                {
                    'name': actor.name,
                    'roles': actor.roles,
                }
                for actor in record.actors
                if actor.name
            ],
            'categories': [cat.label for cat in record.categories if cat.label],
            'preview_image_url': image or '',
            'detail_url': f"/projekt/{slug}",
        }

        return preview

    def _primary_year(self, record: ProjectRecord) -> Optional[int]:
        years = sorted(self._extract_years_from_record(record))
        return years[0] if years else None

    def _build_project_info(
        self,
        subject_id: str,
        card_map: Dict[str, Dict[str, Any]],
        nodes: Dict[str, Dict[str, Any]],
        edges_by_subject: Dict[str, List[Dict[str, Any]]],
    ) -> Optional[Dict[str, Any]]:
        node = nodes.get(subject_id)
        if not node:
            return None

        project_uri = node.get('uri')
        if not project_uri:
            return None

        slug = self._resource_slug(project_uri) or subject_id
        card = card_map.get(subject_id) or card_map.get(project_uri) or {}
        title = card.get('title') or self._get_literal_from_subject(subject_id, edges_by_subject, CardURIs.TITLE)
        if not title:
            return None

        image = card.get('image') or ''

        institution_info = self._collect_institution_info(subject_id, nodes, edges_by_subject)
        category_info = self._collect_category_info(subject_id, nodes, edges_by_subject)
        year_values = self._collect_years(subject_id, nodes, edges_by_subject)
        project_type = self._collect_project_type_from_edges(subject_id, edges_by_subject, nodes)

        return {
            'uri': project_uri,
            'subject_id': subject_id,
            'slug': slug,
            'title': title,
            'image': image,
            'university_label': institution_info['label'],
            'institution_labels': institution_info['labels'],
            'institution_codes': institution_info['codes'],
            'category_labels': category_info['labels'],
            'category_slugs': category_info['slugs'],
            'year_values': year_values,
            'project_type': project_type,
            'actors': [],
        }

    def _collect_institution_info(
        self,
        project_id: str,
        nodes: Dict[str, Dict[str, Any]],
        edges_by_subject: Dict[str, List[Dict[str, Any]]],
    ) -> Dict[str, Any]:
        labels: List[str] = []
        codes: Set[str] = set()

        for edge in edges_by_subject.get(project_id, []):
            if self._canonical(edge) != CardURIs.INSTITUTION:
                continue

            inst_id = edge.get('object_id')
            if not inst_id:
                continue

            inst_node = nodes.get(inst_id, {})
            slug = self._extract_node_slug(inst_node)
            if slug:
                codes.add(slug.lower())
            organization = inst_node.get('organization')
            if organization:
                codes.add(str(organization).lower())

            label = self._get_literal_from_subject(inst_id, edges_by_subject, CardURIs.INSTITUTION_GERMAN_NAME)
            if not label:
                label = inst_node.get('name') or inst_node.get('value') or inst_node.get('uri')
            if label:
                normalized = label.strip()
                if normalized and normalized not in labels:
                    labels.append(normalized)

        primary_label = labels[0] if labels else (next(iter(codes)).upper() if codes else "")

        return {
            'label': primary_label,
            'labels': labels,
            'codes': codes,
        }

    def _collect_category_info(
        self,
        project_id: str,
        nodes: Dict[str, Dict[str, Any]],
        edges_by_subject: Dict[str, List[Dict[str, Any]]],
    ) -> Dict[str, Any]:
        labels: List[str] = []
        slugs: Set[str] = set()

        for edge in edges_by_subject.get(project_id, []):
            if self._canonical(edge) != CardURIs.CATEGORY:
                continue

            category_id = edge.get('object_id')
            if not category_id:
                continue

            category_node = nodes.get(category_id, {})
            slug = self._extract_node_slug(category_node)
            if slug:
                slugs.add(slug.lower())

            label = self._get_literal_from_subject(category_id, edges_by_subject, CardURIs.CATEGORY_GERMAN_NAME)
            if not label:
                label = category_node.get('name') or category_node.get('value')
            if label:
                normalized = label.split('>')[-1].strip() if '>' in label else label.strip()
                if normalized and normalized not in labels:
                    labels.append(normalized)

        return {
            'labels': labels,
            'slugs': slugs,
        }

    def _collect_years(
        self,
        project_id: str,
        nodes: Dict[str, Dict[str, Any]],
        edges_by_subject: Dict[str, List[Dict[str, Any]]],
    ) -> Set[int]:
        years: Set[int] = set()

        for edge in edges_by_subject.get(project_id, []):
            if self._canonical(edge) != CardURIs.EVENT:
                continue

            event_id = edge.get('object_id')
            if not event_id:
                continue

            for event_edge in edges_by_subject.get(event_id, []):
                if self._canonical(event_edge) != CardURIs.EVENT_START:
                    continue
                year = self._extract_year(event_edge.get('object_value'))
                if year is not None:
                    years.add(year)

        if not years:
            project_uri = (nodes.get(project_id) or {}).get('uri')
            if project_uri:
                years.update(self._fetch_years_from_db(project_uri))

        return years

    def _fetch_years_from_db(self, project_uri: str) -> Set[int]:
        result: Set[int] = set()

        if not project_uri:
            return result

        project = Resource.objects.filter(uri=project_uri).first()
        if not project:
            return result

        event_predicate_ids = self._get_resource_ids_by_canonical(CardURIs.EVENT)
        start_predicate_ids = self._get_resource_ids_by_canonical(CardURIs.EVENT_START)
        if not event_predicate_ids or not start_predicate_ids:
            return result

        event_ids = list(
            Triple.objects.filter(
                predicate_id__in=event_predicate_ids,
                subject=project,
            ).values_list('object_id', flat=True)
        )

        if not event_ids:
            return result

        start_values = Triple.objects.filter(
            predicate_id__in=start_predicate_ids,
            subject_id__in=event_ids,
            object__resource_type=ResourceType.LITERAL,
        ).values_list('object__value', flat=True)

        for value in start_values:
            year = self._extract_year(value)
            if year is not None:
                result.add(year)

        return result

    def _collect_project_type_from_edges(
        self,
        project_id: str,
        edges_by_subject: Dict[str, List[Dict[str, Any]]],
        nodes: Dict[str, Dict[str, Any]],
    ) -> Optional[str]:
        for edge in edges_by_subject.get(project_id, []):
            if self._canonical(edge) != ProjectURIs.PROJECT_TYPE_FIELD:
                continue

            if edge.get('object_value'):
                return edge['object_value']

            object_id = edge.get('object_id')
            if object_id and object_id in nodes:
                node = nodes[object_id]
                return node.get('value') or node.get('name')

        return None

    def _get_literal_from_subject(
        self,
        subject_id: str,
        edges_by_subject: Dict[str, List[Dict[str, Any]]],
        predicate: str,
    ) -> Optional[str]:
        for edge in edges_by_subject.get(subject_id, []):
            if self._canonical(edge) == predicate and edge.get('object_value'):
                return edge['object_value']
        return None

    @staticmethod
    def _extract_node_slug(node: Optional[Dict[str, Any]]) -> Optional[str]:
        if not node:
            return None
        for key in ('uri', 'canonical_uri'):
            value = node.get(key)
            if value:
                slug = CatalogInsightsService._resource_slug(value)
                if slug:
                    return slug
        return None

    @staticmethod
    def _canonical(edge: Dict[str, Any]) -> Optional[str]:
        if not edge:
            return None
        return edge.get('predicate_canonical') or edge.get('predicate_uri')

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

        # Get raw project type ID
        project_type_triple = Triple.objects.filter(
            subject=project,
            predicate__canonical_uri=ProjectURIs.PROJECT_TYPE_FIELD,
            object__resource_type=ResourceType.LITERAL
        ).first()

        if project_type_triple and project_type_triple.object:
            project_type_id = project_type_triple.object.literal_value
            # Resolve ID to German name
            return self._resolve_project_type_name_from_id(project_type_id)

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

    def _resolve_project_type_name_from_id(self, project_type_id: str) -> Optional[str]:
        """Resolve project type ID to German name (fallback method)."""
        if not project_type_id:
            return None

        # Construct the project type entity URI
        project_type_uri = f"http://arkumu.org/data/fuk/entities/projektart/{project_type_id}"

        try:
            # Get the project type entity
            project_type_entity = Resource.objects.filter(uri=project_type_uri).first()
            if not project_type_entity:
                return project_type_id  # Return the ID if we can't resolve it

            # Get the German name
            german_name_triple = Triple.objects.filter(
                subject=project_type_entity,
                predicate__canonical_uri='http://arkumu.org/data/properties/deutscher-name-der-projektart'
            ).first()

            if german_name_triple and german_name_triple.object:
                return german_name_triple.object.value

        except Exception as exc:
            logger.warning(f"Failed to resolve project type '{project_type_id}': {exc}")

        return project_type_id  # Return the ID as fallback
