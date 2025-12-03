"""Efficient graph traversal for project data.

Uses relationship_contexts from mapping to traverse junction tables.
Produces both canonical and institutional graphs.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Dict, Iterator, List, Optional, Set, Tuple

if TYPE_CHECKING:
    from arkumu.projects import ProjectRecord

from arkumu.metadata.models.mappings import Mapping
from arkumu.metadata.models.resource import Resource
from arkumu.metadata.models.triples import Triple

PROJECT_TYPE_URI = "http://arkumu.org/data/types/projekt"


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

    def to_project_record(self, subject_id: str) -> "ProjectRecord":
        """Convert graph to ProjectRecord.

        Args:
            subject_id: The resource ID (UUID) of the project

        Returns:
            Populated ProjectRecord with data extracted from triples
        """
        from arkumu.projects.services.graph_record_builder import build_project_record
        return build_project_record(self, subject_id)

    def to_graph_data(self) -> Dict:
        """Convert to format expected by build_rdf_graph().

        Returns dict with 'nodes' and 'edges' compatible with
        CanonicalGraphService.get_entity_graph() format.
        """
        nodes: Dict[str, Dict] = {}
        edges: List[Dict] = []

        # Build nodes from all unique URIs in triples
        for t in self.triples:
            # Subject node (always an entity)
            if t.subject_uri and t.subject_uri not in nodes:
                nodes[t.subject_uri] = {
                    "uri": t.subject_uri,
                    "resource_type": "ENTITY",
                }

            # Object node
            if t.object_value:
                # Literal node - use value as key
                lit_key = f"_lit_{hash(t.object_value)}"
                if lit_key not in nodes:
                    nodes[lit_key] = {
                        "uri": None,
                        "value": t.object_value,
                        "resource_type": "LITERAL",
                    }
                obj_key = lit_key
            elif t.object_uri:
                # Entity/IRI node
                if t.object_uri not in nodes:
                    nodes[t.object_uri] = {
                        "uri": t.object_uri,
                        "resource_type": "ENTITY",
                    }
                obj_key = t.object_uri
            else:
                continue

            # Build edge
            edges.append({
                "subject_id": t.subject_uri,
                "object_id": obj_key,
                "predicate_uri": t.predicate_uri,
                "predicate_canonical": t.predicate_canonical_uri,
            })

        return {
            "root_uri": self.project_uri,
            "nodes": nodes,
            "edges": edges,
        }


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


def _fetch_graphs_for_batch(
    project_resources: List[Resource],
    fk_predicates: Set[str],
) -> Dict[uuid.UUID, ProjectGraphs]:
    """Fetch graphs for a batch of projects efficiently.

    Uses 5 bulk queries instead of 5 queries per project.
    """
    if not project_resources:
        return {}

    # Map project IDs to URIs
    project_id_to_uri = {r.id: r.uri for r in project_resources}
    all_project_ids = set(project_id_to_uri.keys())

    # Query 1: ALL project triples at once
    project_triples = list(Triple.objects.filter(
        subject_id__in=all_project_ids
    ).select_related('subject', 'predicate', 'object'))

    # Track which neighbors belong to which project
    neighbor_to_projects: Dict[uuid.UUID, Set[uuid.UUID]] = defaultdict(set)
    for t in project_triples:
        if t.object_id:
            neighbor_to_projects[t.object_id].add(t.subject_id)

    all_neighbor_ids = set(neighbor_to_projects.keys())

    # Query 2: ALL neighbor triples at once
    neighbor_triples = []
    if all_neighbor_ids:
        neighbor_triples = list(Triple.objects.filter(
            subject_id__in=all_neighbor_ids
        ).select_related('subject', 'predicate', 'object'))

    # Query 3: Find ALL junctions pointing to neighbors via FK predicates
    junction_triples = []
    if all_neighbor_ids and fk_predicates:
        junction_triples = list(Triple.objects.filter(
            predicate__uri__in=fk_predicates,
            object_id__in=all_neighbor_ids
        ).select_related('subject', 'predicate', 'object'))

    # Track which junctions link to which neighbors (and thus which projects)
    junction_to_neighbors: Dict[uuid.UUID, Set[uuid.UUID]] = defaultdict(set)
    for t in junction_triples:
        if t.object_id:
            junction_to_neighbors[t.subject_id].add(t.object_id)

    all_junction_ids = set(junction_to_neighbors.keys())

    # Query 4: ALL junction entity triples
    junction_entity_triples = []
    if all_junction_ids:
        junction_entity_triples = list(Triple.objects.filter(
            subject_id__in=all_junction_ids
        ).select_related('subject', 'predicate', 'object'))

    # Collect ALL linked entities from junctions
    all_linked_ids: Set[uuid.UUID] = set()
    for t in junction_entity_triples:
        if t.object_id and t.object_id not in all_neighbor_ids and t.object_id not in all_project_ids:
            all_linked_ids.add(t.object_id)

    # Query 5: ALL linked entity triples
    linked_triples = []
    if all_linked_ids:
        linked_triples = list(Triple.objects.filter(
            subject_id__in=all_linked_ids
        ).select_related('subject', 'predicate', 'object'))

    # Now assign triples to projects
    # A triple belongs to a project if:
    # - subject is the project itself
    # - subject is a neighbor of the project
    # - subject is a junction pointing to a neighbor of the project
    # - subject is linked from a junction of the project

    def _get_projects_for_subject(subject_id: uuid.UUID) -> Set[uuid.UUID]:
        """Determine which projects a subject belongs to."""
        projects = set()

        # Direct project triple
        if subject_id in all_project_ids:
            projects.add(subject_id)

        # Neighbor of project(s)
        if subject_id in neighbor_to_projects:
            projects.update(neighbor_to_projects[subject_id])

        # Junction pointing to neighbor(s)
        if subject_id in junction_to_neighbors:
            for neighbor_id in junction_to_neighbors[subject_id]:
                if neighbor_id in neighbor_to_projects:
                    projects.update(neighbor_to_projects[neighbor_id])

        return projects

    # Build reverse mapping: linked entity -> junctions -> neighbors -> projects
    linked_to_projects: Dict[uuid.UUID, Set[uuid.UUID]] = defaultdict(set)
    for t in junction_entity_triples:
        if t.object_id in all_linked_ids:
            junction_id = t.subject_id
            for neighbor_id in junction_to_neighbors.get(junction_id, set()):
                linked_to_projects[t.object_id].update(neighbor_to_projects.get(neighbor_id, set()))

    # Group all triples by project
    triples_by_project: Dict[uuid.UUID, List[Triple]] = defaultdict(list)
    seen_by_project: Dict[uuid.UUID, Set[Tuple]] = defaultdict(set)

    def _add_triple_to_projects(t: Triple, project_ids: Set[uuid.UUID]):
        for pid in project_ids:
            key = (t.subject_id, t.predicate_id, t.object_id)
            if key not in seen_by_project[pid]:
                seen_by_project[pid].add(key)
                triples_by_project[pid].append(t)

    # Assign project triples
    for t in project_triples:
        _add_triple_to_projects(t, {t.subject_id})

    # Assign neighbor triples
    for t in neighbor_triples:
        projects = neighbor_to_projects.get(t.subject_id, set())
        _add_triple_to_projects(t, projects)

    # Assign junction triples
    for t in junction_triples:
        projects = _get_projects_for_subject(t.subject_id)
        _add_triple_to_projects(t, projects)

    # Assign junction entity triples
    for t in junction_entity_triples:
        projects = _get_projects_for_subject(t.subject_id)
        _add_triple_to_projects(t, projects)

    # Assign linked entity triples
    for t in linked_triples:
        projects = linked_to_projects.get(t.subject_id, set())
        _add_triple_to_projects(t, projects)

    # Build ProjectGraphs for each project
    result: Dict[uuid.UUID, ProjectGraphs] = {}
    for project_id, triples in triples_by_project.items():
        triple_results = []
        for t in triples:
            triple_results.append(TripleResult(
                subject_uri=t.subject.uri if t.subject else '',
                predicate_uri=t.predicate.uri if t.predicate else '',
                predicate_canonical_uri=t.predicate.canonical_uri if t.predicate else None,
                object_uri=t.object.uri if t.object and not t.object.value else None,
                object_value=t.object.value if t.object else None,
            ))

        result[project_id] = ProjectGraphs(
            project_uri=project_id_to_uri[project_id],
            triples=triple_results,
        )

    return result


def get_all_project_graphs_batched(
    org_code: str,
    batch_size: int = 100,
) -> Iterator[Tuple[str, ProjectGraphs]]:
    """Yield (project_id, ProjectGraphs) for all projects in an org.

    Processes in batches to control memory usage.

    For 3000 projects with batch_size=100:
    - 30 batches x 5 queries = 150 queries (vs 15000 for per-project)
    - Only ~100 projects worth of triples in memory at a time

    Args:
        org_code: Organization code (e.g., 'fuk', 'hmt', 'khm')
        batch_size: Number of projects per batch (default 100)

    Yields:
        (project_id, ProjectGraphs) tuples
    """
    from arkumu.metadata.models.triples import Triple

    RDF_TYPE = 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type'

    # Get junction FK predicates from mapping (once)
    junction_config = _get_junction_config(org_code)
    fk_predicates = junction_config.get('fk_predicates', set())

    # Find projects via rdf:type triple with canonical projekt type
    project_ids = list(
        Triple.objects.filter(
            predicate__uri=RDF_TYPE,
            object__canonical_uri=PROJECT_TYPE_URI,
            subject__organization__code__iexact=org_code,
        ).values_list('subject_id', flat=True).distinct()
    )

    # Get project resources
    project_resources = list(
        Resource.objects.filter(id__in=project_ids).only('id', 'uri')
    )

    # Process in batches
    for i in range(0, len(project_resources), batch_size):
        batch = project_resources[i:i + batch_size]

        # Fetch graphs for this batch (5 queries)
        graphs_map = _fetch_graphs_for_batch(batch, fk_predicates)

        # Yield each project
        for project_id, graphs in graphs_map.items():
            yield str(project_id), graphs
