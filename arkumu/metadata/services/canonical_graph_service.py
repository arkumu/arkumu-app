"""
Canonical Graph Service (blueprint)

Efficient, canonical-URI‑aware graph retrieval for organization-scoped datasets
like FUK "Projekt", with optional expansion to neighbors and canonical
predicate filtering.

This blueprint uses the existing Resource/Triple schema and (optionally)
SchemaService blueprints to identify the canonical class and FK predicates.

Key ideas:
- Subjects are selected via rdf:type against a canonical class URI.
- Predicate canonical_uri normalizes properties across archives.
- Literals are already canonical by URI; class/property resources store
  canonical_uri for Arkumu‑compliant institutions (incl. FUK).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from django.db.models import Q

from arkumu.metadata.models.resource import Resource, ResourceType
from arkumu.metadata.models.triples import Triple
from arkumu.users.models import Organization

try:
    # Optional: leverage mapping blueprints to derive canonical class and FK predicates
    from arkumu.importer.services.schema_service import SchemaService
except Exception:  # pragma: no cover - optional at runtime
    SchemaService = None  # type: ignore


RDF_TYPE_URI = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"

# Entity-type-aware expansion exclusions.
# When expanding FROM entities of a given type, exclude predicates matching these patterns.
# This prevents cross-project pollution (e.g., actors linking to events from other projects).
# Keys are entity type patterns (matched against URI path like /entities/{type}/).
# Values are predicate patterns to exclude (matched case-insensitively against predicate URI).
EXPANSION_EXCLUSIONS_BY_TYPE: Dict[str, Sequence[str]] = {
    "akteurin": ("im-ereignis", "ereignis-hat-akteurin"),  # Don't follow actor -> event links
    "akteur": ("im-ereignis", "ereignis-hat-akteur"),      # Alternative spelling
    "ereignis": ("projekt",),                               # Don't follow event -> project reverse links
}


def _extract_entity_type_from_uri(uri: Optional[str]) -> Optional[str]:
    """Extract entity type from URI like http://arkumu.org/data/fuk/entities/akteurin/123."""
    if not uri:
        return None
    # Look for /entities/{type}/ pattern
    if "/entities/" in uri:
        parts = uri.split("/entities/")
        if len(parts) > 1:
            type_part = parts[1].split("/")[0]
            return type_part.lower() if type_part else None
    return None


def _should_exclude_predicate(entity_type: Optional[str], predicate_uri: Optional[str]) -> bool:
    """Check if a predicate should be excluded based on the source entity type."""
    if not entity_type or not predicate_uri:
        return False
    predicate_lower = predicate_uri.lower()
    for type_pattern, exclusions in EXPANSION_EXCLUSIONS_BY_TYPE.items():
        if type_pattern in entity_type:
            for exclusion in exclusions:
                if exclusion in predicate_lower:
                    return True
    return False


@dataclass
class GraphEdge:
    triple_id: str
    subject_id: str
    predicate_uri: str
    predicate_canonical: Optional[str]
    object_id: str
    object_uri: Optional[str]
    object_type: str  # ResourceType value
    object_value: Optional[str] = None
    object_canonical: Optional[str] = None


