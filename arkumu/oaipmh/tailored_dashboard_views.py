"""Dedicated Tailored OAI-PMH dashboard and proxy views."""

from __future__ import annotations

import logging
from typing import List, Optional

from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from arkumu.metadata.services.oai_stats import (
    OAIDashboardSnapshot,
    _summarize_by_institution,
    classify_project_access,
)
from arkumu.users.mixins import general_login_required

from arkumu.oaipmh.views.config import (
    _force_curated_links,
    _force_db_mode,
    _force_tailored_mode,
)
from arkumu.oaipmh.views.projects import _build_tailored_project_hint_from_resource
from arkumu.oaipmh.views.tailored import _tailored_resources_queryset
from arkumu.oaipmh.views.router import oai_tailored_endpoint

from .dashboard_views import _proxy_oai_request


logger = logging.getLogger(__name__)


def _build_tailored_oai_dashboard_snapshot() -> OAIDashboardSnapshot:
    """Assemble curated/tailored harvest metrics for dashboard display."""

    harvestable_projects = []
    total_objects = 0

    with _force_db_mode(True), _force_curated_links(True), _force_tailored_mode(True):
        queryset = _tailored_resources_queryset()
        for resource in queryset.iterator(chunk_size=100):
            project = _build_tailored_project_hint_from_resource(resource)
            if not project or not project.harvestable:
                continue
            harvestable_projects.append(project)
            total_objects += sum(1 for obj in project.digital_objects if obj.harvestable)

    accessible, blocked, missing = classify_project_access(harvestable_projects)
    summaries = _summarize_by_institution(
        harvestable_projects,
        accessible_uris=accessible,
        blocked_uris=blocked,
        missing_resource_uris=missing,
    )

    return OAIDashboardSnapshot(
        generated_at=timezone.now(),
        total_projects=len(harvestable_projects),
        total_accessible_projects=len(accessible),
        total_blocked_projects=len(blocked),
        total_missing_resources=len(missing),
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
