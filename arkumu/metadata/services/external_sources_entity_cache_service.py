"""Service for bulk caching Wikidata entities locally."""

from __future__ import annotations

import itertools
import logging
from collections import defaultdict
from enum import Enum
from functools import singledispatchmethod
from typing import Iterable, List, Optional, Any

import requests
from django.db import transaction
from django.utils import timezone

from arkumu.metadata.models import ExternalSourcesEntity, Triple, Resource, ResourceType

logger = logging.getLogger(__name__)


class ExternalSourcesEntityCacheService:
    """Resolve and persist Wikidata entities in bulk."""
    class Source(Enum):
        WD="https://query.wikidata.org/sparql"

    USER_AGENT = "arkumu/1.0 (https://arkumu.nrw; kontakt@arkumu.nrw)"

    @singledispatchmethod
    def ensure_cached(
        self,
        data_ids: Iterable[str],
        property_ids: Iterable[str],
        source: Source,
        *,
        force_refresh: bool = False,
    ) -> List[str]:
        """Ensure that the provided IDs are cached locally.

        Returns a list of identifiers that were newly fetched/updated.
        """
        if data_ids is None or property_ids is None or source is None:
            return []
        normalized_q = self._normalize_ids(data_ids)
        if not normalized_q:
            return []
        normalized_p = self._normalize_ids(property_ids)
        if not normalized_p:
            return []
        normalized = itertools.product(normalized_q, normalized_p)

        if not force_refresh:
            existing = set(
                ExternalSourcesEntity.objects.filter(data_id__in=normalized_q)
                .values_list("data_id", "property")
            )
            pending = [qid for qid in normalized if qid not in existing]
        else:
            pending = normalized

        to_fetch = defaultdict(list)
        for q, p in pending:
            to_fetch[p].append(q)
        fetched = self._fetch(to_fetch, source)
        logger.info(fetched)
        ExternalSourcesEntity.objects.bulk_create([ExternalSourcesEntity(**row) for row in fetched],
                                                  update_conflicts=True,
                                                  update_fields=["datum", "updated_at"],
                                                  unique_fields=["source", "data_id", "property"])

        logger.info(
            "External entities cache sync completed – %d entities processed (force=%s)",
            len(fetched),
            force_refresh,
        )
        return fetched

    @ensure_cached.register
    def _(self, force_refresh: bool = False):
        # ----------------------------------
        # Ereignis Orte
        # ----------------------------------
        pred = Resource.objects.get(canonical_uri="http://arkumu.org/data/properties/ereignisort")
        places = Triple.objects.filter(predicate=pred, object__resource_type=ResourceType.LITERAL)
        return self.ensure_cached(set([place.object.value for place in places]), ["P625"], self.Source.WD, force_refresh=force_refresh)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _fetch(self, data, source: Source) -> list[Any]:
        headers = {
            "User-Agent": self.USER_AGENT,
            "Accept": "application/sparql-results+json"
        }

        result_lines = []
        for pred, subj in data.items():
            params = {}
            match source.name:
                case "WD":
                    params = {
                        "query":
                            'SELECT ?subj ?obj '
                            'WHERE {'
                            f'   VALUES ?subj {{ {" ".join([f'wd:{i}' for i in subj])} }}'
                            f'   ?subj wdt:{pred} ?obj .'
                            '}'
                    }

            try:
                response = requests.get(source.value, params=params, headers=headers, timeout=5)
                response.raise_for_status()
                data = response.json()

                result_lines.extend([{ 'data_id': res['subj']['value'].split('/')[-1], 'property': pred, 'datum': res['obj']['value'], 'source': source.name }for res in data['results']['bindings']])

            except requests.RequestException as exc:
                logger.error("Failed to fetch entities: %s\n%s", exc, params)

        return result_lines

    @staticmethod
    def _normalize_id(value: str) -> Optional[str]:
        if not value:
            return None
        value = value.strip().upper()
        if not value:
            return None
        return value

    def _normalize_ids(self, wikidata_ids: Iterable[str]) -> List[str]:
        seen: set[str] = set()
        result: List[str] = []
        for raw_id in wikidata_ids:
            qid = self._normalize_id(raw_id)
            if qid and qid not in seen:
                seen.add(qid)
                result.append(qid)
        return result
