from django.contrib import messages
from django.core.management import call_command
from django.db import models
from django.db.models import Count
from django.http import HttpResponse, HttpResponseBadRequest, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.html import escape
from django.views.decorators.http import require_POST
from django.test import RequestFactory
from io import StringIO

from arkumu.importer.models import IngestSession
from arkumu.metadata.models.resource import Resource, ResourceType
from arkumu.metadata.models.triples import Triple
from arkumu.storage.models.upload_tracking import AsyncUploadSession
from arkumu.storage.tasks import verify_upload_session, recalculate_s3_checksums
from arkumu.storage.services.bucket_service import BucketService
from arkumu.users.mixins import general_login_required
from arkumu.oaipmh.views import oai_endpoint

from .dashboard_helpers import (
    build_session_entry,
    build_upload_display,
    summarize_upload_stats,
)


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
        },
    )


@general_login_required
def all_upload_sessions(request):
    """Displays a list of all upload sessions with their files."""

    entries = [
        build_session_entry(session)
        for session in AsyncUploadSession.objects.select_related("user")
        .prefetch_related("files")
        .order_by("-created_at")
    ]
    total_stats = summarize_upload_stats(entries)

    return render(
        request,
        "all_upload_sessions.html",
        {
            "enhanced_sessions": entries,
            "total_stats": total_stats,
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


@general_login_required
def oai_proxy(request):
    """Proxy the OAI-PMH endpoint for authenticated dashboard users."""

    if request.method != "GET":
        return HttpResponseBadRequest("Only GET requests are supported")

    if "verb" not in request.GET:
        return HttpResponseBadRequest("Missing required 'verb' parameter")

    query_items = [(key, value) for key, values in request.GET.lists() for value in values]
    internal_request = _oai_proxy_request_factory.get("/oai/", data=query_items)

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

    return oai_endpoint(internal_request)


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

    from arkumu.cache.tasks import (
        warm_card_schema_cache,
        warm_cross_institutional_projects_cache,
        warm_schema_cache,
    )

    triggered = []

    if cache_target in {"all", "projects"}:
        warm_cross_institutional_projects_cache.schedule(delay=0)
        triggered.append("Cross-institutional project snapshot")

    if cache_target in {"all", "schema"}:
        warm_schema_cache.schedule(delay=0)
        triggered.append("Schema map (explorer classes & properties)")

    if cache_target in {"all", "card"}:
        warm_card_schema_cache.schedule(delay=0)
        triggered.append("Catalog card schemas")

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
def trigger_link_projects(request):
    if not request.user.is_staff:
        return _maintenance_response(request, "Only staff members can run maintenance tasks.", level="error")

    bucket = request.POST.get("bucket")
    dry_run = request.POST.get("mode") == "dry"

    output = _link_command(request, "link_s3_files_to_projects", bucket, dry_run)
    message = f"Link projects: bucket {bucket or 'all'}, mode={'dry-run' if dry_run else 'apply'}"
    return _maintenance_response(request, message, level="success", details=output)
