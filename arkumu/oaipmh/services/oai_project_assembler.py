"""DB-backed ProjectRecord assembly for OAI-PMH."""

from __future__ import annotations

import logging
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Mapping, MutableMapping, Optional, Protocol

from django.conf import settings
from django.db import transaction

from arkumu.metadata.models.resource import Resource, ResourceType
from arkumu.projects import ProjectRecord, ProjectDigitalObject
from arkumu.projects.services import ProjectSnapshotService
from arkumu.catalog.services.schema_manifest_service import CardSchema
from arkumu.catalog.services.project_views import ProjectURIs
from arkumu.catalog.services.triple_relationship_service import TripleRelationshipService
from arkumu.metadata.services.canonical_graph_service import CanonicalGraphService
from arkumu.storage.models.s3_file_objects import S3FileObject

logger = logging.getLogger(__name__)


class GraphServiceFactory(Protocol):
    """Protocol describing the canonical graph service factory."""

    def __call__(self, *args: Any, **kwargs: Any) -> CanonicalGraphService:  # pragma: no cover - interface only
        ...


@dataclass(frozen=True)
class AssemblyContext:
    """
    Metadata describing a single assembly request.

    Additional fields (e.g., institution overrides, batching hints) can be plugged in
    as the DB-backed pipeline matures.
    """

    resource: Resource


