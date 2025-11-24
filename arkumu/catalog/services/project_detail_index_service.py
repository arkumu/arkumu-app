"""Snapshot-free per-project detail builder using canonical graph access."""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Dict, Optional

from arkumu.catalog.services.schema_manifest_service import CARD_SCHEMA_TEMPLATE, CardSchema
from arkumu.catalog.services.triple_relationship_service import TripleRelationshipService
from arkumu.metadata.models.resource import Resource
from arkumu.metadata.services.canonical_graph_service import CanonicalGraphService
from arkumu.projects import ProjectRecord
from arkumu.projects.services.snapshot_service import ProjectSnapshotService

logger = logging.getLogger(__name__)


class ProjectDetailIndexService:
    """Build a single ProjectRecord without triggering a full snapshot rebuild."""

    def __init__(self) -> None:
        self.snapshot_service = ProjectSnapshotService()

    def get_record(self, project_uri: str) -> Optional[ProjectRecord]:
        if not project_uri:
            return None

        resource = (
            Resource.objects.select_related("organization")
            .filter(uri=project_uri)
            .first()
        )
        if not resource:
            return None

        org_code = getattr(getattr(resource, "organization", None), "code", None)

        try:
            card_schema: CardSchema = self.snapshot_service.schema_service.get_card_schema(org_code or "")
        except Exception:
            logger.warning(
                "ProjectDetailIndexService: falling back to template card schema for org=%s",
                org_code,
            )
            card_schema = CARD_SCHEMA_TEMPLATE

        project_predicates, neighbor_predicates = self.snapshot_service._card_predicate_whitelists()

        graph_service = CanonicalGraphService(org_code=org_code)
        graph = graph_service.get_entity_graph(
            project_uri,
            predicate_canon_whitelist=project_predicates,
            include_incoming=True,
            expand_neighbors=True,
            neighbor_predicate_canon_whitelist=neighbor_predicates,
            depth=2,
            restrict_to_org=False,
        )

        nodes: Dict[str, Dict[str, str]] = graph.get("nodes", {})
        edges = graph.get("edges", [])
        root_id = graph.get("root_id")
        if not root_id:
            return None

        edges_by_subject: Dict[str, list] = defaultdict(list)
        for edge in edges:
            subject_id = edge.get("subject_id") or edge.get("subject") or edge.get("s")
            if subject_id is None:
                continue
            edges_by_subject[str(subject_id)].append(edge)

        storage_files_map: Dict[str, list] = defaultdict(list)
        try:  # pragma: no cover - optional dependency in tests
            from arkumu.storage.models.s3_file_objects import S3FileObject

            node_ids = {str(node_id) for node_id in nodes.keys()}
            if node_ids:
                files_qs = (
                    S3FileObject.objects
                    .filter(related_resource_id__in=node_ids)
                    .order_by("created_at")
                )
                for file_obj in files_qs:
                    storage_files_map[str(file_obj.related_resource_id)].append(file_obj)
        except Exception:
            storage_files_map = defaultdict(list)

        triple_service = TripleRelationshipService(org_code)
        snapshot_builder = ProjectSnapshotService(relationship_org_code=org_code)
        record = snapshot_builder._build_project_record(  # noqa: SLF001 - intentional reuse
            str(root_id),
            nodes,
            edges_by_subject,
            card_schema,
            triple_service,
            storage_files_map,
        )

        return record
