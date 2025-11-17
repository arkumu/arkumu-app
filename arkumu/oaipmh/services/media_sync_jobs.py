"""Utility helpers for tracking async media sync jobs via cache."""

from __future__ import annotations

from typing import Any, Dict
from uuid import uuid4

from django.core.cache import cache

JOB_CACHE_PREFIX = "oai_media_sync_job:"
JOB_CACHE_TTL_SECONDS = 60 * 30  # 30 minutes


def _job_cache_key(job_id: str) -> str:
    return f"{JOB_CACHE_PREFIX}{job_id}"


def create_job(
    *,
    organization_code: str,
    user_id: int | None,
    filters: Dict[str, Any],
) -> str:
    job_id = str(uuid4())
    state: Dict[str, Any] = {
        "status": "pending",
        "message": "",
        "organization_code": organization_code,
        "user_id": user_id,
        "filters": filters,
        "seed_summary": {},
        "sync_summary": {},
    }
    cache.set(_job_cache_key(job_id), state, JOB_CACHE_TTL_SECONDS)
    return job_id


def get_job(job_id: str) -> Dict[str, Any] | None:
    return cache.get(_job_cache_key(job_id))


def update_job(job_id: str, **updates: Any) -> Dict[str, Any] | None:
    state = get_job(job_id)
    if state is None:
        return None
    state.update(updates)
    cache.set(_job_cache_key(job_id), state, JOB_CACHE_TTL_SECONDS)
    return state


def delete_job(job_id: str) -> None:
    cache.delete(_job_cache_key(job_id))
