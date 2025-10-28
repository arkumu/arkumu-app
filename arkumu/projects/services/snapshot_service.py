"""Build and cache reusable project snapshots."""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple
from urllib.parse import urlparse
import uuid

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
from arkumu.metadata.models.resource import Resource, ResourceType, PublicAccessLevel
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
from arkumu.projects.services.dump_fixity_index import find_fixity, FixityRecord
from arkumu.common.arkumu_license import (
    ARKUMU_LICENSE_LABELS,
    ARKUMU_LICENSE_TEXTS,
    ARKUMU_LICENSE_URIS,
    license_token_from_license_info,
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
        "hmt",
    )
    DIGITAL_OBJECT_LINK_URI = "http://arkumu.org/data/properties/digitales-objekt"
    DIGITAL_OBJECT_LICENSE_LINK_URI = "http://arkumu.org/data/properties/lizenzstatus"
    DIGITAL_OBJECT_LICENSE_URI_PROPERTIES: Tuple[str, ...] = (
        "http://arkumu.org/data/properties/uri",
    )
    DIGITAL_OBJECT_LICENSE_LABEL_DE_PROPERTIES: Tuple[str, ...] = (
        "http://arkumu.org/data/properties/deutscher-anzeigetext",
        "http://arkumu.org/data/properties/deutscher-name-der-lizenz",
    )
    DIGITAL_OBJECT_LICENSE_LABEL_EN_PROPERTIES: Tuple[str, ...] = (
        "http://arkumu.org/data/properties/englischer-anzeigetext",
        "http://arkumu.org/data/properties/englischer-name-der-lizenz",
    )
    DIGITAL_OBJECT_LICENSE_RIGHTS_STATEMENT_PROPERTIES: Tuple[str, ...] = (
        "http://arkumu.org/data/properties/zugehoeriges-rechtestatement",
    )
    DIGITAL_OBJECT_LICENSE_IDENTIFIER_PROPERTIES: Tuple[str, ...] = (
        "http://arkumu.org/data/properties/digitales-objekt-lizenz-id",
    )
    DIGITAL_OBJECT_FALLBACK_PREDICATES: Dict[str, Tuple[str, ...]] = {
        'fuk': (
            "http://arkumu.org/data/fuk/properties/vorschaubild",
        ),
        'hmt': (),
        'det': (),
    }
    RIGHTS_STATEMENT_FALLBACK_PREDICATES: Tuple[str, ...] = (
        "http://purl.org/dc/terms/title",
        "http://purl.org/dc/elements/1.1/title",
        "http://purl.org/dc/terms/description",
        "http://purl.org/dc/elements/1.1/description",
        "http://www.w3.org/2000/01/rdf-schema#label",
    )
    NUMERIC_LICENSE_ORGS: Tuple[str, ...] = ("fuk", "rsh", "det")
    EVENT_NAME_DE_PROPERTIES: Tuple[str, ...] = (
        "http://arkumu.org/data/properties/ereignisname",
    )
    EVENT_NAME_EN_PROPERTIES: Tuple[str, ...] = (
        "http://arkumu.org/data/properties/englischer-name",
    )
    EVENT_TYPE_LABEL_DE_PROPERTIES: Tuple[str, ...] = (
        "http://arkumu.org/data/properties/deutscher-name-des-ereignistyps",
        "http://arkumu.org/data/properties/deutscher-name",
    )
    EVENT_TYPE_LABEL_EN_PROPERTIES: Tuple[str, ...] = (
        "http://arkumu.org/data/properties/englischer-name-des-ereignistyps",
        "http://arkumu.org/data/properties/englischer-name",
    )
    EVENT_TYPE_SYNONYM_PROPERTIES: Tuple[str, ...] = (
        "http://arkumu.org/data/properties/synonyme",
    )
    EVENT_TYPE_WIKIDATA_PROPERTIES: Tuple[str, ...] = (
        "http://arkumu.org/data/properties/wikidata-id",
    )
    EVENT_TYPE_GND_PROPERTIES: Tuple[str, ...] = (
        "http://arkumu.org/data/properties/gnd-nummer",
    )
    EVENT_TYPE_AAT_PROPERTIES: Tuple[str, ...] = (
        "http://arkumu.org/data/properties/aat-id",
    )
    EVENT_TYPE_LIDO_PROPERTIES: Tuple[str, ...] = (
        "http://arkumu.org/data/properties/lido-terminologie-id",
    )
    EVENT_START_ESTIMATED_PROPERTIES: Tuple[str, ...] = (
        "http://arkumu.org/data/properties/ereignisbeginn-geschaetzt",
    )
    EVENT_END_ESTIMATED_PROPERTIES: Tuple[str, ...] = (
        "http://arkumu.org/data/properties/ereignisende-geschaetzt",
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
    EVENT_PROJECT_LINK_URI = "http://arkumu.org/data/properties/projekt"
    OWNERSHIP_FILTER_ORGS: Tuple[str, ...] = ("khm", "hmt")

    def __init__(self, relationship_org_code: Optional[str] = None) -> None:
        self.relationship_org_code = relationship_org_code
        self.cache = ProjectCacheService()
        self.schema_service = SchemaManifestService()
        self._graph_service_factory = CanonicalGraphService
        raw_org_codes = getattr(
            settings,
            "PROJECT_SNAPSHOT_ORG_CODES",
            self.DEFAULT_ORGANIZATION_CODES,
        )
        if raw_org_codes is None:
            self.organization_codes = self.DEFAULT_ORGANIZATION_CODES
        else:
            if isinstance(raw_org_codes, str):
                raw_org_codes = [raw_org_codes]
            self.organization_codes = tuple(raw_org_codes)
            if not self.organization_codes:
                self.organization_codes = self.DEFAULT_ORGANIZATION_CODES
        self._force_org_graphs = getattr(
            settings,
            "PROJECT_SNAPSHOT_FORCE_ORG_GRAPHS",
            False,
        )
        self._record_index: Dict[str, ProjectRecord] = {}
        self._record_index_version: Optional[str] = None
        self._digital_object_orgs: set[str] = {
            str(code).lower().strip()
            for code in getattr(settings, "OAI_DIGITAL_OBJECT_LINK_ORGS", ("fuk", "det", "rsh"))
            if code
        }

    def get_record_by_uri(self, uri: str) -> Optional[ProjectRecord]:
        """Return cached project record for a given project URI."""

        if not uri:
            return None

        snapshot = self.get_cross_institutional_snapshot()
        self._ensure_record_index(snapshot)
        return self._record_index.get(uri)

    def get_cross_institutional_snapshot(
        self,
        *,
        force_refresh: bool = False,
        include_non_public: bool = False,
    ) -> ProjectSnapshot:
        """Return cached snapshot or rebuild if necessary."""

        if include_non_public:
            logger.info(
                "ProjectSnapshotService: building snapshot including non-public projects (force_refresh=%s)",
                force_refresh,
            )
            snapshot = self._build_snapshot(include_non_public=True)
            self._ensure_record_index(snapshot)
            return snapshot

        if not force_refresh:
            cached = self.cache.get_cross_institutional_snapshot()
            if cached:
                logger.info("ProjectSnapshotService: cache hit for cross-institutional snapshot")
                self._ensure_record_index(cached)
                return cached

        logger.info("ProjectSnapshotService: cache miss – rebuilding cross-institutional snapshot")
        snapshot = self._build_snapshot(include_non_public=False)
        self.cache.set_cross_institutional_snapshot(snapshot)
        self._ensure_record_index(snapshot)
        return snapshot

    def refresh_cross_institutional_snapshot(self) -> ProjectSnapshot:
        """Force a snapshot rebuild and update cache."""
        snapshot = self._build_snapshot(include_non_public=False)
        self.cache.set_cross_institutional_snapshot(snapshot)
        self._ensure_record_index(snapshot)
        return snapshot

    def _build_snapshot(self, *, include_non_public: bool) -> ProjectSnapshot:
        graph = self._fetch_cross_institutional_graph()
        self._enhance_license_literals(graph)
        card_schema = self._get_card_schema()
        records = self._graph_to_records(graph, card_schema)
        if not include_non_public:
            records = self._filter_public_projects(records)
        return self._finalize_snapshot(graph, records)

    def _filter_public_projects(
        self,
        records: List[ProjectRecord],
    ) -> List[ProjectRecord]:
        """Return only projects whose root resource is approved for public display."""

        if not records:
            return records

        subject_ids: List[str] = [
            str(record.subject_id)
            for record in records
            if getattr(record, "subject_id", None)
        ]
        if not subject_ids:
            return records

        approved_ids: Set[str] = {
            str(resource_id)
            for resource_id in Resource.objects.filter(
                id__in=subject_ids,
                public_access_level=PublicAccessLevel.PUBLIC,
                is_public_approved=True,
            ).values_list('id', flat=True)
        }

        if not approved_ids:
            logger.info(
                "ProjectSnapshotService: no public projects found; returning empty set from %d candidates",
                len(records),
            )
            return []

        filtered: List[ProjectRecord] = [
            record
            for record in records
            if str(record.subject_id) in approved_ids
        ]

        dropped = len(records) - len(filtered)
        if dropped:
            logger.info(
                "ProjectSnapshotService: filtered out %d non-public projects (remaining=%d)",
                dropped,
                len(filtered),
            )

        return filtered

    def _finalize_snapshot(
        self,
        graph: Dict[str, Any],
        records: List[ProjectRecord],
    ) -> ProjectSnapshot:
        counts = dict(graph.get('counts', {}) or {})
        counts['projects'] = len(records)
        if 'subjects' not in counts:
            counts['subjects'] = len(graph.get('subjects', []))
        if 'edges' not in counts:
            counts['edges'] = len(graph.get('edges', []))
        snapshot = ProjectSnapshot(
            projects=records,
            counts=counts,
            generated_at=timezone.now(),
        )
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
        if not self._force_org_graphs and self.organization_codes == self.DEFAULT_ORGANIZATION_CODES:
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

    def _enhance_license_literals(self, graph: Dict[str, Any]) -> None:
        if not graph:
            return

        edges: List[Dict[str, Any]] = graph.get('edges', [])
        nodes: Dict[str, Dict[str, Any]] = graph.get('nodes', {})

        if not edges or not nodes:
            return

        license_ids: set[str] = {
            str(edge.get('object_id'))
            for edge in edges
            if edge.get('predicate_canonical') == self.DIGITAL_OBJECT_LICENSE_LINK_URI and edge.get('object_id')
        }
        if not license_ids:
            return

        predicate_whitelist: List[str] = [
            uri
            for uri in (
                *self.DIGITAL_OBJECT_LICENSE_URI_PROPERTIES,
                *self.DIGITAL_OBJECT_LICENSE_LABEL_DE_PROPERTIES,
                *self.DIGITAL_OBJECT_LICENSE_LABEL_EN_PROPERTIES,
                *self.DIGITAL_OBJECT_LICENSE_RIGHTS_STATEMENT_PROPERTIES,
                *self.DIGITAL_OBJECT_LICENSE_IDENTIFIER_PROPERTIES,
            )
            if uri
        ]
        if not predicate_whitelist:
            return

        triples_qs = (
            Triple.objects.filter(
                subject_id__in=list(license_ids),
                object__resource_type=ResourceType.LITERAL,
            )
            .filter(
                Q(predicate__canonical_uri__in=predicate_whitelist)
                | Q(predicate__uri__in=predicate_whitelist)
            )
            .select_related('predicate', 'object', 'object__organization')
        )

        triples = list(triples_qs)
        if not triples:
            return

        existing_triple_ids: set[str] = {
            str(edge.get('triple_id'))
            for edge in edges
            if edge.get('triple_id')
        }

        added = False
        for triple in triples:
            triple_id = str(triple.id)
            if triple_id in existing_triple_ids:
                continue

            predicate = triple.predicate
            obj = triple.object

            edge_payload = {
                'triple_id': triple_id,
                'subject_id': str(triple.subject_id),
                'predicate_uri': getattr(predicate, 'uri', None),
                'predicate_canonical': getattr(predicate, 'canonical_uri', None),
                'object_id': str(obj.id),
                'object_uri': getattr(obj, 'uri', None),
                'object_type': obj.resource_type,
                'object_value': getattr(obj, 'value', None),
                'object_canonical': getattr(obj, 'canonical_uri', None),
            }
            edges.append(edge_payload)
            existing_triple_ids.add(triple_id)
            added = True

            literal_node_id = str(obj.id)
            if literal_node_id not in nodes:
                nodes[literal_node_id] = {
                    'id': literal_node_id,
                    'uri': getattr(obj, 'uri', None),
                    'name': getattr(obj, 'name', None),
                    'value': getattr(obj, 'value', None),
                    'resource_type': obj.resource_type,
                    'canonical_uri': getattr(obj, 'canonical_uri', None),
                    'organization': getattr(getattr(obj, 'organization', None), 'code', None),
                }

        if added:
            counts = graph.get('counts')
            if counts is not None:
                counts['edges'] = len(edges)
                counts['nodes'] = len(nodes)

    def _build_combined_organization_graphs(self) -> Dict[str, Any]:
        subjects: List[str] = []
        nodes: Dict[str, Dict[str, Any]] = {}
        edges: List[Dict[str, Any]] = []
        edge_signatures: set[tuple] = set()

        from arkumu.users.models import Organization

        available_codes = set(
            Organization.objects.filter(code__in=self.organization_codes)
            .values_list('code', flat=True)
        )
        missing_codes = [code for code in self.organization_codes if code not in available_codes]
        if missing_codes:
            logger.warning(
                "Organizations missing from database (skipped for snapshot): %s",
                missing_codes,
            )

        included_codes = [code for code in self.organization_codes if code in available_codes]
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
            .filter(organization_id__in=self.organization_codes)
            .values_list('organization_id', flat=True)
        )

        missing_orgs = set(self.organization_codes) - available_orgs
        if missing_orgs:
            logger.warning("Orgs without Mappings (excluded from snapshot): %s", sorted(missing_orgs))
        logger.info("Orgs with Mappings (included in snapshot): %s", sorted(available_orgs))

        schemas = [
            self.schema_service.get_card_schema(code)
            for code in self.organization_codes
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
            event_id_raw = entry.get('id')
            event_id = str(event_id_raw) if event_id_raw is not None else None
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
        for event in events:
            self._populate_event_metadata(event, nodes, edges_by_subject)
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
            rights_by_event = payload.get('event_rights', {})
            for event_id in payload.get('event_ids', []):
                rights_flags = rights_by_event.get(event_id, {})
                actors_by_event[event_id].append(
                    ProjectEventActor(
                        name=name,
                        roles=list(roles),
                        is_copyright_holder=rights_flags.get('is_copyright_holder', False),
                        is_neighbouring_rights_holder=rights_flags.get('is_neighbouring_rights_holder', False),
                    )
                )

        for event in events:
            if event.id:
                event.actors = list(actors_by_event.get(event.id, []))

        events_all: List[ProjectEvent] = list(events)
        all_event_ids: List[str] = [event_id for event_id in event_ids if event_id]
        event_owner_map = self._collect_event_owner_map(all_event_ids, nodes)
        for event in events_all:
            key = str(event.id) if event.id is not None else None
            owners = event_owner_map.get(key, [])
            event.owning_project_uris = list(owners) if owners else []

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

        ownership_filtered = False
        reference_events: List[ProjectEvent] = []
        filtered_event_ids_set: Set[str] = set()
        reference_project_uris: Set[str] = set()

        should_filter = self._should_filter_ownership(code_candidates, project_uri)

        if should_filter and events:
            current_project_uri = project_uri
            filtered_events: List[ProjectEvent] = []
            for event in events:
                key = str(event.id) if event.id is not None else None
                raw_owners = event_owner_map.get(key, []) if key is not None else []
                owner_set: Set[str] = {
                    str(owner_uri).strip()
                    for owner_uri in raw_owners
                    if owner_uri and str(owner_uri).strip()
                }
                if owner_set:
                    event.owning_project_uris = sorted(owner_set)
                elif not event.owning_project_uris:
                    event.owning_project_uris = []

                has_current_owner = bool(
                    current_project_uri and current_project_uri in owner_set
                )
                has_foreign_owner = any(
                    owner_uri != current_project_uri for owner_uri in owner_set
                )
                is_grundereignis = self._is_grundereignis_event(event)

                should_reference_event = False
                if owner_set:
                    if not has_current_owner:
                        should_reference_event = True
                    elif has_foreign_owner and not is_grundereignis:
                        should_reference_event = True

                if should_reference_event:
                    ownership_filtered = True
                    event.is_reference_only = True
                    if key:
                        filtered_event_ids_set.add(key)
                    for owner_uri in owner_set:
                        if owner_uri and owner_uri != current_project_uri:
                            reference_project_uris.add(owner_uri)
                    reference_events.append(event)
                    continue
                filtered_events.append(event)
            events = filtered_events
            event_ids = [event_id for event_id in (event.id for event in events) if event_id]
        else:
            for event in events:
                key = str(event.id) if event.id is not None else None
                if key is None:
                    continue
                owners = {
                    str(owner_uri).strip()
                    for owner_uri in event_owner_map.get(key, [])
                    if owner_uri and str(owner_uri).strip()
                }
                if owners:
                    event.owning_project_uris = sorted(owners)

        year_range = self._derive_year_range(events)

        event_sources_map: Dict[str, List[str]] = {}
        for event in events_all:
            key = str(event.id) if event.id is not None else None
            if not key:
                continue
            event_sources_map[key] = list(event.owning_project_uris)

        if reference_events:
            reference_events = list(reference_events)

        digital_only_org = self._is_digital_object_org(code_candidates)

        event_lookup: Dict[str, ProjectEvent] = {}
        for event in events_all:
            if event.id is None:
                continue
            event_lookup[str(event.id)] = event

        digital_origin_map: Dict[str, Dict[str, Any]] = defaultdict(lambda: {"via_project": False, "event_ids": set()})
        project_edge_ids: Set[str] = set(self._related_ids(subject_edges, self.DIGITAL_OBJECT_LINK_URI))
        for digital_id in project_edge_ids:
            record = digital_origin_map[str(digital_id)]
            record["via_project"] = True

        event_edge_map: Dict[str, Set[str]] = {}
        for event_id in all_event_ids:
            event_edges = edges_by_subject.get(event_id, [])
            related_ids = self._related_ids(event_edges, self.DIGITAL_OBJECT_LINK_URI)
            if not related_ids:
                continue
            normalized_ids: Set[str] = {
                str(rel_id) for rel_id in related_ids if rel_id is not None
            }
            if not normalized_ids:
                continue
            event_edge_map[event_id] = normalized_ids
            for digital_id in normalized_ids:
                record = digital_origin_map[digital_id]
                record.setdefault("event_ids", set()).add(event_id)

        filtered_digital_only_ids: Set[str] = set()
        if filtered_event_ids_set:
            candidate_ids: Set[str] = set()
            for filtered_event_id in filtered_event_ids_set:
                candidate_ids.update(event_edge_map.get(filtered_event_id, set()))
            kept_event_id_set: Set[str] = set(event_ids)
            filtered_digital_only_ids = {
                digital_id
                for digital_id in candidate_ids
                if digital_id not in project_edge_ids
                and not any(
                    digital_id in event_edge_map.get(kept_event_id, set())
                    for kept_event_id in kept_event_id_set
                )
            }

        digital_object_sources: Dict[str, Dict[str, Any]] = {}

        checksum_org_code = self._resolve_org_code_for_checksums(
            primary_institution_code,
            institution_codes,
            project_uri,
        )

        storage_files: List[Any] = list(storage_files_map.get(subject_id, []))
        digital_link_predicate = _fk_source_for_target('project', digital_object_path_prop.canonical_uri if digital_object_path_prop else None)

        digital_entries: List[Dict[str, Any]] = []
        if digital_link_predicate:
            project_level_entries = triple_service.get_related_entities(
                subject_id,
                digital_link_predicate,
                organization_code=self.relationship_org_code,
            )
            for entry in project_level_entries:
                object_id_raw = entry.get('id')
                if object_id_raw:
                    key = str(object_id_raw)
                    digital_origin_map[key]["via_project"] = True
                digital_entries.append(entry)

        if digital_only_org and event_ids:
            for event_id in event_ids:
                event_objects = triple_service.get_related_entities(
                    event_id,
                    self.DIGITAL_OBJECT_LINK_URI,
                    organization_code=self.relationship_org_code,
                )
                if not event_objects:
                    continue
                event_key = str(event_id)
                for entry in event_objects:
                    object_id_raw = entry.get('id')
                    if object_id_raw:
                        key = str(object_id_raw)
                        digital_origin_map[key]["event_ids"].add(event_key)
                digital_entries.extend(event_objects)

        if not digital_entries and code_candidates:
            fallback_predicates = self._fallback_digital_predicates_for_org(code_candidates)
            for predicate_uri in fallback_predicates:
                literal_map = triple_service.get_literal_map(
                    subject_ids=[subject_id],
                    predicate_uri=predicate_uri,
                    organization_code=self.relationship_org_code,
                )
                if not literal_map:
                    continue
                candidate_ids = {
                    literal.strip()
                    for literal in literal_map.values()
                    if literal and literal.strip()
                }
                if not candidate_ids:
                    continue

                query = Q()
                for candidate_id in candidate_ids:
                    query |= Q(uri__iendswith=f"/{candidate_id}") | Q(value__iexact=candidate_id)

                if not query:
                    continue

                for resource in Resource.objects.filter(query):
                    resource_id = str(resource.id)
                    digital_origin_map[resource_id]["via_project"] = True
                    digital_entries.append(
                        {
                            'id': resource_id,
                            'uri': resource.uri,
                            'canonical_uri': resource.canonical_uri,
                            'name': resource.name,
                            'value': resource.value,
                            'resource_type': resource.resource_type,
                        }
                    )

        digital_object_ids: List[str] = []
        digital_entry_by_id: Dict[str, Dict[str, Any]] = {}
        for entry in digital_entries:
            object_id_raw = entry.get('id')
            if object_id_raw is None or entry.get('resource_type') == ResourceType.LITERAL:
                continue
            object_id = str(object_id_raw)
            if object_id in digital_entry_by_id:
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
            project_object.resource_id = object_id
            origin_record = digital_origin_map.get(object_id, {"via_project": False, "event_ids": set()})
            event_ids_for_obj = sorted({str(eid) for eid in origin_record.get("event_ids", set()) if eid})
            event_uris_for_obj = [
                event_lookup[event_id].uri
                for event_id in event_ids_for_obj
                if event_id in event_lookup and event_lookup[event_id].uri
            ]
            project_object.source_event_ids = event_ids_for_obj
            project_object.source_event_uris = event_uris_for_obj
            via_project = bool(origin_record.get("via_project"))
            if via_project and event_ids_for_obj:
                source_label = "project+event"
            elif via_project:
                source_label = "project"
            elif event_ids_for_obj:
                source_label = "event"
            else:
                source_label = None
            project_object.source = source_label
            digital_object_sources[object_id] = {
                "source": source_label or "unknown",
                "via_project": via_project,
                "event_ids": list(event_ids_for_obj),
                "event_uris": list(event_uris_for_obj),
            }
            self._populate_digital_object_metadata(
                project_object,
                object_id,
                nodes,
                edges_by_subject,
                code_candidates,
            )
            digital_objects.append(project_object)
            linked_digital_ids.add(object_id)

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
            project_object.resource_id = digital_id_str
            origin_record = digital_origin_map.get(digital_id_str, {"via_project": False, "event_ids": set()})
            event_ids_for_obj = sorted({str(eid) for eid in origin_record.get("event_ids", set()) if eid})
            event_uris_for_obj = [
                event_lookup[event_id].uri
                for event_id in event_ids_for_obj
                if event_id in event_lookup and event_lookup[event_id].uri
            ]
            project_object.source_event_ids = event_ids_for_obj
            project_object.source_event_uris = event_uris_for_obj
            via_project = bool(origin_record.get("via_project"))
            if via_project and event_ids_for_obj:
                source_label = "project+event"
            elif via_project:
                source_label = "project"
            elif event_ids_for_obj:
                source_label = "event"
            else:
                source_label = None
            project_object.source = source_label
            digital_object_sources.setdefault(
                digital_id_str,
                {
                    "source": source_label or "unknown",
                    "via_project": via_project,
                    "event_ids": list(event_ids_for_obj),
                    "event_uris": list(event_uris_for_obj),
                },
            )
            self._populate_digital_object_metadata(
                project_object,
                digital_id_str,
                nodes,
                edges_by_subject,
                code_candidates,
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

        if ownership_filtered and digital_objects:
            retained_objects: List[ProjectDigitalObject] = []
            for obj in digital_objects:
                resource_id = getattr(obj, "resource_id", None)
                if not resource_id:
                    retained_objects.append(obj)
                    continue
                origin_record = digital_origin_map.get(resource_id, {"via_project": False, "event_ids": set()})
                via_project = bool(origin_record.get("via_project"))
                event_ids_for_obj = {
                    str(eid) for eid in origin_record.get("event_ids", set()) if eid
                }
                if should_filter and not via_project and event_ids_for_obj and event_ids_for_obj.issubset(filtered_event_ids_set):
                    filtered_digital_only_ids.add(resource_id)
                    metadata = digital_object_sources.get(resource_id)
                    if metadata is not None:
                        metadata["filtered"] = True
                    continue
                retained_objects.append(obj)
            if len(retained_objects) != len(digital_objects):
                digital_objects = retained_objects
                linked_digital_ids = {
                    obj.resource_id for obj in digital_objects if getattr(obj, "resource_id", None)
                }

        if not digital_only_org:
            for event_id in event_ids:
                storage_files.extend(storage_files_map.get(str(event_id), []))

        if linked_digital_ids and digital_only_org:
            for digital_id in linked_digital_ids:
                storage_files.extend(storage_files_map.get(str(digital_id), []))

        if storage_files and not digital_only_org:
            digital_objects = self._merge_storage_metadata(digital_objects, storage_files)

        if digital_only_org and digital_objects:
            code_scope: List[str] = list(code_candidates)
            if not code_scope and primary_institution_code:
                code_scope.append(primary_institution_code)
            self._apply_dump_storage_matches(digital_objects, code_scope)

        rights_status = self._first_literal_from_predicates(
            subject_edges,
            (
                "http://arkumu.org/data/properties/rechtsstatus",
                "http://arkumu.org/data/fuk/properties/rechtsstatus",
                "http://arkumu.org/data/hmt/properties/rechtsstatus",
                "http://arkumu.org/data/khm/properties/rechtsstatus",
            ),
        )

        if reference_events:
            reference_events = [event for event in events_all if event.is_reference_only]

        filtered_event_ids_list = sorted(filtered_event_ids_set)
        filtered_digital_object_ids_list = sorted(filtered_digital_only_ids)
        reference_project_uris_list = sorted(reference_project_uris)

        for metadata in digital_object_sources.values():
            event_ids_list = list(metadata.get("event_ids", []))
            metadata["event_ids"] = event_ids_list
            metadata["event_uris"] = list(metadata.get("event_uris", []))
            metadata["filtered_event_ids"] = [
                event_id for event_id in event_ids_list if event_id in filtered_event_ids_set
            ]
            metadata["via_project"] = bool(metadata.get("via_project"))

        reference_only_flag = ownership_filtered and not digital_objects
        harvestable_flag = bool(digital_objects)

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
            reference_events=reference_events,
            event_sources=event_sources_map,
            filtered_event_ids=filtered_event_ids_list,
            digital_object_sources=digital_object_sources,
            filtered_digital_object_ids=filtered_digital_object_ids_list,
            reference_project_uris=reference_project_uris_list,
            ownership_filtered=ownership_filtered,
            reference_only=reference_only_flag,
            harvestable=harvestable_flag,
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

    def _apply_dump_storage_matches(
        self,
        digital_objects: List[ProjectDigitalObject],
        institution_codes: Iterable[str],
    ) -> None:
        codes: List[str] = []
        for code in institution_codes:
            normalized = (code or "").strip().lower()
            if not normalized:
                continue
            if normalized not in self._digital_object_orgs:
                continue
            codes.append(normalized)

        if not codes:
            return

        for obj in digital_objects:
            candidates = [
                getattr(obj, "path", None),
                getattr(obj, "storage_key", None),
                getattr(obj, "access_url", None),
                getattr(obj, "file_name", None),
            ]
            matched_key: Optional[str] = None
            fixity_record: Optional[FixityRecord] = None
            dump_matched = False

            for code in codes:
                fixity_record = find_fixity(code, candidates)
                if fixity_record:
                    matched_key = fixity_record.storage_key or fixity_record.dump_key
                    dump_matched = True
                    break

            if matched_key and not getattr(obj, "storage_key", None):
                obj.storage_key = matched_key

            if fixity_record:
                storage_key = fixity_record.storage_key or fixity_record.dump_key
                if storage_key and not getattr(obj, "storage_key", None):
                    obj.storage_key = storage_key

                if fixity_record.status and not getattr(obj, "storage_status", None):
                    obj.storage_status = fixity_record.status

                checksum_value = fixity_record.checksum_or_etag
                if checksum_value and not getattr(obj, "checksum", None):
                    fixity = parse_fixity(checksum_value)
                    if fixity.digest:
                        obj.checksum = fixity.digest
                    if fixity.algorithm and not getattr(obj, "checksum_algorithm", None):
                        obj.checksum_algorithm = fixity.algorithm
                    if fixity.digest and not getattr(obj, "checksum_provenance", None):
                        obj.checksum_provenance = "dump"

            setattr(obj, "_dump_matched", dump_matched)

    def _is_digital_object_org(self, codes: Iterable[str]) -> bool:
        if not self._digital_object_orgs or not codes:
            return False
        for code in codes:
            normalized = (code or "").lower().strip()
            if normalized in self._digital_object_orgs:
                return True
        return False

    def _fallback_digital_predicates_for_org(self, codes: Iterable[str]) -> List[str]:
        predicates: List[str] = []
        seen: set[str] = set()
        for code in codes:
            normalized = (code or "").lower().strip()
            if not normalized:
                continue
            for predicate in self.DIGITAL_OBJECT_FALLBACK_PREDICATES.get(normalized, ()):
                if predicate and predicate not in seen:
                    predicates.append(predicate)
                    seen.add(predicate)
        return predicates

    def _collect_event_owner_map(
        self,
        event_ids: Sequence[str],
        nodes: Dict[str, Dict[str, Any]],
    ) -> Dict[str, List[str]]:

        normalized_ids = [str(event_id) for event_id in event_ids if event_id]
        if not normalized_ids:
            return {}

        owner_map: Dict[str, Set[str]] = defaultdict(set)

        uuid_ids: List[uuid.UUID] = []
        string_ids: List[str] = []
        for event_id in normalized_ids:
            try:
                uuid_ids.append(uuid.UUID(event_id))
            except (ValueError, TypeError, AttributeError):
                string_ids.append(event_id)

        triples_qs = Triple.objects.select_related("object").filter(
            predicate__canonical_uri=self.EVENT_PROJECT_LINK_URI,
        )
        if uuid_ids:
            triples_qs = triples_qs.filter(subject_id__in=uuid_ids)
        else:
            triples_qs = triples_qs.none()

        for triple in triples_qs:
            event_id = str(triple.subject_id)
            project_uri = None
            obj = triple.object
            if obj:
                project_uri = (obj.canonical_uri or obj.uri or obj.value)
            if not project_uri:
                project_uri = self._project_uri_from_nodes(nodes, str(triple.object_id))
            if not project_uri:
                continue
            owner_map[event_id].add(project_uri)

        return {
            event_id: sorted(uris)
            for event_id, uris in owner_map.items()
        }

    @staticmethod
    def _project_uri_from_nodes(
        nodes: Dict[str, Dict[str, Any]],
        resource_id: Optional[str],
    ) -> Optional[str]:
        if not resource_id:
            return None
        node = nodes.get(str(resource_id))
        if node:
            return node.get("uri") or node.get("canonical_uri") or node.get("value")
        try:  # pragma: no cover - defensive DB lookup
            resource = Resource.objects.filter(id=resource_id).only("uri", "canonical_uri", "value").first()
        except Exception:
            resource = None
        if resource:
            return resource.canonical_uri or resource.uri or resource.value
        return None

    def _ownership_filter_orgs(self) -> Set[str]:
        configured = getattr(settings, "PROJECT_SNAPSHOT_OWNERSHIP_FILTER_ORGS", None)
        if configured is None:
            return {code.lower() for code in self.OWNERSHIP_FILTER_ORGS}
        if isinstance(configured, str):
            configured = [configured]
        return {
            str(code).lower().strip()
            for code in configured
            if code
        }

    def _should_filter_ownership(
        self,
        institution_codes: Iterable[str],
        project_uri: Optional[str],
    ) -> bool:
        filter_orgs = self._ownership_filter_orgs()
        if not filter_orgs:
            return False
        candidates: Set[str] = {
            (code or "").lower().strip()
            for code in institution_codes
            if code
        }
        if self.relationship_org_code:
            candidates.add(self.relationship_org_code.lower().strip())
        uri_code = self._extract_org_code_from_uri(project_uri)
        if uri_code:
            candidates.add(uri_code.lower())
        return bool(filter_orgs.intersection(candidates))

    def _checksum_predicate_for_org(self, institution_code: Optional[str]) -> Optional[str]:
        if not institution_code:
            scoped = self.relationship_org_code.lower() if self.relationship_org_code else None
            return self.ROSETTA_CHECKSUM_PREDICATES.get(scoped) if scoped else None
        return self.ROSETTA_CHECKSUM_PREDICATES.get(institution_code.lower())

    @staticmethod
    def _is_grundereignis_event(event: ProjectEvent) -> bool:
        uri_candidates = (
            getattr(event, "uri", None),
            getattr(event, "type_uri", None),
        )
        for candidate in uri_candidates:
            if candidate and "/01-grundereignis/" in candidate:
                return True
        return False

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

    def _literal_list_from_edges(
        self,
        edges: Iterable[Dict[str, Any]],
        predicates: Sequence[str],
    ) -> List[str]:
        items: List[str] = []
        predicate_set = {predicate for predicate in predicates if predicate}
        if not predicate_set:
            return items
        for edge in edges:
            predicate = self._canonical(edge)
            if predicate not in predicate_set:
                continue
            value = self._normalize_text_value(edge.get('object_value'))
            if not value:
                continue
            tokens = [
                token.strip()
                for token in value.replace(';', ',').split(',')
                if token.strip()
            ]
            for token in tokens:
                if token not in items:
                    items.append(token)
        return items

    def _first_literal_from_related_nodes(
        self,
        related_ids: Iterable[str],
        nodes: Dict[str, Dict[str, Any]],
        edges_by_subject: Dict[str, List[Dict[str, Any]]],
        predicates: Sequence[str],
    ) -> Optional[str]:
        for related_id in related_ids:
            related_id_str = str(related_id)
            node = nodes.get(related_id_str, {})
            for key in ('name', 'title', 'label', 'value'):
                candidate = self._normalize_text_value(node.get(key))
                if candidate:
                    return candidate

            related_edges = edges_by_subject.get(related_id_str, [])
            candidate = self._first_literal_any(related_edges, predicates)
            if candidate:
                return candidate
        return None

    def _first_literal_from_db(
        self,
        subject_id: str,
        predicates: Sequence[str],
    ) -> Optional[str]:
        predicate_list = [predicate for predicate in predicates if predicate]
        if not predicate_list:
            return None

        try:
            uuid.UUID(subject_id)
        except (ValueError, TypeError, AttributeError):
            return None

        qs = (
            Triple.objects.filter(
                subject_id=subject_id,
                object__resource_type=ResourceType.LITERAL,
            )
            .filter(
                Q(predicate__canonical_uri__in=predicate_list)
                | Q(predicate__uri__in=predicate_list)
            )
            .values_list('object__value', flat=True)
        )

        try:
            value = qs.first()
        except RuntimeError:
            return None
        except Exception:  # pragma: no cover - defensive
            logger.debug(
                "Literal lookup skipped for %s (predicates=%s)",
                subject_id,
                predicate_list,
            )
            return None
        return self._normalize_text_value(value)

    @staticmethod
    def _normalize_text_value(value: Optional[Any]) -> Optional[str]:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    def _requires_numeric_license_cleanup(self, license_uri: Optional[str]) -> bool:
        if not license_uri:
            return False
        parsed = urlparse(license_uri)
        segments = [segment.lower().strip() for segment in parsed.path.split('/') if segment]
        return any(segment in self.NUMERIC_LICENSE_ORGS for segment in segments)

    def _sanitize_license_text(
        self,
        value: Optional[str],
        identifier: Optional[str],
        *,
        enforce_numeric_cleanup: bool,
    ) -> Optional[str]:
        if value is None:
            return None
        text = value.strip()
        if not text:
            return None
        if identifier and text.lower() == identifier.lower():
            return None
        if enforce_numeric_cleanup and text.isdigit():
            return None
        return text

    @staticmethod
    def _parse_bool_literal(value: Optional[str]) -> Optional[bool]:
        if value is None:
            return None
        token = value.strip().lower()
        if not token:
            return None
        if token in {'1', 'true', 'yes', 'ja'}:
            return True
        if token in {'0', 'false', 'no', 'nein'}:
            return False
        return None

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
        institution_codes: Iterable[str],
    ) -> None:
        edges_for_digital = edges_by_subject.get(str(object_id), [])

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

    def _populate_event_metadata(
        self,
        event: ProjectEvent,
        nodes: Dict[str, Dict[str, Any]],
        edges_by_subject: Dict[str, List[Dict[str, Any]]],
    ) -> None:
        if not event.id:
            return

        event_id = str(event.id)
        event_edges = edges_by_subject.get(event_id, [])

        name_de = self._first_literal_any(event_edges, self.EVENT_NAME_DE_PROPERTIES)
        name_en = self._first_literal_any(event_edges, self.EVENT_NAME_EN_PROPERTIES)

        if name_de:
            event.name_de = name_de
        else:
            event.name_de = event.name or None
        event.name_en = name_en

        start_estimated = self._first_literal_any(event_edges, self.EVENT_START_ESTIMATED_PROPERTIES)
        end_estimated = self._first_literal_any(event_edges, self.EVENT_END_ESTIMATED_PROPERTIES)
        event.start_estimated = self._parse_bool_literal(start_estimated)
        event.end_estimated = self._parse_bool_literal(end_estimated)

        type_ids = self._related_ids(event_edges, ProjectURIs.EVENT_TYPE)
        if type_ids:
            type_id = type_ids[0]
            type_id_str = str(type_id)
            type_node = nodes.get(type_id_str, {})
            type_edges = edges_by_subject.get(type_id_str, [])

            event.type_uri = type_node.get('uri') or type_node.get('canonical_uri')

            type_label_de = self._first_literal_any(type_edges, self.EVENT_TYPE_LABEL_DE_PROPERTIES)
            type_label_en = self._first_literal_any(type_edges, self.EVENT_TYPE_LABEL_EN_PROPERTIES)
            event.type_label_de = type_label_de or event.type
            event.type_label_en = type_label_en

            synonyms = self._literal_list_from_edges(type_edges, self.EVENT_TYPE_SYNONYM_PROPERTIES)
            if synonyms:
                event.type_synonyms_de = synonyms

            event.type_wikidata_id = self._first_literal_any(type_edges, self.EVENT_TYPE_WIKIDATA_PROPERTIES)
            event.type_gnd_id = self._first_literal_any(type_edges, self.EVENT_TYPE_GND_PROPERTIES)
            event.type_aat_id = self._first_literal_any(type_edges, self.EVENT_TYPE_AAT_PROPERTIES)
            event.type_lido_id = self._first_literal_any(type_edges, self.EVENT_TYPE_LIDO_PROPERTIES)
        else:
            event.type_label_de = event.type

        if event.name_de and not event.name:
            event.name = event.name_de

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
        license_id_str = str(license_id)
        license_node = nodes.get(license_id_str, {})
        license_edges = edges_by_subject.get(license_id_str, [])

        if not license_node or not license_edges:
            if license_id_str.startswith("http://") or license_id_str.startswith("https://"):
                try:
                    from arkumu.metadata.models.resource import Resource

                    resource = Resource.objects.filter(uri=license_id_str).only("id").first()
                except Exception:
                    resource = None
                if resource:
                    resolved_id = str(resource.id)
                    license_node = nodes.get(resolved_id, {})
                    license_edges = edges_by_subject.get(resolved_id, [])
                    license_id_str = resolved_id

        uri = self._first_literal_any(license_edges, self.DIGITAL_OBJECT_LICENSE_URI_PROPERTIES)
        if not uri:
            uri = self._normalize_text_value(license_node.get('uri') or license_node.get('value'))
        if not uri:
            uri = self._first_literal_from_db(license_id_str, self.DIGITAL_OBJECT_LICENSE_URI_PROPERTIES)

        label_de = self._first_literal_any(license_edges, self.DIGITAL_OBJECT_LICENSE_LABEL_DE_PROPERTIES)
        if not label_de:
            label_de = self._normalize_text_value(license_node.get('name'))
        if not label_de:
            label_de = self._first_literal_from_db(license_id_str, self.DIGITAL_OBJECT_LICENSE_LABEL_DE_PROPERTIES)

        label_en = self._first_literal_any(license_edges, self.DIGITAL_OBJECT_LICENSE_LABEL_EN_PROPERTIES)
        if not label_en:
            label_en = self._first_literal_from_db(license_id_str, self.DIGITAL_OBJECT_LICENSE_LABEL_EN_PROPERTIES)

        rights_statement = self._first_literal_any(license_edges, self.DIGITAL_OBJECT_LICENSE_RIGHTS_STATEMENT_PROPERTIES)
        if not rights_statement:
            rights_statement_ids: List[str] = []
            for predicate in self.DIGITAL_OBJECT_LICENSE_RIGHTS_STATEMENT_PROPERTIES:
                rights_statement_ids.extend(self._related_ids(license_edges, predicate))
            if rights_statement_ids:
                candidate_predicates: List[str] = list(self.DIGITAL_OBJECT_LICENSE_LABEL_DE_PROPERTIES)
                candidate_predicates.extend(self.DIGITAL_OBJECT_LICENSE_LABEL_EN_PROPERTIES)
                candidate_predicates.extend(self.RESOURCE_LABEL_PREDICATES)
                candidate_predicates.extend(self.RIGHTS_STATEMENT_FALLBACK_PREDICATES)
                rights_statement = self._first_literal_from_related_nodes(
                    rights_statement_ids,
                    nodes,
                    edges_by_subject,
                    candidate_predicates,
                )
        if not rights_statement:
            rights_statement = self._first_literal_from_db(license_id_str, self.DIGITAL_OBJECT_LICENSE_RIGHTS_STATEMENT_PROPERTIES)

        identifier = self._first_literal_any(license_edges, self.DIGITAL_OBJECT_LICENSE_IDENTIFIER_PROPERTIES)
        if not identifier:
            identifier = self._first_literal_from_db(license_id_str, self.DIGITAL_OBJECT_LICENSE_IDENTIFIER_PROPERTIES)

        enforce_numeric_cleanup = (
            self._requires_numeric_license_cleanup(license_node.get('uri'))
            or self._requires_numeric_license_cleanup(uri)
        )

        rights_statement = self._sanitize_license_text(
            rights_statement,
            identifier,
            enforce_numeric_cleanup=enforce_numeric_cleanup,
        )
        label_de = self._sanitize_license_text(
            label_de,
            identifier,
            enforce_numeric_cleanup=enforce_numeric_cleanup,
        )
        label_en = self._sanitize_license_text(
            label_en,
            identifier,
            enforce_numeric_cleanup=enforce_numeric_cleanup,
        )

        if not any([uri, label_de, label_en, rights_statement, identifier]):
            return None

        license_info = ProjectDigitalObjectLicense(
            uri=uri,
            label_de=label_de,
            label_en=label_en,
            rights_statement=rights_statement,
            identifier=identifier,
        )

        token = license_token_from_license_info(license_info)
        if token and token in ARKUMU_LICENSE_LABELS:
            license_info.identifier = token
            license_info.label_de = ARKUMU_LICENSE_LABELS[token]
            license_info.rights_statement = ARKUMU_LICENSE_TEXTS[token]
            license_info.label_en = None
            if not license_info.uri:
                license_info.uri = ARKUMU_LICENSE_URIS.get(token)

        return license_info

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
