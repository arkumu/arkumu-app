"""Efficient graph traversal for project data.

Uses relationship_contexts from mapping to traverse junction tables.
Produces both canonical and institutional graphs.
"""

from __future__ import annotations

import logging
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Dict, Iterator, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

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


def _get_second_degree_neighbors(
    org_codes: Set[str],
    neighbor_triples: List,
    neighbor_ids: Set[uuid.UUID]
) -> Set[uuid.UUID]:
    """Get second-degree neighbors based on schema FK relationships.

    Returns IDs of entities that neighbors link to via FK predicates defined in schema.
    E.g., information carriers linked from events.
    """
    second_degree_ids = set()

    # Get FK predicates for each neighbor entity type from schema
    neighbor_fk_predicates = set()

    for org_code in org_codes:
        try:
            mapping = Mapping.get_active_for_organization(org_code)
            if not mapping:
                continue

            schema = mapping.mapping_config.get('schema_manifest', {})
            for ds_config in schema.values():
                fk_rels = ds_config.get('fk_relationships', [])
                for fk in fk_rels:
                    source_uri = fk.get('source_property_uri')
                    if source_uri:
                        neighbor_fk_predicates.add(source_uri)
        except Exception:
            continue

    if not neighbor_fk_predicates:
        return second_degree_ids

    # Find objects that neighbors link to via these FK predicates
    for triple in neighbor_triples:
        if triple.subject_id in neighbor_ids:
            # Triple objects from ORM have .predicate.uri, not .predicate_uri
            pred_uri = triple.predicate.uri if triple.predicate else None
            if pred_uri in neighbor_fk_predicates and triple.object_id:
                # Exclude entities already in neighbor set
                if triple.object_id not in neighbor_ids:
                    second_degree_ids.add(triple.object_id)

    return second_degree_ids


def _get_junction_config(org_code: str) -> Dict:
    """Extract junction FK predicates from relationship_contexts.

    Returns:
        {
            'fk_predicates': set of predicate URIs that link junctions to main entities,
            'event_fk_predicates': set of predicate URIs that specifically link to events,
        }
    """
    mapping = Mapping.get_active_for_organization(org_code)
    if not mapping:
        return {'fk_predicates': set(), 'event_fk_predicates': set()}

    config = mapping.mapping_config
    schema = config.get('schema_manifest', {})

    fk_predicates = set()
    event_fk_predicates = set()

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

                # Check if this FK links to an event entity (Ereignis)
                target_dataset = rel.get('target_dataset', '').lower()
                if 'ereignis' in target_dataset or 'event' in target_dataset:
                    event_fk_predicates.add(pred_uri)

    return {
        'fk_predicates': fk_predicates,
        'event_fk_predicates': event_fk_predicates,
    }


def get_project_graphs(project_id: str, org_code: str) -> Optional[ProjectGraphs]:
    """Get both canonical and institutional graphs for a project.

    Delegates to _fetch_graphs_for_batch() for single project.
    """
    project_uuid = _as_uuid(project_id)
    if not project_uuid:
        return None

    try:
        project_resource = Resource.objects.only('id', 'uri').get(id=project_uuid)
    except Resource.DoesNotExist:
        return None

    # Get junction FK predicates from mapping
    junction_config = _get_junction_config(org_code)
    fk_predicates = junction_config.get('fk_predicates', set())

    # Use batch function for single project
    result = _fetch_graphs_for_batch([project_resource], fk_predicates)
    return result.get(project_uuid)


