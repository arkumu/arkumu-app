"""Service for extracting actor/rights data from junction entities.

Handles institution-specific junction patterns:
- FUK/RSH/DET: junction -> im-ereignis -> event
- KHM: junction -> projekt -> grundereignis (maps to project by numeric ID)
- HMT: junction -> ereignis -> event

This service consolidates junction logic previously scattered across:
- triple_relationship_service.get_actor_relationships()
- project_index_db_service._batch_fetch_dc_from_junctions()
- project_index_db_service._expand_event_junctions()
"""

from __future__ import annotations

import logging
import uuid
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Set

from django.db.models import Q

logger = logging.getLogger(__name__)


@dataclass
class JunctionActorData:
    """Actor data extracted from a junction entity."""
    actor_id: str
    actor_name: str
    event_id: Optional[str]
    project_id: str
    roles: List[str]
    is_copyright_holder: bool
    is_neighbouring_rights_holder: bool


# Canonical URIs for junction predicates
class _JunctionURIs:
    # Junction -> target predicates
    IM_EREIGNIS = "http://arkumu.org/data/properties/im-ereignis"  # FUK: junction -> event
    PROJEKT = "http://arkumu.org/data/properties/projekt"  # KHM: junction -> grundereignis
    EREIGNIS = "http://arkumu.org/data/properties/ereignis"  # HMT: junction -> event

    # Junction -> actor/role predicates
    ACTOR_LINK = "http://arkumu.org/data/properties/akteurin-im-ereignis"
    ROLE_LINK = "http://arkumu.org/data/properties/rollen-der-akteurin-im-ereignis"

    # Rights predicates
    IST_URHEBERIN = "http://arkumu.org/data/properties/ist-urheberin"
    LEISTUNGSSCHUTZRECHTE = "http://arkumu.org/data/properties/besitzt-leistungsschutzrechte"

    # Name predicates
    ACTOR_NAME = "http://arkumu.org/data/properties/deutscher-name"
    ROLE_NAME = "http://arkumu.org/data/properties/deutscher-name-der-rolle-breadcrumb"


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


def _is_truthy(value: Optional[str]) -> bool:
    """Check if a literal value is truthy (1, true, yes, ja)."""
    if value is None:
        return False
    token = str(value).strip().lower()
    return token in {"1", "true", "yes", "ja"}


