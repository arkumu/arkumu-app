"""FUK/RSH/DET adapter - uses canonical junction pattern.

Junction pattern: junction -> im-ereignis -> event
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


class FukAdapter(InstitutionAdapter):
    """Adapter for FUK, RSH, DET institutions.

    These institutions use the canonical junction pattern:
    - Junction entities link to events via 'im-ereignis' predicate
    - Canonical URIs are properly set on predicates
    """

    ORG_CODE = "fuk"
    JUNCTION_PREDICATE = CanonicalURIs.IM_EREIGNIS

    def _find_junctions(
        self,
        project_uuid: uuid.UUID,
        event_ids: Optional[Sequence[str]],
    ) -> tuple[Set[uuid.UUID], Dict[uuid.UUID, uuid.UUID]]:
        """Find junctions via im-ereignis -> event pattern."""
        from arkumu.metadata.models.triples import Triple

        if not event_ids:
            return set(), {}

        event_uuids = [_as_uuid(eid) for eid in event_ids]
        event_uuids = [e for e in event_uuids if e is not None]
        if not event_uuids:
            return set(), {}

        # Find junctions pointing to events via im-ereignis
        junction_qs = Triple.objects.filter(
            Q(predicate__canonical_uri=self.JUNCTION_PREDICATE)
            | Q(predicate__uri__icontains="im-ereignis"),
            object_id__in=event_uuids,
        )
        if self.org_code:
            junction_qs = junction_qs.filter(
                subject__organization__code__iexact=self.org_code
            )
        junction_triples = junction_qs.values_list("subject_id", "object_id")

        junction_ids: Set[uuid.UUID] = set()
        junction_event_map: Dict[uuid.UUID, uuid.UUID] = {}
        for junction_id, event_id in junction_triples:
            junction_ids.add(junction_id)
            junction_event_map[junction_id] = event_id

        return junction_ids, junction_event_map


# RSH and DET use the same pattern as FUK
class RshAdapter(FukAdapter):
    """RSH adapter - same pattern as FUK."""
    ORG_CODE = "rsh"


class DetAdapter(FukAdapter):
    """DET adapter - same pattern as FUK."""
    ORG_CODE = "det"
