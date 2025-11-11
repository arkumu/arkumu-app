"""
Institutional Graph Service

Builds organization-scoped graphs that preserve the original (non-canonical)
predicates as delivered by partner archives. This complements
`CanonicalGraphService`, which focuses on normalized URIs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence

from django.db.models import Q

from arkumu.metadata.models.resource import Resource, ResourceType
from arkumu.metadata.models.triples import Triple
from arkumu.users.models import Organization


@dataclass
class InstitutionalEdge:
    triple_id: str
    subject_id: str
    predicate_uri: str
    object_id: str
    object_uri: Optional[str]
    object_type: str
    object_value: Optional[str]


class InstitutionalGraphService:
    """Retrieve non-canonical graphs for a given organization."""

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
                edge.object_id
                for edge in edges
                if edge.object_type != ResourceType.LITERAL
            ]
            frontier = [node_id for node_id in frontier if node_id not in visited]

            hops = 0
            while frontier and hops < depth:
                visited.update(frontier)
                next_edges = self._fetch_triples_for_subjects(frontier)
                edges.extend(next_edges)
                next_frontier = [
                    edge.object_id
                    for edge in next_edges
                    if edge.object_type != ResourceType.LITERAL
                ]
                frontier = [node_id for node_id in next_frontier if node_id not in visited]
                hops += 1

        nodes = self._collect_nodes_from_edges(edges)

        return {
            "root_id": root_id,
            "organization": getattr(self.organization, "code", None),
            "nodes": nodes,
            "edges": [edge.__dict__ for edge in edges],
            "counts": {
                "nodes": len(nodes),
                "edges": len(edges),
            },
        }

    # ------------------------------------------------------------------
    def _base_triple_filter(self) -> Q:
        clause = Q(predicate__canonical_uri__isnull=True)
        if self.organization:
            clause &= Q(source=self.organization)
        return clause

    def _fetch_triples_for_subjects(
        self,
        subject_ids: Sequence[str],
    ) -> List[InstitutionalEdge]:
        if not subject_ids:
            return []

        clause = self._base_triple_filter() & Q(subject_id__in=subject_ids)
        triples = (
            Triple.objects.filter(clause)
            .select_related("predicate", "object")
            .only(
                "id",
                "subject_id",
                "predicate__uri",
                "object__id",
                "object__uri",
                "object__resource_type",
                "object__value",
            )
        )
        return [
            InstitutionalEdge(
                triple_id=str(triple.id),
                subject_id=str(triple.subject_id),
                predicate_uri=triple.predicate.uri,
                object_id=str(triple.object.id),
                object_uri=getattr(triple.object, "uri", None),
                object_type=triple.object.resource_type,
                object_value=getattr(triple.object, "value", None),
            )
            for triple in triples
            if getattr(triple.predicate, "uri", None)
        ]

    def _fetch_triples_for_objects(
        self,
        object_ids: Sequence[str],
    ) -> List[InstitutionalEdge]:
        if not object_ids:
            return []

        clause = self._base_triple_filter() & Q(object_id__in=object_ids)
        triples = (
            Triple.objects.filter(clause)
            .select_related("predicate", "object")
            .only(
                "id",
                "subject_id",
                "predicate__uri",
                "object__id",
                "object__uri",
                "object__resource_type",
                "object__value",
            )
        )
        return [
            InstitutionalEdge(
                triple_id=str(triple.id),
                subject_id=str(triple.subject_id),
                predicate_uri=triple.predicate.uri,
                object_id=str(triple.object.id),
                object_uri=getattr(triple.object, "uri", None),
                object_type=triple.object.resource_type,
                object_value=getattr(triple.object, "value", None),
            )
            for triple in triples
            if getattr(triple.predicate, "uri", None)
        ]

    def _collect_nodes_from_edges(
        self,
        edges: Iterable[InstitutionalEdge],
    ) -> Dict[str, Dict[str, Any]]:
        node_ids = {edge.subject_id for edge in edges} | {
            edge.object_id for edge in edges
        }
        if not node_ids:
            return {}

        resources = (
            Resource.objects.filter(id__in=list(node_ids))
            .only(
                "id",
                "uri",
                "name",
                "value",
                "resource_type",
                "organization",
            )
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
                "organization": getattr(resource.organization, "code", None),
            }
        return result

    def _resolve_resource_by_uri(self, uri: str) -> Optional[Resource]:
        clause = Q(uri=uri)
        if self.organization:
            clause &= Q(organization=self.organization)
        return Resource.objects.filter(clause).only("id", "uri", "organization").first()
