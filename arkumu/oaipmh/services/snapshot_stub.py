"""Lightweight snapshot provider used for tests/dev environments."""

from __future__ import annotations

from typing import Callable, Dict, Optional

from django.utils import timezone

from arkumu.metadata.models.resource import Resource
from arkumu.projects import ProjectRecord, ProjectSnapshot


class InMemorySnapshotService:
    """
    Minimal ProjectSnapshotService replacement.

    Builds ProjectRecord instances on demand using a caller-provided builder
    (usually the `_fallback_record_from_storage` helper) and caches them
    in-memory for subsequent requests.
    """

    def __init__(
        self,
        *,
        record_builder: Callable[[Resource], Optional[ProjectRecord]],
        harvestable_statuses: Optional[set[str]] = None,
    ) -> None:
        if not callable(record_builder):
            raise ValueError("record_builder must be callable")
        self._record_builder = record_builder
        self._harvestable_statuses = set(harvestable_statuses or ())
        self._snapshot: Optional[ProjectSnapshot] = None
        self._index: Dict[str, ProjectRecord] = {}

    @classmethod
    def from_view_settings(
        cls,
        *,
        record_builder: Callable[[Resource], Optional[ProjectRecord]],
        harvestable_statuses: Optional[set[str]] = None,
    ) -> "InMemorySnapshotService":
        """Factory hook invoked by the OAI views when configuring the provider."""
        return cls(record_builder=record_builder, harvestable_statuses=harvestable_statuses)

    def _resource_queryset(self):
        queryset = Resource.objects.filter(
            s3fileobject__status__in=list(self._harvestable_statuses or []),
            s3fileobject__s3_key__isnull=False,
        ).exclude(s3fileobject__s3_key="")
        return queryset.distinct()

    def _build_snapshot(self):
        records = []
        index: Dict[str, ProjectRecord] = {}
        for resource in self._resource_queryset():
            record = self._record_builder(resource)
            if not record or not record.uri:
                continue
            records.append(record)
            index[record.uri] = record

        self._snapshot = ProjectSnapshot(
            projects=records,
            counts={"projects": len(records)},
            generated_at=timezone.now(),
        )
        self._index = index

    def _ensure_snapshot(self):
        if self._snapshot is None:
            self._build_snapshot()

    # Public API ------------------------------------------------------------
    def get_cross_institutional_snapshot(self, *, force_refresh: bool = False):
        if force_refresh or self._snapshot is None:
            self._build_snapshot()
        return self._snapshot

    def refresh_cross_institutional_snapshot(self):
        self._build_snapshot()
        return self._snapshot

    def get_record_by_uri(self, uri: str):
        if not uri:
            return None
        self._ensure_snapshot()
        return self._index.get(uri)
