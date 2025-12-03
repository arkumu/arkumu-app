from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from django.db.models import Q

from arkumu.metadata.models.resource import Resource, ResourceType
from arkumu.metadata.models.triples import Triple
from arkumu.users.models import Organization

logger = logging.getLogger(__name__)

RDF_TYPE_URI = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"


@dataclass
class FKRelationship:
    """A foreign key relationship from the manifest."""

    source_dataset: str
    target_dataset: str
    source_predicate_uri: str
    target_predicate_uri: str


@dataclass
class DatasetSchema:
    """Schema info for a dataset from the manifest."""

    name: str
    entity_type_uri: str
    canonical_type_uri: str
    fk_relationships: List[FKRelationship] = field(default_factory=list)
    property_uris: Set[str] = field(default_factory=set)


class ManifestGraphTraverser:
    """Traverses entity graphs using the schema manifest for efficient queries.

    Uses institutional predicate URIs directly from the manifest to avoid
    canonical_uri lookups. The manifest defines:
    - Entity types per dataset (institutional + canonical URIs)
    - FK relationships between datasets (predicate URIs for traversal)
    - Properties per dataset (institutional predicate URIs)
    """

    def __init__(self, org_code: str) -> None:
        self.org_code = org_code
        self._manifest: Optional[Dict[str, Any]] = None
        self._datasets: Dict[str, DatasetSchema] = {}
        self._type_to_dataset: Dict[str, str] = {}  # entity_type_uri -> dataset_name
        self._inbound_fks: Dict[str, List[FKRelationship]] = {}  # target_dataset -> FKs pointing to it

    def _load_manifest(self) -> Dict[str, Any]:
        """Load and parse the schema manifest."""
        if self._manifest is not None:
            return self._manifest

        from arkumu.metadata.models.mappings import Mapping

        mapping = Mapping.get_active_for_organization(self.org_code)
        if mapping and mapping.mapping_config:
            self._manifest = mapping.mapping_config.get("schema_manifest", {}) or {}
        else:
            self._manifest = {}

        self._parse_manifest()
        return self._manifest

    def _parse_manifest(self) -> None:
        """Parse manifest into structured lookup tables."""
        if not self._manifest:
            return

        for ds_name, ds_data in self._manifest.items():
            entity_type = ds_data.get("entity_type", {})
            entity_uri = entity_type.get("uri", "")
            canonical_uri = entity_type.get("canonical_uri", "")

            if not entity_uri:
                continue

            # Build dataset schema
            schema = DatasetSchema(
                name=ds_name,
                entity_type_uri=entity_uri,
                canonical_type_uri=canonical_uri,
            )

            # Parse FK relationships
            for fk in ds_data.get("fk_relationships", []):
                rel = FKRelationship(
                    source_dataset=ds_name,
                    target_dataset=fk.get("target_dataset", ""),
                    source_predicate_uri=fk.get("source_property_uri", ""),
                    target_predicate_uri=fk.get("target_property_uri", ""),
                )
                if rel.target_dataset and rel.source_predicate_uri:
                    schema.fk_relationships.append(rel)

                    # Index inbound FKs for reverse lookups
                    self._inbound_fks.setdefault(rel.target_dataset, []).append(rel)

            # Collect property URIs
            for prop_data in ds_data.get("properties", {}).values():
                prop_uri = prop_data.get("uri", "")
                if prop_uri:
                    schema.property_uris.add(prop_uri)

            self._datasets[ds_name] = schema
            self._type_to_dataset[entity_uri] = ds_name

    def get_dataset_for_type(self, entity_type_uri: str) -> Optional[DatasetSchema]:
        """Get dataset schema for an entity type URI."""
        self._load_manifest()
        ds_name = self._type_to_dataset.get(entity_type_uri)
        return self._datasets.get(ds_name) if ds_name else None

    def get_inbound_relationships(self, dataset_name: str) -> List[FKRelationship]:
        """Get FK relationships pointing TO this dataset."""
        self._load_manifest()
        return self._inbound_fks.get(dataset_name, [])

    def get_fk_predicate_uris(self, dataset_name: str) -> Set[str]:
        """Get all FK predicate URIs for a dataset (for traversal)."""
        self._load_manifest()
        schema = self._datasets.get(dataset_name)
        if not schema:
            return set()
        return {fk.source_predicate_uri for fk in schema.fk_relationships}

    def get_all_datasets(self) -> Dict[str, DatasetSchema]:
        """Get all parsed dataset schemas."""
        self._load_manifest()
        return self._datasets

    def get_junction_datasets(self) -> Dict[str, DatasetSchema]:
        """Get datasets that act as junctions (have 2+ FK relationships).

        Junction datasets connect multiple entities (e.g., Actor-Event-Role).
        They typically have 2 or more FK relationships pointing to different
        target datasets.
        """
        self._load_manifest()
        return {
            name: schema
            for name, schema in self._datasets.items()
            if len(schema.fk_relationships) >= 2
        }

    def get_junction_fk_predicates(self) -> Set[str]:
        """Get FK predicate URIs from junction datasets only."""
        junction_datasets = self.get_junction_datasets()
        predicates: Set[str] = set()
        for schema in junction_datasets.values():
            for fk in schema.fk_relationships:
                if fk.source_predicate_uri:
                    predicates.add(fk.source_predicate_uri)
        return predicates


