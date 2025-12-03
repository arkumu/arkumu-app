"""KHM adapter - uses projekt -> grundereignis pattern.

Junction pattern: junction -> projekt -> grundereignis
KHM maps grundereignis to project by numeric ID:
  01-grundereignis/X -> 00-projekte/X
"""

from __future__ import annotations

import uuid
from typing import Dict, Optional, Sequence, Set

from django.db.models import Q

from arkumu.projects.adapters.base import (
    InstitutionAdapter,
    CanonicalURIs,
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
