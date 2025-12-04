"""OAI-PMH dashboard views for managing media links and monitoring OAI endpoints."""

import json
import logging
from collections import defaultdict
from io import StringIO
from typing import Any, Dict, Iterable, List, Optional, Set

from django.conf import settings
from django.contrib import messages
from django.core.management import call_command
from django.db import models, transaction
from django.db.models import Count, Q, Prefetch, Max, F, Exists, OuterRef
from django.core.paginator import Paginator, EmptyPage
from django.http import HttpResponse, HttpResponseBadRequest, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.test import RequestFactory
from django.urls import reverse
from django.utils import timezone
from django.utils.html import escape
from django.views.decorators.http import require_POST, require_http_methods

from arkumu.metadata.models.resource import PublicAccessLevel, Resource, ResourceType
from arkumu.metadata.models.triples import Triple
from arkumu.users.mixins import general_login_required
from arkumu.users.models import Organization
from arkumu.oaipmh.models import OAIProjectMediaLink, OAIProjectPublication, OAIMediaSyncState
from arkumu.oaipmh.services import OAIProjectMediaSyncService
from arkumu.oaipmh.services.media_sync_planner import (
    collect_publication_candidate_ids,
    collect_seed_candidate_ids,
    get_sync_state,
)
from arkumu.oaipmh.views import (
    _restrict_to_harvestable_files,
    _project_type_filter,
    _build_identifier,
)
from arkumu.oaipmh.views.router import oai_endpoint, oai_db_endpoint
from arkumu.oaipmh.services.oai_project_assembler import OAIProjectAssembler, AssemblyContext
from arkumu.oaipmh.oai_project import OAIProjectBuilder, HARVESTABLE_STORAGE_STATUSES
from arkumu.oaipmh.oai_project_tailored import OAIProjectBuilderTailored
from arkumu.metadata.services.oai_stats import (
    build_oai_dashboard_snapshot,
    classify_project_access,
    OAIDashboardSnapshot,
    _summarize_by_institution,
)
from arkumu.cache.services.project_cache_service import ProjectCacheService
from arkumu.storage.models.s3_file_objects import S3FileObject
from arkumu.oaipmh.services import media_sync_jobs


logger = logging.getLogger(__name__)

_oai_proxy_request_factory = RequestFactory()


def _proxy_oai_request(request, *, handler, internal_path: str):
    """Shared proxy helper for snapshot and DB OAI endpoints."""

    if request.method != "GET":
        return HttpResponseBadRequest("Only GET requests are supported")

    if "verb" not in request.GET:
        return HttpResponseBadRequest("Missing required 'verb' parameter")

    query_items = [(key, value) for key, values in request.GET.lists() for value in values]
    internal_request = _oai_proxy_request_factory.get(internal_path, data=query_items)

    # Propagate authenticated user and session context for downstream checks
    internal_request.user = request.user
    internal_request.session = request.session

    # Preserve host/scheme metadata so OAI responses build correct URLs
    internal_request.META["HTTP_HOST"] = request.get_host()
    internal_request.META["SERVER_NAME"] = request.META.get("SERVER_NAME", request.get_host())
    internal_request.META["SERVER_PORT"] = request.META.get("SERVER_PORT", "443" if request.is_secure() else "80")
    internal_request.META["wsgi.url_scheme"] = request.scheme

    # Mark the request as trusted internal traffic
    internal_request.META["REMOTE_ADDR"] = "127.0.0.1"
    internal_request.META["HTTP_X_INTERNAL_OAI_BYPASS"] = "1"

    return handler(internal_request)


@general_login_required
def oai_proxy(request):
    """Proxy the snapshot-backed OAI-PMH endpoint for authenticated dashboard users."""
    return _proxy_oai_request(request, handler=oai_endpoint, internal_path="/oai/")


@general_login_required
def oai_db_proxy(request):
    """Proxy the DB-backed OAI-PMH endpoint for authenticated dashboard users."""
    return _proxy_oai_request(request, handler=oai_db_endpoint, internal_path="/oai/db/")


@general_login_required
def oai_widget(request):
    """Return the OAI snapshot widget content on demand (HTMX-friendly)."""

    oai_snapshot = None
    try:
        oai_snapshot = build_oai_dashboard_snapshot()
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.exception("Failed to build OAI dashboard snapshot: %s", exc)

    template_name = "oai/partials/oai_widget_card.html"
    return render(
        request,
        template_name,
        {
            "oai_snapshot": oai_snapshot,
        },
    )


def _build_oai_endpoint_summaries(oai_snapshot):
    endpoints = []
    if oai_snapshot and oai_snapshot.institution_summaries:
        for summary in oai_snapshot.institution_summaries:
            if summary.accessible_count > 0:
                endpoints.append(
                    {
                        "code": summary.code,
                        "label": summary.label or summary.code.upper(),
                        "project_count": summary.project_count,
                        "accessible_count": summary.accessible_count,
                    }
                )
    return endpoints


