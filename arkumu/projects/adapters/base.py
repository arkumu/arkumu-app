"""Base class for institution-specific adapters."""

from __future__ import annotations

import logging
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from django.db.models import Q

logger = logging.getLogger(__name__)


@dataclass
class ActorData:
    """Actor data extracted from junction entities."""
    actor_id: str
    actor_name: str
    event_id: Optional[str]
    roles: List[str]
    is_copyright_holder: bool
    is_neighbouring_rights_holder: bool


@dataclass
class EventData:
    """Event data with associated actors."""
    event_id: str
    event_uri: Optional[str]
    name: Optional[str]
    description: Optional[str]
    location: Optional[str]
    start: Optional[str]
    end: Optional[str]
    event_type: Optional[str] = None
    actors: List[ActorData] = field(default_factory=list)


@dataclass
class DigitalObjectData:
    """Digital object data."""
    object_id: str
    object_uri: Optional[str]
    path: Optional[str]
    file_name: Optional[str] = None
    content_type: Optional[str] = None
    license_uri: Optional[str] = None
    license_label: Optional[str] = None
    source_event_ids: List[str] = field(default_factory=list)


@dataclass
class ProjectPropertiesData:
    """Core project properties."""
    title: Optional[str] = None
    subtitle: Optional[str] = None
    description: Optional[str] = None
    image: Optional[str] = None
    institution_uri: Optional[str] = None
    institution_label: Optional[str] = None
    category_uris: List[str] = field(default_factory=list)
    category_labels: List[str] = field(default_factory=list)


@dataclass
class TripleData:
    """A single triple with both institutional and canonical URIs."""
    subject_uri: str
    predicate_uri: str  # Institutional URI
    predicate_canonical: Optional[str]  # Canonical URI (if different)
    object_uri: Optional[str]  # For entity objects
    object_value: Optional[str]  # For literal objects
    object_is_literal: bool = False


@dataclass
class ProjectGraph:
    """Complete project graph data for RDF serialization."""
    project_uri: str
    properties: ProjectPropertiesData
    events: List[EventData]
    actors: List[ActorData]
    digital_objects: List[DigitalObjectData]
    triples: List[TripleData] = field(default_factory=list)

    def get_canonical_triples(self) -> List[TripleData]:
        """Return triples with canonical predicates."""
        result = []
        for t in self.triples:
            if t.predicate_canonical:
                result.append(TripleData(
                    subject_uri=t.subject_uri,
                    predicate_uri=t.predicate_canonical,
                    predicate_canonical=t.predicate_canonical,
                    object_uri=t.object_uri,
                    object_value=t.object_value,
                    object_is_literal=t.object_is_literal,
                ))
            else:
                result.append(t)
        return result

    def get_institutional_triples(self) -> List[TripleData]:
        """Return triples with institutional predicates."""
        return list(self.triples)


# Common canonical URIs from database mappings
class CanonicalURIs:
    """Canonical predicate URIs used across institutions.

    These URIs match the canonical_uri field in the database Predicate/Resource model.
    """
    # Project properties
    TITLE = "http://arkumu.org/data/properties/bevorzugter-titel"
    SUBTITLE = "http://arkumu.org/data/properties/bevorzugter-untertitel"
    DESCRIPTION = "http://arkumu.org/data/properties/beschreibung"
    DESCRIPTION_DE = "http://arkumu.org/data/properties/deutsche-beschreibung"
    IMAGE = "http://arkumu.org/data/properties/vorschaubild"
    INSTITUTION = "http://arkumu.org/data/properties/einliefernde-hochschule"
    CATEGORY = "http://arkumu.org/data/properties/projektkategorie"
    PROJECT_TYPE = "http://arkumu.org/data/properties/projektart"

    # Project -> Event link
    EVENT = "http://arkumu.org/data/properties/ereignis"

    # Junction predicates
    IM_EREIGNIS = "http://arkumu.org/data/properties/im-ereignis"
    PROJEKT = "http://arkumu.org/data/properties/projekt"

    # Event properties
    EVENT_NAME = "http://arkumu.org/data/properties/ereignisname"
    EVENT_START = "http://arkumu.org/data/properties/ereignisbeginn"
    EVENT_END = "http://arkumu.org/data/properties/ereignisende"
    EVENT_LOCATION = "http://arkumu.org/data/properties/ereignisort"
    EVENT_DESCRIPTION = "http://arkumu.org/data/properties/ereignisbeschreibung"
    EVENT_TYPE = "http://arkumu.org/data/properties/ereignistyp"

    # Actor predicates
    ACTOR_LINK = "http://arkumu.org/data/properties/akteurin-im-ereignis"
    ROLE_LINK = "http://arkumu.org/data/properties/rollen-der-akteurin-im-ereignis"
    ACTOR_NAME = "http://arkumu.org/data/properties/deutscher-name"
    ROLE_NAME = "http://arkumu.org/data/properties/deutscher-name-der-rolle-breadcrumb"

    # Rights predicates
    IST_URHEBERIN = "http://arkumu.org/data/properties/ist-urheberin"
    LEISTUNGSSCHUTZRECHTE = "http://arkumu.org/data/properties/besitzt-leistungsschutzrechte"

    # Digital object predicates
    DIGITAL_OBJECT = "http://arkumu.org/data/properties/digitales-objekt"
    FILE_PATH = "http://arkumu.org/data/properties/dateipfad"
    FILE_NAME = "http://arkumu.org/data/properties/dateiname"
    LICENSE = "http://arkumu.org/data/properties/deutscher-name-der-lizenz"

    # Institution/Category name predicates
    INSTITUTION_NAME = "http://arkumu.org/data/properties/deutscher-name-der-einliefernden-hochschule"
    CATEGORY_NAME = "http://arkumu.org/data/properties/deutscher-name-der-projektkategorie-breadcrumb"


