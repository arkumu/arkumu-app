"""OAI-PMH dashboard views for managing media links and monitoring OAI endpoints."""

import json
import logging
from collections import defaultdict
from io import StringIO
from typing import Any, Dict, Iterable, List, Optional

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


logger = logging.getLogger(__name__)

LABEL_PREFERRED_KEYWORDS: tuple[str, ...] = (
    "bevorzugter",
    "preferred",
    "titel",
    "title",
    "name",
    "label",
    "dateiname",
)

MEDIA_LINKS_PAGE_SIZE = 6
PROJECT_LINK_PREDICATES: tuple[str, ...] = tuple(
    uri.strip()
    for uri in getattr(
        settings,
        "OAI_PROJECT_LINK_PREDICATES",
        ("http://arkumu.org/data/properties/projekt",),
    )
    if uri and uri.strip()
)
_PROJECT_TYPE_URIS: tuple[str, ...] = tuple(
    uri.strip()
    for uri in getattr(settings, "OAI_PROJECT_TYPE_URIS", ())
    if uri and uri.strip()
)
_RDF_TYPE_URI = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
_PROJECT_URI_FALLBACK_REGEX = r'/entities/projekt/[^/]+$'

_oai_proxy_request_factory = RequestFactory()


def _has_oai_admin_access(user) -> bool:
    """
    Allow access for Django superusers or Arkumu system administrators.
    """
    if not getattr(user, "is_authenticated", False):
        return False
    if getattr(user, "is_superuser", False):
        return True
    return getattr(user, "role", None) == "system_admin"


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

    db_endpoint_url = request.build_absolute_uri(reverse('oai:db-endpoint'))
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


def _oai_project_queryset_for_org(org: Organization):
    access_clause = (
        Q(public_access_level=PublicAccessLevel.RESTRICTED)
        | (Q(public_access_level=PublicAccessLevel.PUBLIC) & Q(is_public_approved=True))
    )
    queryset = Resource.objects.filter(
        organization=org,
        resource_type=ResourceType.ENTITY,
    ).filter(access_clause)

    scope_clauses: List[Q] = []

    scope_clauses: List[Q] = [Q(uri__regex=_PROJECT_URI_FALLBACK_REGEX)]

    # Annotate project type membership using EXISTS to avoid expensive joins/distinct
    if _PROJECT_TYPE_URIS:
        type_predicate_filter = (
            Q(predicate__uri=_RDF_TYPE_URI)
            | Q(predicate__canonical_uri=_RDF_TYPE_URI)
        )
        type_object_filter = (
            Q(object__uri__in=_PROJECT_TYPE_URIS)
            | Q(object__canonical_uri__in=_PROJECT_TYPE_URIS)
        )
        type_subquery = Triple.objects.filter(
            subject_id=OuterRef('pk'),
        ).filter(type_predicate_filter & type_object_filter)
        queryset = queryset.annotate(has_project_type=Exists(type_subquery))
        scope_clauses.append(Q(has_project_type=True))

    if PROJECT_LINK_PREDICATES:
        link_subquery = Triple.objects.filter(
            object_id=OuterRef('pk'),
        ).filter(
            Q(predicate__uri__in=PROJECT_LINK_PREDICATES)
            | Q(predicate__canonical_uri__in=PROJECT_LINK_PREDICATES)
        )
        queryset = queryset.annotate(has_project_link=Exists(link_subquery))
        scope_clauses.append(Q(has_project_link=True))

    project_scope = scope_clauses[0]
    for clause in scope_clauses[1:]:
        project_scope |= clause

    return queryset.filter(project_scope).order_by('updated_at', 'id')


