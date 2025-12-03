"""Efficient graph traversal for project data.

Uses relationship_contexts from mapping to traverse junction tables.
Produces both canonical and institutional graphs.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

from arkumu.metadata.models.mappings import Mapping
from arkumu.metadata.models.resource import Resource
from arkumu.metadata.models.triples import Triple


@dataclass
class TripleResult:
    """A triple with both institutional and canonical URIs."""
    subject_uri: str
    predicate_uri: str  # institutional
    predicate_canonical_uri: Optional[str]  # canonical
    object_uri: Optional[str]
    object_value: Optional[str]


@dataclass
class ProjectGraphs:
    """Both canonical and institutional graphs for a project."""
    project_uri: str
    triples: List[TripleResult] = field(default_factory=list)

    def get_canonical_triples(self) -> List[Tuple[str, str, str]]:
        """Get triples using canonical URIs."""
        result = []
        for t in self.triples:
            pred = t.predicate_canonical_uri or t.predicate_uri
            obj = t.object_value or t.object_uri
            if obj:
                result.append((t.subject_uri, pred, obj))
        return result

    def get_institutional_triples(self) -> List[Tuple[str, str, str]]:
        """Get triples using institutional URIs."""
        result = []
        for t in self.triples:
            obj = t.object_value or t.object_uri
            if obj:
                result.append((t.subject_uri, t.predicate_uri, obj))
        return result


def _as_uuid(value: str) -> Optional[uuid.UUID]:
    """Convert string to UUID."""
    if not value:
        return None
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (ValueError, AttributeError):
        return None


def _get_junction_config(org_code: str) -> Dict:
    """Extract junction FK predicates from relationship_contexts.

    Returns:
        {
            'fk_predicates': set of predicate URIs that link junctions to main entities,
        }
    """
    mapping = Mapping.get_active_for_organization(org_code)
    if not mapping:
        return {'fk_predicates': set()}

    config = mapping.mapping_config
    schema = config.get('schema_manifest', {})

    fk_predicates = set()

    for ds_name, ds_config in schema.items():
        rel_contexts = ds_config.get('relationship_contexts', [])
        if not rel_contexts:
            continue

        # This dataset has relationship_contexts = it's a junction
        # Get its FK predicates (how it links to other entities)
        fk_rels = ds_config.get('fk_relationships', [])
        for rel in fk_rels:
            pred_uri = rel.get('source_property_uri', '')
            if pred_uri:
                fk_predicates.add(pred_uri)

    return {'fk_predicates': fk_predicates}


def get_project_graphs(project_id: str, org_code: str) -> Optional[ProjectGraphs]:
    """Get both canonical and institutional graphs for a project.

    Traversal:
    1. Project triples
    2. Neighbor triples (events, etc.)
    3. Junction triples (using FK predicates from relationship_contexts)
    4. Junction entity properties (roles, rights)
    5. Linked entity properties (actors, roles)
    """
    project_uuid = _as_uuid(project_id)
    if not project_uuid:
        return None

    try:
        project_resource = Resource.objects.get(id=project_uuid)
    except Resource.DoesNotExist:
        return None

    # Get junction FK predicates from mapping
    junction_config = _get_junction_config(org_code)
    fk_predicates = junction_config.get('fk_predicates', set())

    # Query 1: Project's direct triples
    project_triples = list(Triple.objects.filter(
        subject_id=project_uuid
    ).select_related('subject', 'predicate', 'object'))

    neighbor_ids = {t.object_id for t in project_triples if t.object_id}

    # Query 2: Neighbor triples (events, etc.)
    neighbor_triples = []
    if neighbor_ids:
        neighbor_triples = list(Triple.objects.filter(
            subject_id__in=neighbor_ids
        ).select_related('subject', 'predicate', 'object'))

    # Query 3: Find junctions pointing to neighbors via FK predicates
    junction_triples = []
    if neighbor_ids and fk_predicates:
        junction_triples = list(Triple.objects.filter(
            predicate__uri__in=fk_predicates,
            object_id__in=neighbor_ids
        ).select_related('subject', 'predicate', 'object'))

    junction_ids = {t.subject_id for t in junction_triples}

    # Query 4: Junction entity triples (roles, rights, other FKs)
    junction_entity_triples = []
    if junction_ids:
        junction_entity_triples = list(Triple.objects.filter(
            subject_id__in=junction_ids
        ).select_related('subject', 'predicate', 'object'))

    # Collect entities linked from junctions (actors, roles)
    linked_ids = set()
    for t in junction_entity_triples:
        if t.object_id and t.object_id not in neighbor_ids and t.object_id != project_uuid:
            linked_ids.add(t.object_id)

    # Query 5: Linked entity triples (actor names, role names)
    linked_triples = []
    if linked_ids:
        linked_triples = list(Triple.objects.filter(
            subject_id__in=linked_ids
        ).select_related('subject', 'predicate', 'object'))

    # Combine and dedupe
    all_triples = (
        project_triples +
        neighbor_triples +
        junction_triples +
        junction_entity_triples +
        linked_triples
    )

    triple_results = []
    seen = set()
    for t in all_triples:
        key = (t.subject_id, t.predicate_id, t.object_id)
        if key in seen:
            continue
        seen.add(key)

        triple_results.append(TripleResult(
            subject_uri=t.subject.uri if t.subject else '',
            predicate_uri=t.predicate.uri if t.predicate else '',
            predicate_canonical_uri=t.predicate.canonical_uri if t.predicate else None,
            object_uri=t.object.uri if t.object and not t.object.value else None,
            object_value=t.object.value if t.object else None,
        ))

    return ProjectGraphs(
        project_uri=project_resource.uri,
        triples=triple_results,
    )
