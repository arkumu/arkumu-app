"""HMT adapter - uses junction tables for project-event and event-digital object links.

Junction patterns:
- Project-Event: 01_hfm_Kreuz_Projekt_Ereignis (junction -> projekt -> project, junction -> ereignis -> event)
- Event-DigitalObject: 07_hfm_Kreuz_Ereignis_DigitalesObjekt (junction -> ereignis -> event, junction -> digitales-objekt -> DO)
- Actor-Event: 03_hfm_Kreuz_Ereignis_Akteure (standard actor junction)

HMT predicates often lack canonical_uri mappings in the database.
"""

from __future__ import annotations

import uuid
from typing import Dict, List, Optional, Sequence, Set

from django.db.models import Q

from arkumu.projects.adapters.base import (
    InstitutionAdapter,
    CanonicalURIs,
    DigitalObjectData,
    EventData,
    _as_uuid,
)


class HmtAdapter(InstitutionAdapter):
    """Adapter for HMT institution.

    HMT uses:
    - 'ereignis' predicate (not 'im-ereignis') for junction -> event links
    - Some predicates lack canonical_uri mappings in the database

    The PREDICATE_CANONICAL_MAP provides fallback mappings for predicates
    that don't have canonical_uri set.
    """

    ORG_CODE = "hmt"
    JUNCTION_PREDICATE = "http://arkumu.org/data/hmt/properties/ereignis"

    # Fallback mappings for HMT predicates lacking canonical_uri
    PREDICATE_CANONICAL_MAP = {
        "/ist-urheberin": CanonicalURIs.IST_URHEBERIN,
        "/besitzt-leistungsschutzrechte": CanonicalURIs.LEISTUNGSSCHUTZRECHTE,
        "/akteurin-im-ereignis": CanonicalURIs.ACTOR_LINK,
        "/rollen-der-akteurin-im-ereignis": CanonicalURIs.ROLE_LINK,
        "/deutscher-name": CanonicalURIs.ACTOR_NAME,
    }

    def _find_junctions(
        self,
        project_uuid: uuid.UUID,
        event_ids: Optional[Sequence[str]],
    ) -> tuple[Set[uuid.UUID], Dict[uuid.UUID, uuid.UUID]]:
        """Find junctions via ereignis -> event pattern."""
        from arkumu.metadata.models.triples import Triple

        if not event_ids:
            return set(), {}

        event_uuids = [_as_uuid(eid) for eid in event_ids]
        event_uuids = [e for e in event_uuids if e is not None]
        if not event_uuids:
            return set(), {}

        # Find junctions pointing to events via ereignis predicate
        # HMT uses 'ereignis' not 'im-ereignis'
        junction_triples = Triple.objects.filter(
            Q(predicate__canonical_uri=CanonicalURIs.EVENT)
            | Q(predicate__uri__icontains="ereignis"),
            object_id__in=event_uuids,
            subject__organization__code__iexact="hmt",
        ).values_list("subject_id", "object_id")

        junction_ids: Set[uuid.UUID] = set()
        junction_event_map: Dict[uuid.UUID, uuid.UUID] = {}
        for junction_id, event_id in junction_triples:
            junction_ids.add(junction_id)
            junction_event_map[junction_id] = event_id

        return junction_ids, junction_event_map

    def normalize_predicate(self, predicate_uri: str) -> str:
        """Map HMT predicate to canonical form.

        HMT predicates often lack canonical_uri in the database,
        so we provide explicit mappings.
        """
        if not predicate_uri:
            return predicate_uri

        # Check our explicit mappings
        for suffix, canonical in self.PREDICATE_CANONICAL_MAP.items():
            if predicate_uri.endswith(suffix):
                return canonical

        return predicate_uri

    # -------------------------------------------------------------------------
    # Override methods for HMT junction patterns
    # -------------------------------------------------------------------------

    def _get_event_ids_for_project(self, project_uuid: uuid.UUID) -> List[str]:
        """Get event IDs via project-event junction table.

        HMT pattern: junction -> projekt -> project AND junction -> ereignis -> event
        Junction type: 01_hfm_Kreuz_Projekt_Ereignis
        """
        from arkumu.metadata.models.triples import Triple

        # Find project-event junctions that point to this project
        # Junction has: projekt -> project, ereignis -> event
        projekt_junctions = Triple.objects.filter(
            Q(predicate__canonical_uri=CanonicalURIs.PROJEKT)
            | Q(predicate__uri__icontains="/projekt"),
            object_id=project_uuid,
            subject__organization__code__iexact="hmt",
        ).values_list("subject_id", flat=True)

        junction_ids = list(projekt_junctions)
        if not junction_ids:
            return []

        # Now find ereignis links from these junctions
        event_triples = Triple.objects.filter(
            Q(predicate__canonical_uri=CanonicalURIs.EVENT)
            | Q(predicate__uri__icontains="ereignis"),
            subject_id__in=junction_ids,
        ).values_list("object_id", flat=True)

        return [str(eid) for eid in event_triples if eid]

    def get_digital_objects_for_project(self, project_id: str) -> List[DigitalObjectData]:
        """Get digital objects via event-digital object junction table.

        HMT pattern: junction -> ereignis -> event AND junction -> digitales-objekt -> DO
        Junction type: 07_hfm_Kreuz_Ereignis_DigitalesObjekt
        """
        from arkumu.metadata.models.triples import Triple
        from arkumu.metadata.models.resource import Resource, ResourceType

        project_uuid = _as_uuid(project_id)
        if not project_uuid:
            return []

        # First get event IDs for this project
        event_ids = self._get_event_ids_for_project(project_uuid)
        if not event_ids:
            return []

        event_uuids = [_as_uuid(eid) for eid in event_ids]
        event_uuids = [e for e in event_uuids if e is not None]

        # Find event-DO junctions that point to these events
        event_do_junctions = Triple.objects.filter(
            Q(predicate__canonical_uri=CanonicalURIs.EVENT)
            | Q(predicate__uri__icontains="ereignis"),
            object_id__in=event_uuids,
            subject__organization__code__iexact="hmt",
            subject__entity_type__uri__icontains="kreuz-ereignis-digitalesobjekt",
        ).values_list("subject_id", "object_id")

        junction_ids: Set[uuid.UUID] = set()
        junction_event_map: Dict[uuid.UUID, str] = {}
        for junction_id, event_id in event_do_junctions:
            junction_ids.add(junction_id)
            junction_event_map[junction_id] = str(event_id)

        if not junction_ids:
            # Fallback: try without entity_type filter
            event_do_junctions = Triple.objects.filter(
                Q(predicate__canonical_uri=CanonicalURIs.EVENT)
                | Q(predicate__uri__icontains="ereignis"),
                object_id__in=event_uuids,
                subject__organization__code__iexact="hmt",
            ).values_list("subject_id", "object_id")

            for junction_id, event_id in event_do_junctions:
                junction_ids.add(junction_id)
                junction_event_map[junction_id] = str(event_id)

        if not junction_ids:
            return []

        # Find digital object links from these junctions
        do_triples = Triple.objects.filter(
            Q(predicate__canonical_uri=CanonicalURIs.DIGITAL_OBJECT)
            | Q(predicate__uri__icontains="digitales")
            | Q(predicate__uri__icontains="digitalesobjekt"),
            subject_id__in=junction_ids,
        ).values_list("subject_id", "object_id")

        do_ids: List[str] = []
        do_event_map: Dict[str, List[str]] = {}
        for junction_id, do_id in do_triples:
            if do_id:
                did = str(do_id)
                do_ids.append(did)
                event_id = junction_event_map.get(junction_id)
                if event_id:
                    if did not in do_event_map:
                        do_event_map[did] = []
                    do_event_map[did].append(event_id)

        if not do_ids:
            return []

        # Deduplicate
        do_ids = list(set(do_ids))
        do_uuids = [_as_uuid(did) for did in do_ids]
        do_uuids = [d for d in do_uuids if d is not None]

        # Get digital object URIs
        do_resources = Resource.objects.filter(id__in=do_uuids).values("id", "uri")
        uri_map = {str(r["id"]): r["uri"] for r in do_resources}

        # Get file paths
        path_triples = Triple.objects.filter(
            Q(predicate__canonical_uri=CanonicalURIs.FILE_PATH)
            | Q(predicate__uri__icontains="dateipfad")
            | Q(predicate__uri__icontains="dateiname"),
            subject_id__in=do_uuids,
        ).select_related("object")

        path_map: Dict[str, str] = {}
        for t in path_triples:
            if t.object.resource_type == ResourceType.LITERAL and t.object.value:
                path_map[str(t.subject_id)] = t.object.value

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
                source_event_ids=do_event_map.get(did, []),
            ))

        return results
