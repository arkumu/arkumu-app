import json
import logging
from collections import defaultdict
from functools import wraps
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

from django.conf import settings

from django.contrib import messages
from django.core.management import call_command
from django.db import models, transaction
from django.db.models import Count, Q, Prefetch, Max, F
from django.core.paginator import Paginator, EmptyPage
from django.http import HttpResponse, HttpResponseBadRequest, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.html import escape
from django.views.decorators.http import require_POST, require_http_methods
from django.test import RequestFactory
from io import StringIO

from arkumu.importer.models import IngestSession
from arkumu.metadata.models.resource import PublicAccessLevel, Resource, ResourceType
from arkumu.metadata.models.triples import Triple
from arkumu.metadata.models.mappings import Mapping, MappingSelectionAudit
from arkumu.storage.models.upload_tracking import AsyncUploadSession
from arkumu.storage.tasks import verify_upload_session, recalculate_s3_checksums
from arkumu.storage.services.bucket_service import BucketService
from arkumu.users.mixins import general_login_required
from arkumu.users.models import Organization
from arkumu.oaipmh.models import OAIProjectMediaLink
from arkumu.oaipmh.services import OAIProjectMediaSyncService
from arkumu.oaipmh.views import (
    oai_endpoint,
    oai_db_endpoint,
    _restrict_to_harvestable_files,
    _project_type_filter,
)
from arkumu.oaipmh.services.oai_project_assembler import OAIProjectAssembler, AssemblyContext
from arkumu.oaipmh.oai_project import OAIProjectBuilder
from arkumu.metadata.services.oai_stats import (
    build_oai_dashboard_snapshot,
    classify_project_access,
    OAIDashboardSnapshot,
    _summarize_by_institution,
)
from arkumu.cache.services.project_cache_service import ProjectCacheService
from arkumu.projects.services import ProjectSnapshotService
from arkumu.common.mixins.base_coordinator import BaseCoordinatorMixin

from .dashboard_helpers import (
    build_session_entry,
    build_upload_display,
    summarize_upload_stats,
    UploadSessionDisplay,
)


logger = logging.getLogger(__name__)


def superuser_required(view_func):
    """Decorator to require superuser access for function-based views."""
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return HttpResponseForbidden(
                "<div class='alert alert-error'>Authentication required</div>"
            )
        if not request.user.is_superuser:
            return HttpResponseForbidden(
                "<div class='alert alert-error'>Access denied: Superuser privileges required</div>"
            )
        return view_func(request, *args, **kwargs)
    return wrapper

_oai_proxy_request_factory = RequestFactory()


def _maintenance_response(request, message: str, *, level: str = "info", details: str | None = None):
    if request.headers.get("HX-Request"):
        alert_classes = {
            "success": "alert alert-success",
            "warning": "alert alert-warning",
            "error": "alert alert-error",
            "info": "alert alert-info",
        }
        css_class = alert_classes.get(level, "alert alert-info")
        detail_html = f"<pre class=\"mt-2 whitespace-pre-wrap text-xs\">{escape(details)}</pre>" if details else ""
        html = f"<div class=\"{css_class}\">{escape(message)}{detail_html}</div>"
        return HttpResponse(html)

    getattr(messages, level)(request, message)
    return redirect("metadata:metadata_dashboard")


@general_login_required
@superuser_required
def metadata_dashboard(request):
    """Main dashboard view for metadata visualization and analysis."""

    stats = {
        "total_resources": Resource.objects.count(),
        "total_triples": Triple.objects.count(),
        "iri_resources": Resource.objects.filter(resource_type=ResourceType.IRI).count(),
        "literal_resources": Resource.objects.filter(resource_type=ResourceType.LITERAL).count(),
        "class_resources": Resource.objects.filter(resource_type=ResourceType.CLASS).count(),
        "property_resources": Resource.objects.filter(resource_type=ResourceType.PROPERTY).count(),
        "uploads": AsyncUploadSession.objects.count(),
        "ingests": IngestSession.objects.count(),
    }

    oai_snapshot = None
    try:
        oai_snapshot = build_oai_dashboard_snapshot()
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.exception("Failed to build OAI dashboard snapshot: %s", exc)

    bucket_service = BucketService()
    checksum_buckets = bucket_service.get_predefined_organizations()

    recent_uploads = [
        build_upload_display(session)
        for session in AsyncUploadSession.objects.select_related("user").order_by("-created_at")[:5]
    ]

    recent_ingests = IngestSession.objects.select_related("organization").order_by("-created_at")[:5]

    institutions = (
        Resource.objects.values("organization__name")
        .annotate(count=Count("id"))
        .order_by("-count")[:10]
    )

    from arkumu.users.models import Organization

    organizations_with_data = []
    for org in Organization.objects.filter(is_active=True).order_by("name"):
        triple_count = Triple.objects.for_organization(org).count()
        resource_count = Resource.objects.for_organization(org).count()
        if triple_count > 0 or resource_count > 0:
            organizations_with_data.append(
                {
                    "id": org.id,
                    "name": org.name,
                    "code": org.code,
                    "triple_count": triple_count,
                    "resource_count": resource_count,
                }
            )

    return render(
        request,
        "dashboard.html",
        {
            "stats": stats,
            "recent_uploads": recent_uploads,
            "recent_ingests": recent_ingests,
            "institutions": institutions,
            "organizations_with_data": organizations_with_data,
            "checksum_buckets": checksum_buckets,
            "oai_snapshot": oai_snapshot,
        },
    )