def _build_db_oai_dashboard_snapshot() -> OAIDashboardSnapshot:
    """Assemble DB-backed harvest stats without relying on cached snapshots."""

    builder = OAIProjectBuilderTailored()
    assembler = OAIProjectAssembler()

    # Accept any slug after /entities/projekt/, not just numeric IDs,
    # because canonical URIs vary per institution (e.g., proj-1, khm-0001, etc.).
    project_uri_pattern = r"/entities/projekt/[^/]+$"
    queryset = Resource.objects.filter(
        resource_type=ResourceType.ENTITY,
    ).select_related("organization")

    project_type_q = _project_type_filter()
    if project_type_q is not None:
        queryset = queryset.filter(project_type_q)
    else:
        queryset = queryset.filter(
            Q(canonical_uri__regex=project_uri_pattern)
            | Q(uri__regex=project_uri_pattern)
        )

    queryset = _restrict_to_harvestable_files(queryset).order_by("updated_at", "id")

    harvestable_projects = []
    total_objects = 0

    for resource in queryset.iterator(chunk_size=100):
        try:
            record = assembler.build_record(AssemblyContext(resource=resource))
        except Exception:
            logger.exception("DB dashboard: failed to assemble record for %s", getattr(resource, "uri", "unknown"))
            continue

        if not record:
            continue

        try:
            project = builder.from_project_record(
                record,
                skip_shared_event_filter=True,
                skip_format_exclusion=True,
            )
        except Exception:
            logger.exception("DB dashboard: failed to build OAI project for %s", getattr(resource, "uri", "unknown"))
            continue

        if not project.harvestable:
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


@general_login_required
@require_http_methods(["GET"])
def oai_snapshot_dashboard(request):
    """Display the legacy snapshot-backed OAI endpoints."""

    oai_snapshot = None
    try:
        oai_snapshot = build_oai_dashboard_snapshot()
    except Exception as exc:
        logger.exception("Failed to build OAI dashboard snapshot: %s", exc)

    # Build endpoint examples for each institution
    endpoints = _build_oai_endpoint_summaries(oai_snapshot)

    return render(
        request,
        'oai/oai_snapshot_dashboard.html',
        {
            'endpoints': endpoints,
            'oai_snapshot': oai_snapshot,
        },
    )


def oai_endpoints_info(request):  # Backwards-compat alias for legacy URL
    return oai_snapshot_dashboard(request)


@general_login_required
@require_http_methods(["GET"])
def oai_db_dashboard(request):
    """Describe the DB-backed OAI endpoint with quick links and parity notes."""

    oai_snapshot = None
    try:
        oai_snapshot = _build_db_oai_dashboard_snapshot()
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.exception("Failed to build DB OAI dashboard snapshot: %s", exc)
        oai_snapshot = None

    db_endpoint_url = request.build_absolute_uri(reverse('oai_admin:db-endpoint'))
    snapshot_endpoint_url = request.build_absolute_uri(reverse('metadata:oai_proxy'))
    endpoints = _build_oai_endpoint_summaries(oai_snapshot)

    return render(
        request,
        'oai/oai_db_dashboard.html',
        {
            'oai_snapshot': oai_snapshot,
            'endpoints': endpoints,
            'db_endpoint_url': db_endpoint_url,
            'snapshot_endpoint_url': snapshot_endpoint_url,
        },
    )


@general_login_required
@require_http_methods(["GET"])
def oai_preserialized_dashboard(request):
    """Dashboard for the pre-serialized OAI snapshot endpoint."""
    from arkumu.oaipmh.models import OAISnapshotMeta, OAISnapshotRecord

    meta = OAISnapshotMeta.get_current()
    endpoints = []

    if meta:
        # Build endpoint summaries from OAISnapshotRecord counts
        org_counts = (
            OAISnapshotRecord.objects
            .values("organization__code", "organization__name")
            .annotate(count=models.Count("id"))
            .order_by("-count")
        )

        for row in org_counts:
            org_code = row.get("organization__code")
            if not org_code:
                continue
            endpoints.append({
                "code": org_code,
                "label": row.get("organization__name") or org_code.upper(),
                "accessible_count": row["count"],
            })

    snapshot_proxy_url = request.build_absolute_uri(reverse("metadata:oai_preserialized_proxy"))

    return render(
        request,
        "oai/oai_preserialized_dashboard.html",
        {
            "snapshot_meta": meta,
            "endpoints": endpoints,
            "snapshot_proxy_url": snapshot_proxy_url,
        },
    )


@general_login_required
def oai_preserialized_proxy(request):
    """Proxy pre-serialized OAI requests through the Django session."""
    from arkumu.oaipmh.views.snapshot import oai_snapshot_handler

    return _proxy_oai_request(
        request,
        handler=oai_snapshot_handler,
        internal_path="/oai/snapshot/",
    )
