"""Build and cache reusable project snapshots."""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any, Dict, Iterable, List, Optional, Sequence

from django.utils import timezone

from arkumu.cache.services.project_cache_service import ProjectCacheService
from arkumu.catalog.services.schema_manifest_service import (
    SchemaManifestService,
    CardSchema,
    CardSection,
    CardProperty,
    CanonicalPropertyBinding,
    CARD_SCHEMA_TEMPLATE,
)
from arkumu.catalog.services.triple_relationship_service import TripleRelationshipService
from arkumu.catalog.services.project_views import CardURIs, ProjectURIs
from arkumu.metadata.models.resource import ResourceType
from arkumu.metadata.services.canonical_graph_service import CanonicalGraphService
from arkumu.projects import (
    ProjectActor,
    ProjectAlternateTitle,
    ProjectCategory,
    ProjectCatchphrase,
    ProjectDigitalObject,
    ProjectEvent,
    ProjectEventActor,
    ProjectInstitution,
    ProjectRecord,
    ProjectSnapshot,
    ProjectType,
)

logger = logging.getLogger(__name__)


class ProjectSnapshotService:
    """Constructs project snapshots backed by cache."""

    CROSS_SCOPE_URI = "arkumu:cross_institutional:all_projects"
    DEFAULT_ORGANIZATION_CODES: Sequence[str] = (
        "fuk",
        "rsh",
        "det",
        "khm",
        "uk",
        "hfmt",
    )

    def __init__(self, relationship_org_code: Optional[str] = None) -> None:
        self.relationship_org_code = relationship_org_code
        self.cache = ProjectCacheService()
        self.schema_service = SchemaManifestService()
        self._graph_service_factory = CanonicalGraphService

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
        card_schema = self._get_card_schema()
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
        primary_graph = self._graph_service_factory().get_project_graph(
            dataset_name="Projekt",
            type_canonical_uri=CardURIs.PROJECT_TYPE,
            expand_neighbors=True,
        )

        if primary_graph.get('subjects'):
            logger.info(
                "Cross-institutional graph built from canonical class: %d subjects",
                len(primary_graph.get('subjects', [])),
            )
            return self._deduplicate_graph(primary_graph)

        logger.info(
            "No subjects found for canonical project type; falling back to per-organization graphs",
        )
        combined_graph = self._build_combined_organization_graphs()
        logger.info(
            "Combined per-organization graphs: %d subjects, %d nodes, %d edges",
            len(combined_graph.get('subjects', [])),
            len(combined_graph.get('nodes', {})),
            len(combined_graph.get('edges', [])),
        )
        return combined_graph

    def _build_combined_organization_graphs(self) -> Dict[str, Any]:
        subjects: List[str] = []
        nodes: Dict[str, Dict[str, Any]] = {}
        edges: List[Dict[str, Any]] = []
        edge_signatures: set[tuple] = set()

        for org_code in self.DEFAULT_ORGANIZATION_CODES:
            try:
                org_graph = self._graph_service_factory(org_code=org_code).get_project_graph(
                    dataset_name="Projekt",
                    expand_neighbors=True,
                )
            except Exception as exc:  # pragma: no cover - defensive logging
                logger.exception(
                    "Failed to build organization graph for '%s': %s",
                    org_code,
                    exc,
                )
                continue

            org_subjects = [str(subject) for subject in org_graph.get('subjects', [])]
            for subject in org_subjects:
                if subject not in subjects:
                    subjects.append(subject)

            nodes.update(org_graph.get('nodes', {}))

            for edge in org_graph.get('edges', []):
                signature = self._edge_signature(edge)
                if signature in edge_signatures:
                    continue
                edge_signatures.add(signature)
                edges.append(edge)

        return {
            'organization': 'cross-institutional',
            'dataset': 'Projekt',
            'subjects': subjects,
            'nodes': nodes,
            'edges': edges,
            'counts': {
                'subjects': len(subjects),
                'nodes': len(nodes),
                'edges': len(edges),
            },
        }

    def _deduplicate_graph(self, graph: Dict[str, Any]) -> Dict[str, Any]:
        subjects = []
        seen_subjects: set[str] = set()
        for subject in graph.get('subjects', []):
            subject_str = str(subject)
            if subject_str in seen_subjects:
                continue
            seen_subjects.add(subject_str)
            subjects.append(subject_str)

        nodes = graph.get('nodes', {}) or {}

        edge_signatures: set[tuple] = set()
        edges: List[Dict[str, Any]] = []
        for edge in graph.get('edges', []):
            signature = self._edge_signature(edge)
            if signature in edge_signatures:
                continue
            edge_signatures.add(signature)
            edges.append(edge)

        return {
            'organization': 'cross-institutional',
            'dataset': graph.get('dataset', 'Projekt'),
            'subjects': subjects,
            'nodes': nodes,
            'edges': edges,
            'counts': {
                'subjects': len(subjects),
                'nodes': len(nodes),
                'edges': len(edges),
            },
        }

    @staticmethod
    def _edge_signature(edge: Dict[str, Any]) -> tuple:
        return (
            edge.get('triple_id'),
            edge.get('subject_id') or edge.get('subject') or edge.get('s'),
            edge.get('predicate_uri') or edge.get('predicate_canonical'),
            edge.get('object_id'),
            edge.get('object_value'),
        )

    def _get_card_schema(self) -> CardSchema:
        if self.relationship_org_code:
            return self.schema_service.get_card_schema(self.relationship_org_code)

        from arkumu.metadata.models import Mapping

        available_orgs = set(
            Mapping.objects
            .filter(organization_id__in=self.DEFAULT_ORGANIZATION_CODES)
            .values_list('organization_id', flat=True)
        )

        schemas = [
            self.schema_service.get_card_schema(code)
            for code in self.DEFAULT_ORGANIZATION_CODES
            if code in available_orgs
        ]
        return self._combine_card_schemas(schemas)

    @staticmethod
    def _combine_card_schemas(schemas: Sequence[CardSchema]) -> CardSchema:
        if not schemas:
            return CardSchema(sections={})

        section_names = set(CARD_SCHEMA_TEMPLATE.sections.keys())
        for schema in schemas:
            section_names.update(schema.sections.keys())

        combined_sections: Dict[str, CardSection] = {}
        for name in section_names:
            template_section = CARD_SCHEMA_TEMPLATE.sections.get(name)
            source_section = None
            if not template_section:
                for schema in schemas:
                    candidate = schema.sections.get(name)
                    if candidate:
                        source_section = candidate
                        break

            section_def = template_section or source_section
            if section_def is None:
                continue

            combined_sections[name] = CardSection(
                label=section_def.label,
                canonical_class_uri=section_def.canonical_class_uri,
                properties={
                    prop_name: CardProperty(
                        name=prop.name,
                        canonical_uri=prop.canonical_uri,
                        bindings=[],
                    )
                    for prop_name, prop in section_def.properties.items()
                },
                fk_relationships=[],
            )

        for schema in schemas:
            for section_name, section in schema.sections.items():
                combined_section = combined_sections.get(section_name)
                if not combined_section:
                    continue

                existing_fk_signatures = {
                    ProjectSnapshotService._fk_signature(entry)
                    for entry in combined_section.fk_relationships
                }
                for fk_entry in section.fk_relationships:
                    signature = ProjectSnapshotService._fk_signature(fk_entry)
                    if signature in existing_fk_signatures:
                        continue
                    existing_fk_signatures.add(signature)
                    combined_section.fk_relationships.append(fk_entry)

                for prop_name, prop in section.properties.items():
                    combined_prop = combined_section.properties.get(prop_name)
                    if not combined_prop:
                        continue
                    combined_prop.bindings = ProjectSnapshotService._merge_property_bindings(
                        combined_prop.bindings,
                        prop.bindings,
                    )

        return CardSchema(sections=combined_sections)

    @staticmethod
    def _fk_signature(entry: Dict[str, Any]) -> tuple:
        return (
            entry.get('source_property'),
            entry.get('target_property'),
            entry.get('target_dataset'),
            entry.get('target_column'),
            entry.get('is_multi_value', False),
        )

    @staticmethod
    def _merge_property_bindings(
        existing: Sequence[CanonicalPropertyBinding],
        new_bindings: Sequence[CanonicalPropertyBinding],
    ) -> List[CanonicalPropertyBinding]:
        merged = list(existing)
        seen = {
            (
                binding.dataset,
                binding.column,
                binding.canonical_uri,
                binding.local_uri,
                binding.name,
            )
            for binding in merged
        }

        for binding in new_bindings:
            key = (
                binding.dataset,
                binding.column,
                binding.canonical_uri,
                binding.local_uri,
                binding.name,
            )
            if key in seen:
                continue
            seen.add(key)
            merged.append(binding)

        return merged

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
        category_synonym_prop = _property('project_category', 'synonyms')
        category_wikidata_prop = _property('project_category', 'wikidata_id')
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

        event_entries = triple_service.get_detailed_event_data(
            subject_id,
            event_predicate=event_prop.canonical_uri if event_prop else None,
            event_start_predicate=event_start_prop.canonical_uri if event_start_prop else None,
            event_end_predicate=event_end_prop.canonical_uri if event_end_prop else None,
            event_name_predicate=ProjectURIs.EVENT_NAME,
            event_description_predicate=ProjectURIs.EVENT_DESCRIPTION,
            event_location_predicate=ProjectURIs.EVENT_LOCATION,
            event_type_predicate=ProjectURIs.EVENT_TYPE,
            organization_code=self.relationship_org_code,
        )
        event_ids: List[str] = []
        events: List[ProjectEvent] = []
        for entry in event_entries:
            event_id = entry.get('id')
            if event_id:
                event_ids.append(event_id)
            event_node = nodes.get(event_id, {}) if event_id else {}
            events.append(
                ProjectEvent(
                    id=event_id,
                    uri=event_node.get('uri') or event_node.get('canonical_uri'),
                    name=entry.get('name'),
                    description=entry.get('description'),
                    location=entry.get('location'),
                    location_id=entry.get('location_id'),
                    country=entry.get('country'),
                    latitude=self._maybe_float(entry.get('latitude')),
                    longitude=self._maybe_float(entry.get('longitude')),
                    type=entry.get('type'),
                    start=entry.get('start'),
                    end=entry.get('end'),
                )
            )
        year_range = self._derive_year_range(events)

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
        actors_by_event: Dict[str, List[ProjectEventActor]] = defaultdict(list)
        actors: List[ProjectActor] = []
        for payload in actors_payload:
            name = payload.get('name')
            if not name:
                continue
            roles = list(payload.get('roles', []))
            actors.append(ProjectActor(name=name, roles=roles))
            for event_id in payload.get('event_ids', []):
                actors_by_event[event_id].append(
                    ProjectEventActor(name=name, roles=list(roles))
                )

        for event in events:
            if event.id:
                event.actors = list(actors_by_event.get(event.id, []))

        institution_ids = self._related_ids(subject_edges, institution_prop.canonical_uri if institution_prop else None)
        institution: Optional[ProjectInstitution] = None
        institution_codes: List[str] = []
        if institution_ids:
            for inst_index, inst_id in enumerate(institution_ids):
                inst_node = nodes.get(inst_id, {})
                inst_uri = inst_node.get('uri') or inst_node.get('canonical_uri')
                inst_label = self._first_literal(
                    edges_by_subject.get(inst_id, []),
                    institution_name_prop.canonical_uri if institution_name_prop else None,
                ) or inst_node.get('name') or inst_node.get('value')
                inst_code = inst_node.get('organization') or self._resource_slug(inst_uri)
                normalized_code = str(inst_code).lower() if inst_code else None
                if normalized_code and normalized_code not in institution_codes:
                    institution_codes.append(normalized_code)

                inst_object = ProjectInstitution(
                    label=inst_label,
                    uri=inst_uri,
                    code=normalized_code,
                )
                if inst_index == 0 and institution is None:
                    institution = inst_object


        categories: List[ProjectCategory] = []
        category_slugs: List[str] = []
        seen_category_keys: set[tuple] = set()
        for category_id in self._related_ids(subject_edges, category_prop.canonical_uri if category_prop else None):
            cat_node = nodes.get(category_id, {})
            if (cat_node.get('resource_type') or '').upper() == ResourceType.LITERAL:
                continue
            cat_uri = cat_node.get('uri') or cat_node.get('canonical_uri')
            wikidata_literal = self._first_literal(
                edges_by_subject.get(category_id, []),
                category_wikidata_prop.canonical_uri if category_wikidata_prop else None,
            )
            raw_label = self._first_literal(
                edges_by_subject.get(category_id, []),
                category_name_prop.canonical_uri if category_name_prop else None,
            ) or cat_node.get('name') or cat_node.get('value')
            synonym_literal = self._first_literal(
                edges_by_subject.get(category_id, []),
                category_synonym_prop.canonical_uri if category_synonym_prop else None,
            )
            cat_label = self._resolve_category_label(wikidata_literal, synonym_literal, raw_label)
            if not cat_label:
                continue
            cat_slug = self._resource_slug(cat_uri)
            dedupe_key = (cat_uri, cat_label)
            if dedupe_key in seen_category_keys:
                continue
            seen_category_keys.add(dedupe_key)
            if cat_slug:
                normalized_slug = cat_slug.lower()
                if normalized_slug not in category_slugs:
                    category_slugs.append(normalized_slug)
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

    @staticmethod
    def _maybe_float(value: Optional[Any]) -> Optional[float]:
        if value is None or value == "":
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

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
    def _resolve_category_label(
        wikidata_literal: Optional[Any],
        synonyms_literal: Optional[Any],
        breadcrumb_literal: Optional[Any],
    ) -> Optional[str]:
        wikidata_label = ProjectSnapshotService._normalize_wikidata_id(wikidata_literal)
        if wikidata_label:
            return wikidata_label
        synonym = ProjectSnapshotService._preferred_synonym(synonyms_literal)
        if synonym:
            return synonym
        breadcrumb = ProjectSnapshotService._normalize_breadcrumb(breadcrumb_literal)
        if breadcrumb:
            return breadcrumb
        return None

    @staticmethod
    def _normalize_wikidata_id(value: Optional[Any]) -> Optional[str]:
        if value is None:
            return None
        text = str(value).strip().upper()
        if not text:
            return None
        if text.startswith('Q') and text[1:].isdigit():
            return text
        if text.isdigit():
            return f"Q{text}"
        return None

    @staticmethod
    def _normalize_breadcrumb(label: Optional[Any]) -> Optional[str]:
        if label is None:
            return None
        text = str(label).strip()
        if not text:
            return None
        if '>' in text:
            parts = [part.strip() for part in text.split('>') if part.strip()]
            text = parts[-1] if parts else ''
        if not text or text.isdigit():
            return None
        return text

    @staticmethod
    def _preferred_synonym(value: Optional[Any]) -> Optional[str]:
        if value is None:
            return None
        tokens = [token.strip() for token in str(value).replace(';', ',').split(',') if token.strip()]
        if not tokens:
            return None
        return tokens[0]

    @staticmethod
    def _derive_year_range(events: Sequence[ProjectEvent]) -> Optional[str]:
        for event in events:
            start = event.start
            end = event.end
            if start and end:
                start_year = start.split('-')[0] if '-' in start else start
                end_year = end.split('-')[0] if '-' in end else end
                return start_year if start_year == end_year else f"{start_year} bis {end_year}"
            if start:
                return start.split('-')[0] if '-' in start else start
            if end:
                return end.split('-')[0] if '-' in end else end
        return None
