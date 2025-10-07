"""Helpers for summarizing OAI-PMH harvestable project availability."""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, List, Optional

from django.utils import timezone

from arkumu.cache.services.project_cache_service import ProjectCacheService
from arkumu.oaipmh.oai_project import OAIProject, OAIProjectBuilder
from arkumu.projects.services import ProjectSnapshotService


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class InstitutionHarvestSummary:
    """Aggregated harvestable project availability for an institution."""

    code: str
    label: Optional[str]
    project_count: int


@dataclass(frozen=True)
class OAIDashboardSnapshot:
    """Lightweight projection exposed to the metadata dashboard."""

    generated_at: datetime
    total_projects: int
    institution_summaries: List[InstitutionHarvestSummary]
    total_harvestable_objects: int


def _institution_bucket(project: OAIProject) -> tuple[str, Optional[str]]:
    """Normalize institution identifiers used for aggregation."""

    code = (project.institution_code or "").strip() or "unknown"
    label = None
    if getattr(project.record, "institution", None):
        label = getattr(project.record.institution, "label", None)
        label = label.strip() if isinstance(label, str) else label
    return code.lower(), label


def build_oai_dashboard_snapshot(
    *,
    snapshot_service: Optional[ProjectSnapshotService] = None,
    project_builder: Optional[OAIProjectBuilder] = None,
    cache_service: Optional[ProjectCacheService] = None,
) -> OAIDashboardSnapshot:
    """Return aggregated harvestable project metrics for dashboard display."""

    project_builder = project_builder or OAIProjectBuilder()
    snapshot = None

    if snapshot_service is not None:
        snapshot = snapshot_service.get_cross_institutional_snapshot()
    else:
        cache_service = cache_service or ProjectCacheService()
        snapshot = cache_service.get_cross_institutional_snapshot()

    if snapshot is None:
        logger.info(
            "OAI dashboard snapshot: cache is empty; returning zeroed metrics until warmers run."
        )
        return OAIDashboardSnapshot(
            generated_at=timezone.now(),
            total_projects=0,
            institution_summaries=[],
            total_harvestable_objects=0,
        )

    harvestable_projects: List[OAIProject] = []
    total_objects = 0
    for record in snapshot.projects:
        project = project_builder.from_project_record(record)
        if not project.harvestable:
            continue
        harvestable_projects.append(project)
        harvestable_objects = [obj for obj in project.digital_objects if obj.harvestable]
        total_objects += len(harvestable_objects)

    summaries = _summarize_by_institution(harvestable_projects)

    return OAIDashboardSnapshot(
        generated_at=snapshot.generated_at,
        total_projects=len(harvestable_projects),
        institution_summaries=summaries,
        total_harvestable_objects=total_objects,
    )


def _summarize_by_institution(projects: Iterable[OAIProject]) -> List[InstitutionHarvestSummary]:
    buckets: dict[str, dict[str, object]] = defaultdict(lambda: {"label": None, "count": 0})

    for project in projects:
        code, label = _institution_bucket(project)
        bucket = buckets[code]
        bucket["count"] = int(bucket["count"]) + 1
        if label and not bucket.get("label"):
            bucket["label"] = label

    summaries = [
        InstitutionHarvestSummary(
            code=code,
            label=(bucket.get("label") or None),
            project_count=int(bucket.get("count", 0)),
        )
        for code, bucket in buckets.items()
    ]

    summaries.sort(key=lambda summary: summary.project_count, reverse=True)
    return summaries
