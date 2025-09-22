"""Caching helpers for surfacing recent metadata submissions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, List, Optional

from django.utils import timezone

from arkumu.cache.services.base_cache_service import BaseCacheService


@dataclass
class RecentMetadataEntry:
    """Lightweight summary of a metadata submission."""

    title: str
    uri: str
    organization_code: str
    saved_at: datetime
    resource_id: Optional[str] = None


class _MetadataEntryCache(BaseCacheService):
    """Cache wrapper scoped to metadata entry utilities."""

    def __init__(self) -> None:
        super().__init__("metadata")

    def fetch(self, organization_code: str) -> List[dict]:
        return self.get_cached("recent_entries", organization=organization_code) or []

    def store(self, organization_code: str, entries: List[dict]) -> None:
        self.set_cached(
            "recent_entries",
            entries,
            ttl_key="metadata_recent_entries",
            organization=organization_code,
        )


class RecentMetadataEntryService:
    """Expose recent metadata submissions for quick feedback loops."""

    MAX_ENTRIES = 8

    def __init__(self) -> None:
        self._cache = _MetadataEntryCache()

    def record_entry(
        self,
        *,
        organization_code: str,
        title: Optional[str],
        uri: Optional[str],
        resource_id: Optional[str],
    ) -> None:
        """Push a new submission to the per-organization cache."""

        normalized_title = (title or "Unbenanntes Projekt").strip()
        payload = {
            "title": normalized_title or "Unbenanntes Projekt",
            "uri": uri or "",
            "organization_code": organization_code,
            "saved_at": timezone.now().isoformat(),
            "resource_id": resource_id or "",
        }
        entries = self._cache.fetch(organization_code)

        # Remove duplicates for the same URI before prepending the new entry.
        filtered = [item for item in entries if item.get("uri") != payload["uri"]]
        filtered.insert(0, payload)
        trimmed = filtered[: self.MAX_ENTRIES]

        self._cache.store(organization_code, trimmed)

    def list_recent_entries(
        self,
        *,
        organization_code: Optional[str],
        fallback_codes: Iterable[str],
        limit: int = 6,
    ) -> List[RecentMetadataEntry]:
        """Return the most recent submissions for the selected organization.

        If no organization is selected yet, aggregate across the provided fallback
        codes (typically the allowed organization list).
        """

        codes: List[str]
        if organization_code:
            codes = [organization_code]
        else:
            codes = list({code for code in fallback_codes if code})
        if not codes:
            return []

        raw_entries: List[dict] = []
        for code in codes:
            raw_entries.extend(self._cache.fetch(code))

        def _parse(entry: dict) -> RecentMetadataEntry:
            saved_raw = entry.get("saved_at")
            try:
                saved_at = datetime.fromisoformat(saved_raw) if saved_raw else timezone.now()
            except ValueError:
                saved_at = timezone.now()
            return RecentMetadataEntry(
                title=entry.get("title", "Unbenanntes Projekt"),
                uri=entry.get("uri", ""),
                organization_code=entry.get("organization_code", ""),
                saved_at=saved_at,
                resource_id=entry.get("resource_id") or None,
            )

        parsed = [_parse(item) for item in raw_entries]
        sorted_entries = sorted(parsed, key=lambda item: item.saved_at, reverse=True)
        return sorted_entries[:limit]
