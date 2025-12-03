"""HMT adapter - uses ereignis predicate, lacks some canonical URIs.

Junction pattern: junction -> ereignis -> event
HMT predicates often lack canonical_uri mappings in the database.
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