@general_login_required
def publish_projects_visibility(request):
    """Set all project resources for an organization to public visibility."""
    is_htmx = request.headers.get("HX-Request") == "true"

    if request.method != "POST":
        if is_htmx:
            return HttpResponse('<div class="alert alert-error">Invalid request method.</div>', status=400)
        return redirect("metadata:metadata_dashboard")

    if not request.user.is_superuser:
        error_msg = "Only superusers can publish organization projects."
        if is_htmx:
            return HttpResponse(f'<div class="alert alert-error">{error_msg}</div>', status=403)
        messages.error(request, error_msg)
        return redirect("metadata:metadata_dashboard")

    organization_id = request.POST.get("organization_id")
    if not organization_id:
        error_msg = "Select an organization to publish its projects."
        if is_htmx:
            return HttpResponse(f'<div class="alert alert-warning">{error_msg}</div>', status=400)
        messages.error(request, error_msg)
        return redirect("metadata:metadata_dashboard")

    try:
        organization = Organization.objects.get(id=organization_id)
    except Organization.DoesNotExist:
        error_msg = "The selected organization does not exist."
        if is_htmx:
            return HttpResponse(f'<div class="alert alert-error">{error_msg}</div>', status=404)
        messages.error(request, error_msg)
        return redirect("metadata:metadata_dashboard")

    # Query projects directly from database using canonical URIs (same approach as CanonicalGraphService)
    # Projects are identified by rdf:type with canonical_uri = http://arkumu.org/data/types/projekt
    RDF_TYPE_URI = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
    PROJECT_CANONICAL_TYPE = "http://arkumu.org/data/types/projekt"  # CardURIs.PROJECT_TYPE

    project_resources = Resource.objects.filter(
        organization=organization,
        subject_triples__predicate__uri=RDF_TYPE_URI,
        subject_triples__object__canonical_uri=PROJECT_CANONICAL_TYPE,
    ).distinct()

    project_count = project_resources.count()

    if project_count == 0:
        warning_msg = f"No projects were found for {organization.name}."
        if is_htmx:
            return HttpResponse(f'<div class="alert alert-warning">{warning_msg}</div>')
        messages.warning(request, warning_msg)
        return redirect("metadata:metadata_dashboard")

    now = timezone.now()
    updated = project_resources.update(
        public_access_level=PublicAccessLevel.PUBLIC,
        is_public_approved=True,
        is_public=True,
        public_approved_by=request.user,
        public_approved_at=now,
    )

    if updated == 0:
        warning_msg = f"Projects for {organization.name} were already public or no matching resources existed."
        if is_htmx:
            return HttpResponse(f'<div class="alert alert-warning">{warning_msg}</div>')
        messages.warning(request, warning_msg)
    else:
        success_msg = f"Published {updated} project resources for {organization.name}. Use the dashboard refresh control when you want to rebuild the project snapshot."
        if is_htmx:
            return HttpResponse(f'<div class="alert alert-success">{success_msg}</div>')
        messages.success(request, success_msg)

    if is_htmx:
        return HttpResponse('')
    return redirect("metadata:metadata_dashboard")


@general_login_required
def all_upload_sessions(request):
    """Displays a list of all upload sessions with their files."""

    page_number = request.GET.get("page", 1)
    per_page = 25

    sessions_qs = (
        AsyncUploadSession.objects.select_related("user")
        .annotate(
            total_files_agg=Count("files"),
            completed_files_agg=Count("files", filter=Q(files__status="completed")),
            failed_files_agg=Count("files", filter=Q(files__status="failed")),
            uploading_files_agg=Count("files", filter=Q(files__status="uploading")),
            processing_files_agg=Count("files", filter=Q(files__status="processing")),
            pending_files_agg=Count("files", filter=Q(files__status="pending")),
        )
        .order_by("-created_at")
    )

    paginator = Paginator(sessions_qs, per_page)
    try:
        page_obj = paginator.page(page_number)
    except EmptyPage:
        page_obj = paginator.page(paginator.num_pages or 1)

    # Build lightweight session displays without loading per-file rows
    entries = []
    for session in page_obj.object_list:
        uploaded_count = (getattr(session, "uploading_files_agg", 0) or 0) + (
            getattr(session, "processing_files_agg", 0) or 0
        )
        pending_count = getattr(session, "pending_files_agg", 0) or 0

        display = UploadSessionDisplay(
            id=str(session.id),
            created_at=session.created_at,
            completed_at=session.completed_at,
            status=session.status,
            status_display=session.get_status_display(),
            user=session.user,
            institution=session.organization or "Not specified",
            organization=session.organization or "",
            folder_name=session.base_folder or "",
            total_files=(getattr(session, "total_files_agg", None) or session.total_files or 0),
            completed_files=getattr(session, "completed_files_agg", 0) or 0,
            failed_files=getattr(session, "failed_files_agg", 0) or 0,
            uploaded_files=uploaded_count,
            pending_files=pending_count,
            import_stats={"duration_seconds": 0, "total_size": 0, "total_size_formatted": "0 B", "summary": {}, "error_count": 0, "error": None},
        )

        entries.append(
            {
                "session": display,
                "files": [],  # defer file details to modal/HTMX
                "file_count": display.total_files,
                "completed_files": display.completed_files,
                "failed_files": display.failed_files,
            }
        )

    total_stats = summarize_upload_stats(entries)

    return render(
        request,
        "all_upload_sessions.html",
        {
            "enhanced_sessions": entries,
            "total_stats": total_stats,
            "page_obj": page_obj,
        },
    )


@general_login_required
def all_ingest_sessions(request):
    """Displays a list of all ingest sessions with their datasets."""

    all_ingests = (
        IngestSession.objects.select_related("organization")
        .prefetch_related("import_tasks")
        .order_by("-created_at")
    )

    enhanced_sessions = []
    for session in all_ingests:
        import_tasks = list(session.import_tasks.all())

        datasets = []
        if import_tasks:
            for task in import_tasks:
                datasets.append(
                    {
                        "name": task.dataset_name,
                        "file_path": task.file_path,
                        "status": task.status,
                        "rows_processed": task.rows_processed,
                        "task_id": task.task_id,
                    }
                )
        elif session.file_paths:
            for file_path in session.file_paths:
                filename = file_path.split("/")[-1] if "/" in file_path else file_path
                datasets.append(
                    {
                        "name": filename,
                        "file_path": file_path,
                        "status": session.status,
                        "rows_processed": session.processed_rows
                        if len(session.file_paths) == 1
                        else None,
                    }
                )
        else:
            datasets.append(
                {
                    "name": session.dataset_name or session.file_name or "Unknown Dataset",
                    "file_path": session.s3_object_key,
                    "status": session.status,
                    "rows_processed": session.processed_rows,
                }
            )

        enhanced_sessions.append(
            {
                "session": session,
                "datasets": datasets,
                "dataset_count": len(datasets),
                "is_multi_dataset": len(datasets) > 1,
            }
        )

    total_stats = {
        "total_sessions": len(enhanced_sessions),
        "total_datasets": sum(item["dataset_count"] for item in enhanced_sessions),
        "completed_sessions": sum(
            1 for item in enhanced_sessions if item["session"].status == "completed"
        ),
        "failed_sessions": sum(
            1 for item in enhanced_sessions if item["session"].status == "failed"
        ),
        "processing_sessions": sum(
            1 for item in enhanced_sessions if item["session"].status == "processing"
        ),
        "total_rows_processed": 0,
        "total_resources_created": 0,
        "total_triples_created": 0,
        "sessions_with_stats": 0,
    }

    for item in enhanced_sessions:
        session = item["session"]
        if session.ingestion_stats:
            total_stats["sessions_with_stats"] += 1
            total_stats["total_rows_processed"] += session.ingestion_stats.get("rows_processed", 0)
            total_stats["total_resources_created"] += session.ingestion_stats.get(
                "resources_created", 0
            )
            total_stats["total_triples_created"] += session.ingestion_stats.get(
                "triples_created", 0
            )

    return render(
        request,
        "all_ingest_sessions.html",
        {
            "enhanced_sessions": enhanced_sessions,
            "total_stats": total_stats,
        },
    )


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
def ingest_session_stats(request, session_id):
    """HTMX endpoint to show detailed stats for a specific ingest session."""

    try:
        session = IngestSession.objects.get(pk=session_id)
        return render(
            request,
            "importer/partials/stats_modal_content.html",
            {"session": session, "show_expanded": True},
        )
    except IngestSession.DoesNotExist:
        return render(
            request,
            "partials/error_message.html",
            {"error": "Ingest session not found"},
        )