def _run_media_link_seed(org: Organization) -> dict[str, int]:
    service = OAIProjectMediaSyncService()
    summary = {"projects": 0, "created": 0, "refreshed": 0, "stale": 0, "skipped": 0}
    org_label = getattr(org, "code", None) or getattr(org, "name", "unknown")
    is_debug_logging = logger.isEnabledFor(logging.DEBUG)
    if is_debug_logging:
        logger.debug("Media link seed run started for org=%s (preview=False)", org_label)
    for idx, project in enumerate(_oai_project_queryset_for_org(org).iterator(chunk_size=100), start=1):
        result = service.sync_project(project)
        summary["projects"] += 1
        summary["created"] += getattr(result, "created", 0)
        summary["refreshed"] += getattr(result, "refreshed", 0)
        summary["stale"] += getattr(result, "stale", 0)
        summary["skipped"] += getattr(result, "skipped", 0)
        if is_debug_logging and idx % 25 == 0:
            logger.debug(
                "Media link seed progress org=%s processed=%s created=%s refreshed=%s stale=%s skipped=%s",
                org_label,
                summary["projects"],
                summary["created"],
                summary["refreshed"],
                summary["stale"],
                summary["skipped"],
            )
    if is_debug_logging:
        logger.debug(
            "Media link seed run completed for org=%s processed=%s created=%s refreshed=%s stale=%s skipped=%s",
            org_label,
            summary["projects"],
            summary["created"],
            summary["refreshed"],
            summary["stale"],
            summary["skipped"],
        )
    return summary


@general_login_required
@require_http_methods(["GET"])
def oai_media_links_dashboard(request):
    if not _has_oai_admin_access(request.user):
        return HttpResponseForbidden(
            "<div class='alert alert-error'>Access denied: system administrator permissions required</div>"
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
        'oai/oai_media_links_dashboard.html',
        {
            'organizations': organizations,
            'selected_org': selected_org,
            'selected_org_code': selected_org.code if selected_org else '',
            'status_choices': OAIProjectMediaLink.STATUS_CHOICES,
            'status_filter': status_filter,
            'panel_context': panel_context,
        },
    )


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
    project_access_filter: str = "all",
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
        "project_access_filter": project_access_filter,
    }


def _resource_display_label(
    resource: Optional[Resource],
    *,
    fallback: str = "",
    label_lookup: Optional[Dict[Any, str]] = None,
) -> str:
    """
    Return a concise label for a resource, preferring cached labels or explicit fields.

    Falls back to the URI tail (or provided fallback) when no direct label exists.
    """
    if not resource:
        return fallback

    if label_lookup:
        resource_id = getattr(resource, "id", None)
        if resource_id in label_lookup:
            return label_lookup[resource_id]

    label = getattr(resource, "name", None) or getattr(resource, "value", None)
    if label:
        return str(label)

    uri = getattr(resource, "uri", None)
    if uri:
        tail = uri.rstrip("/").split("/")[-1]
        if tail:
            return tail

    resource_id = getattr(resource, "id", None)
    if resource_id:
        return str(resource_id)

    return fallback


def _prefetch_resource_labels(
    resources: Iterable[Resource],
    *,
    cache: Optional[Dict[Any, str]] = None,
) -> Dict[Any, str]:
    """
    Populate a cache of display labels for the provided resources.

    Prefers literal triples whose predicate resembles title/label semantics,
    then falls back to the first literal, then to URI tails.
    """
    if cache is None:
        cache = {}

    pending: Dict[Any, Resource] = {}
    for resource in resources:
        if not resource:
            continue
        resource_id = getattr(resource, "id", None)
        if resource_id is None or resource_id in cache:
            continue
        # For entities, always check triples first
        # Only use name/value as fallback if no triples found
        pending[resource_id] = resource

    if not pending:
        return cache

    literal_triples = list(
        Triple.objects.filter(
            subject_id__in=list(pending.keys()),
            object__resource_type=ResourceType.LITERAL,
        )
        .select_related("predicate", "object")
    )

    def _literal_value(triple: Triple) -> Optional[str]:
        obj = triple.object
        if not obj:
            return None
        value = obj.value or obj.name
        return str(value).strip() if value else None

    for triple in literal_triples:
        subject_id = triple.subject_id
        if subject_id not in pending:
            continue
        predicate_value = (
            (getattr(triple.predicate, "uri", "") or "")
            + " "
            + (getattr(triple.predicate, "name", "") or "")
        ).lower()
        if predicate_value and any(token in predicate_value for token in LABEL_PREFERRED_KEYWORDS):
            literal = _literal_value(triple)
            if literal:
                cache[subject_id] = literal
                pending.pop(subject_id, None)

    for triple in literal_triples:
        subject_id = triple.subject_id
        if subject_id not in pending:
            continue
        literal = _literal_value(triple)
        if literal:
            cache[subject_id] = literal
            pending.pop(subject_id, None)

    if pending:
        for subject_id, resource in pending.items():
            cache[subject_id] = _resource_display_label(resource, fallback="", label_lookup=None)

    return cache


