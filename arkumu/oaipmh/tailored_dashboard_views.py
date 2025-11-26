"""Dedicated Tailored OAI-PMH dashboard and proxy views."""

from __future__ import annotations

import logging
from typing import List, Optional

from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from arkumu.metadata.models.resource import PublicAccessLevel, Resource
from arkumu.metadata.services.oai_stats import OAIDashboardSnapshot, InstitutionHarvestSummary
from arkumu.users.mixins import general_login_required

from arkumu.oaipmh.views.router import oai_tailored_endpoint
from arkumu.oaipmh.models import OAIProjectMediaLink, OAIProjectPublication

from .dashboard_views import _proxy_oai_request


logger = logging.getLogger(__name__)


def _is_accessible_resource(resource: Resource) -> bool:
    level = resource.public_access_level
    if level == PublicAccessLevel.RESTRICTED:
        return True
    if level == PublicAccessLevel.PUBLIC:
        return bool(resource.is_public_approved)
    return False


def _build_tailored_oai_dashboard_snapshot() -> OAIDashboardSnapshot:
    """Assemble curated/tailored harvest metrics using curated links + publications only."""

    pubs = (
        OAIProjectPublication.objects.select_related("project", "project__organization")
        .filter(is_approved=True, project__organization__is_active=True)
        .order_by("project__organization__code", "project__uri")
    )

    total_projects = 0
    total_accessible = 0
    total_blocked = 0
    total_missing = 0

    org_buckets: dict[str, dict[str, int | str | None]] = {}

    project_ids = []
    for pub in pubs:
        project = getattr(pub, "project", None)
        if project is None:
            total_missing += 1
            continue
        total_projects += 1
        project_ids.append(project.id)

        org = getattr(project, "organization", None)
        org_code = (getattr(org, "code", None) or "unknown").strip().lower()
        org_label = getattr(org, "name", None)

        bucket = org_buckets.setdefault(
            org_code,
            {"label": org_label, "project_count": 0, "accessible": 0, "blocked": 0, "missing": 0},
        )
        bucket["project_count"] = int(bucket["project_count"]) + 1

        if _is_accessible_resource(project):
            total_accessible += 1
            bucket["accessible"] = int(bucket["accessible"]) + 1
        else:
            total_blocked += 1
            bucket["blocked"] = int(bucket["blocked"]) + 1

    summaries = [
        InstitutionHarvestSummary(
            code=code,
            label=(bucket.get("label") or None),
            project_count=int(bucket.get("project_count", 0)),
            accessible_count=int(bucket.get("accessible", 0)),
            blocked_count=int(bucket.get("blocked", 0)),
            missing_resource_count=int(bucket.get("missing", 0)),
        )
        for code, bucket in org_buckets.items()
    ]
    summaries.sort(key=lambda summary: summary.project_count, reverse=True)

    # Harvestable object count = curated, non-stale links for approved publications
    total_objects = (
        OAIProjectMediaLink.objects.filter(
            project_id__in=project_ids,
            is_stale=False,
        )
        .count()
    )

    return OAIDashboardSnapshot(
        generated_at=timezone.now(),
        total_projects=total_projects,
        total_accessible_projects=total_accessible,
        total_blocked_projects=total_blocked,
        total_missing_resources=total_missing,
        institution_summaries=summaries,
        total_harvestable_objects=total_objects,
    )


def _build_tailored_endpoint_summaries(
    snapshot: Optional[OAIDashboardSnapshot],
) -> List[dict[str, object]]:
    endpoints: List[dict[str, object]] = []
    if not snapshot or not snapshot.institution_summaries:
        return endpoints

    for summary in snapshot.institution_summaries:
        if summary.accessible_count <= 0:
            continue
        endpoints.append(
            {
                "code": summary.code,
                "label": summary.label or summary.code.upper(),
                "project_count": summary.project_count,
                "accessible_count": summary.accessible_count,
            }
        )
    return endpoints


@general_login_required
@require_http_methods(["GET"])
def oai_tailored_dashboard(request):
    """Display curated/tailored OAI endpoint details and helper links."""

    tailored_snapshot: Optional[OAIDashboardSnapshot] = None
    try:
        tailored_snapshot = _build_tailored_oai_dashboard_snapshot()
    except Exception as exc:  # pragma: no cover - defensive guardrail
        logger.exception("Failed to build tailored OAI dashboard snapshot: %s", exc)

    endpoints = _build_tailored_endpoint_summaries(tailored_snapshot)
    tailored_endpoint_url = request.build_absolute_uri(reverse("oai_admin:tailored-endpoint"))
    tailored_proxy_url = request.build_absolute_uri(reverse("metadata:oai_tailored_proxy"))

    return render(
        request,
        "oai/oai_tailored_dashboard.html",
        {
            "tailored_snapshot": tailored_snapshot,
            "endpoints": endpoints,
            "tailored_endpoint_url": tailored_endpoint_url,
            "tailored_proxy_url": tailored_proxy_url,
        },
    )


@general_login_required
def oai_tailored_proxy(request):
    """Proxy tailored OAI requests through the Django session for dashboard use."""

    return _proxy_oai_request(
        request,
        handler=oai_tailored_endpoint,
        internal_path="/oai/tailored/",
    )
