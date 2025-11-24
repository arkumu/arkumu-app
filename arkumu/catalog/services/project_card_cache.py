"""Lightweight cache for project card payloads."""

from __future__ import annotations

import json
import logging
from typing import Optional

from django.core.cache import cache

logger = logging.getLogger(__name__)


class ProjectCardCache:
    """Cache card dicts per project URI to avoid rehydrating on search pages."""

    CACHE_PREFIX = "project_card:"
    TTL_SECONDS = 6 * 3600  # 6 hours; adjust as needed or tie to invalidation signals

    @classmethod
    def get(cls, project_uri: str) -> Optional[dict]:
        if not project_uri:
            return None
        cached = cache.get(f"{cls.CACHE_PREFIX}{project_uri}")
        if cached is None:
            return None
        try:
            return json.loads(cached)
        except Exception:
            logger.warning("ProjectCardCache: failed to decode cache entry for %s", project_uri)
            return None

    @classmethod
    def set(cls, project_uri: str, card: dict) -> None:
        if not project_uri or not card:
            return
        try:
            cache.set(f"{cls.CACHE_PREFIX}{project_uri}", json.dumps(card), cls.TTL_SECONDS)
        except Exception:
            logger.warning("ProjectCardCache: failed to encode cache entry for %s", project_uri)

    @classmethod
    def delete(cls, project_uri: str) -> None:
        if not project_uri:
            return
        cache.delete(f"{cls.CACHE_PREFIX}{project_uri}")