@general_login_required
def upload_session_stats(request, session_id):
    """HTMX endpoint to show detailed stats for a specific upload session."""

    try:
        session = AsyncUploadSession.objects.prefetch_related("files").get(pk=session_id)
    except AsyncUploadSession.DoesNotExist:
        return render(
            request,
            "partials/error_message.html",
            {"error": "Upload session not found"},
        )

    entry = build_session_entry(session)

    return render(
        request,
        "partials/upload_stats_modal_content.html",
        {
            "session": entry["session"],
            "files": entry["files"],
            "file_count": entry["file_count"],
            "completed_files": entry["completed_files"],
            "failed_files": entry["failed_files"],
        },
    )


@general_login_required
@require_POST
def trigger_upload_verification(request, session_id):
    """Manually trigger verification for an async upload session."""

    session = get_object_or_404(AsyncUploadSession, pk=session_id)

    if not request.user.is_staff:
        return HttpResponseForbidden("Only staff members can verify uploads.")

    if session.status == "completed":
        messages.info(request, "Verification already completed for this session.")
        redirect_to = request.POST.get("next") or request.META.get("HTTP_REFERER") or reverse("metadata:all_upload_sessions")
        return redirect(redirect_to)

    if session.status == "processing":
        messages.info(request, "Verification already running in the background.")
        redirect_to = request.POST.get("next") or request.META.get("HTTP_REFERER") or reverse("metadata:all_upload_sessions")
        return redirect(redirect_to)

    session.mark_processing()
    verify_upload_session.schedule(args=(str(session.id),), delay=0)
    messages.success(request, "Upload verification was queued in the background.")

    redirect_to = request.POST.get("next") or request.META.get("HTTP_REFERER") or reverse("metadata:all_upload_sessions")
    return redirect(redirect_to)


@general_login_required
@require_POST
def trigger_cache_refresh(request):
    """Enqueue Huey jobs that rebuild project and schema caches."""

    if not request.user.is_staff:
        messages.error(request, "Only staff members can trigger cache refreshes.")
        return redirect("metadata:metadata_dashboard")

    cache_target = request.POST.get("cache", "all")
    action = request.POST.get("action", "warm").lower()
    action = "refresh" if action == "refresh" else "warm"
    is_refresh = action == "refresh"

    from arkumu.cache.tasks import (
        warm_card_schema_cache,
        warm_cross_institutional_projects_cache,
        warm_schema_cache,
        refresh_card_schema_cache,
        refresh_schema_cache,
        warm_canonical_graph_cache,
        refresh_canonical_graph_cache,
    )

    triggered = []
    action_label = "Refreshed" if is_refresh else "Warmed"

    if cache_target in {"all", "projects"}:
        schedule_kwargs = {"delay": 0}
        if is_refresh:
            schedule_kwargs["kwargs"] = {"force_refresh": True}
        warm_cross_institutional_projects_cache.schedule(**schedule_kwargs)
        triggered.append(f"{action_label} cross-institutional project snapshot")

    if cache_target in {"all", "schema"}:
        task = refresh_schema_cache if is_refresh else warm_schema_cache
        task.schedule(delay=0)
        triggered.append(f"{action_label} schema map (explorer classes & properties)")

    if cache_target in {"all", "card"}:
        task = refresh_card_schema_cache if is_refresh else warm_card_schema_cache
        task.schedule(delay=0)
        triggered.append(f"{action_label} catalog card schemas")

    if cache_target in {"all", "canonical_graph"}:
        task = refresh_canonical_graph_cache if is_refresh else warm_canonical_graph_cache
        task.schedule(delay=0)
        triggered.append(f"{action_label} canonical graph cache")

    if not triggered:
        messages.warning(request, "No cache task was selected.")
    else:
        messages.success(
            request,
            "Enqueued: " + ", ".join(triggered) + ". Huey will refresh these caches shortly.",
        )

    return redirect("metadata:metadata_dashboard")


@general_login_required
@require_POST
def trigger_checksum_refresh(request):
    """Queue checksum recalculation for S3 files via Huey."""

    if not request.user.is_staff:
        messages.error(request, "Only staff members can trigger checksum refreshes.")
        return redirect("metadata:metadata_dashboard")

    bucket = request.POST.get("checksum_bucket") or None
    mode = request.POST.get("checksum_mode", "missing")
    limit_raw = request.POST.get("checksum_limit")

    missing_only = mode != "all"
    limit = None

    if limit_raw:
        try:
            limit = int(limit_raw)
            if limit <= 0:
                limit = None
        except ValueError:
            messages.warning(request, "Invalid limit provided; ignoring.")

    recalculate_s3_checksums.schedule(
        args=(bucket,),
        kwargs={"missing_only": missing_only, "limit": limit},
        delay=0,
    )

    scope = bucket or "all buckets"
    mode_label = "missing checksums" if missing_only else "all files"
    if limit:
        mode_label = f"{mode_label} (limit {limit})"

    messages.success(request, f"Queued checksum recalculation for {scope}: {mode_label}.")
    return redirect("metadata:metadata_dashboard")


@general_login_required
@require_POST
def trigger_mark_missing(request):
    if not request.user.is_staff:
        return _maintenance_response(request, "Only staff members can run maintenance tasks.", level="error")

    bucket = request.POST.get("bucket")
    dry_run = request.POST.get("mode") == "dry"

    out = StringIO()
    cmd_kwargs = {}
    if bucket:
        cmd_kwargs["bucket"] = bucket
    if dry_run:
        cmd_kwargs["dry_run"] = True

    call_command("mark_missing_s3_files", stdout=out, **cmd_kwargs)
    output = out.getvalue().strip()
    message = f"Mark missing: bucket {bucket or 'all'}, mode={'dry-run' if dry_run else 'apply'}"
    return _maintenance_response(request, message, level="success", details=output)


