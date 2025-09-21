"""Service for bulk caching Wikidata entities locally."""

from __future__ import annotations

import logging
from typing import Dict, Iterable, List, Optional, Sequence

import requests
from django.db import transaction
from django.utils import timezone

from arkumu.metadata.models import WikidataEntity

logger = logging.getLogger(__name__)


class WikidataEntityCacheService:
    """Resolve and persist Wikidata entities in bulk."""

    API_URL = "https://www.wikidata.org/w/api.php"
    MAX_BATCH_SIZE = 50
    DEFAULT_LANGUAGES: Sequence[str] = ("de", "en")
    USER_AGENT = "arkumu/1.0 (https://arkumu.nrw; kontakt@arkumu.nrw)"

    def __init__(self, languages: Optional[Sequence[str]] = None) -> None:
        self.languages = tuple(languages) if languages else self.DEFAULT_LANGUAGES

    def ensure_cached(
        self,
        wikidata_ids: Iterable[str],
        *,
        force_refresh: bool = False,
    ) -> List[str]:
        """Ensure that the provided Wikidata IDs are cached locally.

        Returns a list of identifiers that were newly fetched/updated.
        """

        normalized = self._normalize_ids(wikidata_ids)
        if not normalized:
            return []

        if not force_refresh:
            existing = set(
                WikidataEntity.objects.filter(wikidata_id__in=normalized)
                .values_list("wikidata_id", flat=True)
            )
            pending = [qid for qid in normalized if qid not in existing]
        else:
            pending = normalized

        updated: List[str] = []
        for chunk in self._chunked(pending, self.MAX_BATCH_SIZE):
            payload = self._fetch(chunk)
            if not payload:
                continue
            saved = self._upsert_payload(payload)
            updated.extend(saved)

        logger.info(
            "Wikidata cache sync completed – %d entities processed (force=%s)",
            len(updated),
            force_refresh,
        )
        return updated

    def get_label(self, wikidata_id: str, language: str = "de") -> Optional[str]:
        """Return a cached label if available."""

        qid = self._normalize_id(wikidata_id)
        if not qid:
            return None

        try:
            entity = WikidataEntity.objects.get(wikidata_id=qid)
        except WikidataEntity.DoesNotExist:
            return None

        if language.startswith("de"):
            return entity.label_de or None
        if language.startswith("en"):
            return entity.label_en or entity.label_de or None
        return entity.label_de or entity.label_en or None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _fetch(self, wikidata_ids: Sequence[str]) -> Dict[str, Dict]:
        params = {
            "action": "wbgetentities",
            "format": "json",
            "props": "labels|descriptions|aliases",
            "ids": "|".join(wikidata_ids),
            "languages": "|".join(self.languages),
        }

        headers = {"User-Agent": self.USER_AGENT}

        try:
            response = requests.get(self.API_URL, params=params, headers=headers, timeout=5)
            response.raise_for_status()
            data = response.json()
        except requests.RequestException as exc:  # pragma: no cover - network failure logging
            logger.error("Failed to fetch Wikidata entities %s: %s", wikidata_ids, exc)
            return {}

        return data.get("entities", {})

    @transaction.atomic
    def _upsert_payload(self, entities: Dict[str, Dict]) -> List[str]:
        saved: List[str] = []
        resolved_at = timezone.now()

        for entity_id, payload in entities.items():
            qid = self._normalize_id(entity_id)
            if not qid:
                continue

            labels = payload.get("labels", {})
            descriptions = payload.get("descriptions", {})
            aliases = payload.get("aliases", {})

            defaults = {
                "label_de": self._extract_label(labels, "de"),
                "label_en": self._extract_label(labels, "en"),
                "description_de": self._extract_description(descriptions, "de"),
                "aliases_de": self._extract_aliases(aliases, "de"),
                "raw_payload": payload,
                "last_resolved_at": resolved_at,
            }

            WikidataEntity.objects.update_or_create(
                wikidata_id=qid,
                defaults=defaults,
            )
            saved.append(qid)

        return saved

    @staticmethod
    def _extract_label(labels: Dict, language: str) -> str:
        value = labels.get(language) or labels.get(language.split("-")[0])
        if value and isinstance(value, dict):
            return value.get("value", "")
        if value and isinstance(value, str):
            return value
        return ""

    @staticmethod
    def _extract_description(descriptions: Dict, language: str) -> str:
        value = descriptions.get(language) or descriptions.get(language.split("-")[0])
        if value and isinstance(value, dict):
            return value.get("value", "")
        if value and isinstance(value, str):
            return value
        return ""

    @staticmethod
    def _extract_aliases(aliases: Dict, language: str) -> List[str]:
        entries = aliases.get(language) or []
        results = []
        for entry in entries:
            if isinstance(entry, dict):
                value = entry.get("value")
            else:
                value = entry
            if value:
                results.append(str(value))
        return results

    @staticmethod
    def _normalize_id(value: str) -> Optional[str]:
        if not value:
            return None
        value = value.strip().upper()
        if not value:
            return None
        if not value.startswith("Q"):
            if value.isdigit():
                value = f"Q{value}"
            else:
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

    @staticmethod
    def _chunked(sequence: Sequence[str], size: int) -> Iterable[List[str]]:
        for index in range(0, len(sequence), size):
            yield list(sequence[index:index + size])