class InstitutionalGraphService:
    """Build org-scoped graphs using archive-native predicates."""

    def __init__(self, org_code: Optional[str] = None) -> None:
        self.org_code = org_code
        self.organization = (
            Organization.objects.get(code=org_code) if org_code else None
        )
        self._traverser: Optional[ManifestGraphTraverser] = None

    def _get_traverser(self) -> ManifestGraphTraverser:
        """Get or create the manifest traverser."""
        if self._traverser is None and self.org_code:
            self._traverser = ManifestGraphTraverser(self.org_code)
        return self._traverser

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

    def fetch_junction_entities(
        self,
        target_ids: Sequence[str],
        target_dataset: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Find junction entities pointing TO target entities using manifest.

        Uses the schema manifest to identify junction datasets and their FK
        predicates, then queries using institutional URIs directly (no
        canonical_uri lookups).

        Args:
            target_ids: Entity IDs to find junctions pointing to (e.g., Event IDs)
            target_dataset: Optional dataset name of target entities. If provided,
                           only looks for junctions that have FKs to this dataset.

        Returns:
            List of edge dicts from junction entities (with native predicate_uri).
        """
        if not target_ids:
            return []

        traverser = self._get_traverser()
        if not traverser:
            logger.warning("No manifest traverser available for org %s", self.org_code)
            return []

        # Get all datasets and find which ones have FKs pointing to our target
        datasets = traverser.get_all_datasets()
        if not datasets:
            logger.debug("No datasets in manifest for org %s", self.org_code)
            return []

        # Collect FK predicate URIs that point to the target dataset
        fk_predicate_uris: Set[str] = set()

        if target_dataset:
            # Only look at FKs pointing to the specific target dataset
            inbound_fks = traverser.get_inbound_relationships(target_dataset)
            for fk in inbound_fks:
                if fk.source_predicate_uri:
                    fk_predicate_uris.add(fk.source_predicate_uri)
        else:
            # Look at all FK relationships
            for schema in datasets.values():
                for fk in schema.fk_relationships:
                    if fk.source_predicate_uri:
                        fk_predicate_uris.add(fk.source_predicate_uri)

        if not fk_predicate_uris:
            logger.debug("No FK predicates found in manifest for target %s", target_dataset)
            return []

        # Find entities that have FK predicates pointing to our targets
        # This is the key query - using institutional predicate URIs directly
        junction_ids = list(
            Triple.objects.filter(
                self._triple_filter(),
                predicate__uri__in=fk_predicate_uris,
                object_id__in=list(target_ids),
            )
            .values_list("subject_id", flat=True)
            .distinct()
        )

        if not junction_ids:
            return []

        # Fetch all edges from junction entities
        return self._fetch_triples_for_subjects(junction_ids)