@general_login_required
@require_POST
def trigger_deduplicate(request):
    if not request.user.is_staff:
        return _maintenance_response(request, "Only staff members can run maintenance tasks.", level="error")

    bucket = request.POST.get("bucket")
    dry_run = request.POST.get("mode") == "dry"

    out = StringIO()
    cmd_kwargs = {}
    if bucket:
        cmd_kwargs["organization"] = bucket
    if dry_run:
        cmd_kwargs["dry_run"] = True

    call_command("deduplicate_s3_files", stdout=out, **cmd_kwargs)
    output = out.getvalue().strip()
    message = f"Deduplicate: bucket {bucket or 'all'}, mode={'dry-run' if dry_run else 'apply'}"
    return _maintenance_response(request, message, level="success", details=output)


def _link_command(request, command_name: str, bucket: str | None, dry_run: bool):
    out = StringIO()
    cmd_kwargs = {}
    if bucket:
        cmd_kwargs["bucket"] = bucket
    if dry_run:
        cmd_kwargs["dry_run"] = True

    call_command(command_name, stdout=out, **cmd_kwargs)
    return out.getvalue().strip()


@general_login_required
@require_POST
def trigger_link_events(request):
    if not request.user.is_staff:
        return _maintenance_response(request, "Only staff members can run maintenance tasks.", level="error")

    bucket = request.POST.get("bucket")
    dry_run = request.POST.get("mode") == "dry"

    output = _link_command(request, "link_s3_files_to_events", bucket, dry_run)
    message = f"Link events: bucket {bucket or 'all'}, mode={'dry-run' if dry_run else 'apply'}"
    return _maintenance_response(request, message, level="success", details=output)


@general_login_required
@require_POST
def trigger_link_digital_objects(request):
    if not request.user.is_staff:
        return _maintenance_response(request, "Only staff members can run maintenance tasks.", level="error")

    bucket = request.POST.get("bucket")
    dry_run = request.POST.get("mode") == "dry"

    output = _link_command(request, "link_s3_files_to_digital_objects", bucket, dry_run)
    message = f"Link digital objects: bucket {bucket or 'all'}, mode={'dry-run' if dry_run else 'apply'}"
    return _maintenance_response(request, message, level="success", details=output)


@general_login_required
def project_snapshot_stats(request):
    """Display cached project snapshot summaries without triggering rebuilds."""

    cache_service = ProjectCacheService()
    snapshot = cache_service.get_cross_institutional_snapshot()

    alias_map = {
        str(src).lower(): str(target).lower()
        for src, target in getattr(settings, "OAI_INSTITUTION_CODE_ALIASES", {}).items()
    }

    stats_rows = []
    totals = {
        "projects": 0,
        "events": 0,
        "actors": 0,
        "digital_objects": 0,
        "rosetta_objects": 0,
    }

    if snapshot and snapshot.projects:
        stats_map = defaultdict(
            lambda: {
                "code": "",
                "label": "",
                "projects": 0,
                "events": 0,
                "actors": 0,
                "digital_objects": 0,
                "rosetta_objects": 0,
            }
        )

        for record in snapshot.projects:
            raw_code = (
                record.institution.code
                if record.institution and record.institution.code
                else "unknown"
            ).lower()
            normalized_code = alias_map.get(raw_code, raw_code)
            stats = stats_map[normalized_code]
            if not stats["code"]:
                stats["code"] = normalized_code

            stats["projects"] += 1
            stats["events"] += len(record.events or [])
            stats["actors"] += len(record.actors or [])

            digital_objects = record.digital_objects or []
            stats["digital_objects"] += sum(
                1 for obj in digital_objects if obj.path or obj.storage_key or obj.access_url
            )
            stats["rosetta_objects"] += sum(
                1 for obj in digital_objects if obj.path and obj.path.startswith("/rosetta/")
            )

        known_codes = [
            entry["code"]
            for entry in stats_map.values()
            if entry["code"] not in {"", "unknown"}
        ]
        label_lookup = {
            org.code.lower(): org.name
            for org in Organization.objects.filter(code__in=known_codes)
        }

        for entry in stats_map.values():
            code = entry["code"] or "unknown"
            if code == "unknown" and entry["projects"] == 0:
                continue
            entry["label"] = label_lookup.get(
                code,
                code.upper() if code != "unknown" else "Unknown",
            )
            stats_rows.append(entry)

        stats_rows.sort(key=lambda item: item["label"].lower())

        totals = {
            "projects": sum(item["projects"] for item in stats_rows),
            "events": sum(item["events"] for item in stats_rows),
            "actors": sum(item["actors"] for item in stats_rows),
            "digital_objects": sum(item["digital_objects"] for item in stats_rows),
            "rosetta_objects": sum(item["rosetta_objects"] for item in stats_rows),
        }

    template_name = (
        "partials/project_snapshot_stats.html"
        if request.headers.get("HX-Request")
        else "dashboard_project_snapshot.html"
    )

    return render(
        request,
        template_name,
        {
            "snapshot_stats": stats_rows,
            "snapshot_totals": totals,
            "snapshot_generated": snapshot.generated_at if snapshot else None,
            "snapshot_available": bool(snapshot),
        },
    )
    return redirect('metadata:metadata_dashboard')

@general_login_required
@require_POST
def trigger_external_sources_refresh(request):
    if not request.user.is_staff:
        messages.error(request, 'Only staff members can trigger external sources refreshes.')
        return redirect('metadata:metadata_dashboard')

    from arkumu.metadata.tasks import ensure_cached_all_task

    ensure_cached_all_task.schedule(kwargs={"force_refresh": True}, delay=0)

    messages.success(
        request,
        'Reload of external sources started.',
    )
    return redirect('metadata:metadata_dashboard')


@general_login_required
def oai_widget(request):
    """Return the OAI snapshot widget content on demand (HTMX-friendly)."""

    oai_snapshot = None
    try:
        oai_snapshot = build_oai_dashboard_snapshot()
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.exception("Failed to build OAI dashboard snapshot: %s", exc)

    template_name = "partials/oai_widget_card.html"
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

    builder = OAIProjectBuilder()
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
        'metadata/oai_snapshot_dashboard.html',
        {
            'endpoints': endpoints,
            'oai_snapshot': oai_snapshot,
        },
    )


def oai_endpoints_info(request):  # Backwards-compat alias for legacy URL
    return oai_snapshot_dashboard(request)


