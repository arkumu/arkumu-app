"""Build and cache reusable project snapshots."""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import urlparse

from django.utils import timezone
from django.conf import settings
from django.db.models import Q

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
from arkumu.metadata.models.triples import Triple
from arkumu.metadata.services.canonical_graph_service import CanonicalGraphService
from arkumu.projects import (
    ProjectActor,
    ProjectAlternateTitle,
    ProjectCategory,
    ProjectCatchphrase,
    ProjectDigitalObject,
    ProjectDigitalObjectLicense,
    ProjectEvent,
    ProjectEventActor,
    ProjectInstitution,
    ProjectRecord,
    ProjectSnapshot,
    ProjectType,
)
from arkumu.projects.fixity import parse_fixity

logger = logging.getLogger(__name__)



class ProjectSnapshotService:
    """Constructs project snapshots backed by cache."""

    CROSS_SCOPE_URI = "arkumu:cross_institutional:all_projects"
    DEFAULT_ORGANIZATION_CODES: Sequence[str] = (
        "fuk",
        "rsh",
        "det",
        "khm",
        "hmt",
    )
    DIGITAL_OBJECT_LINK_URI = "http://arkumu.org/data/properties/digitales-objekt"
    DIGITAL_OBJECT_LICENSE_LINK_URI = "http://arkumu.org/data/properties/lizenzstatus"
    DIGITAL_OBJECT_LICENSE_URI_PROPERTY = "http://arkumu.org/data/properties/uri"
    DIGITAL_OBJECT_LICENSE_LABEL_DE_PROPERTY = "http://arkumu.org/data/properties/deutscher-name-der-lizenz"
    DIGITAL_OBJECT_LICENSE_LABEL_EN_PROPERTY = "http://arkumu.org/data/properties/englischer-name-der-lizenz"
    DIGITAL_OBJECT_LICENSE_RIGHTS_STATEMENT_PROPERTY = "http://arkumu.org/data/properties/zugehoeriges-rechtestatement"
    DIGITAL_OBJECT_LICENSE_URI_FALLBACKS: Tuple[str, ...] = (
        DIGITAL_OBJECT_LICENSE_URI_PROPERTY,
        "http://arkumu.org/data/fuk/properties/uri",
        "http://arkumu.org/data/hmt/properties/uri",
        "http://arkumu.org/data/khm/properties/uri",
    )
    DIGITAL_OBJECT_LICENSE_LABEL_DE_FALLBACKS: Tuple[str, ...] = (
        DIGITAL_OBJECT_LICENSE_LABEL_DE_PROPERTY,
        "http://arkumu.org/data/fuk/properties/deutscher-name-der-lizenz",
        "http://arkumu.org/data/fuk/properties/deutscher-anzeigetext",
        "http://arkumu.org/data/hmt/properties/deutscher-name-der-lizenz",
        "http://arkumu.org/data/khm/properties/deutscher-name-der-lizenz",
    )
    DIGITAL_OBJECT_LICENSE_LABEL_EN_FALLBACKS: Tuple[str, ...] = (
        DIGITAL_OBJECT_LICENSE_LABEL_EN_PROPERTY,
        "http://arkumu.org/data/fuk/properties/englischer-name-der-lizenz",
        "http://arkumu.org/data/fuk/properties/englischer-anzeigetext",
        "http://arkumu.org/data/hmt/properties/englischer-name-der-lizenz",
        "http://arkumu.org/data/khm/properties/englischer-name-der-lizenz",
    )
    DIGITAL_OBJECT_LICENSE_RIGHTS_STATEMENT_FALLBACKS: Tuple[str, ...] = (
        DIGITAL_OBJECT_LICENSE_RIGHTS_STATEMENT_PROPERTY,
        "http://arkumu.org/data/fuk/properties/zugehoeriges-rechtestatement",
        "http://arkumu.org/data/hmt/properties/zugehoeriges-rechtestatement",
        "http://arkumu.org/data/khm/properties/zugehoeriges-rechtestatement",
    )
    DIGITAL_OBJECT_UUID_PROPERTY = "http://arkumu.org/data/properties/uuid"
    DIGITAL_OBJECT_GENESIS_PROPERTIES = (
        "http://arkumu.org/data/properties/entstehung",
    )
    DIGITAL_OBJECT_MEDIA_TYPE_PROPERTY = "http://arkumu.org/data/properties/medientyp"
    DIGITAL_OBJECT_SIGNIFICANT_DE_PROPERTIES = (
        "http://arkumu.org/data/properties/wesentliche-eigenschaften-deutsch",
        "http://arkumu.org/data/properties/description-de-verkettet",
    )
    DIGITAL_OBJECT_SIGNIFICANT_EN_PROPERTIES = (
        "http://arkumu.org/data/properties/wesentliche-eigenschaften-englisch",
        "http://arkumu.org/data/properties/description-en-verkettet",
    )
    RESOURCE_LABEL_PREDICATES = (
        "http://arkumu.org/data/properties/deutscher-name",
        "http://arkumu.org/data/properties/name",
        "http://arkumu.org/data/properties/deutscher-name-der-medientyp",
    )
    ROSETTA_CHECKSUM_PREDICATES: Dict[str, str] = {
        'khm': 'http://arkumu.org/data/khm/properties/pruefsumme-sha256',
        'hmt': 'http://arkumu.org/data/hmt/properties/pruefsumme-sha256',
    }

    def __init__(self, relationship_org_code: Optional[str] = None) -> None:
        self.relationship_org_code = relationship_org_code
        self.cache = ProjectCacheService()
        self.schema_service = SchemaManifestService()
        self._graph_service_factory = CanonicalGraphService
        self._record_index: Dict[str, ProjectRecord] = {}
        self._record_index_version: Optional[str] = None
        self._digital_object_orgs: set[str] = {
            str(code).lower().strip()
            for code in getattr(settings, "OAI_DIGITAL_OBJECT_LINK_ORGS", ("fuk", "hmt", "det"))
            if code
        }

    def get_record_by_uri(self, uri: str) -> Optional[ProjectRecord]:
        """Return cached project record for a given project URI."""

        if not uri:
            return None

        snapshot = self.get_cross_institutional_snapshot()
        self._ensure_record_index(snapshot)
        return self._record_index.get(uri)

    def get_cross_institutional_snapshot(self, *, force_refresh: bool = False) -> ProjectSnapshot:
        """Return cached snapshot or rebuild if necessary."""
        if not force_refresh:
            cached = self.cache.get_cross_institutional_snapshot()
            if cached:
                logger.info("ProjectSnapshotService: cache hit for cross-institutional snapshot")
                self._ensure_record_index(cached)
                return cached

        logger.info("ProjectSnapshotService: cache miss – rebuilding cross-institutional snapshot")
        snapshot = self._build_snapshot()
        self.cache.set_cross_institutional_snapshot(snapshot)
        self._ensure_record_index(snapshot)
        return snapshot

    def refresh_cross_institutional_snapshot(self) -> ProjectSnapshot:
        """Force a snapshot rebuild and update cache."""
        snapshot = self._build_snapshot()
        self.cache.set_cross_institutional_snapshot(snapshot)
        self._ensure_record_index(snapshot)
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
        snapshot = ProjectSnapshot(
            projects=records,
            counts=counts,
            generated_at=timezone.now(),
        )
        self._ensure_record_index(snapshot)
        return snapshot

    def _ensure_record_index(self, snapshot: ProjectSnapshot) -> None:
        marker = snapshot.generated_at.isoformat()
        if self._record_index_version == marker and self._record_index:
            return
        self._record_index = {
            record.uri: record
            for record in snapshot.projects
            if record.uri
        }
        self._record_index_version = marker

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

        from arkumu.users.models import Organization

        available_codes = set(
            Organization.objects.filter(code__in=self.DEFAULT_ORGANIZATION_CODES)
            .values_list('code', flat=True)
        )
        missing_codes = [code for code in self.DEFAULT_ORGANIZATION_CODES if code not in available_codes]
        if missing_codes:
            logger.warning(
                "Organizations missing from database (skipped for snapshot): %s",
                missing_codes,
            )

        included_codes = [code for code in self.DEFAULT_ORGANIZATION_CODES if code in available_codes]
        if included_codes:
            logger.info("Organizations included in snapshot: %s", included_codes)

        for org_code in included_codes:
            try:
                org_graph = self._graph_service_factory(org_code=org_code).get_project_graph(
                    dataset_name="Projekt",
                    expand_neighbors=True,
                    type_canonical_uri=CardURIs.PROJECT_TYPE,
                )
            except ValueError as exc:  # Happens when schema is unavailable
                logger.warning(
                    "Skipping organization graph for '%s': %s",
                    org_code,
                    exc,
                )
                continue
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

        missing_orgs = set(self.DEFAULT_ORGANIZATION_CODES) - available_orgs
        if missing_orgs:
            logger.warning("Orgs without Mappings (excluded from snapshot): %s", sorted(missing_orgs))
        logger.info("Orgs with Mappings (included in snapshot): %s", sorted(available_orgs))

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

        storage_files_map: Dict[str, List[Any]] = defaultdict(list)
        try:  # pragma: no cover - storage optional during tests
            from arkumu.storage.models.s3_file_objects import S3FileObject

            node_ids = {str(node_id) for node_id in nodes.keys()}
            if node_ids:
                files_qs = (
                    S3FileObject.objects
                    .filter(related_resource_id__in=node_ids)
                    .order_by('created_at')
                )
                for file_obj in files_qs:
                    storage_files_map[str(file_obj.related_resource_id)].append(file_obj)
        except Exception:
            storage_files_map = defaultdict(list)

        triple_service = TripleRelationshipService(self.relationship_org_code)
        records: List[ProjectRecord] = []

        for subject_id in subjects:
            record = self._build_project_record(
                str(subject_id),
                nodes,
                edges_by_subject,
                card_schema,
                triple_service,
                storage_files_map,
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
        storage_files_map: Dict[str, Sequence[Any]],
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
            event_location_wikidata_predicate=ProjectURIs.EVENT_LOCATION_WIKIDATA,
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

        primary_institution_code: Optional[str] = None
        if institution and institution.code:
            primary_institution_code = institution.code.lower().strip()
        elif institution_codes:
            first_code = (institution_codes[0] or "") if institution_codes else ""
            primary_institution_code = first_code.lower().strip() or None

        code_candidates: set[str] = set(filter(None, institution_codes))
        if primary_institution_code:
            code_candidates.add(primary_institution_code)
        digital_only_org = self._is_digital_object_org(code_candidates)

        checksum_org_code = self._resolve_org_code_for_checksums(
            primary_institution_code,
            institution_codes,
            project_uri,
        )

        storage_files: List[Any] = list(storage_files_map.get(subject_id, []))
        digital_link_predicate = _fk_source_for_target('project', digital_object_path_prop.canonical_uri if digital_object_path_prop else None)

        digital_entries = []
        if digital_link_predicate:
            digital_entries = triple_service.get_related_entities(
                subject_id,
                digital_link_predicate,
                organization_code=self.relationship_org_code,
            )

        digital_object_ids: List[str] = []
        digital_entry_by_id: Dict[str, Dict[str, Any]] = {}
        for entry in digital_entries:
            object_id = entry.get('id')
            if not object_id or entry.get('resource_type') == ResourceType.LITERAL:
                continue
            digital_object_ids.append(object_id)
            digital_entry_by_id[object_id] = entry

        path_map: Dict[str, str] = {}
        if digital_object_ids and digital_object_path_prop:
            path_map = triple_service.get_literal_map(
                subject_ids=digital_object_ids,
                predicate_uri=digital_object_path_prop.canonical_uri,
                organization_code=self.relationship_org_code,
            )

        checksum_predicate = self._checksum_predicate_for_org(checksum_org_code)
        checksum_map: Dict[str, str] = {}
        if checksum_predicate and digital_object_ids:
            checksum_map.update(
                triple_service.get_literal_map(
                    subject_ids=digital_object_ids,
                    predicate_uri=checksum_predicate,
                    organization_code=self.relationship_org_code,
                )
            )

        digital_objects: List[ProjectDigitalObject] = []
        seen_paths: set[str] = set()
        linked_digital_ids: set[str] = set()
        for object_id in digital_object_ids:
            raw_path = path_map.get(object_id)
            if not raw_path:
                continue
            normalized_path = raw_path.strip()
            if not normalized_path or normalized_path in seen_paths:
                continue
            seen_paths.add(normalized_path)
            digital_entry = digital_entry_by_id.get(object_id, {})
            project_object = ProjectDigitalObject(
                path=normalized_path,
                uri=digital_entry.get('uri') or digital_entry.get('canonical_uri'),
            )
            self._populate_digital_object_metadata(
                project_object,
                object_id,
                nodes,
                edges_by_subject,
            )
            digital_objects.append(project_object)
            linked_digital_ids.add(str(object_id))

            checksum_value = (checksum_map.get(object_id) or "").strip()
            if checksum_value:
                fixity_info = parse_fixity(checksum_value)
                project_object.checksum = fixity_info.digest or checksum_value
                project_object.checksum_algorithm = fixity_info.algorithm or 'sha256'
                project_object.checksum_provenance = fixity_info.provenance or 'metadata'

        collected_ids: set[str] = set()
        collected_ids.update(
            self._related_ids(subject_edges, self.DIGITAL_OBJECT_LINK_URI)
        )
        for event_id in event_ids:
            event_edges = edges_by_subject.get(event_id, [])
            collected_ids.update(
                self._related_ids(event_edges, self.DIGITAL_OBJECT_LINK_URI)
            )

        for digital_id in collected_ids:
            digital_id_str = str(digital_id)
            if digital_id_str in linked_digital_ids:
                continue

            edges_for_digital = edges_by_subject.get(digital_id_str, [])
            path_literal = self._first_literal(
                edges_for_digital,
                digital_object_path_prop.canonical_uri if digital_object_path_prop else None,
            )
            if not path_literal:
                continue
            digital_node = nodes.get(digital_id_str, {})
            project_object = ProjectDigitalObject(
                path=path_literal,
                uri=digital_node.get('uri') or digital_node.get('canonical_uri'),
            )
            self._populate_digital_object_metadata(
                project_object,
                digital_id_str,
                nodes,
                edges_by_subject,
            )
            digital_objects.append(project_object)
            linked_digital_ids.add(digital_id_str)

            if checksum_predicate:
                checksum_map.update(
                    triple_service.get_literal_map(
                        subject_ids=[digital_id_str],
                        predicate_uri=checksum_predicate,
                        organization_code=self.relationship_org_code,
                    )
                )
                checksum_value = (checksum_map.get(digital_id_str) or "").strip()
                if checksum_value:
                    fixity_info = parse_fixity(checksum_value)
                    project_object.checksum = fixity_info.digest or checksum_value
                    project_object.checksum_algorithm = fixity_info.algorithm or 'sha256'
                    project_object.checksum_provenance = fixity_info.provenance or 'metadata'

        if not digital_only_org:
            for event_id in event_ids:
                storage_files.extend(storage_files_map.get(str(event_id), []))

        if linked_digital_ids and digital_only_org:
            for digital_id in linked_digital_ids:
                storage_files.extend(storage_files_map.get(str(digital_id), []))

        if storage_files:
            digital_objects = self._merge_storage_metadata(digital_objects, storage_files)

        rights_status = self._first_literal_from_predicates(
            subject_edges,
            (
                "http://arkumu.org/data/properties/rechtsstatus",
                "http://arkumu.org/data/fuk/properties/rechtsstatus",
                "http://arkumu.org/data/hmt/properties/rechtsstatus",
                "http://arkumu.org/data/khm/properties/rechtsstatus",
            ),
        )

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
            rights_status=rights_status,
        )
        return record

    def _merge_storage_metadata(
        self,
        digital_objects: List[ProjectDigitalObject],
        storage_files: Sequence[Any],
    ) -> List[ProjectDigitalObject]:
        if not storage_files:
            return digital_objects

        objects_by_path: Dict[str, ProjectDigitalObject] = {}
        for obj in digital_objects:
            keys = [obj.path, obj.storage_key, obj.access_url]
            for key in keys:
                if not key:
                    continue
                stripped = key.strip()
                objects_by_path.setdefault(stripped, obj)
                if stripped != key:
                    objects_by_path.setdefault(key, obj)

        for file_obj in storage_files:
            candidates = [
                getattr(file_obj, 's3_key', None),
                getattr(file_obj, 'original_path', None),
                getattr(file_obj, 'file_name', None),
            ]
            matched: Optional[ProjectDigitalObject] = None
            search_order = [candidate.strip() for candidate in candidates if candidate]
            search_order.extend(candidate for candidate in candidates if candidate)
            for candidate in search_order:
                if candidate and candidate in objects_by_path:
                    matched = objects_by_path[candidate]
                    break

            if not matched:
                derived_path = next(
                    (candidate for candidate in candidates if candidate),
                    None,
                ) or ""
                initial_path = derived_path.strip()
                matched = ProjectDigitalObject(path=initial_path)
                digital_objects.append(matched)
                key_for_cache = (matched.path or matched.storage_key or matched.access_url or "").strip()
                if key_for_cache:
                    objects_by_path.setdefault(key_for_cache, matched)

            raw_s3_key = getattr(file_obj, 's3_key', None)
            if raw_s3_key:
                matched.storage_key = raw_s3_key
                if not matched.path:
                    matched.path = raw_s3_key
                objects_by_path.setdefault(raw_s3_key.strip(), matched)
                if raw_s3_key.strip() != raw_s3_key:
                    objects_by_path.setdefault(raw_s3_key, matched)
            matched.file_name = getattr(file_obj, 'file_name', None) or matched.file_name
            matched.content_type = getattr(file_obj, 'content_type', None) or matched.content_type
            matched.size_bytes = getattr(file_obj, 'file_size_bytes', None) or matched.size_bytes

            raw_checksum = getattr(file_obj, 'sha256_checksum', None)
            fixity = parse_fixity(raw_checksum)
            if fixity.digest:
                matched.checksum = fixity.digest
            if fixity.algorithm:
                matched.checksum_algorithm = fixity.algorithm
            elif matched.checksum and not matched.checksum_algorithm:
                inferred = parse_fixity(matched.checksum)
                if inferred.algorithm:
                    matched.checksum_algorithm = inferred.algorithm
            if fixity.digest and not matched.checksum_provenance:
                matched.checksum_provenance = 's3'

            matched.access_url = getattr(file_obj, 's3_url', None) or matched.access_url
            matched.storage_status = getattr(file_obj, 'status', None) or matched.storage_status

            created_at = getattr(file_obj, 'created_at', None)
            if created_at and not matched.created_at:
                matched.created_at = created_at.isoformat()

            updated_at = getattr(file_obj, 'updated_at', None)
            if updated_at:
                matched.updated_at = updated_at.isoformat()

        return digital_objects

    def _is_digital_object_org(self, codes: Iterable[str]) -> bool:
        if not self._digital_object_orgs or not codes:
            return False
        for code in codes:
            normalized = (code or "").lower().strip()
            if normalized in self._digital_object_orgs:
                return True
        return False

    def _checksum_predicate_for_org(self, institution_code: Optional[str]) -> Optional[str]:
        if not institution_code:
            scoped = self.relationship_org_code.lower() if self.relationship_org_code else None
            return self.ROSETTA_CHECKSUM_PREDICATES.get(scoped) if scoped else None
        return self.ROSETTA_CHECKSUM_PREDICATES.get(institution_code.lower())

    def _resolve_org_code_for_checksums(
        self,
        primary_code: Optional[str],
        institution_codes: Sequence[str],
        project_uri: Optional[str],
    ) -> Optional[str]:
        """Return best-guess organization code for checksum lookups."""

        candidates: List[str] = []

        def _push(value: Optional[str]) -> None:
            if not value:
                return
            normalized = value.strip().lower()
            if normalized:
                candidates.append(normalized)

        _push(primary_code)
        for code in institution_codes:
            _push(code)

        _push(self._extract_org_code_from_uri(project_uri))
        _push(self.relationship_org_code)

        for code in candidates:
            if code in self.ROSETTA_CHECKSUM_PREDICATES:
                return code

        return candidates[0] if candidates else None

    @staticmethod
    def _extract_org_code_from_uri(project_uri: Optional[str]) -> Optional[str]:
        if not project_uri:
            return None

        parsed = urlparse(project_uri)
        segments = [segment for segment in parsed.path.split('/') if segment]
        if not segments:
            return None

        if segments[0] == 'data' and len(segments) > 1:
            return segments[1].lower()

        return segments[0].lower()

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

    def _first_literal_from_predicates(
        self,
        edges: Iterable[Dict[str, Any]],
        predicates: Iterable[Optional[str]],
    ) -> Optional[str]:
        for predicate in predicates:
            value = self._first_literal(edges, predicate)
            if value:
                return value
        return None

    def _first_literal_from_db(
        self,
        resource_id: Optional[str],
        predicates: Iterable[str],
    ) -> Optional[str]:
        if not resource_id:
            return None
        predicate_list = [p for p in predicates if p]
        if not predicate_list:
            return None
        q = Triple.objects.filter(
            subject_id=resource_id,
            object__resource_type=ResourceType.LITERAL,
        ).order_by('id')
        q = q.filter(Q(predicate__uri__in=predicate_list) | Q(predicate__canonical_uri__in=predicate_list))
        value = q.values_list('object__value', flat=True).first()
        return value

    def _related_ids(self, edges: Iterable[Dict[str, Any]], predicate: Optional[str]) -> List[str]:
        if not predicate:
            return []
        ids: List[str] = []
        for edge in edges:
            if self._canonical(edge) == predicate and edge.get('object_id'):
                ids.append(str(edge['object_id']))
        return ids

    def _first_literal_any(
        self,
        edges: Iterable[Dict[str, Any]],
        predicates: Sequence[str],
    ) -> Optional[str]:
        for predicate in predicates:
            value = self._first_literal(edges, predicate)
            if value:
                normalized = self._normalize_text_value(value)
                if normalized:
                    return normalized
        return None

    @staticmethod
    def _normalize_text_value(value: Optional[Any]) -> Optional[str]:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

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
        qid = ProjectSnapshotService._normalize_wikidata_id(wikidata_literal)
        if qid:
            return qid

        qid = ProjectSnapshotService._first_qid_from_literal(synonyms_literal)
        if qid:
            return qid

        qid = ProjectSnapshotService._first_qid_from_literal(breadcrumb_literal)
        if qid:
            return qid

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
    def _first_qid_from_literal(value: Optional[Any]) -> Optional[str]:
        if value is None:
            return None
        text = str(value).replace(';', ',')
        for token in text.split(','):
            normalized = ProjectSnapshotService._normalize_wikidata_id(token)
            if normalized:
                return normalized
        return None

    @staticmethod
    def _preferred_synonym(value: Optional[Any]) -> Optional[str]:
        if value is None:
            return None
        tokens = [token.strip() for token in str(value).replace(';', ',').split(',') if token.strip()]
        if not tokens:
            return None
        return tokens[0]

    def _populate_digital_object_metadata(
        self,
        project_object: ProjectDigitalObject,
        object_id: str,
        nodes: Dict[str, Dict[str, Any]],
        edges_by_subject: Dict[str, List[Dict[str, Any]]],
    ) -> None:
        edges_for_digital = edges_by_subject.get(str(object_id), [])
        if not edges_for_digital:
            return

        uuid_value = self._normalize_text_value(
            self._first_literal(edges_for_digital, self.DIGITAL_OBJECT_UUID_PROPERTY)
        )
        if uuid_value:
            project_object.uuid = uuid_value

        genesis_value = self._first_literal_any(
            edges_for_digital,
            self.DIGITAL_OBJECT_GENESIS_PROPERTIES,
        )
        if genesis_value:
            project_object.genesis_type = genesis_value

        media_value = self._resolve_media_type(
            edges_for_digital,
            nodes,
            edges_by_subject,
        )
        if media_value:
            project_object.media_type = media_value

        significant_de = self._first_literal_any(
            edges_for_digital,
            self.DIGITAL_OBJECT_SIGNIFICANT_DE_PROPERTIES,
        )
        if significant_de:
            project_object.significant_properties_de = significant_de

        significant_en = self._first_literal_any(
            edges_for_digital,
            self.DIGITAL_OBJECT_SIGNIFICANT_EN_PROPERTIES,
        )
        if significant_en:
            project_object.significant_properties_en = significant_en

        license_info = self._build_digital_object_license(
            edges_for_digital,
            nodes,
            edges_by_subject,
        )
        if license_info:
            project_object.license = license_info

    def _resolve_media_type(
        self,
        edges_for_digital: Iterable[Dict[str, Any]],
        nodes: Dict[str, Dict[str, Any]],
        edges_by_subject: Dict[str, List[Dict[str, Any]]],
    ) -> Optional[str]:
        literal_value = self._normalize_text_value(
            self._first_literal(edges_for_digital, self.DIGITAL_OBJECT_MEDIA_TYPE_PROPERTY)
        )
        if literal_value:
            return literal_value

        media_ids = self._related_ids(edges_for_digital, self.DIGITAL_OBJECT_MEDIA_TYPE_PROPERTY)
        for media_id in media_ids:
            media_node = nodes.get(str(media_id), {})
            candidate = self._normalize_text_value(media_node.get('name') or media_node.get('value'))
            if candidate:
                return candidate
            media_edges = edges_by_subject.get(str(media_id), [])
            label = self._first_literal_any(media_edges, self.RESOURCE_LABEL_PREDICATES)
            if label:
                return label
        return None

    def _build_digital_object_license(
        self,
        edges_for_digital: Iterable[Dict[str, Any]],
        nodes: Dict[str, Dict[str, Any]],
        edges_by_subject: Dict[str, List[Dict[str, Any]]],
    ) -> Optional[ProjectDigitalObjectLicense]:
        license_ids = self._related_ids(edges_for_digital, self.DIGITAL_OBJECT_LICENSE_LINK_URI)
        if not license_ids:
            return None

        license_id = license_ids[0]
        resource_id = str(license_id)
        license_edges = edges_by_subject.get(resource_id, [])
        license_node = nodes.get(resource_id, {})

        uri = self._first_literal_any(license_edges, self.DIGITAL_OBJECT_LICENSE_URI_FALLBACKS)
        if not uri:
            uri = self._normalize_text_value(
                self._first_literal_from_db(resource_id, self.DIGITAL_OBJECT_LICENSE_URI_FALLBACKS)
            )
        if not uri:
            uri = self._normalize_text_value(license_node.get('uri') or license_node.get('value'))

        label_de = self._first_literal_any(license_edges, self.DIGITAL_OBJECT_LICENSE_LABEL_DE_FALLBACKS)
        if not label_de:
            label_de = self._normalize_text_value(
                self._first_literal_from_db(resource_id, self.DIGITAL_OBJECT_LICENSE_LABEL_DE_FALLBACKS)
            )

        label_en = self._first_literal_any(license_edges, self.DIGITAL_OBJECT_LICENSE_LABEL_EN_FALLBACKS)
        if not label_en:
            label_en = self._normalize_text_value(
                self._first_literal_from_db(resource_id, self.DIGITAL_OBJECT_LICENSE_LABEL_EN_FALLBACKS)
            )

        rights_statement = self._first_literal_any(license_edges, self.DIGITAL_OBJECT_LICENSE_RIGHTS_STATEMENT_FALLBACKS)
        if not rights_statement:
            rights_statement = self._normalize_text_value(
                self._first_literal_from_db(resource_id, self.DIGITAL_OBJECT_LICENSE_RIGHTS_STATEMENT_FALLBACKS)
            )

        if not any([uri, label_de, label_en, rights_statement]):
            return None

        return ProjectDigitalObjectLicense(
            uri=uri,
            label_de=label_de,
            label_en=label_en,
            rights_statement=rights_statement,
        )

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
