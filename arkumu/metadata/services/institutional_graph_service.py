from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence

from django.db.models import Q

from arkumu.metadata.models.resource import Resource, ResourceType
from arkumu.metadata.models.triples import Triple
from arkumu.users.models import Organization


class InstitutionalGraphService:
    """Build org-scoped graphs using archive-native predicates."""

    def __init__(self, org_code: Optional[str] = None) -> None:
        self.organization = (
            Organization.objects.get(code=org_code) if org_code else None
        )

    def get_entity_graph(
        self,
        resource_uri: str,
        *,
        include_incoming: bool = True,
        expand_neighbors: bool = True,
        depth: int = 1,
    ) -> Dict[str, Any]:
        resource = self._resolve_resource_by_uri(resource_uri)
        if resource is None:
            raise ValueError(f"Resource not found: {resource_uri}")

        root_id = str(resource.id)
        edges = self._fetch_triples_for_subjects([root_id])

        if include_incoming:
            edges += self._fetch_triples_for_objects([root_id])

        if expand_neighbors and depth > 0:
            visited: set[str] = {root_id}
            frontier = [
                edge.get("object_id")
                for edge in edges
                if edge.get("object_type") == ResourceType.ENTITY
            ]
            frontier = [
                node_id for node_id in frontier if node_id and node_id not in visited
            ]

            hops = 0
            while frontier and hops < depth:
                visited.update(frontier)
                next_edges = self._fetch_triples_for_subjects(frontier)
                edges.extend(next_edges)
                next_frontier = [
                    edge.get("object_id")
                    for edge in next_edges
                    if edge.get("object_type") == ResourceType.ENTITY
                ]
                frontier = [
                    node_id
                    for node_id in next_frontier
                    if node_id and node_id not in visited
                ]
                hops += 1

        nodes = self._collect_nodes_from_edges(edges)
        return {
            "organization": getattr(self.organization, "code", None),
            "root_id": root_id,
            "nodes": nodes,
            "edges": edges,
            "counts": {"nodes": len(nodes), "edges": len(edges)},
        }

    # Helpers --------------------------------------------------------------
    def _triple_filter(self) -> Q:
        if self.organization:
            return Q(source=self.organization) | Q(source__isnull=True)
        return Q()

    def _fetch_triples_for_subjects(
        self,
        subject_ids: Sequence[str],
    ) -> List[Dict[str, Any]]:
        if not subject_ids:
            return []

        clause = (
            self._triple_filter()
            & Q(subject_id__in=subject_ids)
            & Q(subject__resource_type=ResourceType.ENTITY)
        )
        triples = (
            Triple.objects.filter(clause)
            .select_related("predicate", "object")
            .only(
                "id",
                "subject_id",
                "predicate__uri",
                "predicate__canonical_uri",
                "object__id",
                "object__uri",
                "object__canonical_uri",
                "object__resource_type",
                "object__value",
            )
        )
        return [
            {
                "triple_id": str(t.id),
                "subject_id": str(t.subject_id),
                "predicate_uri": t.predicate.uri,
                "predicate_canonical": getattr(t.predicate, "canonical_uri", None),
                "object_id": str(t.object.id),
                "object_uri": getattr(t.object, "uri", None),
                "object_canonical": getattr(t.object, "canonical_uri", None),
                "object_type": t.object.resource_type,
                "object_value": getattr(t.object, "value", None),
            }
            for t in triples
            if getattr(t.predicate, "uri", None)
        ]

    def _fetch_triples_for_objects(
        self,
        object_ids: Sequence[str],
    ) -> List[Dict[str, Any]]:
        if not object_ids:
            return []

        clause = (
            self._triple_filter()
            & Q(object_id__in=object_ids)
            & Q(subject__resource_type=ResourceType.ENTITY)
        )
        triples = (
            Triple.objects.filter(clause)
            .select_related("predicate", "object")
            .only(
                "id",
                "subject_id",
                "predicate__uri",
                "predicate__canonical_uri",
                "object__id",
                "object__uri",
                "object__canonical_uri",
                "object__resource_type",
                "object__value",
            )
        )
        return [
            {
                "triple_id": str(t.id),
                "subject_id": str(t.subject_id),
                "predicate_uri": t.predicate.uri,
                "predicate_canonical": getattr(t.predicate, "canonical_uri", None),
                "object_id": str(t.object.id),
                "object_uri": getattr(t.object, "uri", None),
                "object_canonical": getattr(t.object, "canonical_uri", None),
                "object_type": t.object.resource_type,
                "object_value": getattr(t.object, "value", None),
            }
            for t in triples
            if getattr(t.predicate, "uri", None)
        ]

    def _collect_nodes_from_edges(
        self,
        edges: Iterable[Dict[str, Any]],
    ) -> Dict[str, Dict[str, Any]]:
        node_ids: set[str] = set()
        for edge in edges:
            subj = edge.get("subject_id")
            obj = edge.get("object_id")
            if subj:
                node_ids.add(str(subj))
            if obj:
                node_ids.add(str(obj))
        if not node_ids:
            return {}
        resources = (
            Resource.objects.filter(id__in=list(node_ids))
            .only("id", "uri", "name", "value", "resource_type", "canonical_uri", "organization")
            .select_related("organization")
        )
        result: Dict[str, Dict[str, Any]] = {}
        for resource in resources:
            result[str(resource.id)] = {
                "id": str(resource.id),
                "uri": resource.uri,
                "name": resource.name,
                "value": resource.value,
                "resource_type": resource.resource_type,
                "canonical_uri": resource.canonical_uri,
                "organization": getattr(resource.organization, "code", None),
            }
        return result

    def _resolve_resource_by_uri(self, uri: str) -> Optional[Resource]:
        clause = Q(uri=uri)
        if self.organization:
            clause &= Q(organization=self.organization)
        return Resource.objects.filter(clause).only("id", "uri", "organization").first()