@general_login_required
def oai_db_dashboard(request):
    """Describe the DB-backed OAI endpoint with quick links and parity notes."""

    oai_snapshot = None
    try:
        oai_snapshot = _build_db_oai_dashboard_snapshot()
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.exception("Failed to build DB OAI dashboard snapshot: %s", exc)
        oai_snapshot = None

    db_endpoint_url = request.build_absolute_uri(reverse('oai:db-endpoint'))
    snapshot_endpoint_url = request.build_absolute_uri(reverse('oai:endpoint'))
    endpoints = _build_oai_endpoint_summaries(oai_snapshot)

    return render(
        request,
        'metadata/oai_db_dashboard.html',
        {
            'oai_snapshot': oai_snapshot,
            'endpoints': endpoints,
            'db_endpoint_url': db_endpoint_url,
            'snapshot_endpoint_url': snapshot_endpoint_url,
            'db_proxy_base_url': reverse('metadata:oai_db_proxy'),
        },
    )


def _oai_project_queryset_for_org(org: Organization):
    access_clause = (
        Q(public_access_level=PublicAccessLevel.RESTRICTED)
        | (Q(public_access_level=PublicAccessLevel.PUBLIC) & Q(is_public_approved=True))
    )
    return (
        Resource.objects.filter(
            organization=org,
            resource_type=ResourceType.ENTITY,
        )
        .filter(uri__regex=r'/entities/projekt/[0-9]+$')
        .filter(access_clause)
        .order_by('updated_at', 'id')
    )


def _run_media_link_seed(org: Organization) -> dict[str, int]:
    service = OAIProjectMediaSyncService()
    summary = {"projects": 0, "created": 0, "refreshed": 0, "stale": 0, "skipped": 0}
    for project in _oai_project_queryset_for_org(org).iterator(chunk_size=100):
        result = service.sync_project(project)
        summary["projects"] += 1
        summary["created"] += getattr(result, "created", 0)
        summary["refreshed"] += getattr(result, "refreshed", 0)
        summary["stale"] += getattr(result, "stale", 0)
        summary["skipped"] += getattr(result, "skipped", 0)
    return summary


@general_login_required
@require_http_methods(["GET"])
def oai_media_links_dashboard(request):
    if not request.user.is_staff:
        return HttpResponseForbidden(
            "<div class='alert alert-error'>Access denied: staff membership required</div>"
        )

    organizations = list(Organization.objects.filter(is_active=True).order_by('name'))
    org_lookup = {
        (org.code or '').lower(): org
        for org in organizations
        if org.code
    }

    selected_code = (request.GET.get('organization') or '').strip().lower()
    selected_org = org_lookup.get(selected_code) if selected_code else None
    if selected_code and not selected_org:
        messages.error(request, f"Unknown organization code '{selected_code}'.")

    status_filter = _normalized_media_link_status(request.GET.get('status'))
    page_param = request.GET.get('page') or '1'
    try:
        page_number = max(int(page_param), 1)
    except ValueError:
        page_number = 1

    panel_context = None
    if selected_org:
        panel_context = _build_media_links_panel_context(
            organization=selected_org,
            status_filter=status_filter,
            page_number=page_number,
        )

    return render(
        request,
        'metadata/oai_media_links_dashboard.html',
        {
            'organizations': organizations,
            'selected_org': selected_org,
            'selected_org_code': selected_org.code if selected_org else '',
            'status_choices': OAIProjectMediaLink.STATUS_CHOICES,
            'status_filter': status_filter,
            'panel_context': panel_context,
        },
    )

MEDIA_LINKS_PAGE_SIZE = 6


def _normalized_media_link_status(value: Optional[str]) -> str:
    if not value:
        return "all"
    token = value.strip().lower()
    valid_statuses = {choice[0] for choice in OAIProjectMediaLink.STATUS_CHOICES}
    if token in valid_statuses:
        return token
    return "all"


def _resolve_organization_by_code(code: Optional[str]) -> Optional[Organization]:
    if not code:
        return None
    return Organization.objects.filter(code__iexact=str(code).strip()).first()


def _media_link_prefetch_queryset(org: Organization):
    return (
        OAIProjectMediaLink.objects.filter(project__organization=org)
        .select_related('digital_object')
        .annotate(
            other_project_refs=Count(
                'digital_object__oai_media_references',
                filter=~Q(digital_object__oai_media_references__project_id=F('project_id')),
                distinct=True,
            )
        )
        .ordered()
    )


def _build_media_links_summary(
    organization: Organization,
    link_qs,
    *,
    status_filter: str,
) -> dict[str, Any]:
    links_total = link_qs.count()
    filtered_total = links_total if status_filter == "all" else link_qs.filter(status=status_filter).count()
    raw_stats = (
        link_qs.values('status')
        .annotate(count=Count('id'))
        .order_by('status')
    )
    status_map = dict(OAIProjectMediaLink.STATUS_CHOICES)
    status_totals = [
        {
            "status": row["status"],
            "label": status_map.get(row["status"], row["status"]),
            "count": row["count"],
        }
        for row in raw_stats
    ]
    return {
        "links_total": links_total,
        "filtered_links_total": filtered_total,
        "status_totals": status_totals,
        "stale_count": link_qs.filter(is_stale=True).count(),
        "available_project_count": _oai_project_queryset_for_org(organization).count(),
        "selected_org_code": organization.code or "",
        "organization": organization,
        "status_filter": status_filter,
    }


def _build_project_row_context(
    resource: Resource,
    *,
    builder: OAIProjectBuilder,
    assembler: OAIProjectAssembler,
    status_filter: str,
    org_code: str,
) -> dict[str, Any]:
    prefetched_links: List[OAIProjectMediaLink] = list(getattr(resource, "prefetched_media_links", []) or [])
    filtered_links = (
        prefetched_links
        if status_filter == "all"
        else [link for link in prefetched_links if link.status == status_filter]
    )

    row = {
        "resource": resource,
        "project_uri": resource.uri,
        "project_label": resource.name or "Untitled project",
        "links": filtered_links,
        "total_links": len(prefetched_links),
        "selected_org_code": org_code,
        "status_filter": status_filter,
        "builder_error": False,
        "graph_only_uris": (),
        "curated_missing_uris": (),
        "warnings": (),
        "harvestable_count": 0,
        "curated_selection": None,
    }

    context = AssemblyContext(resource=resource)
    try:
        record = assembler.build_record(context)
    except Exception:
        logger.exception("Failed to assemble project record for %s", resource.uri)
        row["builder_error"] = True
        return row

    if record is None:
        row["builder_error"] = True
        return row

    try:
        curated_project = builder.from_project_record(
            record,
            skip_shared_event_filter=True,
            skip_format_exclusion=True,
            use_curated_media_links=True,
        )
    except Exception:
        logger.exception("Failed to build curated project view for %s", resource.uri)
        row["builder_error"] = True
        return row

    row["harvestable_count"] = sum(1 for obj in curated_project.digital_objects if obj.harvestable)
    selection = curated_project.curated_selection
    if selection:
        row["curated_selection"] = selection
        row["graph_only_uris"] = selection.graph_only_uris
        row["curated_missing_uris"] = selection.curated_missing_uris
        row["warnings"] = selection.warnings

    return row