def _build_project_row_context(
    resource: Resource,
    *,
    builder: OAIProjectBuilder,
    assembler: OAIProjectAssembler,
    status_filter: str,
    org_code: str,
    label_lookup: Optional[Dict[Any, str]] = None,
) -> dict[str, Any]:
    prefetched_links: List[OAIProjectMediaLink] = list(getattr(resource, "prefetched_media_links", []) or [])
    for link in prefetched_links:
        link.digital_object_display_label = _resource_display_label(  # type: ignore[attr-defined]
            getattr(link, "digital_object", None),
            fallback="Untitled digital object",
            label_lookup=label_lookup,
        )
    filtered_links = (
        prefetched_links
        if status_filter == "all"
        else [link for link in prefetched_links if link.status == status_filter]
    )

    row = {
        "resource": resource,
        "project_uri": resource.uri,
        "project_label": _resource_display_label(resource, fallback="Untitled project", label_lookup=label_lookup),
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
    project_access_filter: str = "all",
    search_query: str = "",
) -> dict[str, Any]:
    link_base_qs = OAIProjectMediaLink.objects.filter(project__organization=organization)
    summary = _build_media_links_summary(
        organization,
        link_base_qs,
        status_filter=status_filter,
        project_access_filter=project_access_filter,
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

    if project_access_filter != "all":
        projects_qs = projects_qs.filter(public_access_level=project_access_filter)

    paginator = Paginator(projects_qs, MEDIA_LINKS_PAGE_SIZE)
    page_obj = paginator.get_page(page_number)
    project_resources: List[Resource] = list(page_obj.object_list)
    page_obj.object_list = project_resources

    builder = OAIProjectBuilder()
    assembler = OAIProjectAssembler()
    rows: List[dict[str, Any]] = []
    builder_errors: List[str] = []

    label_lookup = _prefetch_resource_labels(project_resources)
    digital_resources: List[Resource] = []
    for project_resource in project_resources:
        for link in getattr(project_resource, "prefetched_media_links", []) or []:
            digital = getattr(link, "digital_object", None)
            if digital:
                digital_resources.append(digital)
    if digital_resources:
        label_lookup = _prefetch_resource_labels(digital_resources, cache=label_lookup)

    # Apply search filter if provided
    if search_query:
        search_lower = search_query.lower()
        filtered_projects = []
        for project_resource in project_resources:
            project_label = label_lookup.get(project_resource.id, "")
            if search_lower in project_label.lower() or search_lower in project_resource.uri.lower():
                filtered_projects.append(project_resource)
        project_resources = filtered_projects
        page_obj.object_list = project_resources

    for project_resource in project_resources:
        row = _build_project_row_context(
            project_resource,
            builder=builder,
            assembler=assembler,
            status_filter=status_filter,
            org_code=organization.code or "",
            label_lookup=label_lookup,
        )
        if row["builder_error"]:
            builder_errors.append(project_resource.uri)
        rows.append(row)

    return {
        "selected_org": organization,
        "selected_org_code": organization.code or "",
        "status_filter": status_filter,
        "search_query": search_query,
        "summary": summary,
        "project_rows": rows,
        "project_total": paginator.count,
        "current_page": page_obj.number,
        "page_obj": page_obj,
        "per_page": MEDIA_LINKS_PAGE_SIZE,
        "builder_errors": builder_errors,
        "status_choices": OAIProjectMediaLink.STATUS_CHOICES,
        "view_mode": "project",
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
    label_lookup = _prefetch_resource_labels([resource])
    digital_resources: List[Resource] = []
    for link in getattr(resource, "prefetched_media_links", []) or []:
        digital = getattr(link, "digital_object", None)
        if digital:
            digital_resources.append(digital)
    if digital_resources:
        label_lookup = _prefetch_resource_labels(digital_resources, cache=label_lookup)

    return _build_project_row_context(
        resource,
        builder=builder,
        assembler=assembler,
        status_filter=status_filter,
        org_code=organization.code or "",
        label_lookup=label_lookup,
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
    return render(request, 'oai/partials/oai_media_links_project_row.html', context)


def _preview_media_link_seed(org: Organization) -> dict[str, int]:
    service = OAIProjectMediaSyncService()
    summary = {"projects": 0, "created": 0, "refreshed": 0, "stale": 0, "skipped": 0}
    org_label = getattr(org, "code", None) or getattr(org, "name", "unknown")
    is_debug_logging = logger.isEnabledFor(logging.DEBUG)
    if is_debug_logging:
        logger.debug("Media link seed preview started for org=%s", org_label)
    with transaction.atomic():
        for idx, project in enumerate(_oai_project_queryset_for_org(org).iterator(chunk_size=100), start=1):
            result = service.sync_project(project)
            summary["projects"] += 1
            summary["created"] += getattr(result, "created", 0)
            summary["refreshed"] += getattr(result, "refreshed", 0)
            summary["stale"] += getattr(result, "stale", 0)
            summary["skipped"] += getattr(result, "skipped", 0)
            if is_debug_logging and idx % 25 == 0:
                logger.debug(
                    "Media link seed preview progress org=%s processed=%s created=%s refreshed=%s stale=%s skipped=%s",
                    org_label,
                    summary["projects"],
                    summary["created"],
                    summary["refreshed"],
                    summary["stale"],
                    summary["skipped"],
                )
        transaction.set_rollback(True)
    if is_debug_logging:
        logger.debug(
            "Media link seed preview completed for org=%s processed=%s created=%s refreshed=%s stale=%s skipped=%s",
            org_label,
            summary["projects"],
            summary["created"],
            summary["refreshed"],
            summary["stale"],
            summary["skipped"],
        )
    return summary


@general_login_required
@require_http_methods(["GET"])
def oai_media_links_panel(request):
    if not _has_oai_admin_access(request.user):
        return HttpResponseForbidden(
            "<div class='alert alert-error'>Access denied: system administrator permissions required</div>"
        )

    organization = _resolve_organization_by_code(request.GET.get('organization'))
    if not organization:
        return HttpResponseBadRequest("<div class='alert alert-error'>Select a valid organization.</div>")

    status_filter = _normalized_media_link_status(request.GET.get('status'))
    project_access_filter = request.GET.get('project_access', 'all').strip().lower()
    if project_access_filter not in ['all', 'private', 'restricted', 'public']:
        project_access_filter = 'all'

    search_query = (request.GET.get('search') or '').strip()

    page_param = request.GET.get('page') or '1'
    try:
        page_number = max(int(page_param), 1)
    except ValueError:
        page_number = 1

    panel_context = _build_media_links_panel_context(
        organization=organization,
        status_filter=status_filter,
        page_number=page_number,
        project_access_filter=project_access_filter,
        search_query=search_query,
    )
    panel_context['status_choices'] = OAIProjectMediaLink.STATUS_CHOICES

    # If not an HTMX request, redirect to the full dashboard with params
    if not request.headers.get('HX-Request'):
        return redirect(f"{reverse('oai_admin:oai_media_links_dashboard')}?organization={organization.code}&status={status_filter}")

    return render(request, 'oai/partials/oai_media_links_panel.html', panel_context)


@general_login_required
@require_http_methods(["POST"])
def oai_media_link_update(request, link_id):
    if not _has_oai_admin_access(request.user):
        return HttpResponseForbidden(
            "<div class='alert alert-error'>Access denied: system administrator permissions required</div>"
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
    if not _has_oai_admin_access(request.user):
        return HttpResponseForbidden(
            "<div class='alert alert-error'>Access denied: system administrator permissions required</div>"
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
        return render(request, 'oai/partials/oai_media_links_panel.html', panel_context)

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
    if not _has_oai_admin_access(request.user):
        return HttpResponseForbidden(
            "<div class='alert alert-error'>Access denied: system administrator permissions required</div>"
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
    if not _has_oai_admin_access(request.user):
        return HttpResponseForbidden(
            "<div class='alert alert-error'>Access denied: system administrator permissions required</div>"
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
    return render(request, 'oai/partials/oai_media_links_seed_modal.html', context)


@general_login_required
@require_http_methods(["POST"])
def oai_media_link_seed_execute(request):
    if not _has_oai_admin_access(request.user):
        return HttpResponseForbidden(
            "<div class='alert alert-error'>Access denied: system administrator permissions required</div>"
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
    return render(request, 'oai/partials/oai_media_links_panel.html', panel_context)


def _build_digital_object_centric_context(
    *,
    organization: Organization,
    status_filter: str,
    page_number: int,
    project_access_filter: str = "all",
    shared_filter: str = "all",
    search_query: str = "",
) -> dict[str, Any]:
    """Build context for digital object-centric view (groups by digital object, shows projects)."""

    link_base_qs = OAIProjectMediaLink.objects.filter(project__organization=organization)

    # Apply filters to the link queryset
    filtered_qs = link_base_qs
    if status_filter != "all":
        filtered_qs = filtered_qs.filter(status=status_filter)
    if project_access_filter != "all":
        filtered_qs = filtered_qs.filter(project__public_access_level=project_access_filter)

    # Group by digital object and aggregate project information
    digital_objects_data = (
        filtered_qs
        .values('digital_object_id')
        .annotate(
            project_count=Count('project_id', distinct=True),
            approved_count=Count('id', filter=Q(status=OAIProjectMediaLink.STATUS_APPROVED)),
            pending_count=Count('id', filter=Q(status=OAIProjectMediaLink.STATUS_PENDING)),
            rejected_count=Count('id', filter=Q(status=OAIProjectMediaLink.STATUS_REJECTED)),
            is_shared=Count('project_id', distinct=True, filter=~Q(project_id=F('project_id'))),
            has_stale=Count('id', filter=Q(is_stale=True)),
        )
        .order_by('-project_count', 'digital_object_id')
    )

    # Apply shared filter
    if shared_filter == "shared":
        digital_objects_data = digital_objects_data.filter(project_count__gt=1)
    elif shared_filter == "single":
        digital_objects_data = digital_objects_data.filter(project_count=1)

    # Paginate digital objects
    paginator = Paginator(digital_objects_data, MEDIA_LINKS_PAGE_SIZE)
    page_obj = paginator.get_page(page_number)

    # Get full digital object resources and their links for the current page
    digital_object_ids = [item['digital_object_id'] for item in page_obj.object_list]
    digital_resources = {
        res.id: res
        for res in Resource.objects.filter(id__in=digital_object_ids)
    }

    # Prefetch all links for these digital objects with their projects
    links_for_page = (
        OAIProjectMediaLink.objects
        .filter(digital_object_id__in=digital_object_ids)
        .select_related('project', 'digital_object', 'last_reviewed_by')
        .annotate(
            other_project_refs=Count(
                'digital_object__oai_media_references',
                filter=~Q(digital_object__oai_media_references__project_id=F('project_id')),
                distinct=True,
            )
        )
        .order_by('project__uri')
    )

    if status_filter != "all":
        links_for_page = links_for_page.filter(status=status_filter)
    if project_access_filter != "all":
        links_for_page = links_for_page.filter(project__public_access_level=project_access_filter)

    # Group links by digital object
    links_by_digital_object: Dict[Any, List[OAIProjectMediaLink]] = defaultdict(list)
    for link in links_for_page:
        links_by_digital_object[link.digital_object_id].append(link)

    # Prefetch labels for all resources
    all_resources = list(digital_resources.values())
    for links in links_by_digital_object.values():
        all_resources.extend([link.project for link in links])
    label_lookup = _prefetch_resource_labels(all_resources)

    # Build rows with digital object info and their project links
    digital_object_rows: List[dict[str, Any]] = []
    for item in page_obj.object_list:
        digital_object_id = item['digital_object_id']
        digital_resource = digital_resources.get(digital_object_id)
        if not digital_resource:
            continue

        links = links_by_digital_object.get(digital_object_id, [])

        # Add display labels to links
        for link in links:
            link.project_display_label = _resource_display_label(  # type: ignore[attr-defined]
                link.project,
                fallback="Untitled project",
                label_lookup=label_lookup,
            )

        digital_object_label = _resource_display_label(
            digital_resource,
            fallback="Untitled digital object",
            label_lookup=label_lookup,
        )

        # Apply search filter if provided
        if search_query:
            search_lower = search_query.lower()
            if search_lower not in digital_object_label.lower() and search_lower not in digital_resource.uri.lower():
                continue

        digital_object_rows.append({
            "digital_object": digital_resource,
            "digital_object_uri": digital_resource.uri,
            "digital_object_label": digital_object_label,
            "project_count": item['project_count'],
            "approved_count": item['approved_count'],
            "pending_count": item['pending_count'],
            "rejected_count": item['rejected_count'],
            "is_shared": item['project_count'] > 1,
            "has_stale": item['has_stale'] > 0,
            "links": links,
        })

    # Build summary stats (same as project view)
    summary = _build_media_links_summary(
        organization,
        link_base_qs,
        status_filter=status_filter,
        project_access_filter=project_access_filter,
    )

    # Calculate digital object statistics
    all_digital_objects = (
        link_base_qs
        .values('digital_object_id')
        .annotate(project_count=Count('project_id', distinct=True))
    )
    total_digital_objects = all_digital_objects.count()
    shared_count = all_digital_objects.filter(project_count__gt=1).count()
    single_count = all_digital_objects.filter(project_count=1).count()

    return {
        "selected_org": organization,
        "selected_org_code": organization.code or "",
        "status_filter": status_filter,
        "project_access_filter": project_access_filter,
        "shared_filter": shared_filter,
        "search_query": search_query,
        "summary": summary,
        "digital_object_rows": digital_object_rows,
        "digital_object_total": paginator.count,
        "total_digital_objects": total_digital_objects,
        "shared_count": shared_count,
        "single_count": single_count,
        "current_page": page_obj.number,
        "page_obj": page_obj,
        "per_page": MEDIA_LINKS_PAGE_SIZE,
        "status_choices": OAIProjectMediaLink.STATUS_CHOICES,
        "view_mode": "digital",
    }


@general_login_required
@require_http_methods(["GET"])
def oai_media_links_digital_view(request):
    """Digital object-centric view showing digital objects grouped by object with their projects."""
    if not _has_oai_admin_access(request.user):
        return HttpResponseForbidden(
            "<div class='alert alert-error'>Access denied: system administrator permissions required</div>"
        )

    organization = _resolve_organization_by_code(request.GET.get('organization'))
    if not organization:
        return HttpResponseBadRequest("<div class='alert alert-error'>Select a valid organization.</div>")

    status_filter = _normalized_media_link_status(request.GET.get('status'))
    project_access_filter = request.GET.get('project_access', 'all').strip().lower()
    if project_access_filter not in ['all', 'private', 'restricted', 'public']:
        project_access_filter = 'all'

    shared_filter = request.GET.get('shared', 'all').strip().lower()
    if shared_filter not in ['all', 'shared', 'single']:
        shared_filter = 'all'

    search_query = (request.GET.get('search') or '').strip()

    page_param = request.GET.get('page') or '1'
    try:
        page_number = max(int(page_param), 1)
    except ValueError:
        page_number = 1

    context = _build_digital_object_centric_context(
        organization=organization,
        status_filter=status_filter,
        page_number=page_number,
        project_access_filter=project_access_filter,
        shared_filter=shared_filter,
        search_query=search_query,
    )

    # If not an HTMX request, redirect to the full dashboard with params
    if not request.headers.get('HX-Request'):
        return redirect(
            f"{reverse('oai_admin:oai_media_links_dashboard')}?organization={organization.code}"
            f"&status={status_filter}&view=digital&shared={shared_filter}"
        )

    return render(request, 'oai/partials/oai_media_links_digital_panel.html', context)


@general_login_required
@require_http_methods(["POST"])
def oai_project_status_update(request, resource_id):
    if not _has_oai_admin_access(request.user):
        return HttpResponseForbidden(
            "<div class='alert alert-error'>Access denied: system administrator permissions required</div>"
        )

    try:
        resource = Resource.objects.get(id=resource_id)
    except Resource.DoesNotExist:
        return HttpResponseBadRequest("<div class='alert alert-error'>Project not found.</div>")

    new_status = request.POST.get('public_access_level', '').strip().lower()
    valid_statuses = ['private', 'restricted', 'public']

    if new_status not in valid_statuses:
        return HttpResponseBadRequest("<div class='alert alert-error'>Invalid status.</div>")

    resource.public_access_level = new_status
    resource.save()

    organization = resource.organization
    status_filter = request.GET.get('status', 'all')

    panel_context = _build_media_links_panel_context(
        organization=organization,
        status_filter=status_filter,
        page_number=1,
    )
    panel_context['status_choices'] = OAIProjectMediaLink.STATUS_CHOICES
    return render(request, 'oai/partials/oai_media_links_panel.html', panel_context)
