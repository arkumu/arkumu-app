"""DB-backed ProjectRecord assembly for OAI-PMH."""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Mapping, MutableMapping, Optional, Protocol

from django.db import transaction

from arkumu.metadata.models.resource import Resource
from arkumu.projects import ProjectRecord
from arkumu.projects.services import ProjectSnapshotService
from arkumu.catalog.services.schema_manifest_service import CardSchema
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