def _build_media_links_panel_context(
    *,
    organization: Organization,
    status_filter: str,
    page_number: int,
) -> dict[str, Any]:
    link_base_qs = OAIProjectMediaLink.objects.filter(project__organization=organization)
    summary = _build_media_links_summary(
        organization,
        link_base_qs,
        status_filter=status_filter,
    )

    project_prefetch = Prefetch(
        'oai_media_links',
        queryset=_media_link_prefetch_queryset(organization),
        to_attr='prefetched_media_links',
    )
    projects_qs = (
        Resource.objects.filter(organization=organization, resource_type=ResourceType.ENTITY)
        .prefetch_related(project_prefetch)
        .filter(oai_media_links__isnull=False)
        .distinct()
        .order_by('-updated_at', 'uri')
    )
    if status_filter != "all":
        projects_qs = projects_qs.filter(oai_media_links__status=status_filter)

    paginator = Paginator(projects_qs, MEDIA_LINKS_PAGE_SIZE)
    page_obj = paginator.get_page(page_number)

    builder = OAIProjectBuilder()
    assembler = OAIProjectAssembler()
    rows: List[dict[str, Any]] = []
    builder_errors: List[str] = []

    for project_resource in page_obj.object_list:
        row = _build_project_row_context(
            project_resource,
            builder=builder,
            assembler=assembler,
            status_filter=status_filter,
            org_code=organization.code or "",
        )
        if row["builder_error"]:
            builder_errors.append(project_resource.uri)
        rows.append(row)

    return {
        "selected_org": organization,
        "selected_org_code": organization.code or "",
        "status_filter": status_filter,
        "summary": summary,
        "project_rows": rows,
        "project_total": paginator.count,
        "current_page": page_obj.number,
        "page_obj": page_obj,
        "per_page": MEDIA_LINKS_PAGE_SIZE,
        "builder_errors": builder_errors,
        "status_choices": OAIProjectMediaLink.STATUS_CHOICES,
    }


def _build_single_project_row_context(
    *,
    organization: Organization,
    project_id: Any,
    status_filter: str,
) -> Optional[dict[str, Any]]:
    project_prefetch = Prefetch(
        'oai_media_links',
        queryset=_media_link_prefetch_queryset(organization),
        to_attr='prefetched_media_links',
    )
    resource = (
        Resource.objects.filter(organization=organization, id=project_id, resource_type=ResourceType.ENTITY)
        .prefetch_related(project_prefetch)
        .first()
    )
    if not resource:
        return None

    builder = OAIProjectBuilder()
    assembler = OAIProjectAssembler()
    return _build_project_row_context(
        resource,
        builder=builder,
        assembler=assembler,
        status_filter=status_filter,
        org_code=organization.code or "",
    )


def _render_project_row_response(
    request,
    *,
    organization: Organization,
    project_id: Any,
    status_filter: str,
    page_number: int,
):
    row = _build_single_project_row_context(
        organization=organization,
        project_id=project_id,
        status_filter=status_filter,
    )
    if row is None:
        return HttpResponseBadRequest("<div class='alert alert-error'>Unable to load project row.</div>")

    summary = _build_media_links_summary(
        organization,
        OAIProjectMediaLink.objects.filter(project__organization=organization),
        status_filter=status_filter,
    )
    context = {
        "row": row,
        "summary": summary,
        "status_choices": OAIProjectMediaLink.STATUS_CHOICES,
        "current_page": page_number,
        "include_summary": True,
    }
    return render(request, 'metadata/partials/oai_media_links_project_row.html', context)


def _preview_media_link_seed(org: Organization) -> dict[str, int]:
    service = OAIProjectMediaSyncService()
    summary = {"projects": 0, "created": 0, "refreshed": 0, "stale": 0, "skipped": 0}
    with transaction.atomic():
        for project in _oai_project_queryset_for_org(org).iterator(chunk_size=100):
            result = service.sync_project(project)
            summary["projects"] += 1
            summary["created"] += getattr(result, "created", 0)
            summary["refreshed"] += getattr(result, "refreshed", 0)
            summary["stale"] += getattr(result, "stale", 0)
            summary["skipped"] += getattr(result, "skipped", 0)
        transaction.set_rollback(True)
    return summary


@general_login_required
@require_http_methods(["GET"])
def oai_media_links_panel(request):
    if not request.user.is_staff:
        return HttpResponseForbidden(
            "<div class='alert alert-error'>Access denied: staff membership required</div>"
        )

    organization = _resolve_organization_by_code(request.GET.get('organization'))
    if not organization:
        return HttpResponseBadRequest("<div class='alert alert-error'>Select a valid organization.</div>")

    status_filter = _normalized_media_link_status(request.GET.get('status'))
    page_param = request.GET.get('page') or '1'
    try:
        page_number = max(int(page_param), 1)
    except ValueError:
        page_number = 1

    panel_context = _build_media_links_panel_context(
        organization=organization,
        status_filter=status_filter,
        page_number=page_number,
    )
    panel_context['status_choices'] = OAIProjectMediaLink.STATUS_CHOICES
    return render(request, 'metadata/partials/oai_media_links_panel.html', panel_context)


