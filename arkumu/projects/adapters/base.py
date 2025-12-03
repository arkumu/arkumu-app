"""Base class for institution-specific adapters."""

from __future__ import annotations

import logging
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Set

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
    actors: List[ActorData]


# Common canonical URIs
class CanonicalURIs:
    """Canonical predicate URIs used across institutions."""
    # Project -> Event link
    EVENT = "http://arkumu.org/data/properties/ereignis"

    # Junction predicates
    IM_EREIGNIS = "http://arkumu.org/data/properties/im-ereignis"
    PROJEKT = "http://arkumu.org/data/properties/projekt"

    # Actor predicates
    ACTOR_LINK = "http://arkumu.org/data/properties/akteurin-im-ereignis"
    ROLE_LINK = "http://arkumu.org/data/properties/rollen-der-akteurin-im-ereignis"
    ACTOR_NAME = "http://arkumu.org/data/properties/deutscher-name"
    ROLE_NAME = "http://arkumu.org/data/properties/deutscher-name-der-rolle-breadcrumb"

    # Rights predicates
    IST_URHEBERIN = "http://arkumu.org/data/properties/ist-urheberin"
    LEISTUNGSSCHUTZRECHTE = "http://arkumu.org/data/properties/besitzt-leistungsschutzrechte"


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