def _fetch_graphs_for_batch(
    project_resources: List[Resource],
    fk_predicates: Set[str],
) -> Dict[uuid.UUID, ProjectGraphs]:
    """Fetch graphs for a batch of projects efficiently.

    Uses 5 bulk queries instead of 5 queries per project.
    """
    if not project_resources:
        return {}

    # Collect FK predicates from ALL organizations in this batch
    # This handles mixed-org batches where different orgs use different junction schemas
    org_codes = {r.organization.code for r in project_resources if r.organization}
    all_fk_predicates = set(fk_predicates)  # Start with passed-in predicates
    event_fk_predicates = set()  # FK predicates that link to events

    for org_code in org_codes:
        org_config = _get_junction_config(org_code)
        org_predicates = org_config.get('fk_predicates', set())
        all_fk_predicates.update(org_predicates)

        # Track which FK predicates link to events (not actors)
        event_predicates = org_config.get('event_fk_predicates', set())
        event_fk_predicates.update(event_predicates)

    # Use combined FK predicates for junction discovery
    fk_predicates = all_fk_predicates

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

    # Query 1b: Incoming links via canonical projekt predicate
    # This catches KHM Grundereignis which links TO project (not FROM project)
    CANONICAL_PROJEKT = 'http://arkumu.org/data/properties/projekt'
    incoming_triples = list(Triple.objects.filter(
        object_id__in=all_project_ids,
        predicate__canonical_uri=CANONICAL_PROJEKT,
    ).select_related('subject', 'predicate', 'object'))

    for t in incoming_triples:
        if t.subject_id and t.object_id:
            neighbor_to_projects[t.subject_id].add(t.object_id)

    all_neighbor_ids = set(neighbor_to_projects.keys())

    # Identify project/oberwerk entities among neighbors - don't expand their graphs
    # This prevents explosion through oberwerk (parent work) relationships
    # where one parent work has hundreds of events shared by siblings
    # Use canonical rdf:type to identify projekt and ereignis entities
    RDF_TYPE_URI = 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type'
    CANONICAL_PROJEKT_TYPE = 'http://arkumu.org/data/types/projekt'
    CANONICAL_EREIGNIS_TYPE = 'http://arkumu.org/data/types/ereignis'

    project_neighbor_ids: Set[uuid.UUID] = set()
    if all_neighbor_ids:
        project_type_triples = Triple.objects.filter(
            subject_id__in=all_neighbor_ids,
            predicate__uri=RDF_TYPE_URI,
            object__canonical_uri=CANONICAL_PROJEKT_TYPE
        ).values_list('subject_id', flat=True)
        project_neighbor_ids = set(project_type_triples)
        if project_neighbor_ids:
            logger.debug(
                "Excluding %d project neighbors from expansion (canonical type)",
                len(project_neighbor_ids)
            )

    # Filter neighbors for expansion (exclude project entities)
    expandable_neighbor_ids = all_neighbor_ids - project_neighbor_ids

    # Query 2: ALL neighbor triples at once (excluding project entities)
    neighbor_triples = []
    if expandable_neighbor_ids:
        neighbor_triples = list(Triple.objects.filter(
            subject_id__in=expandable_neighbor_ids
        ).select_related('subject', 'predicate', 'object'))

        # Filter out triples that link TO project entities (prevents pulling in sibling projects)
        # e.g., event -> projekt links that point to other projects sharing the event
        neighbor_object_ids = {t.object_id for t in neighbor_triples if t.object_id}
        if neighbor_object_ids:
            project_object_triples = Triple.objects.filter(
                subject_id__in=neighbor_object_ids,
                predicate__uri=RDF_TYPE_URI,
                object__canonical_uri=CANONICAL_PROJEKT_TYPE
            ).values_list('subject_id', flat=True)
            project_object_ids = set(project_object_triples)
            if project_object_ids:
                original_count = len(neighbor_triples)
                neighbor_triples = [
                    t for t in neighbor_triples
                    if t.object_id not in project_object_ids or t.object_id in all_project_ids
                ]
                filtered_count = original_count - len(neighbor_triples)
                if filtered_count:
                    logger.debug(
                        "Filtered %d neighbor triples linking to other projects",
                        filtered_count
                    )

    # Query 2b: Fetch second-degree neighbors based on schema FK relationships
    # E.g., information carriers linked from events
    second_degree_neighbor_ids = _get_second_degree_neighbors(
        org_codes, neighbor_triples, expandable_neighbor_ids
    )

    second_degree_triples = []
    if second_degree_neighbor_ids:
        second_degree_triples = list(Triple.objects.filter(
            subject_id__in=second_degree_neighbor_ids
        ).select_related('subject', 'predicate', 'object'))
        logger.debug(
            "Fetched %d second-degree neighbors from schema FK relationships",
            len(second_degree_neighbor_ids)
        )

    # Query 3: Find ALL junctions pointing to neighbors via FK predicates
    # Only look for junctions pointing to expandable neighbors (not project entities)
    junction_triples = []
    if expandable_neighbor_ids and fk_predicates:
        junction_triples = list(Triple.objects.filter(
            predicate__uri__in=fk_predicates,
            object_id__in=expandable_neighbor_ids
        ).select_related('subject', 'predicate', 'object'))

    # Filter out digital object junctions (kreuz-digitaleobjekte-proj) - they bloat RDF
    junction_triples = [
        t for t in junction_triples
        if not (t.subject and t.subject.uri and 'kreuz-digitaleobjekte' in t.subject.uri.lower())
    ]

    # Filter out project and event entities from junction subjects
    # Query 3 finds entities pointing to neighbors via FK - but projects and events also use FK predicates!
    # This causes 553 sibling projects and 1104 events to be treated as "junctions"
    junction_subject_ids = {t.subject_id for t in junction_triples if t.subject_id}
    # Exclude our own projects and direct neighbor events
    junction_subject_ids -= all_project_ids
    junction_subject_ids -= all_neighbor_ids
    if junction_subject_ids:
        # Find project subjects
        project_junction_triples = Triple.objects.filter(
            subject_id__in=junction_subject_ids,
            predicate__uri=RDF_TYPE_URI,
            object__canonical_uri=CANONICAL_PROJEKT_TYPE
        ).values_list('subject_id', flat=True)
        project_junction_ids = set(project_junction_triples)

        # Find event subjects (events that aren't direct neighbors)
        event_junction_triples = Triple.objects.filter(
            subject_id__in=junction_subject_ids,
            predicate__uri=RDF_TYPE_URI,
            object__canonical_uri=CANONICAL_EREIGNIS_TYPE
        ).values_list('subject_id', flat=True)
        event_junction_ids = set(event_junction_triples)

        # Filter out both
        exclude_ids = project_junction_ids | event_junction_ids
        if exclude_ids:
            original_count = len(junction_triples)
            junction_triples = [
                t for t in junction_triples
                if t.subject_id not in exclude_ids
            ]
            filtered_count = original_count - len(junction_triples)
            if filtered_count:
                logger.debug(
                    "Filtered %d junction triples with project/event subjects (%d projects, %d events)",
                    filtered_count, len(project_junction_ids), len(event_junction_ids)
                )

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

        # Filter out triples that link TO sibling projects (prevents oberwerk explosion)
        junction_object_ids = {t.object_id for t in junction_entity_triples if t.object_id}
        # Exclude our own projects from the check
        junction_object_ids -= all_project_ids
        if junction_object_ids:
            sibling_project_triples = Triple.objects.filter(
                subject_id__in=junction_object_ids,
                predicate__uri=RDF_TYPE_URI,
                object__canonical_uri=CANONICAL_PROJEKT_TYPE
            ).values_list('subject_id', flat=True)
            sibling_project_ids = set(sibling_project_triples)
            if sibling_project_ids:
                original_count = len(junction_entity_triples)
                junction_entity_triples = [
                    t for t in junction_entity_triples
                    if t.object_id not in sibling_project_ids
                ]
                filtered_count = original_count - len(junction_entity_triples)
                if filtered_count:
                    logger.debug(
                        "Filtered %d junction triples linking to sibling projects",
                        filtered_count
                    )

        # Filter junction ENTITIES to prevent explosion from shared actors
        # Strategy: Keep junctions only if their event FK links point to neighbors
        # This prevents pulling in junctions for non-neighbor events via shared actors
        # Use FK predicates from schema manifests - works for both canonical and org-specific models

        junction_event_links: Dict[uuid.UUID, Set[uuid.UUID]] = defaultdict(set)
        for t in junction_entity_triples:
            if t.object_id and t.object and t.predicate:
                # Check if this is an event FK predicate (resource link to event)
                pred_uri = t.predicate.uri
                if pred_uri in event_fk_predicates:
                    junction_event_links[t.subject_id].add(t.object_id)

        junctions_to_keep = set()
        for junction_id, event_links in junction_event_links.items():
            # Keep junction if it links to at least ONE neighbor event or project
            # This allows junction→neighbor_event for all org schemas
            allowed_ids = all_neighbor_ids | all_project_ids
            if event_links and event_links & allowed_ids:
                junctions_to_keep.add(junction_id)

        # Debug logging for first batch
        if junctions_to_keep and len(all_project_ids) ==  1:
            logger.debug(
                "Junction filter: keeping %d junctions (link to neighbor events) out of %d total",
                len(junctions_to_keep), len(all_junction_ids)
            )

        # Remove all junctions that are NOT in the keep set
        junctions_to_remove = all_junction_ids - junctions_to_keep

        if junctions_to_remove:
            original_count = len(junction_entity_triples)
            junction_entity_triples = [
                t for t in junction_entity_triples
                if t.subject_id not in junctions_to_remove
            ]
            filtered_count = original_count - len(junction_entity_triples)

            # Also update junction_to_neighbors mapping to remove filtered junctions
            for junction_id in junctions_to_remove:
                junction_to_neighbors.pop(junction_id, None)

            # Update all_junction_ids to reflect filtered set
            all_junction_ids = junctions_to_keep

            if filtered_count:
                logger.debug(
                    "Filtered %d junction entity triples (from %d junction entities linking to non-neighbor events)",
                    filtered_count, len(junctions_to_remove)
                )

    # Collect ALL linked entities from junctions
    all_linked_ids: Set[uuid.UUID] = set()
    for t in junction_entity_triples:
        if t.object_id and t.object_id not in all_neighbor_ids and t.object_id not in all_project_ids:
            all_linked_ids.add(t.object_id)

    # Filter out project entities from linked IDs (e.g., oberwerk entities linked from junctions)
    # This prevents expansion through oberwerk relationships
    if all_linked_ids:
        linked_project_triples = Triple.objects.filter(
            subject_id__in=all_linked_ids,
            predicate__uri=RDF_TYPE_URI,
            object__canonical_uri=CANONICAL_PROJEKT_TYPE
        ).values_list('subject_id', flat=True)
        linked_project_ids_set = set(linked_project_triples)
        if linked_project_ids_set:
            logger.debug(
                "Excluding %d project entities from linked expansion (canonical type)",
                len(linked_project_ids_set)
            )
            all_linked_ids -= linked_project_ids_set

    # Filter out event entities from linked IDs (events that aren't direct neighbors)
    # This prevents pulling in hundreds of events shared through actors
    if all_linked_ids:
        linked_event_triples = Triple.objects.filter(
            subject_id__in=all_linked_ids,
            predicate__uri=RDF_TYPE_URI,
            object__canonical_uri=CANONICAL_EREIGNIS_TYPE
        ).values_list('subject_id', flat=True)
        linked_event_ids_set = set(linked_event_triples)
        if linked_event_ids_set:
            logger.debug(
                "Excluding %d event entities from linked expansion (canonical type)",
                len(linked_event_ids_set)
            )
            all_linked_ids -= linked_event_ids_set

    # Query 5: ALL linked entity triples (excluding project and event entities)
    linked_triples = []
    if all_linked_ids:
        linked_triples = list(Triple.objects.filter(
            subject_id__in=all_linked_ids
        ).select_related('subject', 'predicate', 'object'))

        # Filter out triples that link TO sibling projects
        linked_object_ids = {t.object_id for t in linked_triples if t.object_id}
        linked_object_ids -= all_project_ids  # Exclude our own projects
        if linked_object_ids:
            linked_sibling_triples = Triple.objects.filter(
                subject_id__in=linked_object_ids,
                predicate__uri=RDF_TYPE_URI,
                object__canonical_uri=CANONICAL_PROJEKT_TYPE
            ).values_list('subject_id', flat=True)
            linked_sibling_ids = set(linked_sibling_triples)
            if linked_sibling_ids:
                original_count = len(linked_triples)
                linked_triples = [
                    t for t in linked_triples
                    if t.object_id not in linked_sibling_ids
                ]
                filtered_count = original_count - len(linked_triples)
                if filtered_count:
                    logger.debug(
                        "Filtered %d linked triples linking to sibling projects",
                        filtered_count
                    )

        # Filter out triples that link TO events (not direct neighbors)
        # This prevents actors from pulling in hundreds of shared events
        linked_object_ids = {t.object_id for t in linked_triples if t.object_id}
        linked_object_ids -= all_neighbor_ids  # Keep links to direct neighbor events
        if linked_object_ids:
            linked_event_object_triples = Triple.objects.filter(
                subject_id__in=linked_object_ids,
                predicate__uri=RDF_TYPE_URI,
                object__canonical_uri=CANONICAL_EREIGNIS_TYPE
            ).values_list('subject_id', flat=True)
            linked_event_object_ids = set(linked_event_object_triples)
            if linked_event_object_ids:
                original_count = len(linked_triples)
                linked_triples = [
                    t for t in linked_triples
                    if t.object_id not in linked_event_object_ids
                ]
                filtered_count = original_count - len(linked_triples)
                if filtered_count:
                    logger.debug(
                        "Filtered %d linked triples linking to non-neighbor events",
                        filtered_count
                    )

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

    # Query 5b: Fetch 3rd-degree entities for KHM equipmentart
    # Equipment (19) links to Equipmentart (20) which has wikidata/gnd/aat IDs
    # This is a special case - normally we stop at 2nd degree
    third_degree_ids: Set[uuid.UUID] = set()
    third_degree_triples = []

    # Find equipmentart entities linked from equipment (in linked_triples)
    for t in linked_triples:
        if t.object and t.object.uri and '/20-equipmentart/' in t.object.uri:
            third_degree_ids.add(t.object_id)

    if third_degree_ids:
        third_degree_triples = list(Triple.objects.filter(
            subject_id__in=third_degree_ids
        ).select_related('subject', 'predicate', 'object'))
        logger.debug(
            "Fetched %d 3rd-degree entities (equipmentart) with %d triples",
            len(third_degree_ids), len(third_degree_triples)
        )

    # Build mapping: 3rd-degree entity -> projects (via linked entities)
    third_degree_to_projects: Dict[uuid.UUID, Set[uuid.UUID]] = defaultdict(set)
    for t in linked_triples:
        if t.object_id in third_degree_ids:
            third_degree_to_projects[t.object_id].update(linked_to_projects.get(t.subject_id, set()))

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

    # Assign incoming triples (Grundereignis -> project)
    for t in incoming_triples:
        if t.object_id:
            _add_triple_to_projects(t, {t.object_id})

    # Assign neighbor triples
    for t in neighbor_triples:
        projects = neighbor_to_projects.get(t.subject_id, set())
        _add_triple_to_projects(t, projects)

    # Assign second-degree neighbor triples (e.g., information carriers)
    # These belong to same projects as their parent neighbors
    second_degree_to_projects: Dict[uuid.UUID, Set[uuid.UUID]] = defaultdict(set)
    for t in neighbor_triples:
        if t.subject_id in neighbor_to_projects and t.object_id in second_degree_neighbor_ids:
            second_degree_to_projects[t.object_id].update(neighbor_to_projects[t.subject_id])

    for t in second_degree_triples:
        projects = second_degree_to_projects.get(t.subject_id, set())
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

    # Assign 3rd-degree entity triples (equipmentart)
    for t in third_degree_triples:
        projects = third_degree_to_projects.get(t.subject_id, set())
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

    logger.info("get_all_project_graphs_batched: starting for org=%s", org_code)

    # Get junction FK predicates from mapping (once)
    junction_config = _get_junction_config(org_code)
    fk_predicates = junction_config.get('fk_predicates', set())

    # Find projects via rdf:type triple with canonical projekt type
    logger.info("get_all_project_graphs_batched: finding projects for org=%s...", org_code)
    project_ids = list(
        Triple.objects.filter(
            predicate__uri=RDF_TYPE,
            object__canonical_uri=PROJECT_TYPE_URI,
            subject__organization__code__iexact=org_code,
        ).values_list('subject_id', flat=True).distinct()
    )
    logger.info("get_all_project_graphs_batched: found %d projects for org=%s", len(project_ids), org_code)

    # Get project resources
    project_resources = list(
        Resource.objects.filter(id__in=project_ids).only('id', 'uri')
    )

    total_batches = (len(project_resources) + batch_size - 1) // batch_size

    # Process in batches
    for i in range(0, len(project_resources), batch_size):
        batch_num = i // batch_size + 1
        batch = project_resources[i:i + batch_size]
        logger.info("get_all_project_graphs_batched: processing batch %d/%d (%d projects)", batch_num, total_batches, len(batch))

        # Fetch graphs for this batch (5 queries)
        graphs_map = _fetch_graphs_for_batch(batch, fk_predicates)

        # Yield each project
        for project_id, graphs in graphs_map.items():
            yield str(project_id), graphs
