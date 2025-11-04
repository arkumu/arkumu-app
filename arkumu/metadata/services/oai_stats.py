"""Helpers for summarizing OAI-PMH harvestable project availability."""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Iterable, List, Optional, Set

from django.utils import timezone

from arkumu.metadata.models.resource import Resource, PublicAccessLevel
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
    accessible_count: int
    blocked_count: int
    missing_resource_count: int


@dataclass(frozen=True)
class OAIDashboardSnapshot:
    """Lightweight projection exposed to the metadata dashboard."""

    generated_at: datetime
    total_projects: int
    total_accessible_projects: int
    total_blocked_projects: int
    total_missing_resources: int
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
            total_accessible_projects=0,
            total_blocked_projects=0,
            total_missing_resources=0,
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

    accessible_uris, blocked_uris, missing_resource_uris = classify_project_access(harvestable_projects)

    summaries = _summarize_by_institution(
        harvestable_projects,
        accessible_uris=accessible_uris,
        blocked_uris=blocked_uris,
        missing_resource_uris=missing_resource_uris,
    )

    return OAIDashboardSnapshot(
        generated_at=snapshot.generated_at,
        total_projects=len(harvestable_projects),
        total_accessible_projects=len(accessible_uris),
        total_blocked_projects=len(blocked_uris),
        total_missing_resources=len(missing_resource_uris),
        institution_summaries=summaries,
        total_harvestable_objects=total_objects,
    )


def _load_project_access_map(project_uris: Iterable[str]) -> Dict[str, Dict[str, object]]:
    uris = list({uri for uri in project_uris if uri})
    if not uris:
        return {}

    resources = Resource.objects.filter(uri__in=uris).values(
        "uri", "public_access_level", "is_public_approved"
    )
    return {
        row["uri"]: {
            "public_access_level": row["public_access_level"],
            "is_public_approved": row["is_public_approved"],
        }
        for row in resources
    }


def _is_accessible(access_info: Dict[str, object]) -> bool:
    level = access_info.get("public_access_level")
    approved = bool(access_info.get("is_public_approved"))

    if level == PublicAccessLevel.RESTRICTED:
        return True
    if level == PublicAccessLevel.PUBLIC:
        return approved
    return False


def classify_project_access(projects: Iterable[OAIProject]) -> tuple[Set[str], Set[str], Set[str]]:
    uris = [project.uri for project in projects]
    access_map = _load_project_access_map(uris)

    accessible: Set[str] = set()
    blocked: Set[str] = set()
    missing: Set[str] = set()

    for project in projects:
        uri = project.uri
        info = access_map.get(uri)
        if info is None:
            missing.add(uri)
            blocked.add(uri)
            continue

        if _is_accessible(info):
            accessible.add(uri)
        else:
            blocked.add(uri)

    return accessible, blocked, missing


def _summarize_by_institution(
    projects: Iterable[OAIProject],
    *,
    accessible_uris: Set[str],
    blocked_uris: Set[str],
    missing_resource_uris: Set[str],
) -> List[InstitutionHarvestSummary]:
    buckets: dict[str, dict[str, object]] = defaultdict(
        lambda: {"label": None, "count": 0, "accessible": 0, "blocked": 0, "missing": 0}
    )

    for project in projects:
        code, label = _institution_bucket(project)
        bucket = buckets[code]
        bucket["count"] = int(bucket["count"]) + 1
        if label and not bucket.get("label"):
            bucket["label"] = label
        if project.uri in accessible_uris:
            bucket["accessible"] = int(bucket["accessible"]) + 1
        if project.uri in blocked_uris:
            bucket["blocked"] = int(bucket["blocked"]) + 1
        if project.uri in missing_resource_uris:
            bucket["missing"] = int(bucket["missing"]) + 1

    summaries = [
        InstitutionHarvestSummary(
            code=code,
            label=(bucket.get("label") or None),
            project_count=int(bucket.get("count", 0)),
            accessible_count=int(bucket.get("accessible", 0)),
            blocked_count=int(bucket.get("blocked", 0)),
            missing_resource_count=int(bucket.get("missing", 0)),
        )
        for code, bucket in buckets.items()
    ]

    summaries.sort(key=lambda summary: summary.project_count, reverse=True)
    return summaries
