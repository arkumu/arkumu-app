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

from huey.contrib.djhuey import db_task

from arkumu.metadata.models import ExternalSourcesEntity, Triple, Resource, ResourceType

logger = logging.getLogger(__name__)

class ExternalSourcesEntityCacheService:
    """Resolve and persist Wikidata entities in bulk."""
    class Source(Enum):
        WD="https://query.wikidata.org/sparql"

    USER_AGENT = "arkumu/1.0 (https://arkumu.nrw; kontakt@arkumu.nrw)"

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

        if len(data_ids) > 100:
            ret = []
            data_ids = list(data_ids)
            for i in range (0, len(data_ids), 100):
                ret.append(self.ensure_cached(data_ids[i:i+100], property_ids, source, force_refresh=force_refresh))
            return ret

        if data_ids is None or property_ids is None or source is None:
            return []
        normalized_q = self._normalize_ids(data_ids)
        if not normalized_q:
            return []
        normalized_p = self._normalize_ids(property_ids)
        if not normalized_p:
            return []
        normalized = [*itertools.product(normalized_q, normalized_p)]

        if not force_refresh:
            existing = set(
                ExternalSourcesEntity.objects.filter(data_id__in=normalized_q)
                .values_list("data_id", "property")
            )
            pending = [qid for qid in normalized if qid not in existing]
        else:
            pending = normalized
        ExternalSourcesEntity.objects.filter(data_id__in=[q for q, p in pending], property__in=[p for q, p in pending], source=source.name).delete()

        to_fetch = defaultdict(list)
        for q, p in pending:
            to_fetch[p].append(q)
        fetched = self._fetch(to_fetch, source)

        ExternalSourcesEntity.objects.bulk_create([ExternalSourcesEntity(**row) for row in fetched])

        logger.info(
            "Querying one batch of external entities completed – %d entities processed (force=%s)",
            len(fetched),
            force_refresh,
        )
        return fetched

    def ensure_cached_all(self, force_refresh: bool = False):
        # ----------------------------------
        # Ereignis Orte
        # ----------------------------------
        ereignisort_preds = self._resolve_predicates("http://arkumu.org/data/properties/ereignisort")
        if ereignisort_preds:
            ereignisort_values = set(
                Triple.objects.filter(
                    predicate__in=ereignisort_preds,
                    object__resource_type=ResourceType.LITERAL,
                    object__value__isnull=False,
                ).values_list("object__value", flat=True)
            )
            if ereignisort_values:
                self.ensure_cached(ereignisort_values, ["P625", "label_de"], self.Source.WD, force_refresh=force_refresh)

        schlagwort_preds = self._resolve_predicates("http://arkumu.org/data/properties/schlagwort")
        if schlagwort_preds:
            schlagwort_values = set(
                Triple.objects.filter(
                    predicate__in=schlagwort_preds,
                    object__value__isnull=False,
                ).values_list("object__value", flat=True)
            )
            if schlagwort_values:
                self.ensure_cached(schlagwort_values, ["label_de"], self.Source.WD, force_refresh=force_refresh)

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
                    if pred == 'label_de':
                        params = {
                            "query":
                                'SELECT ?subj ?obj '
                                'WHERE {'
                                f'   VALUES ?subj {{ {" ".join([f'wd:{i}' for i in subj])} }} '
                                '    SERVICE wikibase:label { '
                                '       bd:serviceParam wikibase:language "de" . '
                                '       ?subj rdfs:label ?obj .'
                                '    }'
                                '}'
                        }
                    else:
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
        value = value.strip()
        if value[0] == 'q' or value[0] == 'p':
            value = value.upper()
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

    def _resolve_predicates(self, canonical_uri: str) -> list[Resource]:
        predicates = list(
            Resource.objects.filter(
                canonical_uri=canonical_uri,
                resource_type=ResourceType.PROPERTY,
            )
        )

        if not predicates:
            logger.warning("No predicate resources found for canonical URI %s", canonical_uri)
            return []

        if len(predicates) > 1:
            logger.info(
                "Multiple predicate resources found for canonical URI %s; processing all %d variants",
                canonical_uri,
                len(predicates),
            )

        return predicates