@general_login_required
@require_http_methods(["POST"])
def oai_media_link_update(request, link_id):
    if not request.user.is_staff:
        return HttpResponseForbidden(
            "<div class='alert alert-error'>Access denied: staff membership required</div>"
        )

    organization = _resolve_organization_by_code(request.POST.get('organization'))
    if not organization:
        return HttpResponseBadRequest("<div class='alert alert-error'>Select an organization.</div>")

    status_filter = _normalized_media_link_status(request.POST.get('status_filter'))
    page_param = request.POST.get('page') or '1'
    try:
        page_number = max(int(page_param), 1)
    except ValueError:
        page_number = 1

    try:
        link = OAIProjectMediaLink.objects.select_related('project__organization').get(id=link_id)
    except OAIProjectMediaLink.DoesNotExist:
        messages.error(request, 'Media link not found or already deleted.')
        return HttpResponseBadRequest("<div class='alert alert-error'>Media link not found.</div>")

    if link.project.organization_id != organization.id:
        return HttpResponseForbidden("<div class='alert alert-error'>Permission denied for this media link.</div>")

    valid_statuses = {choice[0] for choice in OAIProjectMediaLink.STATUS_CHOICES}
    updates: set[str] = set()

    requested_status = request.POST.get('status')
    current_status = request.POST.get('current_status') or link.status
    new_status = requested_status if requested_status in valid_statuses else current_status
    if new_status in valid_statuses and new_status != link.status:
        link.status = new_status
        link.last_reviewed_by = request.user
        link.last_reviewed_at = timezone.now()
        updates.update({'status', 'last_reviewed_by', 'last_reviewed_at'})

    order_input = (request.POST.get('order_index') or '').strip()
    if order_input:
        try:
            order_value = int(order_input)
        except ValueError:
            return HttpResponseBadRequest("<div class='alert alert-error'>Order index must be an integer.</div>")
    else:
        order_value = None
    if order_value != link.order_index:
        link.order_index = order_value
        updates.add('order_index')

    label_value = request.POST.get('label_override', '')
    if label_value != (link.label_override or ''):
        link.label_override = label_value
        updates.add('label_override')

    notes_value = request.POST.get('notes', '')
    if notes_value != (link.notes or ''):
        link.notes = notes_value
        updates.add('notes')

    if request.POST.get('clear_stale') == '1' and link.is_stale:
        link.is_stale = False
        updates.add('is_stale')

    if updates:
        updates.add('updated_at')
        link.save(update_fields=list(updates))
        messages.success(request, f"Updated media link for {link.project.uri}.")
    else:
        messages.info(request, 'No changes detected for the selected media link.')

    return _render_project_row_response(
        request,
        organization=organization,
        project_id=link.project_id,
        status_filter=status_filter,
        page_number=page_number,
    )


@general_login_required
@require_http_methods(["POST"])
def oai_media_link_delete(request, link_id):
    if not request.user.is_staff:
        return HttpResponseForbidden(
            "<div class='alert alert-error'>Access denied: staff membership required</div>"
        )

    organization = _resolve_organization_by_code(request.POST.get('organization'))
    if not organization:
        return HttpResponseBadRequest("<div class='alert alert-error'>Select an organization.</div>")

    status_filter = _normalized_media_link_status(request.POST.get('status_filter'))
    page_param = request.POST.get('page') or '1'
    try:
        page_number = max(int(page_param), 1)
    except ValueError:
        page_number = 1

    try:
        link = OAIProjectMediaLink.objects.select_related('project__organization').get(id=link_id)
    except OAIProjectMediaLink.DoesNotExist:
        messages.error(request, 'Media link not found or already deleted.')
        return HttpResponseBadRequest("<div class='alert alert-error'>Media link not found.</div>")

    if link.project.organization_id != organization.id:
        return HttpResponseForbidden("<div class='alert alert-error'>Permission denied for this media link.</div>")

    project_id = link.project_id
    link.delete()
    messages.success(
        request,
        f"Removed digital object {link.digital_object.uri} from project {link.project.uri}.",
    )

    row_context = _build_single_project_row_context(
        organization=organization,
        project_id=project_id,
        status_filter=status_filter,
    )
    if not row_context or row_context["total_links"] == 0:
        panel_context = _build_media_links_panel_context(
            organization=organization,
            status_filter=status_filter,
            page_number=1,
        )
        panel_context['status_choices'] = OAIProjectMediaLink.STATUS_CHOICES
        return render(request, 'metadata/partials/oai_media_links_panel.html', panel_context)

    return _render_project_row_response(
        request,
        organization=organization,
        project_id=project_id,
        status_filter=status_filter,
        page_number=page_number,
    )


@general_login_required
@require_http_methods(["POST"])
def oai_media_link_add(request):
    if not request.user.is_staff:
        return HttpResponseForbidden(
            "<div class='alert alert-error'>Access denied: staff membership required</div>"
        )

    organization = _resolve_organization_by_code(request.POST.get('organization'))
    if not organization:
        return HttpResponseBadRequest("<div class='alert alert-error'>Select an organization.</div>")

    status_filter = _normalized_media_link_status(request.POST.get('status_filter'))
    page_param = request.POST.get('page') or '1'
    try:
        page_number = max(int(page_param), 1)
    except ValueError:
        page_number = 1

    project_uri = (request.POST.get('project_uri') or '').strip()
    digital_uri = (request.POST.get('digital_uri') or '').strip()
    if not project_uri or not digital_uri:
        return HttpResponseBadRequest("<div class='alert alert-error'>Project and digital object URIs are required.</div>")

    project = Resource.objects.filter(
        organization=organization,
        uri=project_uri,
        resource_type=ResourceType.ENTITY,
    ).first()
    if not project:
        return HttpResponseBadRequest("<div class='alert alert-error'>Project not found for this organization.</div>")

    digital_object = Resource.objects.filter(
        uri=digital_uri,
        resource_type=ResourceType.ENTITY,
    ).first()
    if not digital_object:
        return HttpResponseBadRequest("<div class='alert alert-error'>Digital object not found.</div>")

    exists = OAIProjectMediaLink.objects.filter(
        project=project,
        digital_object=digital_object,
    ).exists()
    if exists:
        messages.warning(request, 'This digital object is already linked to the selected project.')
        return _render_project_row_response(
            request,
            organization=organization,
            project_id=project.id,
            status_filter=status_filter,
            page_number=page_number,
        )

    valid_statuses = {choice[0] for choice in OAIProjectMediaLink.STATUS_CHOICES}
    requested_status = (request.POST.get('status') or OAIProjectMediaLink.STATUS_PENDING).strip().lower()
    status_value = requested_status if requested_status in valid_statuses else OAIProjectMediaLink.STATUS_PENDING

    order_input = (request.POST.get('order_index') or '').strip()
    order_value: Optional[int]
    if order_input:
        try:
            order_value = int(order_input)
        except ValueError:
            return HttpResponseBadRequest("<div class='alert alert-error'>Order index must be an integer.</div>")
    else:
        order_value = None

    link = OAIProjectMediaLink.objects.create(
        project=project,
        digital_object=digital_object,
        status=status_value,
        order_index=order_value,
        label_override=request.POST.get('label_override', ''),
        notes=request.POST.get('notes', ''),
        source=OAIProjectMediaLink.SOURCE_MANUAL,
        last_reviewed_by=request.user if request.user.is_authenticated else None,
        last_reviewed_at=timezone.now(),
    )
    messages.success(request, f"Linked {digital_object.uri} to project {project.uri}.")

    return _render_project_row_response(
        request,
        organization=organization,
        project_id=link.project_id,
        status_filter=status_filter,
        page_number=page_number,
    )