def _as_uuid(val: Any) -> Optional[uuid.UUID]:
    """Convert value to UUID if possible."""
    if val is None:
        return None
    if isinstance(val, uuid.UUID):
        return val
    try:
        return uuid.UUID(str(val))
    except (ValueError, TypeError):
        return None


def _is_truthy(value: Any) -> bool:
    """Check if a value is truthy (1, true, yes, ja)."""
    if value is None:
        return False
    token = str(value).strip().lower()
    return token in {"1", "true", "yes", "ja"}


class InstitutionAdapter(ABC):
    """Base class for institution-specific data adapters.

    Subclasses implement institution-specific logic for:
    - Finding junction entities (actor-event relationships)
    - Mapping predicates (when canonical URIs are missing)
    - Building event/actor data structures
    """

    # Override in subclasses
    ORG_CODE: str = ""

    # Junction predicate for this institution
    JUNCTION_PREDICATE: str = CanonicalURIs.IM_EREIGNIS

    # Predicate mappings for institutions lacking canonical URIs
    # Format: {local_predicate_suffix: canonical_uri}
    PREDICATE_CANONICAL_MAP: Dict[str, str] = {}

    def __init__(self, org_code: Optional[str] = None):
        self.org_code = (org_code or self.ORG_CODE).strip().lower()

    def get_actors_for_project(
        self,
        project_id: str,
        event_ids: Optional[Sequence[str]] = None,
    ) -> List[ActorData]:
        """Get all actors with rights data for a project.

        Args:
            project_id: The project's resource ID (UUID string).
            event_ids: Optional list of event IDs. If not provided, will be fetched.

        Returns:
            List of ActorData with actor info and rights flags.
        """
        project_uuid = _as_uuid(project_id)
        if not project_uuid:
            return []

        # Get event IDs if not provided
        if event_ids is None:
            event_ids = self._get_event_ids_for_project(project_uuid)

        # Find junctions and process them
        junction_ids, junction_event_map = self._find_junctions(project_uuid, event_ids)
        if not junction_ids:
            return []

        return self._process_junctions(junction_ids, junction_event_map, project_uuid)

    def _get_event_ids_for_project(self, project_uuid: uuid.UUID) -> List[str]:
        """Get event IDs linked to a project."""
        from arkumu.metadata.models.triples import Triple

        event_triples = Triple.objects.filter(
            Q(predicate__canonical_uri=CanonicalURIs.EVENT)
            | Q(predicate__uri__icontains="ereignis"),
            subject_id=project_uuid,
        ).values_list("object_id", flat=True)

        return [str(eid) for eid in event_triples if eid]

    @abstractmethod
    def _find_junctions(
        self,
        project_uuid: uuid.UUID,
        event_ids: Optional[Sequence[str]],
    ) -> tuple[Set[uuid.UUID], Dict[uuid.UUID, uuid.UUID]]:
        """Find junction entities for this institution's pattern.

        Returns:
            Tuple of (junction_ids, junction_event_map).
            junction_event_map maps junction_id -> event_id (may be empty for KHM).
        """
        ...

    def normalize_predicate(self, predicate_uri: str) -> str:
        """Map an institutional predicate URI to its canonical form.

        Override in subclasses that have non-canonical predicates.
        """
        if not predicate_uri:
            return predicate_uri

        for suffix, canonical in self.PREDICATE_CANONICAL_MAP.items():
            if predicate_uri.endswith(suffix):
                return canonical

        return predicate_uri

    def _process_junctions(
        self,
        junction_ids: Set[uuid.UUID],
        junction_event_map: Dict[uuid.UUID, uuid.UUID],
        project_uuid: uuid.UUID,
    ) -> List[ActorData]:
        """Process junction entities to extract actor/rights data."""
        from arkumu.metadata.models.triples import Triple
        from arkumu.metadata.models.resource import ResourceType

        if not junction_ids:
            return []

        # Fetch all triples for junctions
        junction_triples = Triple.objects.filter(
            subject_id__in=junction_ids,
        ).select_related("predicate", "object")

        # Build junction data
        junction_data: Dict[uuid.UUID, Dict[str, Any]] = {}
        for t in junction_triples:
            jid = t.subject_id
            if jid not in junction_data:
                junction_data[jid] = {
                    "actor_id": None,
                    "role_ids": set(),
                    "is_copyright_holder": False,
                    "is_neighbouring_rights_holder": False,
                }

            # Get predicate - use canonical if available, then try to normalize
            pred_raw = t.predicate.canonical_uri or t.predicate.uri or ""
            pred = self.normalize_predicate(pred_raw)

            # Actor link
            if pred == CanonicalURIs.ACTOR_LINK or pred.endswith("/akteurin-im-ereignis"):
                if t.object and t.object.resource_type != ResourceType.LITERAL:
                    junction_data[jid]["actor_id"] = t.object_id

            # Role link
            elif pred == CanonicalURIs.ROLE_LINK or "rollen-der-akteurin" in pred:
                if t.object and t.object.resource_type != ResourceType.LITERAL:
                    junction_data[jid]["role_ids"].add(t.object_id)

            # Copyright holder
            elif pred == CanonicalURIs.IST_URHEBERIN or "ist-urheberin" in pred_raw:
                val = getattr(t.object, "value", None)
                junction_data[jid]["is_copyright_holder"] = _is_truthy(val)

            # Neighbouring rights
            elif pred == CanonicalURIs.LEISTUNGSSCHUTZRECHTE or "leistungsschutz" in pred_raw:
                val = getattr(t.object, "value", None)
                junction_data[jid]["is_neighbouring_rights_holder"] = _is_truthy(val)

        # Fetch actor names
        actor_ids = {d["actor_id"] for d in junction_data.values() if d["actor_id"]}
        actor_names = self._fetch_actor_names(actor_ids)

        # Fetch role names
        all_role_ids: Set[uuid.UUID] = set()
        for data in junction_data.values():
            all_role_ids.update(data["role_ids"])
        role_names = self._fetch_role_names(all_role_ids)

        # Build results
        results: List[ActorData] = []
        for junction_id, data in junction_data.items():
            actor_id = data["actor_id"]
            if not actor_id:
                continue

            name = actor_names.get(actor_id)
            if not name:
                continue

            event_id = None
            if junction_event_map:
                event_uuid = junction_event_map.get(junction_id)
                event_id = str(event_uuid) if event_uuid else None

            roles = [role_names[rid] for rid in data["role_ids"] if rid in role_names]

            results.append(ActorData(
                actor_id=str(actor_id),
                actor_name=name,
                event_id=event_id,
                roles=roles,
                is_copyright_holder=data["is_copyright_holder"],
                is_neighbouring_rights_holder=data["is_neighbouring_rights_holder"],
            ))

        return results

    def _fetch_actor_names(self, actor_ids: Set[uuid.UUID]) -> Dict[uuid.UUID, str]:
        """Fetch names for actor entities."""
        from arkumu.metadata.models.triples import Triple

        if not actor_ids:
            return {}

        actor_names: Dict[uuid.UUID, str] = {}
        name_triples = Triple.objects.filter(
            subject_id__in=actor_ids,
        ).filter(
            Q(predicate__canonical_uri=CanonicalURIs.ACTOR_NAME)
            | Q(predicate__uri__icontains="name")
        ).select_related("object")

        for t in name_triples:
            name = getattr(t.object, "value", None)
            if name and t.subject_id not in actor_names:
                actor_names[t.subject_id] = str(name).strip()

        return actor_names

    def _fetch_role_names(self, role_ids: Set[uuid.UUID]) -> Dict[uuid.UUID, str]:
        """Fetch names for role entities."""
        from arkumu.metadata.models.triples import Triple

        if not role_ids:
            return {}

        role_names: Dict[uuid.UUID, str] = {}
        role_triples = Triple.objects.filter(
            subject_id__in=role_ids,
            predicate__canonical_uri=CanonicalURIs.ROLE_NAME,
        ).select_related("object")

        for t in role_triples:
            name = getattr(t.object, "value", None)
            if name and t.subject_id not in role_names:
                role_names[t.subject_id] = str(name).strip()

        return role_names

    def get_graph_data(
        self,
        resource_uri: str,
        depth: int = 2,
    ) -> Dict[str, Any]:
        """Fetch graph data for RDF serialization.

        Uses InstitutionalGraphService for institution-specific data.
        DEPRECATED: Use get_project_graph() instead for efficient queries.
        """
        from arkumu.metadata.services.institutional_graph_service import InstitutionalGraphService

        service = InstitutionalGraphService(org_code=self.org_code)
        try:
            return service.get_entity_graph(
                resource_uri,
                include_incoming=True,
                expand_neighbors=True,
                depth=depth,
            )
        except ValueError:
            return {}

    # -------------------------------------------------------------------------
    # New methods for efficient project data fetching
    # -------------------------------------------------------------------------

    def get_events_for_project(self, project_id: str) -> List[EventData]:
        """Get all events for a project with their properties.

        Override in subclasses that use junction tables for project-event links.
        Default implementation uses direct ereignis predicate (FUK pattern).
        """
        from arkumu.metadata.models.triples import Triple
        from arkumu.metadata.models.resource import Resource, ResourceType

        project_uuid = _as_uuid(project_id)
        if not project_uuid:
            return []

        # Find events linked to project
        event_ids = self._get_event_ids_for_project(project_uuid)
        if not event_ids:
            return []

        # Fetch event properties
        event_uuids = [_as_uuid(eid) for eid in event_ids]
        event_uuids = [e for e in event_uuids if e is not None]

        # Get event URIs
        event_resources = Resource.objects.filter(id__in=event_uuids).values("id", "uri")
        uri_map = {str(r["id"]): r["uri"] for r in event_resources}

        # Get event properties
        property_predicates = [
            CanonicalURIs.EVENT_NAME,
            CanonicalURIs.EVENT_START,
            CanonicalURIs.EVENT_END,
            CanonicalURIs.EVENT_LOCATION,
            CanonicalURIs.EVENT_DESCRIPTION,
            CanonicalURIs.EVENT_TYPE,
        ]

        event_props: Dict[str, Dict[str, Optional[str]]] = {eid: {} for eid in event_ids}

        prop_triples = Triple.objects.filter(
            subject_id__in=event_uuids,
        ).filter(
            Q(predicate__canonical_uri__in=property_predicates)
            | Q(predicate__uri__icontains="ereignis")
        ).select_related("predicate", "object")

        for t in prop_triples:
            eid = str(t.subject_id)
            pred = t.predicate.canonical_uri or t.predicate.uri or ""
            pred = self.normalize_predicate(pred)

            if t.object.resource_type == ResourceType.LITERAL:
                value = t.object.value
            else:
                value = t.object.uri or t.object.value

            if eid in event_props:
                if pred == CanonicalURIs.EVENT_NAME or "ereignisname" in pred:
                    event_props[eid]["name"] = value
                elif pred == CanonicalURIs.EVENT_START or "ereignisbeginn" in pred:
                    event_props[eid]["start"] = value
                elif pred == CanonicalURIs.EVENT_END or "ereignisende" in pred:
                    event_props[eid]["end"] = value
                elif pred == CanonicalURIs.EVENT_LOCATION or "ereignisort" in pred:
                    event_props[eid]["location"] = value
                elif pred == CanonicalURIs.EVENT_DESCRIPTION or "ereignisbeschreibung" in pred:
                    event_props[eid]["description"] = value
                elif pred == CanonicalURIs.EVENT_TYPE or "ereignistyp" in pred:
                    event_props[eid]["event_type"] = value

        # Get actors for each event
        actors = self.get_actors_for_project(project_id, event_ids)
        actors_by_event: Dict[str, List[ActorData]] = {}
        for actor in actors:
            if actor.event_id:
                if actor.event_id not in actors_by_event:
                    actors_by_event[actor.event_id] = []
                actors_by_event[actor.event_id].append(actor)

        # Build EventData objects
        events: List[EventData] = []
        for eid in event_ids:
            props = event_props.get(eid, {})
            events.append(EventData(
                event_id=eid,
                event_uri=uri_map.get(eid),
                name=props.get("name"),
                description=props.get("description"),
                location=props.get("location"),
                start=props.get("start"),
                end=props.get("end"),
                event_type=props.get("event_type"),
                actors=actors_by_event.get(eid, []),
            ))

        return events

    def get_digital_objects_for_project(self, project_id: str) -> List[DigitalObjectData]:
        """Get all digital objects for a project.

        Override in subclasses that use junction tables for digital object links.
        Default implementation uses direct digitales-objekt predicate (FUK pattern).
        """
        from arkumu.metadata.models.triples import Triple
        from arkumu.metadata.models.resource import Resource, ResourceType

        project_uuid = _as_uuid(project_id)
        if not project_uuid:
            return []

        # Track which events link to which digital objects
        do_event_map: Dict[str, List[str]] = {}

        # Find digital objects linked directly to project
        do_triples = Triple.objects.filter(
            Q(predicate__canonical_uri=CanonicalURIs.DIGITAL_OBJECT)
            | Q(predicate__uri__icontains="digitales-objekt"),
            subject_id=project_uuid,
        ).values_list("object_id", flat=True)

        do_ids = [str(did) for did in do_triples if did]

        # Also find digital objects via events
        event_ids = self._get_event_ids_for_project(project_uuid)
        if event_ids:
            event_uuids = [_as_uuid(eid) for eid in event_ids]
            event_uuids = [e for e in event_uuids if e is not None]

            event_do_triples = Triple.objects.filter(
                Q(predicate__canonical_uri=CanonicalURIs.DIGITAL_OBJECT)
                | Q(predicate__uri__icontains="digitales-objekt"),
                subject_id__in=event_uuids,
            ).values_list("object_id", "subject_id")

            for do_id, event_id in event_do_triples:
                if do_id:
                    did = str(do_id)
                    do_ids.append(did)
                    if did not in do_event_map:
                        do_event_map[did] = []
                    do_event_map[did].append(str(event_id))

        if not do_ids:
            return []

        # Deduplicate
        do_ids = list(set(do_ids))
        do_uuids = [_as_uuid(did) for did in do_ids]
        do_uuids = [d for d in do_uuids if d is not None]

        # Get digital object URIs
        do_resources = Resource.objects.filter(id__in=do_uuids).values("id", "uri")
        uri_map = {str(r["id"]): r["uri"] for r in do_resources}

        # Get all properties for digital objects in one query
        property_predicates = [
            CanonicalURIs.FILE_PATH,
            CanonicalURIs.LICENSE,
        ]
        do_properties = Triple.objects.filter(
            Q(predicate__canonical_uri__in=property_predicates)
            | Q(predicate__uri__icontains="dateipfad")
            | Q(predicate__uri__icontains="dateiname")
            | Q(predicate__uri__icontains="mime")
            | Q(predicate__uri__icontains="lizenz"),
            subject_id__in=do_uuids,
        ).select_related("predicate", "object")

        path_map: Dict[str, str] = {}
        file_name_map: Dict[str, str] = {}
        content_type_map: Dict[str, str] = {}
        license_uri_map: Dict[str, str] = {}

        for t in do_properties:
            did = str(t.subject_id)
            pred = t.predicate.canonical_uri or t.predicate.uri or ""

            if t.object.resource_type == ResourceType.LITERAL:
                value = t.object.value
            else:
                value = t.object.uri or str(t.object_id)

            if "dateipfad" in pred or pred == CanonicalURIs.FILE_PATH:
                path_map[did] = value
            elif "dateiname" in pred:
                file_name_map[did] = value
            elif "mime" in pred:
                content_type_map[did] = value
            elif "lizenz" in pred or pred == CanonicalURIs.LICENSE:
                license_uri_map[did] = value

        # Build DigitalObjectData
        results: List[DigitalObjectData] = []
        for did in do_ids:
            path = path_map.get(did)
            if not path:
                continue
            results.append(DigitalObjectData(
                object_id=did,
                object_uri=uri_map.get(did),
                path=path,
                file_name=file_name_map.get(did),
                content_type=content_type_map.get(did),
                license_uri=license_uri_map.get(did),
                source_event_ids=do_event_map.get(did, []),
            ))

        return results

    def get_project_properties(self, project_id: str) -> Optional[ProjectPropertiesData]:
        """Get core project properties (title, description, etc.)."""
        from arkumu.metadata.models.triples import Triple
        from arkumu.metadata.models.resource import Resource, ResourceType

        project_uuid = _as_uuid(project_id)
        if not project_uuid:
            return None

        # Get project resource
        try:
            project_resource = Resource.objects.get(id=project_uuid)
        except Resource.DoesNotExist:
            return None

        # Get project properties - use canonical URIs from database
        property_predicates = [
            CanonicalURIs.TITLE,
            CanonicalURIs.SUBTITLE,
            CanonicalURIs.DESCRIPTION,
            CanonicalURIs.DESCRIPTION_DE,
            CanonicalURIs.IMAGE,
            CanonicalURIs.INSTITUTION,
            CanonicalURIs.CATEGORY,
        ]

        props: Dict[str, Any] = {}
        category_uris: List[str] = []
        category_ids: List[uuid.UUID] = []
        institution_id: Optional[uuid.UUID] = None

        # Query by canonical_uri since the DB has proper mappings
        prop_triples = Triple.objects.filter(
            subject_id=project_uuid,
            predicate__canonical_uri__in=property_predicates,
        ).select_related("predicate", "object")

        for t in prop_triples:
            # Use canonical_uri for matching since that's what we filter by
            pred = t.predicate.canonical_uri

            if t.object.resource_type == ResourceType.LITERAL:
                value = t.object.value
            else:
                value = t.object.uri or str(t.object_id)

            if pred == CanonicalURIs.TITLE:
                props["title"] = value
            elif pred == CanonicalURIs.SUBTITLE:
                props["subtitle"] = value
            elif pred in (CanonicalURIs.DESCRIPTION, CanonicalURIs.DESCRIPTION_DE):
                # Only set description if not already set
                if "description" not in props:
                    props["description"] = value
            elif pred == CanonicalURIs.IMAGE:
                props["image"] = value
            elif pred == CanonicalURIs.INSTITUTION:
                if t.object.resource_type == ResourceType.LITERAL:
                    props["institution_label"] = value
                else:
                    props["institution_uri"] = value
                    institution_id = t.object_id
            elif pred == CanonicalURIs.CATEGORY:
                category_uris.append(value)
                if t.object.resource_type != ResourceType.LITERAL:
                    category_ids.append(t.object_id)

        # Fetch institution label
        institution_label = None
        if institution_id:
            inst_label_triples = Triple.objects.filter(
                Q(predicate__canonical_uri=CanonicalURIs.INSTITUTION_NAME)
                | Q(predicate__uri__icontains="deutscher-name")
                | Q(predicate__uri__icontains="name"),
                subject_id=institution_id,
            ).select_related("object")[:1]
            for t in inst_label_triples:
                if t.object.resource_type == ResourceType.LITERAL and t.object.value:
                    institution_label = t.object.value
                    break

        # Fetch category labels
        category_labels: List[str] = []
        if category_ids:
            cat_label_triples = Triple.objects.filter(
                Q(predicate__canonical_uri=CanonicalURIs.CATEGORY_NAME)
                | Q(predicate__uri__icontains="deutscher-name")
                | Q(predicate__uri__icontains="name"),
                subject_id__in=category_ids,
            ).select_related("object")

            label_map: Dict[uuid.UUID, str] = {}
            for t in cat_label_triples:
                if t.object.resource_type == ResourceType.LITERAL and t.object.value:
                    if t.subject_id not in label_map:
                        label_map[t.subject_id] = t.object.value

            category_labels = [label_map.get(cid, "") for cid in category_ids]

        # Use institution_label from props (literal) or fetched label (entity)
        final_institution_label = props.get("institution_label") or institution_label

        return ProjectPropertiesData(
            title=props.get("title"),
            subtitle=props.get("subtitle"),
            description=props.get("description"),
            image=props.get("image"),
            institution_uri=props.get("institution_uri"),
            institution_label=final_institution_label,
            category_uris=category_uris,
            category_labels=category_labels,
        )

    # -------------------------------------------------------------------------
    # Efficient graph traversal (3 queries)
    # -------------------------------------------------------------------------

    def get_project_graph(self, project_id: str) -> Optional[ProjectGraph]:
        """Get complete project data using efficient 3-query graph traversal.

        Query 1: Project's direct triples
        Query 2: Junction triples (to get their targets)
        Query 3: Entity triples (events, actors, DOs)

        Returns a ProjectGraph with all data needed to generate both
        canonical and institutional RDF.
        """
        from arkumu.metadata.models.triples import Triple
        from arkumu.metadata.models.resource import Resource, ResourceType
        from collections import defaultdict

        project_uuid = _as_uuid(project_id)
        if not project_uuid:
            return None

        try:
            project_resource = Resource.objects.get(id=project_uuid)
        except Resource.DoesNotExist:
            return None

        # Query 1: Project's direct triples
        project_triples = list(Triple.objects.filter(
            subject_id=project_uuid
        ).select_related('predicate', 'object'))

        if not project_triples:
            return ProjectGraph(
                project_uri=project_resource.uri,
                properties=ProjectPropertiesData(),
                events=[],
                actors=[],
                digital_objects=[],
                triples=[],
            )

        # Get neighbor IDs and their URIs
        neighbor_ids: Set[uuid.UUID] = set()
        for t in project_triples:
            if t.object_id and t.object.resource_type != ResourceType.LITERAL:
                neighbor_ids.add(t.object_id)

        # Fetch URIs for neighbors to identify junctions
        uri_map: Dict[uuid.UUID, str] = {project_uuid: project_resource.uri}
        if neighbor_ids:
            for r in Resource.objects.filter(id__in=neighbor_ids).values('id', 'uri'):
                uri_map[r['id']] = r['uri']

        # Separate junctions from real entities
        junction_ids: Set[uuid.UUID] = set()
        entity_ids: Set[uuid.UUID] = set()
        for nid in neighbor_ids:
            uri = uri_map.get(nid, '')
            if self._is_junction(uri):
                junction_ids.add(nid)
            else:
                entity_ids.add(nid)

        # Query 2: Junction triples (to get their targets)
        junction_triples: List = []
        junction_target_ids: Set[uuid.UUID] = set()
        if junction_ids:
            junction_triples = list(Triple.objects.filter(
                subject_id__in=junction_ids
            ).select_related('predicate', 'object'))

            for t in junction_triples:
                if t.object_id and t.object.resource_type != ResourceType.LITERAL:
                    junction_target_ids.add(t.object_id)

            # Get URIs for junction targets
            new_ids = junction_target_ids - set(uri_map.keys())
            if new_ids:
                for r in Resource.objects.filter(id__in=new_ids).values('id', 'uri'):
                    uri_map[r['id']] = r['uri']

            # Check for nested junctions (e.g., project -> junction1 -> junction2 -> entity)
            nested_junction_ids: Set[uuid.UUID] = set()
            for tid in junction_target_ids:
                uri = uri_map.get(tid, '')
                if self._is_junction(uri):
                    nested_junction_ids.add(tid)
                else:
                    entity_ids.add(tid)

            # Follow nested junctions if any
            if nested_junction_ids:
                nested_triples = list(Triple.objects.filter(
                    subject_id__in=nested_junction_ids
                ).select_related('predicate', 'object'))
                junction_triples.extend(nested_triples)
                junction_ids.update(nested_junction_ids)

                for t in nested_triples:
                    if t.object_id and t.object.resource_type != ResourceType.LITERAL:
                        entity_ids.add(t.object_id)
                        if t.object_id not in uri_map:
                            # Fetch URI
                            try:
                                r = Resource.objects.get(id=t.object_id)
                                uri_map[t.object_id] = r.uri
                            except Resource.DoesNotExist:
                                pass

        # Query 3: Entity triples (properties of events, actors, DOs)
        entity_triples: List = []
        if entity_ids:
            entity_triples = list(Triple.objects.filter(
                subject_id__in=entity_ids
            ).select_related('predicate', 'object'))

            # Get URIs for any new objects
            new_object_ids: Set[uuid.UUID] = set()
            for t in entity_triples:
                if t.object_id and t.object.resource_type != ResourceType.LITERAL:
                    if t.object_id not in uri_map:
                        new_object_ids.add(t.object_id)
            if new_object_ids:
                for r in Resource.objects.filter(id__in=new_object_ids).values('id', 'uri'):
                    uri_map[r['id']] = r['uri']

        # Combine all triples
        all_triples = project_triples + junction_triples + entity_triples

        # Build the graph from collected triples
        return self._build_graph_from_triples(
            project_uuid=project_uuid,
            project_uri=project_resource.uri,
            all_triples=all_triples,
            junction_ids=junction_ids,
            uri_map=uri_map,
        )

    def _is_junction(self, uri: str) -> bool:
        """Check if URI represents a junction entity.

        Junctions are intermediate linking entities, identifiable by URI pattern.
        Override in subclasses for institution-specific patterns.
        """
        if not uri:
            return False
        uri_lower = uri.lower()
        return 'kreuz' in uri_lower or 'kreuztabelle' in uri_lower

    def _build_graph_from_triples(
        self,
        project_uuid: uuid.UUID,
        project_uri: str,
        all_triples: List,
        junction_ids: Set[uuid.UUID],
        uri_map: Dict[uuid.UUID, str],
    ) -> ProjectGraph:
        """Build ProjectGraph from collected triples."""
        from arkumu.metadata.models.resource import ResourceType
        from collections import defaultdict

        # Group triples by subject
        triples_by_subject: Dict[uuid.UUID, List] = defaultdict(list)
        for t in all_triples:
            triples_by_subject[t.subject_id].append(t)

        # Extract project properties
        properties = self._extract_properties_from_triples(triples_by_subject[project_uuid])

        # Classify entities and build structured data
        events: List[EventData] = []
        actors: List[ActorData] = []
        digital_objects: List[DigitalObjectData] = []

        # Track which actors we've seen (to avoid duplicates from junctions)
        seen_actor_ids: Set[uuid.UUID] = set()

        for entity_id, entity_triples in triples_by_subject.items():
            if entity_id == project_uuid:
                continue

            if entity_id in junction_ids:
                # Extract actor data from junction
                actor_data = self._extract_actor_from_junction(
                    entity_triples, uri_map, triples_by_subject
                )
                if actor_data and actor_data.actor_id:
                    actor_uuid = _as_uuid(actor_data.actor_id)
                    if actor_uuid and actor_uuid not in seen_actor_ids:
                        seen_actor_ids.add(actor_uuid)
                        actors.append(actor_data)
            else:
                # Classify entity type
                entity_type = self._classify_entity(entity_triples)
                entity_uri = uri_map.get(entity_id)

                if entity_type == 'event':
                    events.append(self._build_event_from_triples(
                        entity_id, entity_uri, entity_triples
                    ))
                elif entity_type == 'digital_object':
                    digital_objects.append(self._build_do_from_triples(
                        entity_id, entity_uri, entity_triples
                    ))
                elif entity_type == 'actor':
                    if entity_id not in seen_actor_ids:
                        seen_actor_ids.add(entity_id)
                        actors.append(self._build_actor_from_triples(
                            entity_id, entity_triples, uri_map, triples_by_subject
                        ))

        # Build TripleData for RDF serialization
        triple_data = self._build_triple_data(all_triples, uri_map)

        return ProjectGraph(
            project_uri=project_uri,
            properties=properties,
            events=events,
            actors=actors,
            digital_objects=digital_objects,
            triples=triple_data,
        )

    def _classify_entity(self, triples: List) -> str:
        """Classify entity type from its triples using canonical URIs."""
        predicates: Set[str] = set()
        for t in triples:
            if t.predicate.canonical_uri:
                predicates.add(t.predicate.canonical_uri.lower())
            if t.predicate.uri:
                predicates.add(t.predicate.uri.lower())

        pred_str = ' '.join(predicates)

        # Digital object: has file path
        if 'dateipfad' in pred_str or 'dateiname' in pred_str:
            return 'digital_object'

        # Event: has event-specific properties
        if 'ereignisname' in pred_str or 'ereignisbeginn' in pred_str or 'ereignistyp' in pred_str:
            return 'event'

        # Actor: has name property (but not event/DO)
        if 'deutscher-name' in pred_str or 'akteurin-name' in pred_str:
            return 'actor'

        return 'unknown'

    def _extract_properties_from_triples(self, triples: List) -> ProjectPropertiesData:
        """Extract project properties from triples."""
        from arkumu.metadata.models.resource import ResourceType

        props: Dict[str, Any] = {}
        category_uris: List[str] = []
        category_labels: List[str] = []

        for t in triples:
            pred = (t.predicate.canonical_uri or t.predicate.uri or '').lower()

            if t.object.resource_type == ResourceType.LITERAL:
                value = t.object.value
            else:
                value = t.object.uri or str(t.object_id)

            if 'bevorzugter-titel' in pred and 'untertitel' not in pred:
                props['title'] = value
            elif 'bevorzugter-untertitel' in pred or ('untertitel' in pred and 'sprache' not in pred):
                props['subtitle'] = value
            elif 'beschreibung' in pred and 'ereignis' not in pred:
                if 'description' not in props:
                    props['description'] = value
            elif 'vorschaubild' in pred:
                props['image'] = value
            elif 'einliefernde-hochschule' in pred:
                if t.object.resource_type == ResourceType.LITERAL:
                    props['institution_label'] = value
                else:
                    props['institution_uri'] = value
            elif 'projektkategorie' in pred:
                if t.object.resource_type != ResourceType.LITERAL:
                    category_uris.append(value)

        return ProjectPropertiesData(
            title=props.get('title'),
            subtitle=props.get('subtitle'),
            description=props.get('description'),
            image=props.get('image'),
            institution_uri=props.get('institution_uri'),
            institution_label=props.get('institution_label'),
            category_uris=category_uris,
            category_labels=category_labels,
        )

    def _build_event_from_triples(
        self, event_id: uuid.UUID, event_uri: Optional[str], triples: List
    ) -> EventData:
        """Build EventData from triples."""
        from arkumu.metadata.models.resource import ResourceType

        props: Dict[str, Optional[str]] = {}

        for t in triples:
            pred = (t.predicate.canonical_uri or t.predicate.uri or '').lower()

            if t.object.resource_type == ResourceType.LITERAL:
                value = t.object.value
            else:
                value = t.object.uri

            if 'ereignisname' in pred or 'eventname' in pred:
                props['name'] = value
            elif 'ereignisbeginn' in pred or 'eventanfang' in pred:
                props['start'] = value
            elif 'ereignisende' in pred or 'eventend' in pred:
                props['end'] = value
            elif 'ereignisort' in pred:
                props['location'] = value
            elif 'ereignisbeschreibung' in pred:
                props['description'] = value
            elif 'ereignistyp' in pred:
                props['event_type'] = value

        return EventData(
            event_id=str(event_id),
            event_uri=event_uri,
            name=props.get('name'),
            description=props.get('description'),
            location=props.get('location'),
            start=props.get('start'),
            end=props.get('end'),
            event_type=props.get('event_type'),
            actors=[],  # Actors are extracted from junctions
        )

    def _build_do_from_triples(
        self, do_id: uuid.UUID, do_uri: Optional[str], triples: List
    ) -> DigitalObjectData:
        """Build DigitalObjectData from triples."""
        from arkumu.metadata.models.resource import ResourceType

        path: Optional[str] = None
        file_name: Optional[str] = None
        license_uri: Optional[str] = None

        for t in triples:
            pred = (t.predicate.canonical_uri or t.predicate.uri or '').lower()

            if t.object.resource_type == ResourceType.LITERAL:
                value = t.object.value
            else:
                value = t.object.uri

            if 'dateipfad' in pred:
                path = value
            elif 'dateiname' in pred:
                file_name = value
            elif 'lizenz' in pred and t.object.resource_type != ResourceType.LITERAL:
                license_uri = value

        return DigitalObjectData(
            object_id=str(do_id),
            object_uri=do_uri,
            path=path,
            file_name=file_name,
            license_uri=license_uri,
            source_event_ids=[],
        )

    def _build_actor_from_triples(
        self,
        actor_id: uuid.UUID,
        triples: List,
        uri_map: Dict[uuid.UUID, str],
        triples_by_subject: Dict[uuid.UUID, List],
    ) -> ActorData:
        """Build ActorData from actor entity triples."""
        from arkumu.metadata.models.resource import ResourceType

        name: Optional[str] = None

        for t in triples:
            pred = (t.predicate.canonical_uri or t.predicate.uri or '').lower()

            if 'deutscher-name' in pred or 'akteurin-name' in pred or 'name' in pred:
                if t.object.resource_type == ResourceType.LITERAL and t.object.value:
                    name = t.object.value
                    break

        return ActorData(
            actor_id=str(actor_id),
            actor_name=name or '',
            event_id=None,
            roles=[],
            is_copyright_holder=False,
            is_neighbouring_rights_holder=False,
        )

    def _extract_actor_from_junction(
        self,
        junction_triples: List,
        uri_map: Dict[uuid.UUID, str],
        triples_by_subject: Dict[uuid.UUID, List],
    ) -> Optional[ActorData]:
        """Extract actor data from junction triples."""
        from arkumu.metadata.models.resource import ResourceType

        actor_id: Optional[uuid.UUID] = None
        event_id: Optional[uuid.UUID] = None
        role_ids: List[uuid.UUID] = []
        is_copyright = False
        is_neighbouring = False

        for t in junction_triples:
            pred = (t.predicate.canonical_uri or t.predicate.uri or '').lower()

            if 'akteurin-im-ereignis' in pred or 'akteur' in pred and 'fk' in pred:
                if t.object.resource_type != ResourceType.LITERAL:
                    actor_id = t.object_id
            elif 'im-ereignis' in pred or 'ereignis' in pred and 'fk' in pred:
                if t.object.resource_type != ResourceType.LITERAL:
                    event_id = t.object_id
            elif 'rollen-der-akteurin' in pred or 'rolle' in pred:
                if t.object.resource_type != ResourceType.LITERAL:
                    role_ids.append(t.object_id)
            elif 'ist-urheberin' in pred:
                is_copyright = _is_truthy(getattr(t.object, 'value', None))
            elif 'leistungsschutzrechte' in pred:
                is_neighbouring = _is_truthy(getattr(t.object, 'value', None))

        if not actor_id:
            return None

        # Get actor name from actor's triples
        actor_name = ''
        actor_triples = triples_by_subject.get(actor_id, [])
        for t in actor_triples:
            pred = (t.predicate.canonical_uri or t.predicate.uri or '').lower()
            if 'deutscher-name' in pred or 'akteurin-name' in pred or 'name' in pred:
                if t.object.resource_type == ResourceType.LITERAL and t.object.value:
                    actor_name = t.object.value
                    break

        # Get role names
        role_names: List[str] = []
        for role_id in role_ids:
            role_triples = triples_by_subject.get(role_id, [])
            for t in role_triples:
                pred = (t.predicate.canonical_uri or t.predicate.uri or '').lower()
                if 'name' in pred and 'rolle' in pred:
                    if t.object.resource_type == ResourceType.LITERAL and t.object.value:
                        role_names.append(t.object.value)
                        break

        return ActorData(
            actor_id=str(actor_id),
            actor_name=actor_name,
            event_id=str(event_id) if event_id else None,
            roles=role_names,
            is_copyright_holder=is_copyright,
            is_neighbouring_rights_holder=is_neighbouring,
        )

    def _build_triple_data(
        self, triples: List, uri_map: Dict[uuid.UUID, str]
    ) -> List[TripleData]:
        """Build TripleData list for RDF serialization."""
        from arkumu.metadata.models.resource import ResourceType

        results: List[TripleData] = []
        for t in triples:
            subject_uri = uri_map.get(t.subject_id, str(t.subject_id))
            predicate_uri = t.predicate.uri or ''
            predicate_canonical = t.predicate.canonical_uri

            if t.object.resource_type == ResourceType.LITERAL:
                results.append(TripleData(
                    subject_uri=subject_uri,
                    predicate_uri=predicate_uri,
                    predicate_canonical=predicate_canonical,
                    object_uri=None,
                    object_value=t.object.value,
                    object_is_literal=True,
                ))
            else:
                object_uri = uri_map.get(t.object_id) or t.object.uri or str(t.object_id)
                results.append(TripleData(
                    subject_uri=subject_uri,
                    predicate_uri=predicate_uri,
                    predicate_canonical=predicate_canonical,
                    object_uri=object_uri,
                    object_value=None,
                    object_is_literal=False,
                ))

        return results