class CanonicalGraphService:
    """Canonical‑aware graph retrieval for a given organization.

    Example usage:

        svc = CanonicalGraphService(org_code="fuk", mapping_id=<UUID>)
        graph = svc.get_project_graph(
            dataset_name="Projekt",
            expand_neighbors=True,
        )
    """

    def __init__(
        self,
        org_code: Optional[str] = None,  # Made optional for cross-institutional use
        mapping_id: Optional[str] = None,
    ) -> None:
        # Organization is optional - when None, searches across all institutions
        self.organization = Organization.objects.get(code=org_code) if org_code else None
        self.org_code = org_code  # Keep for backward compatibility
        self.mapping_id = mapping_id
        self._schema: Optional[SchemaService] = None
        if mapping_id and SchemaService is not None:
            self._schema = SchemaService(mapping_id=mapping_id)

    # ----- Public API -----------------------------------------------------
    def get_project_graph(
        self,
        dataset_name: str = "Projekt",
        *,
        type_canonical_uri: Optional[str] = None,
        predicate_canon_whitelist: Optional[Sequence[str]] = None,
        expand_neighbors: bool = True,
        neighbor_predicate_canon_whitelist: Optional[Sequence[str]] = None,
    ) -> Dict[str, Any]:
        """Build a subject‑centric graph for a dataset (e.g., FUK Projekt).

        - Resolves project subjects by rdf:type with a canonical class
          (from SchemaService when available; otherwise `type_canonical_uri`).
        - Fetches all subject triples, optionally filtered by canonical predicates.
        - Optionally expands one hop to neighbor entities (non‑literal objects),
          using FK predicate canonical whitelist derived from the schema or provided.
        """

        canonical_type = type_canonical_uri or self._get_canonical_type_from_schema(dataset_name)
        if not canonical_type:
            raise ValueError("Canonical class URI is required (schema unavailable and not provided).")

        # Get ALL subjects with canonical mapping - no limits
        subject_ids = self._find_subject_ids_by_class(canonical_type)

        edges = self._fetch_triples_for_subjects(subject_ids, predicate_canon_whitelist)

        if expand_neighbors:
            neighbor_pred_canons = neighbor_predicate_canon_whitelist or self._get_fk_predicate_canons(dataset_name)
            neighbor_ids = [e.object_id for e in edges if e.object_type != ResourceType.LITERAL]
            if neighbor_ids:
                edges.extend(self._fetch_triples_for_subjects(neighbor_ids, neighbor_pred_canons))

        nodes = self._collect_nodes_from_edges(edges)

        return {
            "organization": self.organization.code if self.organization else "cross-institutional",
            "dataset": dataset_name,
            "type_canonical_uri": canonical_type,
            "subjects": subject_ids,
            "nodes": nodes,
            "edges": [e.__dict__ for e in edges],
            "counts": {
                "subjects": len(subject_ids),
                "nodes": len(nodes),
                "edges": len(edges),
            },
        }

    def get_entity_graph(
        self,
        resource_uri: str,
        *,
        predicate_canon_whitelist: Optional[Sequence[str]] = None,
        include_incoming: bool = True,
        expand_neighbors: bool = True,
        neighbor_predicate_canon_whitelist: Optional[Sequence[str]] = None,
        depth: int = 1,
        restrict_to_org: bool = True,
    ) -> Dict[str, Any]:
        """Build a canonical-aware graph for a single resource (entity).

        - Outgoing edges (subject = resource) are always included.
        - Incoming edges (object = resource) can be included via `include_incoming`.
        - Neighbor expansion (non-literal objects) is controlled by `expand_neighbors` and `depth`.
        - Canonical predicate whitelists constrain which properties are included at each stage.
        """

        resource = self._resolve_resource_by_uri(resource_uri, restrict_to_org=restrict_to_org)
        if resource is None:
            raise ValueError(f"Resource not found or not accessible in org '{self.organization.code}': {resource_uri}")

        root_id = str(resource.id)
        edges = self._fetch_triples_for_subjects([root_id], predicate_canon_whitelist)

        if include_incoming:
            edges += self._fetch_triples_for_objects([root_id], predicate_canon_whitelist)

        if expand_neighbors and depth > 0:
            visited: set[str] = {root_id}
            # Track (id, uri) tuples for entity-type-aware filtering
            frontier_with_uris: List[Tuple[str, Optional[str]]] = [
                (e.object_id, e.object_uri) for e in edges if e.object_type != ResourceType.LITERAL
            ]
            frontier_with_uris = [
                (nid, uri) for nid, uri in dict.fromkeys(frontier_with_uris) if nid not in visited
            ]
            hops = 0
            while frontier_with_uris and hops < depth:
                frontier_ids = [nid for nid, _ in frontier_with_uris]
                visited.update(frontier_ids)

                # Build a map of subject_id -> entity_type for filtering
                subject_type_map: Dict[str, Optional[str]] = {
                    nid: _extract_entity_type_from_uri(uri) for nid, uri in frontier_with_uris
                }

                next_edges = self._fetch_triples_for_subjects(frontier_ids, neighbor_predicate_canon_whitelist)

                # Filter edges based on entity-type-aware exclusions
                filtered_edges: List[GraphEdge] = []
                for edge in next_edges:
                    entity_type = subject_type_map.get(edge.subject_id)
                    predicate = edge.predicate_canonical or edge.predicate_uri
                    if not _should_exclude_predicate(entity_type, predicate):
                        filtered_edges.append(edge)

                edges.extend(filtered_edges)
                next_frontier = [
                    (e.object_id, e.object_uri) for e in filtered_edges if e.object_type != ResourceType.LITERAL
                ]
                frontier_with_uris = [
                    (nid, uri) for nid, uri in dict.fromkeys(next_frontier) if nid not in visited
                ]
                hops += 1

        nodes = self._collect_nodes_from_edges(edges)

        return {
            "organization": self.organization.code if self.organization else "cross-institutional",
            "root_uri": resource.uri,
            "root_id": root_id,
            "nodes": nodes,
            "edges": [e.__dict__ for e in edges],
            "counts": {
                "nodes": len(nodes),
                "edges": len(edges),
            },
        }

    # ----- Internals ------------------------------------------------------
    def _get_canonical_type_from_schema(self, dataset_name: str) -> Optional[str]:
        if not self._schema:
            return None
        try:
            schema = self._schema.get_dataset_schema(dataset_name)
            if not schema:
                return None
            entity_type = schema.get("entity_type")
            if not entity_type:
                return None
            # Prefer canonical if present
            return getattr(entity_type, "canonical_uri", None) or entity_type.uri
        except Exception:
            return None

    def _get_fk_predicate_canons(self, dataset_name: str) -> Optional[List[str]]:
        if not self._schema:
            return None
        try:
            schema = self._schema.get_dataset_schema(dataset_name)
            if not schema:
                return None
            fk_canons: List[str] = []
            prop_map: Dict[str, Resource] = schema.get("properties", {})
            for fk in schema.get("fk_relationships", []):
                col = fk.get("source_column")
                if col and col in prop_map:
                    prop_res: Resource = prop_map[col]
                    if getattr(prop_res, "canonical_uri", None):
                        fk_canons.append(prop_res.canonical_uri)  # type: ignore[arg-type]
                    else:
                        fk_canons.append(prop_res.uri)
            return fk_canons or None
        except Exception:
            return None

    def _find_subject_ids_by_class(
        self,
        canonical_type_uri: str,
        *,
        restrict_to_org: Optional[bool] = None,  # None means use default based on self.organization
    ) -> List[str]:
        # ONLY find subjects with canonical URI mapping - no fallbacks
        q = Q(predicate__uri=RDF_TYPE_URI) & Q(object__canonical_uri=canonical_type_uri)

        # Default behavior: restrict to org only if organization is set
        if restrict_to_org is None:
            restrict_to_org = self.organization is not None

        if restrict_to_org and self.organization:
            q &= Q(subject__organization=self.organization)

        # Get ALL subjects with canonical mapping - no limits
        qs = (
            Triple.objects.filter(q)
            .order_by("subject_id")
            .values_list("subject_id", flat=True)
            .distinct()
        )
        return list(qs)

    def _fetch_triples_for_subjects(
        self,
        subject_ids: Sequence[str],
        predicate_canon_whitelist: Optional[Sequence[str]] = None,
    ) -> List[GraphEdge]:
        if not subject_ids:
            return []

        q = Q(subject_id__in=subject_ids)
        if predicate_canon_whitelist:
            # ONLY use canonical URIs - no fallbacks
            q &= Q(predicate__canonical_uri__in=predicate_canon_whitelist)

        triples = (
            Triple.objects.filter(q)
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

        edges: List[GraphEdge] = []
        for t in triples.iterator(chunk_size=2000):
            edges.append(
                GraphEdge(
                    triple_id=str(t.id),
                    subject_id=str(t.subject_id),
                    predicate_uri=t.predicate.uri,
                    predicate_canonical=t.predicate.canonical_uri if hasattr(t.predicate, "canonical_uri") else None,
                    object_id=str(t.object.id),
                    object_uri=t.object.uri if hasattr(t.object, "uri") else None,
                    object_type=t.object.resource_type,
                    object_value=t.object.value if hasattr(t.object, "value") else None,
                    object_canonical=t.object.canonical_uri if hasattr(t.object, "canonical_uri") else None,
                )
            )
        return edges

    def _collect_nodes_from_edges(self, edges: Iterable[GraphEdge]) -> Dict[str, Dict[str, Any]]:
        node_ids = {e.subject_id for e in edges} | {e.object_id for e in edges}
        if not node_ids:
            return {}
        resources = (
            Resource.objects.filter(id__in=list(node_ids))
            .only("id", "uri", "name", "value", "resource_type", "canonical_uri", "organization")
            .select_related("organization")
        )
        result: Dict[str, Dict[str, Any]] = {}
        for r in resources:
            result[str(r.id)] = {
                "id": str(r.id),
                "uri": r.uri,
                "name": r.name,
                "value": r.value,
                "resource_type": r.resource_type,
                "canonical_uri": r.canonical_uri,
                "organization": getattr(r.organization, "code", None),
            }
        return result

    def _resolve_resource_by_uri(self, uri: str, restrict_to_org: bool = True) -> Optional[Resource]:
        q = Q(uri=uri)
        if restrict_to_org:
            q &= Q(organization=self.organization)
        return Resource.objects.filter(q).only("id", "uri", "organization").first()

    def _fetch_triples_for_objects(
        self,
        object_ids: Sequence[str],
        predicate_canon_whitelist: Optional[Sequence[str]] = None,
    ) -> List[GraphEdge]:
        """Fetch triples where object is in `object_ids` (incoming edges)."""
        if not object_ids:
            return []

        q = Q(object_id__in=object_ids)
        if predicate_canon_whitelist:
            q &= Q(predicate__canonical_uri__in=predicate_canon_whitelist) | Q(
                predicate__uri__in=predicate_canon_whitelist
            )

        triples = (
            Triple.objects.filter(q)
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

        edges: List[GraphEdge] = []
        for t in triples.iterator(chunk_size=2000):
            edges.append(
                GraphEdge(
                    triple_id=str(t.id),
                    subject_id=str(t.subject_id),
                    predicate_uri=t.predicate.uri,
                    predicate_canonical=t.predicate.canonical_uri if hasattr(t.predicate, "canonical_uri") else None,
                    object_id=str(t.object.id),
                    object_uri=t.object.uri if hasattr(t.object, "uri") else None,
                    object_type=t.object.resource_type,
                    object_value=t.object.value if hasattr(t.object, "value") else None,
                    object_canonical=t.object.canonical_uri if hasattr(t.object, "canonical_uri") else None,
                )
            )
        return edges

    def fetch_junction_entities(
        self,
        target_ids: Sequence[str],
        *,
        junction_type_uris: Optional[Sequence[str]] = None,
    ) -> List[GraphEdge]:
        """Find junction entities (Kreuztabelle) pointing TO target entities.

        Junction tables in Arkumu model n-ary relationships like Actor-Event-Role.
        They have edges pointing TO events and FROM actors, plus properties like
        'ist-urheberin' (is copyright holder) and 'rolle' (role).

        This method finds junction entities that point to any of the target_ids,
        then returns ALL edges from those junction entities.

        Args:
            target_ids: Entity IDs to find junctions pointing to (e.g., Event IDs)
            junction_type_uris: Canonical type URIs for junction tables.
                               Defaults to actor-event and actor-actor junctions.

        Returns:
            List of GraphEdges from junction entities (including their properties).
        """
        if not target_ids:
            return []

        # Default junction types
        if junction_type_uris is None:
            junction_type_uris = [
                "http://arkumu.org/data/types/akteurin-ereignis-kreuztabelle",
                "http://arkumu.org/data/types/akteurin-akteurin-kreuztabelle",
            ]

        # Build org filter if organization is set
        org_filter = Q()
        if self.organization:
            org_filter = Q(subject__organization=self.organization)

        # Single optimized query: find junction entities by type that point to targets
        # Using subquery to find subjects of junction type, then filter by target
        junction_type_subjects = (
            Triple.objects.filter(
                Q(predicate__uri=RDF_TYPE_URI)
                & (
                    Q(object__canonical_uri__in=junction_type_uris)
                    | Q(object__uri__in=junction_type_uris)
                )
            )
            .filter(org_filter)
            .values_list("subject_id", flat=True)
        )

        # Find junction entities that point to our targets
        junction_ids = set(
            Triple.objects.filter(
                subject_id__in=junction_type_subjects,
                object_id__in=list(target_ids),
            )
            .values_list("subject_id", flat=True)
            .distinct()
        )

        if not junction_ids:
            return []

        # Fetch ALL edges from junction entities
        return self._fetch_triples_for_subjects(list(junction_ids), None)