@general_login_required
@require_http_methods(["GET"])
def oai_media_link_seed_preview(request):
    if not request.user.is_staff:
        return HttpResponseForbidden(
            "<div class='alert alert-error'>Access denied: staff membership required</div>"
        )

    organization = _resolve_organization_by_code(request.GET.get('organization'))
    if not organization:
        return HttpResponseBadRequest("<div class='alert alert-error'>Select an organization.</div>")

    summary = _preview_media_link_seed(organization)
    context = {
        "organization": organization,
        "seed_summary": summary,
        "status_filter": _normalized_media_link_status(request.GET.get('status')),
    }
    return render(request, 'metadata/partials/oai_media_links_seed_modal.html', context)


@general_login_required
@require_http_methods(["POST"])
def oai_media_link_seed_execute(request):
    if not request.user.is_staff:
        return HttpResponseForbidden(
            "<div class='alert alert-error'>Access denied: staff membership required</div>"
        )

    organization = _resolve_organization_by_code(request.POST.get('organization'))
    if not organization:
        return HttpResponseBadRequest("<div class='alert alert-error'>Select an organization.</div>")

    status_filter = _normalized_media_link_status(request.POST.get('status'))
    summary = _run_media_link_seed(organization)

    if summary["projects"] == 0:
        messages.warning(request, f"No eligible projects found for organization {organization.code.upper()}.")
    else:
        messages.success(
            request,
            (
                f"Seeded {summary['projects']} project(s): "
                f"created {summary['created']}, refreshed {summary['refreshed']}, marked stale {summary['stale']}."
            ),
        )

    panel_context = _build_media_links_panel_context(
        organization=organization,
        status_filter=status_filter,
        page_number=1,
    )
    panel_context['status_choices'] = OAIProjectMediaLink.STATUS_CHOICES
    return render(request, 'metadata/partials/oai_media_links_panel.html', panel_context)

@require_http_methods(["GET", "POST"])
@superuser_required
def mapping_selector_widget(request):
    """
    HTMX widget for selecting the active mapping for ALL organizations.

    **SUPERUSER ONLY**: Only superusers can view and change schema mappings.
    This affects how the projekt snapshot service and metadata entry services
    interpret organizational data structures globally.
    """
    from arkumu.users.models import Organization
    from django.db import transaction

    if request.method == "POST":
        # Handle mapping selection for a specific organization
        organization_id = request.POST.get('organization_id')
        mapping_id = request.POST.get('mapping_id')

        if not organization_id:
            return HttpResponse(
                "<div class='alert alert-error'>Organization ID required</div>"
            )

        try:
            organization = Organization.objects.get(code=organization_id)
        except Organization.DoesNotExist:
            return HttpResponse(
                "<div class='alert alert-error'>Organization not found</div>"
            )

        # Use transaction to ensure atomic is_active updates
        with transaction.atomic():
            # Clear mapping if empty selection
            if not mapping_id:
                # Set all mappings for this org to is_active=False
                Mapping.objects.filter(
                    organization_id=organization_id,
                    is_active=True
                ).update(is_active=False)

                logger.info(
                    f"SUPERUSER {request.user.username} cleared active mapping for org {organization_id}"
                )

                # Log audit trail
                MappingSelectionAudit.objects.create(
                    user=request.user,
                    organization_id=organization_id,
                    mapping=None,
                    mapping_name='',
                    action='cleared',
                    ip_address=request.META.get('REMOTE_ADDR')
                )

            else:
                # Set new mapping as active
                try:
                    mapping = Mapping.objects.get(id=mapping_id, organization_id=organization_id)

                    # Deactivate all other mappings for this org
                    Mapping.objects.filter(
                        organization_id=organization_id,
                        is_active=True
                    ).exclude(id=mapping.id).update(is_active=False)

                    # Activate the selected mapping
                    mapping.is_active = True
                    mapping.save(update_fields=['is_active'])

                    # Log the change for audit trail
                    logger.info(
                        f"SUPERUSER {request.user.username} set active mapping to '{mapping.name}' "
                        f"(ID: {mapping.id}) for org {organization_id}"
                    )

                    # Create audit record
                    MappingSelectionAudit.objects.create(
                        user=request.user,
                        organization_id=organization_id,
                        mapping=mapping,
                        mapping_name=mapping.name,
                        action='set',
                        ip_address=request.META.get('REMOTE_ADDR')
                    )

                except Mapping.DoesNotExist:
                    return HttpResponse(
                        "<div class='alert alert-error'>Mapping not found or does not belong to this organization</div>"
                    )

        # Return updated widget with HX-Trigger for other components
        organizations_with_mappings = _get_organizations_with_mappings()

        response = render(request, 'metadata/partials/mapping_selector_widget.html', {
            'organizations_with_mappings': organizations_with_mappings,
            'mapping_changed_success': True,
            'changed_org_name': organization.name
        })
        response['HX-Trigger'] = json.dumps({
            'mapping-changed': {
                'mapping_id': str(mapping_id) if mapping_id else None,
                'organization_id': organization_id,
                'action': 'set' if mapping_id else 'cleared'
            }
        })
        return response

    # GET request - render selector with all organizations
    organizations_with_mappings = _get_organizations_with_mappings()

    return render(request, 'metadata/partials/mapping_selector_widget.html', {
        'organizations_with_mappings': organizations_with_mappings
    })


def _get_organizations_with_mappings():
    """Helper function to get production organizations with their mappings."""
    from arkumu.users.models import Organization

    # Hardcoded list of production organizations (excludes test orgs)
    PRODUCTION_ORG_CODES = ['fuk', 'hmt', 'khm', 'rsh', 'det']

    organizations = Organization.objects.filter(code__in=PRODUCTION_ORG_CODES).order_by('name')

    organizations_data = []
    for org in organizations:
        mappings = Mapping.objects.filter(organization_id=org.code).order_by('-created_at')
        active_mapping = mappings.filter(is_active=True).first()

        # Only include orgs that have at least one mapping
        if mappings.exists():
            organizations_data.append({
                'organization': org,
                'mappings': mappings,
                'active_mapping': active_mapping
            })

    return organizations_data