class JunctionActorService:
    """Service for extracting actor/rights data from junction entities."""

    def __init__(self, organization_code: Optional[str] = None):
        self.org_code = (organization_code or "").strip().lower()

    def get_actors_for_project(
        self,
        project_id: str,
        event_ids: Optional[Sequence[str]] = None,
    ) -> List[JunctionActorData]:
        """Get all actors with rights data for a project.

        Automatically handles FUK, KHM, HMT patterns based on org_code.

        Args:
            project_id: The project's resource ID (UUID string).
            event_ids: Optional list of event IDs linked to the project.
                      If not provided, will be fetched.

        Returns:
            List of JunctionActorData with actor info and rights flags.
        """
        if self.org_code == "khm":
            return self._get_actors_khm(project_id)
        elif self.org_code == "hmt":
            return self._get_actors_hmt(project_id, event_ids)
        else:
            # FUK, RSH, DET and others use canonical pattern
            return self._get_actors_canonical(project_id, event_ids)

    def _get_actors_canonical(
        self,
        project_id: str,
        event_ids: Optional[Sequence[str]] = None,
    ) -> List[JunctionActorData]:
        """Get actors for FUK/RSH/DET pattern: junction -> im-ereignis -> event.

        The project links TO events, junctions link TO events.
        """
        from arkumu.metadata.models.triples import Triple

        project_uuid = _as_uuid(project_id)
        if not project_uuid:
            return []

        # Get event IDs if not provided
        if event_ids is None:
            event_ids = self._get_event_ids_for_project(project_uuid)

        if not event_ids:
            return []

        event_uuids = [_as_uuid(eid) for eid in event_ids if _as_uuid(eid)]
        if not event_uuids:
            return []

        # Find junctions pointing to events via im-ereignis
        junction_triples = Triple.objects.filter(
            Q(predicate__canonical_uri=_JunctionURIs.IM_EREIGNIS)
            | Q(predicate__uri__icontains="im-ereignis"),
            object_id__in=event_uuids,
        )
        if self.org_code:
            junction_triples = junction_triples.filter(
                subject__organization__code__iexact=self.org_code
            )
        junction_triples = junction_triples.values_list("subject_id", "object_id")

        junction_ids: Set[uuid.UUID] = set()
        junction_event_map: Dict[uuid.UUID, uuid.UUID] = {}
        for junction_id, event_id in junction_triples:
            junction_ids.add(junction_id)
            junction_event_map[junction_id] = event_id

        if not junction_ids:
            return []

        return self._process_junctions(
            junction_ids,
            junction_event_map,
            project_uuid,
        )

    def _get_actors_khm(self, project_id: str) -> List[JunctionActorData]:
        """Get actors for KHM pattern: junction -> projekt -> grundereignis.

        KHM maps grundereignis to project by numeric ID:
        01-grundereignis/X -> 00-projekte/X
        """
        from arkumu.metadata.models.triples import Triple
        from arkumu.metadata.models.resource import Resource

        project_uuid = _as_uuid(project_id)
        if not project_uuid:
            return []

        # Get project URI to extract numeric ID
        try:
            project_resource = Resource.objects.get(id=project_uuid)
        except Resource.DoesNotExist:
            return []

        project_uri = project_resource.uri
        if "/00-projekte/" not in project_uri:
            return []

        # Build grundereignis URI from project URI
        grundereignis_uri = project_uri.replace("/00-projekte/", "/01-grundereignis/")

        # Find grundereignis resource
        try:
            grundereignis = Resource.objects.get(uri=grundereignis_uri)
        except Resource.DoesNotExist:
            return []

        # Find junctions pointing to grundereignis via projekt predicate
        junction_triples = Triple.objects.filter(
            Q(predicate__canonical_uri=_JunctionURIs.PROJEKT)
            | Q(predicate__uri__icontains="projekt"),
            object_id=grundereignis.id,
            subject__organization__code__iexact="khm",
        ).values_list("subject_id", "object_id")

        junction_ids: Set[uuid.UUID] = set()
        for junction_id, _ in junction_triples:
            junction_ids.add(junction_id)

        if not junction_ids:
            return []

        # For KHM, junctions link to grundereignis not events
        # Pass None for event mapping since we go directly to project
        return self._process_junctions(
            junction_ids,
            None,  # No event mapping for KHM
            project_uuid,
        )

    def _get_actors_hmt(
        self,
        project_id: str,
        event_ids: Optional[Sequence[str]] = None,
    ) -> List[JunctionActorData]:
        """Get actors for HMT pattern: junction -> ereignis -> event -> project.

        HMT junctions use 'ereignis' predicate (not 'im-ereignis').
        """
        from arkumu.metadata.models.triples import Triple

        project_uuid = _as_uuid(project_id)
        if not project_uuid:
            return []

        # Get event IDs if not provided
        if event_ids is None:
            event_ids = self._get_event_ids_for_project(project_uuid)

        if not event_ids:
            return []

        event_uuids = [_as_uuid(eid) for eid in event_ids if _as_uuid(eid)]
        if not event_uuids:
            return []

        # Find junctions pointing to events via ereignis predicate
        junction_triples = Triple.objects.filter(
            Q(predicate__canonical_uri=_JunctionURIs.EREIGNIS)
            | Q(predicate__uri__icontains="ereignis"),
            object_id__in=event_uuids,
            subject__organization__code__iexact="hmt",
        ).values_list("subject_id", "object_id")

        junction_ids: Set[uuid.UUID] = set()
        junction_event_map: Dict[uuid.UUID, uuid.UUID] = {}
        for junction_id, event_id in junction_triples:
            junction_ids.add(junction_id)
            junction_event_map[junction_id] = event_id

        if not junction_ids:
            return []

        return self._process_junctions(
            junction_ids,
            junction_event_map,
            project_uuid,
        )

    def _get_event_ids_for_project(self, project_uuid: uuid.UUID) -> List[str]:
        """Get event IDs linked to a project."""
        from arkumu.metadata.models.triples import Triple

        EREIGNIS_PREDICATE = "http://arkumu.org/data/properties/ereignis"

        event_triples = Triple.objects.filter(
            Q(predicate__canonical_uri=EREIGNIS_PREDICATE)
            | Q(predicate__uri__icontains="ereignis"),
            subject_id=project_uuid,
        ).values_list("object_id", flat=True)

        return [str(eid) for eid in event_triples if eid]

    def _process_junctions(
        self,
        junction_ids: Set[uuid.UUID],
        junction_event_map: Optional[Dict[uuid.UUID, uuid.UUID]],
        project_uuid: uuid.UUID,
    ) -> List[JunctionActorData]:
        """Process junction entities to extract actor/rights data.

        Args:
            junction_ids: Set of junction entity UUIDs.
            junction_event_map: Optional mapping junction_id -> event_id.
            project_uuid: The project UUID (all junctions belong to this project).

        Returns:
            List of JunctionActorData.
        """
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

            pred = t.predicate.canonical_uri or t.predicate.uri or ""

            # Actor link - match exact predicate to avoid matching role predicate
            if pred == _JunctionURIs.ACTOR_LINK or pred.endswith("/akteurin-im-ereignis"):
                if t.object and t.object.resource_type != ResourceType.LITERAL:
                    junction_data[jid]["actor_id"] = t.object_id

            # Role link
            elif pred == _JunctionURIs.ROLE_LINK or "rollen-der-akteurin" in pred:
                if t.object and t.object.resource_type != ResourceType.LITERAL:
                    junction_data[jid]["role_ids"].add(t.object_id)

            # Copyright holder flag
            elif pred == _JunctionURIs.IST_URHEBERIN or "ist-urheberin" in pred:
                val = getattr(t.object, "value", None)
                junction_data[jid]["is_copyright_holder"] = _is_truthy(val)

            # Neighbouring rights flag
            elif pred == _JunctionURIs.LEISTUNGSSCHUTZRECHTE or "leistungsschutz" in pred:
                val = getattr(t.object, "value", None)
                junction_data[jid]["is_neighbouring_rights_holder"] = _is_truthy(val)

        # Fetch actor names
        actor_ids = {d["actor_id"] for d in junction_data.values() if d["actor_id"]}
        actor_names: Dict[uuid.UUID, str] = {}
        if actor_ids:
            name_triples = Triple.objects.filter(
                subject_id__in=actor_ids,
            ).filter(
                Q(predicate__canonical_uri=_JunctionURIs.ACTOR_NAME)
                | Q(predicate__uri__icontains="name")
            ).select_related("object")

            for t in name_triples:
                name = getattr(t.object, "value", None)
                if name and t.subject_id not in actor_names:
                    actor_names[t.subject_id] = str(name).strip()

        # Fetch role names
        all_role_ids: Set[uuid.UUID] = set()
        for data in junction_data.values():
            all_role_ids.update(data["role_ids"])

        role_names: Dict[uuid.UUID, str] = {}
        if all_role_ids:
            role_triples = Triple.objects.filter(
                subject_id__in=all_role_ids,
                predicate__canonical_uri=_JunctionURIs.ROLE_NAME,
            ).select_related("object")

            for t in role_triples:
                name = getattr(t.object, "value", None)
                if name and t.subject_id not in role_names:
                    role_names[t.subject_id] = str(name).strip()

        # Build results
        results: List[JunctionActorData] = []
        for junction_id, data in junction_data.items():
            actor_id = data["actor_id"]
            if not actor_id:
                continue

            name = actor_names.get(actor_id)
            if not name:
                continue

            # Get event ID from mapping if available
            event_id = None
            if junction_event_map:
                event_uuid = junction_event_map.get(junction_id)
                event_id = str(event_uuid) if event_uuid else None

            # Get role names
            roles = [
                role_names[rid]
                for rid in data["role_ids"]
                if rid in role_names
            ]

            results.append(JunctionActorData(
                actor_id=str(actor_id),
                actor_name=name,
                event_id=event_id,
                project_id=str(project_uuid),
                roles=roles,
                is_copyright_holder=data["is_copyright_holder"],
                is_neighbouring_rights_holder=data["is_neighbouring_rights_holder"],
            ))

        return results

    def get_dc_creators_contributors(
        self,
        project_id: str,
        event_ids: Optional[Sequence[str]] = None,
    ) -> Dict[str, List[str]]:
        """Get dc:creator and dc:contributor lists for a project.

        Convenience method that extracts DC metadata from junction actors.

        Returns:
            Dict with 'creators' and 'contributors' lists.
        """
        actors = self.get_actors_for_project(project_id, event_ids)

        creators: List[str] = []
        contributors: List[str] = []

        for actor in actors:
            is_creator = actor.is_copyright_holder or actor.is_neighbouring_rights_holder
            if is_creator:
                if actor.actor_name not in creators:
                    creators.append(actor.actor_name)
            else:
                if actor.actor_name not in contributors:
                    contributors.append(actor.actor_name)

        return {"creators": creators, "contributors": contributors}
