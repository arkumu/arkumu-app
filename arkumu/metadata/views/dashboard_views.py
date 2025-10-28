import logging
from collections import defaultdict

from django.conf import settings

from django.contrib import messages
from django.core.management import call_command
from django.db import models
from django.db.models import Count
from django.http import HttpResponse, HttpResponseBadRequest, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.html import escape
from django.views.decorators.http import require_POST
from django.test import RequestFactory
from io import StringIO

from arkumu.importer.models import IngestSession
from arkumu.metadata.models.resource import PublicAccessLevel, Resource, ResourceType
from arkumu.metadata.models.triples import Triple
from arkumu.storage.models.upload_tracking import AsyncUploadSession
from arkumu.storage.tasks import verify_upload_session, recalculate_s3_checksums
from arkumu.storage.services.bucket_service import BucketService
from arkumu.users.mixins import general_login_required
from arkumu.users.models import Organization
from arkumu.oaipmh.views import oai_endpoint
from arkumu.metadata.services.oai_stats import build_oai_dashboard_snapshot
from arkumu.cache.services.project_cache_service import ProjectCacheService
from arkumu.projects.services import ProjectSnapshotService

from .dashboard_helpers import (
    build_session_entry,
    build_upload_display,
    summarize_upload_stats,
)


logger = logging.getLogger(__name__)

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

    if request.method != "POST":
        return redirect("metadata:metadata_dashboard")

    if not request.user.is_superuser:
        messages.error(request, "Only superusers can publish organization projects.")
        return redirect("metadata:metadata_dashboard")

    organization_id = request.POST.get("organization_id")
    if not organization_id:
        messages.error(request, "Select an organization to publish its projects.")
        return redirect("metadata:metadata_dashboard")

    try:
        organization = Organization.objects.get(id=organization_id)
    except Organization.DoesNotExist:
        messages.error(request, "The selected organization does not exist.")
        return redirect("metadata:metadata_dashboard")

    snapshot = ProjectSnapshotService().get_cross_institutional_snapshot(include_non_public=True)
    project_uris = [
        project.subject_id
        for project in snapshot.projects
        if _project_matches_organization(project, organization)
    ]

    if not project_uris:
        messages.warning(
            request,
            f"No projects were found for {organization.name}.",
        )
        return redirect("metadata:metadata_dashboard")

    now = timezone.now()
    updated = Resource.objects.filter(
        id__in=project_uris,
        organization=organization,
    ).update(
        public_access_level=PublicAccessLevel.PUBLIC,
        is_public_approved=True,
        is_public=True,
        public_approved_by=request.user,
        public_approved_at=now,
    )

    if updated == 0:
        messages.warning(
            request,
            f"Projects for {organization.name} were already public or no matching resources existed.",
        )
    else:
        messages.success(
            request,
            f"Published {updated} project resources for {organization.name}. Use the dashboard refresh control when you want to rebuild the project snapshot.",
        )

    return redirect("metadata:metadata_dashboard")


def _project_matches_organization(project, organization) -> bool:
    """Return True when project should be considered part of the organization."""

    org_code = (organization.code or "").lower().strip()
    if not org_code:
        return False

    code_aliases = {
        str(alias).lower().strip(): str(target).lower().strip()
        for alias, target in getattr(settings, "OAI_INSTITUTION_CODE_ALIASES", {}).items()
        if alias and target
    }
    label_aliases = {
        str(label).lower().strip(): str(code).lower().strip()
        for label, code in getattr(settings, "OAI_INSTITUTION_LABEL_ALIASES", {}).items()
        if label and code
    }

    def normalize_code(value: str | None) -> str | None:
        if not value:
            return None
        normalized = str(value).lower().strip()
        if not normalized:
            return None
        return code_aliases.get(normalized, normalized)

    candidate_codes: set[str] = set()

    institution = getattr(project, "institution", None)
    if institution:
        inst_code = normalize_code(getattr(institution, "code", None))
        if inst_code:
            candidate_codes.add(inst_code)
        label = getattr(institution, "label", None)
        if label:
            label_key = str(label).lower().strip()
            alias_code = label_aliases.get(label_key)
            if alias_code:
                candidate_codes.add(alias_code)

    for raw_code in getattr(project, "institution_codes", []) or []:
        norm_code = normalize_code(raw_code)
        if norm_code:
            candidate_codes.add(norm_code)

    return org_code in candidate_codes and getattr(project, "subject_id", None) is not None


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
