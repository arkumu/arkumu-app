"""Build and cache reusable project snapshots."""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any, Dict, Iterable, List, Optional, Sequence

from django.utils import timezone

from arkumu.cache.services.project_cache_service import ProjectCacheService
from arkumu.catalog.services.schema_manifest_service import SchemaManifestService, CardSchema, CardProperty
from arkumu.catalog.services.triple_relationship_service import TripleRelationshipService
from arkumu.catalog.services.project_views import CardURIs, ProjectURIs
from arkumu.metadata.services.canonical_graph_service import CanonicalGraphService
from arkumu.projects import (
    ProjectActor,
    ProjectAlternateTitle,
    ProjectCategory,
    ProjectCatchphrase,
    ProjectDigitalObject,
    ProjectEvent,
    ProjectInstitution,
    ProjectRecord,
    ProjectSnapshot,
    ProjectType,
)

logger = logging.getLogger(__name__)


class ProjectSnapshotService:
    """Constructs project snapshots backed by cache."""

    CROSS_SCOPE_URI = "arkumu:cross_institutional:all_projects"

    def __init__(self, relationship_org_code: Optional[str] = None) -> None:
        self.relationship_org_code = relationship_org_code
        self.cache = ProjectCacheService()
        self.schema_service = SchemaManifestService()

    def get_cross_institutional_snapshot(self, *, force_refresh: bool = False) -> ProjectSnapshot:
        """Return cached snapshot or rebuild if necessary."""
        if not force_refresh:
            cached = self.cache.get_cross_institutional_snapshot()
            if cached:
                logger.info("ProjectSnapshotService: cache hit for cross-institutional snapshot")
                return cached

        logger.info("ProjectSnapshotService: cache miss – rebuilding cross-institutional snapshot")
        snapshot = self._build_snapshot()
        self.cache.set_cross_institutional_snapshot(snapshot)
        return snapshot

    def refresh_cross_institutional_snapshot(self) -> ProjectSnapshot:
        """Force a snapshot rebuild and update cache."""
        snapshot = self._build_snapshot()
        self.cache.set_cross_institutional_snapshot(snapshot)
        return snapshot

    def _build_snapshot(self) -> ProjectSnapshot:
        graph = self._fetch_cross_institutional_graph()
        card_schema = self.schema_service.get_card_schema('fuk')
        records = self._graph_to_records(graph, card_schema)
        counts = graph.get('counts', {})
        if not counts:
            counts = {
                'projects': len(records),
                'subjects': len(graph.get('subjects', [])),
                'edges': len(graph.get('edges', [])),
            }
        return ProjectSnapshot(
            projects=records,
            counts=counts,
            generated_at=timezone.now(),
        )

    def _fetch_cross_institutional_graph(self) -> Dict[str, Any]:
        logger.info("Building cross-institutional project graph via CanonicalGraphService")
        service = CanonicalGraphService()
        canonical_project_uri = CardURIs.PROJECT_TYPE

        subject_ids = service._find_subject_ids_by_class(canonical_project_uri)
        normalized_subject_ids = [str(subject_id) for subject_id in subject_ids]
        logger.info("Found %d projects using canonical URI", len(normalized_subject_ids))

        if not normalized_subject_ids:
            logger.info("Falling back to organization-specific project classes")
            institution_uris = [
                "http://arkumu.org/data/fuk/types/projekt",
                "http://arkumu.org/data/rsh/types/projekt",
                "http://arkumu.org/data/det/types/projekt",
                "http://arkumu.org/data/khm/types/projekt",
                "http://arkumu.org/data/uk/types/projekt",
                "http://arkumu.org/data/hfmt/types/projekt",
            ]
            for uri in institution_uris:
                ids = service._find_subject_ids_by_class(uri)
                normalized_subject_ids.extend(str(subject_id) for subject_id in ids)
                logger.info("  %s -> %d subjects", uri, len(ids))

        edges = service._fetch_triples_for_subjects(normalized_subject_ids)
        if edges:
            neighbor_ids = [edge.object_id for edge in edges if edge.object_type != 'LITERAL'][:1000]
            if neighbor_ids:
                neighbor_edges = service._fetch_triples_for_subjects(neighbor_ids)
                edges.extend(neighbor_edges)
        nodes = service._collect_nodes_from_edges(edges)

        graph = {
            'organization': 'cross-institutional',
            'dataset': 'Projekt',
            'subjects': normalized_subject_ids,
            'nodes': nodes,
            'edges': [edge.__dict__ for edge in edges],
            'counts': {
                'subjects': len(normalized_subject_ids),
                'nodes': len(nodes),
                'edges': len(edges),
            },
        }
        logger.info(
            "Cross-institutional graph built: %d subjects, %d nodes, %d edges",
            graph['counts']['subjects'],
            graph['counts']['nodes'],
            graph['counts']['edges'],
        )
        return graph

    def _graph_to_records(self, graph: Dict[str, Any], card_schema: CardSchema) -> List[ProjectRecord]:
        nodes: Dict[str, Dict[str, Any]] = graph.get('nodes', {})
        edges: List[Dict[str, Any]] = graph.get('edges', [])
        subjects: Sequence[str] = graph.get('subjects', [])

        edges_by_subject: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for edge in edges:
            subject_id = edge.get('subject_id') or edge.get('subject') or edge.get('s')
            if subject_id is None:
                continue
            edges_by_subject[str(subject_id)].append(edge)

        triple_service = TripleRelationshipService(self.relationship_org_code)
        records: List[ProjectRecord] = []

        for subject_id in subjects:
            record = self._build_project_record(
                str(subject_id),
                nodes,
                edges_by_subject,
                card_schema,
                triple_service,
            )
            if record:
                records.append(record)

        logger.info("Built %d project records from graph", len(records))
        return records

    def _build_project_record(
        self,
        subject_id: str,
        nodes: Dict[str, Dict[str, Any]],
        edges_by_subject: Dict[str, List[Dict[str, Any]]],
        card_schema: CardSchema,
        triple_service: TripleRelationshipService,
    ) -> Optional[ProjectRecord]:
        node = nodes.get(subject_id)
        if not node:
            return None

        project_uri = node.get('uri') or node.get('canonical_uri') or node.get('value')
        if not project_uri:
            return None

        subject_edges = edges_by_subject.get(subject_id, [])

        def _property(section: str, prop: str) -> Optional[CardProperty]:
            section_obj = card_schema.sections.get(section)
            if not section_obj:
                return None
            return section_obj.properties.get(prop)

        title_prop = _property('project', 'title')
        subtitle_prop = _property('project', 'subtitle')
        image_prop = _property('project', 'image')
        event_prop = _property('project', 'event')
        institution_prop = _property('project', 'institution')
        category_prop = _property('project', 'category')

        event_start_prop = _property('event', 'start')
        event_end_prop = _property('event', 'end')

        actor_link_prop = _property('actor_event', 'actor_link')
        role_link_prop = _property('actor_event', 'role_link')
        actor_name_prop = _property('actor', 'name')
        role_name_prop = _property('role', 'name')

        institution_name_prop = _property('institution', 'german_name')
        category_name_prop = _property('project_category', 'german_name')
        digital_object_path_prop = _property('digital_object', 'path')

        title = self._first_literal(subject_edges, title_prop.canonical_uri if title_prop else None)
        subtitle = self._first_literal(subject_edges, subtitle_prop.canonical_uri if subtitle_prop else None)
        image = self._first_literal(subject_edges, image_prop.canonical_uri if image_prop else None)

        description = triple_service.get_project_description(
            subject_id,
            description_predicate=ProjectURIs.DESCRIPTION,
            organization_code=self.relationship_org_code,
        )

        alternative_titles = [
            ProjectAlternateTitle(value=value)
            for value in triple_service.get_alternative_titles(
                subject_id,
                alternative_title_set_predicate=ProjectURIs.ALTERNATIVE_TITLE,
                alternative_title_predicate=ProjectURIs.ALTERNATIVE_TITLE_VALUE,
                organization_code=self.relationship_org_code,
            )
            if value
        ]

        catchphrases = [
            ProjectCatchphrase(label=value)
            for value in triple_service.get_catchphrases(
                subject_id,
                catchphrase_predicate=ProjectURIs.CATCHPHRASE,
                catchphrase_label_predicate=ProjectURIs.CATCHPHRASE_WIKIDATA,
                organization_code=self.relationship_org_code,
            )
            if value
        ]

        project_type_label = triple_service.get_project_type(
            subject_id,
            project_type_predicate=ProjectURIs.PROJECT_TYPE_FIELD,
            organization_code=self.relationship_org_code,
        )
        project_type = ProjectType(label=project_type_label) if project_type_label else None

        events_payload = triple_service.get_event_data(
            subject_id,
            event_predicate=event_prop.canonical_uri if event_prop else None,
            event_start_predicate=event_start_prop.canonical_uri if event_start_prop else None,
            event_end_predicate=event_end_prop.canonical_uri if event_end_prop else None,
            organization_code=self.relationship_org_code,
        )
        event_ids = events_payload.get('event_ids', [])
        event_details = events_payload.get('event_details', {})
        events = [
            ProjectEvent(
                start=event_details.get(event_id, {}).get('start'),
                end=event_details.get(event_id, {}).get('end'),
                uri=nodes.get(event_id, {}).get('uri'),
            )
            for event_id in event_ids
        ]
        year_range = self._derive_year_range(event_ids, event_details)

        actors_payload = triple_service.get_actor_relationships(
            subject_id,
            event_predicate=event_prop.canonical_uri if event_prop else None,
            actor_link_predicate=actor_link_prop.canonical_uri if actor_link_prop else None,
            role_link_predicate=role_link_prop.canonical_uri if role_link_prop else None,
            actor_name_predicate=actor_name_prop.canonical_uri if actor_name_prop else None,
            role_name_predicate=role_name_prop.canonical_uri if role_name_prop else None,
            event_ids=event_ids,
            organization_code=self.relationship_org_code,
        )
        actors = [
            ProjectActor(name=payload.get('name'), roles=payload.get('roles', []))
            for payload in actors_payload
        ]

        institution_ids = self._related_ids(subject_edges, institution_prop.canonical_uri if institution_prop else None)
        institution = None
        institution_codes: List[str] = []
        if institution_ids:
            inst_id = institution_ids[0]
            inst_node = nodes.get(inst_id, {})
            inst_uri = inst_node.get('uri') or inst_node.get('canonical_uri')
            inst_label = self._first_literal(
                edges_by_subject.get(inst_id, []),
                institution_name_prop.canonical_uri if institution_name_prop else None,
            ) or inst_node.get('name') or inst_node.get('value')
            inst_code = inst_node.get('organization') or self._resource_slug(inst_uri)
            if inst_code:
                institution_codes.append(str(inst_code).lower())
            institution = ProjectInstitution(
                label=inst_label,
                uri=inst_uri,
                code=str(inst_code).lower() if inst_code else None,
            )

        categories: List[ProjectCategory] = []
        category_slugs: List[str] = []
        for category_id in self._related_ids(subject_edges, category_prop.canonical_uri if category_prop else None):
            cat_node = nodes.get(category_id, {})
            cat_uri = cat_node.get('uri') or cat_node.get('canonical_uri')
            cat_label = self._first_literal(
                edges_by_subject.get(category_id, []),
                category_name_prop.canonical_uri if category_name_prop else None,
            ) or cat_node.get('name') or cat_node.get('value')
            cat_slug = self._resource_slug(cat_uri)
            if cat_slug:
                category_slugs.append(cat_slug.lower())
            categories.append(ProjectCategory(label=cat_label, uri=cat_uri, slug=cat_slug))

        def _fk_source_for_target(section_name: str, target_property: Optional[str]) -> Optional[str]:
            if not target_property:
                return None
            section = card_schema.sections.get(section_name)
            if not section or not section.fk_relationships:
                return None
            for fk in section.fk_relationships:
                if fk.get('target_property') == target_property:
                    return fk.get('source_property')
            return None

        digital_link_predicate = _fk_source_for_target('project', digital_object_path_prop.canonical_uri if digital_object_path_prop else None)
        digital_objects = [
            ProjectDigitalObject(path=path)
            for path in triple_service.get_digital_object_paths(
                subject_id,
                link_predicate=digital_link_predicate,
                path_predicate=digital_object_path_prop.canonical_uri if digital_object_path_prop else None,
                organization_code=self.relationship_org_code,
            )
            if path
        ]

        if not title:
            return None

        record = ProjectRecord(
            subject_id=subject_id,
            uri=project_uri,
            title=title,
            subtitle=subtitle,
            description=description,
            image=image,
            institution=institution,
            categories=categories,
            events=events,
            actors=actors,
            alternative_titles=alternative_titles,
            catchphrases=catchphrases,
            project_type=project_type,
            digital_objects=digital_objects,
            year_range=year_range or None,
            institution_codes=institution_codes,
            category_slugs=category_slugs,
        )
        return record

    @staticmethod
    def _canonical(edge: Dict[str, Any]) -> Optional[str]:
        if not edge:
            return None
        return edge.get('predicate_canonical') or edge.get('predicate_uri')

    def _first_literal(self, edges: Iterable[Dict[str, Any]], predicate: Optional[str]) -> Optional[str]:
        if not predicate:
            return None
        for edge in edges:
            if self._canonical(edge) == predicate and edge.get('object_value'):
                return edge['object_value']
        return None

    def _related_ids(self, edges: Iterable[Dict[str, Any]], predicate: Optional[str]) -> List[str]:
        if not predicate:
            return []
        ids: List[str] = []
        for edge in edges:
            if self._canonical(edge) == predicate and edge.get('object_id'):
                ids.append(str(edge['object_id']))
        return ids

    @staticmethod
    def _resource_slug(uri: Optional[str]) -> Optional[str]:
        if not uri:
            return None
        return uri.rstrip('/').split('/')[-1]

    @staticmethod
    def _derive_year_range(
        event_ids: Sequence[str],
        event_details: Dict[str, Dict[str, Optional[str]]],
    ) -> Optional[str]:
        for event_id in event_ids:
            entry = event_details.get(event_id) or {}
            start = entry.get('start')
            end = entry.get('end')
            if start and end:
                start_year = start.split('-')[0] if '-' in start else start
                end_year = end.split('-')[0] if '-' in end else end
                return start_year if start_year == end_year else f"{start_year} bis {end_year}"
            if start:
                return start.split('-')[0] if '-' in start else start
            if end:
                return end.split('-')[0] if '-' in end else end
        return None
