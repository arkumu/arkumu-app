"""KHM adapter - uses projekt -> grundereignis pattern.

Junction patterns:
- Actor-Event: junction -> projekt -> grundereignis (maps to project by numeric ID)
- Digital Object: 11_Kreuz_DigitaleObjekte_Proj junction

KHM maps grundereignis to project by numeric ID:
  01-grundereignis/X -> 00-projekte/X
"""

from __future__ import annotations

import uuid
from typing import Dict, List, Optional, Sequence, Set

from django.db.models import Q

from arkumu.projects.adapters.base import (
    InstitutionAdapter,
    CanonicalURIs,
    DigitalObjectData,
    _as_uuid,
)


class KhmAdapter(InstitutionAdapter):
    """Adapter for KHM institution.

    KHM uses a unique junction pattern:
    - Junction entities link to 'grundereignis' via 'projekt' predicate
    - Grundereignis maps to project by numeric ID (01-grundereignis/X -> 00-projekte/X)
    - Actors are associated with the project (no event_id in ActorData)
    """

    ORG_CODE = "khm"
    JUNCTION_PREDICATE = CanonicalURIs.PROJEKT

    def _find_junctions(
        self,
        project_uuid: uuid.UUID,
        event_ids: Optional[Sequence[str]],
    ) -> tuple[Set[uuid.UUID], Dict[uuid.UUID, uuid.UUID]]:
        """Find junctions via projekt -> grundereignis pattern.

        Returns empty junction_event_map since KHM links directly to project.
        """
        from arkumu.metadata.models.triples import Triple
        from arkumu.metadata.models.resource import Resource

        # Get project URI to extract numeric ID
        try:
            project_resource = Resource.objects.get(id=project_uuid)
        except Resource.DoesNotExist:
            return set(), {}

        project_uri = project_resource.uri
        if "/00-projekte/" not in project_uri:
            return set(), {}

        # Build grundereignis URI from project URI
        grundereignis_uri = project_uri.replace("/00-projekte/", "/01-grundereignis/")

        # Find grundereignis resource
        try:
            grundereignis = Resource.objects.get(uri=grundereignis_uri)
        except Resource.DoesNotExist:
            return set(), {}

        # Find junctions pointing to grundereignis via projekt predicate
        junction_triples = Triple.objects.filter(
            Q(predicate__canonical_uri=self.JUNCTION_PREDICATE)
            | Q(predicate__uri__icontains="projekt"),
            object_id=grundereignis.id,
            subject__organization__code__iexact="khm",
        ).values_list("subject_id", "object_id")

        junction_ids: Set[uuid.UUID] = set()
        for junction_id, _ in junction_triples:
            junction_ids.add(junction_id)

        # KHM has no event mapping - actors link to project directly
        return junction_ids, {}

    # -------------------------------------------------------------------------
    # Override methods for KHM patterns
    # -------------------------------------------------------------------------

    def _get_grundereignis_id(self, project_uuid: uuid.UUID) -> Optional[uuid.UUID]:
        """Get the grundereignis ID for a project.

        KHM pattern: 00-projekte/X -> 01-grundereignis/X
        """
        from arkumu.metadata.models.resource import Resource

        try:
            project_resource = Resource.objects.get(id=project_uuid)
        except Resource.DoesNotExist:
            return None

        project_uri = project_resource.uri
        if "/00-projekte/" not in project_uri:
            return None

        grundereignis_uri = project_uri.replace("/00-projekte/", "/01-grundereignis/")

        try:
            grundereignis = Resource.objects.get(uri=grundereignis_uri)
            return grundereignis.id
        except Resource.DoesNotExist:
            return None

    def _get_event_ids_for_project(self, project_uuid: uuid.UUID) -> List[str]:
        """Get event IDs via grundereignis pattern.

        KHM pattern: project (00-projekte/X) -> grundereignis (01-grundereignis/X)
        The grundereignis IS the event for KHM.
        """
        grundereignis_id = self._get_grundereignis_id(project_uuid)
        if grundereignis_id:
            return [str(grundereignis_id)]
        return []

    def get_digital_objects_for_project(self, project_id: str) -> List[DigitalObjectData]:
        """Get digital objects via grundereignis and junction table.

        KHM pattern: Uses 11_Kreuz_DigitaleObjekte_Proj junction or direct links
        from grundereignis to digital objects.
        """
        from arkumu.metadata.models.triples import Triple
        from arkumu.metadata.models.resource import Resource, ResourceType

        project_uuid = _as_uuid(project_id)
        if not project_uuid:
            return []

        # Get grundereignis ID
        grundereignis_id = self._get_grundereignis_id(project_uuid)

        # Collect digital object IDs from multiple sources
        do_ids: List[str] = []
        do_event_map: Dict[str, List[str]] = {}

        # 1. Direct links from project
        project_do_triples = Triple.objects.filter(
            Q(predicate__canonical_uri=CanonicalURIs.DIGITAL_OBJECT)
            | Q(predicate__uri__icontains="digitales-objekt")
            | Q(predicate__uri__icontains="digitaleobjekte"),
            subject_id=project_uuid,
        ).values_list("object_id", flat=True)

        for do_id in project_do_triples:
            if do_id:
                do_ids.append(str(do_id))

        # 2. Direct links from grundereignis
        if grundereignis_id:
            grundereignis_do_triples = Triple.objects.filter(
                Q(predicate__canonical_uri=CanonicalURIs.DIGITAL_OBJECT)
                | Q(predicate__uri__icontains="digitales-objekt")
                | Q(predicate__uri__icontains="digitaleobjekte"),
                subject_id=grundereignis_id,
            ).values_list("object_id", flat=True)

            for do_id in grundereignis_do_triples:
                if do_id:
                    did = str(do_id)
                    do_ids.append(did)
                    if did not in do_event_map:
                        do_event_map[did] = []
                    do_event_map[did].append(str(grundereignis_id))

        # 3. Via junction table (11_Kreuz_DigitaleObjekte_Proj)
        # Junction links to project via Projekt_ID and to digital object
        # Use URI pattern instead of entity_type (which doesn't exist on Resource)
        junction_triples = Triple.objects.filter(
            Q(predicate__canonical_uri=CanonicalURIs.PROJEKT)
            | Q(predicate__uri__icontains="/projekt"),
            object_id=project_uuid,
            subject__organization__code__iexact="khm",
            subject__uri__icontains="kreuz-digitaleobjekte",
        ).values_list("subject_id", flat=True)

        junction_ids = list(junction_triples)

        if not junction_ids and grundereignis_id:
            # Try with grundereignis
            try:
                junction_triples = Triple.objects.filter(
                    Q(predicate__canonical_uri=CanonicalURIs.PROJEKT)
                    | Q(predicate__uri__icontains="/projekt"),
                    object_id=grundereignis_id,
                    subject__organization__code__iexact="khm",
                ).values_list("subject_id", flat=True)
                junction_ids = list(junction_triples)
            except Exception:
                junction_ids = []

        if junction_ids:
            # Find digital object links from junctions
            junction_do_triples = Triple.objects.filter(
                Q(predicate__canonical_uri=CanonicalURIs.DIGITAL_OBJECT)
                | Q(predicate__uri__icontains="digitales")
                | Q(predicate__uri__icontains="dat-id"),
                subject_id__in=junction_ids,
            ).values_list("object_id", flat=True)

            for do_id in junction_do_triples:
                if do_id:
                    did = str(do_id)
                    do_ids.append(did)
                    if grundereignis_id and did not in do_event_map:
                        do_event_map[did] = [str(grundereignis_id)]

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
            | Q(predicate__uri__icontains="dateipfad"),
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