class OAIProjectAssembler:
    """
    Build ProjectRecord instances directly from canonical graphs without relying on cached snapshots.

    Pipeline:
    1. Use CanonicalGraphService to fetch a resource-centric graph (with neighbors expanded).
    2. Map graph payloads into the shape expected by ProjectSnapshotService._build_project_record.
    3. Reuse the snapshot service's mature filtering/normalization logic to guarantee parity.
    """

    GRAPH_DEPTH = 2  # Include project neighbors (events, actors, digital objects) and their literals.

    def __init__(
        self,
        *,
        graph_service_factory: Optional[GraphServiceFactory] = None,
        snapshot_service: Optional[ProjectSnapshotService] = None,
    ) -> None:
        self._graph_service_factory = graph_service_factory or CanonicalGraphService
        self._snapshot_service = snapshot_service or ProjectSnapshotService()
        self._card_schema_cache: MutableMapping[Optional[str], CardSchema] = {}
        self._event_chain_orgs: set[str] = {
            str(code).lower().strip()
            for code in getattr(settings, "OAI_EVENT_CHAIN_ORGS", ("khm", "hmt"))
            if code
        }

    # ------------------------------------------------------------------
    def build_record(self, context: AssemblyContext) -> Optional[ProjectRecord]:
        """Assemble a ProjectRecord for the provided resource."""

        resource = context.resource
        uri = getattr(resource, "uri", None)
        if not uri:
            logger.warning("OAI assembler received resource without URI: %s", resource)
            return None

        org_code = self._infer_org_code(resource, uri)

        graph = self._build_entity_graph(uri, org_code, resource=resource)
        if not graph:
            return None

        subject_id = str(graph.get("root_id") or getattr(resource, "id", ""))
        if not subject_id:
            logger.warning("Canonical graph for %s missing root identifier", uri)
            return None

        nodes: Dict[str, Dict[str, Any]] = graph.get("nodes", {})
        edges = graph.get("edges", [])
        if not nodes and not edges:
            logger.warning("Canonical graph for %s returned no nodes/edges", uri)
            return None

        edges_by_subject: Dict[str, list[Dict[str, Any]]] = defaultdict(list)
        for edge in edges:
            subject = edge.get("subject_id") or edge.get("subject") or edge.get("s")
            if subject is None:
                continue
            edges_by_subject[str(subject)].append(edge)

        card_schema = self._card_schema_for_org(org_code)
        triple_service = TripleRelationshipService(org_code)
        storage_files_map = self._storage_files_map(nodes.keys())

        record = self._snapshot_service._build_project_record(
            subject_id,
            nodes,
            edges_by_subject,
            card_schema,
            triple_service,
            storage_files_map,
        )
        record = self._augment_shared_event_objects(record, nodes, edges_by_subject, graph, org_code)
        return record

    # ------------------------------------------------------------------
    def _infer_org_code(self, resource: Resource, uri: str) -> Optional[str]:
        code = getattr(getattr(resource, "organization", None), "code", None)
        if code:
            return str(code).lower().strip()
        try:
            return self._snapshot_service._extract_org_code_from_uri(uri)  # type: ignore[attr-defined]
        except AttributeError:
            return None

    def _build_entity_graph(
        self,
        project_uri: str,
        org_code: Optional[str],
        *,
        resource: Optional[Resource] = None,
    ) -> Optional[Dict[str, Any]]:
        graph_service = self._graph_service_factory(org_code=org_code) if org_code else self._graph_service_factory()
        try:
            graph = graph_service.get_entity_graph(
                project_uri,
                include_incoming=True,
                expand_neighbors=True,
                depth=self.GRAPH_DEPTH,
            )
            graph.setdefault("subjects", [graph.get("root_id")])
            return graph
        except ValueError:
            logger.warning("DB assembler could not resolve canonical graph for %s", project_uri)
            return None
        except Exception:  # pragma: no cover - defensive logging
            logger.exception("Canonical graph retrieval failed for %s", project_uri)
            return None

    def _card_schema_for_org(self, org_code: Optional[str]) -> CardSchema:
        cache_key = org_code or "__default__"
        if cache_key in self._card_schema_cache:
            return self._card_schema_cache[cache_key]

        cache_key = org_code or "__default__"
        if org_code:
            schema = self._snapshot_service.schema_service.get_card_schema(org_code)
        else:
            schema = self._snapshot_service._get_card_schema()  # type: ignore[attr-defined]
        self._card_schema_cache[cache_key] = schema
        return schema

    def _storage_files_map(self, node_ids: Iterable[str]) -> Dict[str, list[Any]]:
        ids = [nid for nid in {str(node_id) for node_id in node_ids or []} if nid]
        if not ids:
            return defaultdict(list)  # type: ignore[return-value]

        files_map: Dict[str, list[Any]] = defaultdict(list)
        try:
            with transaction.atomic():
                files = (
                    S3FileObject.objects
                    .filter(related_resource_id__in=ids)
                    .order_by("created_at")
                )
                for file_obj in files:
                    files_map[str(file_obj.related_resource_id)].append(file_obj)
        except Exception:
            logger.exception("Failed to load S3 file metadata for nodes %s", ids)
            return defaultdict(list)  # type: ignore[return-value]

        return files_map

    def _augment_shared_event_objects(
        self,
        record: Optional[ProjectRecord],
        nodes: Dict[str, Dict[str, Any]],
        edges_by_subject: Dict[str, list[Dict[str, Any]]],
        graph: Dict[str, Any],
        org_code: Optional[str],
    ) -> Optional[ProjectRecord]:
        if record is None:
            return None

        normalized_org = (org_code or "").strip().lower()
        if normalized_org not in self._event_chain_orgs:
            return record

        if getattr(record, "digital_objects", None):
            return record

        root_id = graph.get("root_id")
        if not root_id:
            return record
        root_key = str(root_id)

        event_ids = self._collect_event_ids_from_graph(root_key, edges_by_subject)
        if not event_ids:
            return record

        event_graph_service = self._graph_service_factory(org_code=org_code) if org_code else self._graph_service_factory()
        extras: list[ProjectDigitalObject] = []
        for event_id in event_ids:
            event_node = nodes.get(event_id, {})
            event_uri = event_node.get("uri") or event_node.get("canonical_uri")
            if not event_uri:
                continue
            event_type = str(event_node.get("resource_type") or "").upper()
            if event_type and event_type != ResourceType.ENTITY:
                logger.debug(
                    "Skipping supplemental event objects for %s (resource_type=%s)",
                    event_uri,
                    event_type,
                )
                continue
            extras.extend(
                self._digital_objects_from_event(
                    event_graph_service,
                    event_uri,
                    event_id,
                    org_code,
                )
            )

        if not extras:
            return record

        existing = {
            (getattr(obj, "resource_id", None), getattr(obj, "path", None))
            for obj in getattr(record, "digital_objects", []) or []
        }
        sources = getattr(record, "digital_object_sources", None)
        if not isinstance(sources, dict):
            sources = dict(sources or {})

        for obj in extras:
            key = (getattr(obj, "resource_id", None), getattr(obj, "path", None))
            if key in existing:
                continue
            record.digital_objects.append(obj)
            existing.add(key)
            resource_id = getattr(obj, "resource_id", None)
            if resource_id:
                sources[str(resource_id)] = {
                    "source": obj.source or "event",
                    "via_project": False,
                    "event_ids": list(getattr(obj, "source_event_ids", []) or []),
                    "event_uris": list(getattr(obj, "source_event_uris", []) or []),
                }

        record.digital_object_sources = sources
        record.harvestable = bool(record.digital_objects)
        return record

    def _collect_event_ids_from_graph(
        self,
        root_id: str,
        edges_by_subject: Dict[str, list[Dict[str, Any]]],
    ) -> set[str]:
        event_predicate = getattr(self._snapshot_service, "EVENT_RELATION_URI", None)
        if not event_predicate:
            return set()

        visited: set[str] = set()
        queue: deque[str] = deque()

        for edge in edges_by_subject.get(root_id, []):
            predicate = edge.get("predicate_canonical") or edge.get("predicate_uri")
            obj_id = edge.get("object_id")
            if predicate == event_predicate and obj_id:
                queue.append(str(obj_id))

        while queue:
            event_id = queue.popleft()
            if event_id in visited:
                continue
            visited.add(event_id)
            for edge in edges_by_subject.get(event_id, []):
                predicate = edge.get("predicate_canonical") or edge.get("predicate_uri")
                obj_id = edge.get("object_id")
                if predicate == event_predicate and obj_id:
                    queue.append(str(obj_id))

        return visited

    def _digital_objects_from_event(
        self,
        graph_service: CanonicalGraphService,
        event_uri: str,
        event_id: str,
        org_code: Optional[str],
    ) -> list[ProjectDigitalObject]:
        try:
            event_graph = graph_service.get_entity_graph(
                event_uri,
                include_incoming=False,
                expand_neighbors=True,
                depth=1,
            )
        except Exception:
            logger.debug("Unable to load event graph for %s", event_uri, exc_info=True)
            return []

        nodes: Dict[str, Dict[str, Any]] = event_graph.get("nodes", {})
        edges: list[Dict[str, Any]] = event_graph.get("edges", [])
        if not nodes or not edges:
            return []

        edges_by_subject: Dict[str, list[Dict[str, Any]]] = defaultdict(list)
        for edge in edges:
            subject = edge.get("subject_id") or edge.get("subject") or edge.get("s")
            if subject is None:
                continue
            edges_by_subject[str(subject)].append(edge)

        root_id = str(event_graph.get("root_id") or "")
        if not root_id:
            return []

        digital_predicate = getattr(self._snapshot_service, "DIGITAL_OBJECT_LINK_URI", None)
        if not digital_predicate:
            return []

        event_edges = edges_by_subject.get(root_id, [])
        digital_ids: list[str] = [
            str(edge.get("object_id"))
            for edge in event_edges
            if edge.get("object_id") and (edge.get("predicate_canonical") or edge.get("predicate_uri")) == digital_predicate
        ]
        if not digital_ids:
            return []

        path_predicates: list[str] = [ProjectURIs.DIGITAL_OBJECT_PATH]
        fallback_predicates = []
        if org_code:
            fallback_predicates = self._snapshot_service._fallback_digital_predicates_for_org((org_code,))
        for predicate in fallback_predicates:
            if predicate and predicate not in path_predicates:
                path_predicates.append(predicate)

        extras: list[ProjectDigitalObject] = []
        for digital_id in digital_ids:
            digital_edges = edges_by_subject.get(digital_id, [])
            path_literal = self._snapshot_service._first_literal_from_predicates(  # type: ignore[attr-defined]
                digital_edges,
                path_predicates,
            )
            if not path_literal:
                continue
            digital_node = nodes.get(digital_id, {})
            project_object = ProjectDigitalObject(
                path=path_literal,
                uri=digital_node.get("uri") or digital_node.get("canonical_uri"),
            )
            project_object.resource_id = digital_id
            project_object.source_event_ids = [event_id]
            project_object.source_event_uris = [event_uri]
            project_object.source = "event"
            extras.append(project_object)

        return extras
