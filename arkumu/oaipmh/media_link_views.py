"""Dedicated views for the curated media-links dashboard."""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any, Dict, Iterable, List, Optional, Set

from django.conf import settings
from django.contrib import messages
from django.core.paginator import EmptyPage, Paginator
from django.db import models, transaction
from django.db.models import Count, F, Max, Prefetch, Q
from django.http import HttpResponseBadRequest, HttpResponseForbidden
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.html import escape
from django.views.decorators.http import require_http_methods, require_POST

from arkumu.metadata.models.resource import PublicAccessLevel, Resource, ResourceType
from arkumu.metadata.models.triples import Triple
from arkumu.oaipmh.models import OAIMediaSyncState, OAIProjectMediaLink, OAIProjectPublication
from arkumu.oaipmh.oai_project import HARVESTABLE_STORAGE_STATUSES, OAIProjectBuilder
from arkumu.oaipmh.oai_project_tailored import OAIProjectBuilderTailored
from arkumu.oaipmh.services import OAIProjectMediaSyncService, media_sync_jobs
from arkumu.oaipmh.services.media_sync_planner import (
    collect_publication_candidate_ids,
    collect_seed_candidate_ids,
    get_sync_state,
)
from arkumu.oaipmh.services.oai_project_assembler import AssemblyContext, OAIProjectAssembler
from arkumu.oaipmh.services.project_scope import project_queryset_for_org
from arkumu.oaipmh.views import _build_identifier, _project_type_filter, _restrict_to_harvestable_files
from arkumu.storage.models.s3_file_objects import S3FileObject
from arkumu.users.mixins import general_login_required
from arkumu.users.models import Organization


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


def _has_oai_admin_access(user) -> bool:
    """Allow access for Django superusers or Arkumu system administrators."""

    if not getattr(user, "is_authenticated", False):
        return False
    if getattr(user, "is_superuser", False):
        return True
    return getattr(user, "role", None) == "system_admin"


def _run_media_link_seed(org: Organization) -> dict[str, int]:
    service = OAIProjectMediaSyncService()
    summary = {"projects": 0, "created": 0, "refreshed": 0, "stale": 0, "skipped": 0}
    org_label = getattr(org, "code", None) or getattr(org, "name", "unknown")
    is_debug_logging = logger.isEnabledFor(logging.DEBUG)
    if is_debug_logging:
        logger.debug("Media link seed run started for org=%s (preview=False)", org_label)

    state = get_sync_state(org, profile=OAIMediaSyncState.PROFILE_TAILORED)
    full_refresh, candidate_ids = collect_seed_candidate_ids(org, since=state.last_seed_at)
    queryset = project_queryset_for_org(org)
    if not full_refresh:
        if not candidate_ids:
            state.last_seed_at = timezone.now()
            state.save(update_fields=["last_seed_at", "updated_at"])
            return summary
        queryset = queryset.filter(id__in=list(candidate_ids))

    for idx, project in enumerate(queryset.iterator(chunk_size=100), start=1):
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

    state.last_seed_at = timezone.now()
    state.save(update_fields=["last_seed_at", "updated_at"])
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

    page_param = request.GET.get('page') or '1'
    try:
        page_number = max(int(page_param), 1)
    except ValueError:
        page_number = 1

    panel_context = None
    if selected_org:
        panel_context = _build_media_links_panel_context(
            organization=selected_org,
            page_number=page_number,
        )

    return render(
        request,
        'oai/oai_media_links_dashboard.html',
        {
            'organizations': organizations,
            'selected_org': selected_org,
            'selected_org_code': selected_org.code if selected_org else '',
            'panel_context': panel_context,
        },
    )


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
    project_access_filter: str = "all",
    oai_publish_filter: str = "all",
    harvestable_filter: str = "all",
    s3_harvestable_ids: Optional[Set[int]] = None,
    curated_harvestable_ids: Optional[Set[int]] = None,
) -> dict[str, Any]:
    links_total = link_qs.count()
    filtered_total = links_total
    # Project-level stats for summary header
    project_ids_qs = (
        link_qs.order_by()
        .values_list('project_id', flat=True)
        .distinct()
    )
    project_qs = project_queryset_for_org(organization).filter(id__in=project_ids_qs)
    distinct_projects_qs = project_qs.order_by().values('uri').distinct()
    available_projects = distinct_projects_qs.count()
    if s3_harvestable_ids is not None:
        harvestable_projects = len(s3_harvestable_ids)
    elif curated_harvestable_ids is not None:
        harvestable_projects = len(curated_harvestable_ids)
    else:
        harvestable_projects = (
            _restrict_to_harvestable_files(project_qs)
            .order_by()
            .values('uri')
            .distinct()
            .count()
        )

    return {
        "links_total": links_total,
        "filtered_links_total": filtered_total,
        "status_totals": [],
        "stale_count": link_qs.filter(is_stale=True).count(),
        "available_project_count": available_projects,
        "harvestable_project_count": harvestable_projects,
        "selected_org_code": organization.code or "",
        "organization": organization,
        "project_access_filter": project_access_filter,
        "oai_publish_filter": oai_publish_filter,
        "harvestable_filter": harvestable_filter,
    }


def _is_s3_org(organization: Organization) -> bool:
    codes = {
        code.lower().strip()
        for code in getattr(settings, "OAI_S3_HARVESTABLE_ORGS", ())
        if code
    }
    org_code = (organization.code or "").strip().lower()
    return org_code in codes


def _s3_harvestable_project_ids(organization: Organization) -> Set[int]:
    statuses = HARVESTABLE_STORAGE_STATUSES
    qs = (
        OAIProjectMediaLink.objects.filter(
            project__organization=organization,
            digital_object__s3fileobject__status__in=statuses,
        )
        .exclude(digital_object__s3fileobject__s3_key__isnull=True)
        .exclude(digital_object__s3fileobject__s3_key__exact="")
        .values_list("project_id", flat=True)
        .distinct()
    )
    return set(qs)


def _curated_harvestable_project_ids(organization: Organization) -> Set[int]:
    qs = (
        OAIProjectMediaLink.objects.filter(
            project__organization=organization,
            is_stale=False,
        )
        .values_list("project_id", flat=True)
        .distinct()
    )
    return set(qs)


def _curated_harvestable_project_ids(organization: Organization) -> Set[int]:
    qs = (
        OAIProjectMediaLink.objects.filter(
            project__organization=organization,
            is_stale=False,
        )
        .values_list("project_id", flat=True)
        .distinct()
    )
    return set(qs)


def _sync_oai_publication_for_org(
    organization: Organization,
    *,
    user=None,
) -> dict[str, int]:
    """Auto-approve OAI publication according to institution-specific rules."""

    assembler = OAIProjectAssembler()
    builder = OAIProjectBuilderTailored()
    is_s3_org = _is_s3_org(organization)
    summary: dict[str, int] = {"projects": 0, "auto_approved": 0, "errors": 0}

    state = get_sync_state(organization, profile=OAIMediaSyncState.PROFILE_TAILORED)
    full_refresh, candidate_ids = collect_publication_candidate_ids(
        organization,
        since=state.last_publication_sync_at,
    )
    queryset = project_queryset_for_org(organization)
    if not full_refresh:
        if not candidate_ids:
            state.last_publication_sync_at = timezone.now()
            state.save(update_fields=["last_publication_sync_at", "updated_at"])
            return summary
        queryset = queryset.filter(id__in=list(candidate_ids))

    for project in queryset.iterator(chunk_size=100):
        summary["projects"] += 1

        context = AssemblyContext(resource=project)
        try:
            record = assembler.build_record(context)
        except Exception:
            logger.exception("OAI publish sync: failed to assemble record for %s", project.uri)
            summary["errors"] += 1
            continue

        if record is None:
            continue

        try:
            oai_project = builder.from_project_record(
                record,
                skip_shared_event_filter=True,
                skip_format_exclusion=True,
                use_curated_media_links=True,
            )
        except Exception:
            logger.exception("OAI publish sync: failed to build project for %s", project.uri)
            summary["errors"] += 1
            continue

        digital_objects = list(getattr(oai_project, "digital_objects", []) or [])
        if not digital_objects:
            continue
        if is_s3_org and not any(obj.harvestable for obj in digital_objects):
            continue

        publication, created = OAIProjectPublication.objects.get_or_create(project=project)
        if not publication.is_approved:
            publication.is_approved = True
            publication.approved_at = timezone.now()
            if user is not None and getattr(user, "is_authenticated", False):
                publication.approved_by = user
            publication.save()
            summary["auto_approved"] += 1

    state.last_publication_sync_at = timezone.now()
    state.save(update_fields=["last_publication_sync_at", "updated_at"])
    return summary


def _auto_approve_publication_if_needed(
    project: Resource,
    *,
    has_harvestable: bool,
    allow_auto_approval: bool,
    publication: OAIProjectPublication | None,
    user=None,
) -> OAIProjectPublication | None:
    if not allow_auto_approval or not has_harvestable or publication is not None:
        return publication

    publication, _ = OAIProjectPublication.objects.get_or_create(project=project)
    if publication.is_approved:
        return publication

    publication.is_approved = True
    publication.approved_at = timezone.now()
    if user is not None and getattr(user, "is_authenticated", False):
        publication.approved_by = user
    publication.save(update_fields=["is_approved", "approved_at", "approved_by", "updated_at"])
    return publication


def _emit_media_sync_messages(request, state: dict[str, Any], organization: Organization) -> None:
    seed_summary = state.get('seed_summary') or {}
    seed_projects = seed_summary.get('projects', 0)
    if seed_projects:
        messages.success(
            request,
            (
                f"Seeded {seed_projects} project(s): "
                f"created {seed_summary.get('created', 0)}, "
                f"refreshed {seed_summary.get('refreshed', 0)}, "
                f"marked stale {seed_summary.get('stale', 0)}."
            ),
        )
    else:
        messages.warning(request, f"No eligible projects found for organization {organization.code.upper()}.")

    sync_summary = state.get('sync_summary') or {}
    approved_count = sync_summary.get('auto_approved', 0)
    if approved_count:
        messages.success(
            request,
            f"Auto-approved OAI publication for {approved_count} project(s).",
        )
    else:
        messages.info(request, "No additional projects were auto-approved for OAI.")


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


def _attach_s3_metadata(
    project_resources: Iterable[Resource],
    organization: Organization,
) -> None:
    """
    Attach transient S3 flags to curated links so the UI and builders can make
    harvestability decisions based on real storage presence.
    """

    resources = list(project_resources)
    if not resources or not _is_s3_org(organization):
        return

    digital_ids: set[Any] = set()
    for project_resource in resources:
        for link in getattr(project_resource, "prefetched_media_links", []) or []:
            digital = getattr(link, "digital_object", None)
            if digital and getattr(digital, "id", None):
                digital_ids.add(digital.id)

    if not digital_ids:
        return

    s3_qs = (
        S3FileObject.objects.filter(
            related_resource_id__in=digital_ids,
            status__in=HARVESTABLE_STORAGE_STATUSES,
            s3_key__isnull=False,
        )
        .exclude(s3_key="")
    )

    best_file_by_resource: Dict[Any, S3FileObject] = {}
    for file_obj in s3_qs:
        rid = file_obj.related_resource_id
        existing = best_file_by_resource.get(rid)
        if existing is None or (
            existing.status != "verified" and file_obj.status == "verified"
        ):
            best_file_by_resource[rid] = file_obj

    for project_resource in resources:
        for link in getattr(project_resource, "prefetched_media_links", []) or []:
            digital = getattr(link, "digital_object", None)
            has_s3 = False
            s3_key_preview = ""
            digital_id = getattr(digital, "id", None)
            if digital_id in best_file_by_resource:
                file_obj = best_file_by_resource[digital_id]
                has_s3 = True
                s3_key_preview = file_obj.s3_key or ""
            setattr(link, "has_s3_file", has_s3)
            setattr(link, "s3_key_preview", s3_key_preview)


def _build_project_row_context(
    resource: Resource,
    *,
    builder: OAIProjectBuilder,
    assembler: OAIProjectAssembler,
    org_code: str,
    is_s3_org: bool,
    label_lookup: Optional[Dict[Any, str]] = None,
    publication_by_id: Optional[Dict[Any, OAIProjectPublication]] = None,
) -> dict[str, Any]:
    prefetched_links: List[OAIProjectMediaLink] = list(getattr(resource, "prefetched_media_links", []) or [])
    for link in prefetched_links:
        link.digital_object_display_label = _resource_display_label(  # type: ignore[attr-defined]
            getattr(link, "digital_object", None),
            fallback="Untitled digital object",
            label_lookup=label_lookup,
        )
    filtered_links = list(prefetched_links)

    publication = None
    if publication_by_id is not None:
        publication = publication_by_id.get(resource.id)

    project_uri = getattr(resource, "uri", "") or ""

    row = {
        "resource": resource,
        "project_uri": project_uri,
        "project_label": _resource_display_label(resource, fallback="Untitled project", label_lookup=label_lookup),
        "links": filtered_links,
        "total_links": len(prefetched_links),
        "selected_org_code": org_code,
        "builder_error": False,
        "graph_only_uris": (),
        "curated_missing_uris": (),
        "warnings": (),
        "harvestable_count": 0,
        "has_harvestable_files": False,
        "curated_selection": None,
        "oai_identifier": _build_identifier(project_uri),
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

    # Prefer assembled ProjectRecord title for display label when available
    record_title = getattr(record, "title", None)
    if record_title:
        row["project_label"] = record_title

    # All normalized objects in curated_project.digital_objects are harvestable;
    # use them to derive per-project and per-link harvestable flags.
    normalized_objects = list(curated_project.digital_objects or ())
    row["harvestable_count"] = len(normalized_objects)
    harvestable_resource_ids: set[str] = set()
    harvestable_uris: set[str] = set()
    for obj in normalized_objects:
        resource_id = getattr(obj, "resource_id", None)
        if resource_id not in (None, ""):
            harvestable_resource_ids.add(str(resource_id))
        uri = getattr(obj, "uri", None)
        if uri:
            harvestable_uris.add(uri)
    has_harvestable = bool(harvestable_resource_ids or harvestable_uris)
    row["has_harvestable_files"] = has_harvestable

    # Attach per-link harvestable flag for UI (digital object column).
    for link in filtered_links:
        digital = getattr(link, "digital_object", None)
        is_harvestable = False
        if digital:
            if str(getattr(digital, "id", "")) in harvestable_resource_ids:
                is_harvestable = True
            elif getattr(digital, "uri", None) in harvestable_uris:
                is_harvestable = True
        if is_s3_org and not getattr(link, "has_s3_file", False):
            is_harvestable = False
        setattr(link, "is_harvestable", is_harvestable)
    selection = curated_project.curated_selection
    if selection:
        row["curated_selection"] = selection
        row["graph_only_uris"] = selection.graph_only_uris
        row["curated_missing_uris"] = selection.curated_missing_uris
        row["warnings"] = selection.warnings

    has_verified_s3 = False
    if is_s3_org:
        has_verified_s3 = any(
            getattr(link, "is_harvestable", False) and getattr(link, "has_s3_file", False)
            for link in filtered_links
        )
        row["has_harvestable_files"] = has_verified_s3

    publication = _auto_approve_publication_if_needed(
        resource,
        has_harvestable=has_harvestable,
        allow_auto_approval=(not is_s3_org) or has_verified_s3,
        publication=publication,
    )
    if publication and publication_by_id is not None:
        publication_by_id[resource.id] = publication

    row["oai_is_approved"] = bool(getattr(publication, "is_approved", False))
    row["oai_approved_at"] = getattr(publication, "approved_at", None)
    row["oai_approved_by"] = getattr(publication, "approved_by", None)

    return row


def _build_media_links_panel_context(
    *,
    organization: Organization,
    page_number: int,
    project_access_filter: str = "all",
    oai_publish_filter: str = "all",
    harvestable_filter: str = "all",
    search_query: str = "",
) -> dict[str, Any]:
    is_s3_org = _is_s3_org(organization)
    link_base_qs = OAIProjectMediaLink.objects.filter(project__organization=organization)
    s3_harvestable_ids: Optional[Set[int]] = None
    curated_harvestable_ids: Optional[Set[int]] = None
    if is_s3_org:
        s3_harvestable_ids = _s3_harvestable_project_ids(organization)
    else:
        curated_harvestable_ids = _curated_harvestable_project_ids(organization)
    summary = _build_media_links_summary(
        organization,
        link_base_qs,
        project_access_filter=project_access_filter,
        oai_publish_filter=oai_publish_filter,
        harvestable_filter=harvestable_filter,
        s3_harvestable_ids=s3_harvestable_ids,
        curated_harvestable_ids=curated_harvestable_ids,
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

    if project_access_filter != "all":
        projects_qs = projects_qs.filter(public_access_level=project_access_filter)

    if oai_publish_filter == "approved":
        projects_qs = projects_qs.filter(oai_publication__is_approved=True)
    elif oai_publish_filter == "pending":
        projects_qs = projects_qs.filter(
            models.Q(oai_publication__isnull=True) | models.Q(oai_publication__is_approved=False)
        )

    if harvestable_filter == "harvestable":
        if s3_harvestable_ids is not None:
            if s3_harvestable_ids:
                projects_qs = projects_qs.filter(id__in=s3_harvestable_ids)
            else:
                projects_qs = projects_qs.none()
        elif curated_harvestable_ids is not None:
            if curated_harvestable_ids:
                projects_qs = projects_qs.filter(id__in=curated_harvestable_ids)
            else:
                projects_qs = projects_qs.none()
        else:
            projects_qs = _restrict_to_harvestable_files(projects_qs)
    elif harvestable_filter == "non_harvestable":
        if s3_harvestable_ids is not None:
            if s3_harvestable_ids:
                projects_qs = projects_qs.exclude(id__in=s3_harvestable_ids)
        elif curated_harvestable_ids is not None:
            if curated_harvestable_ids:
                projects_qs = projects_qs.exclude(id__in=curated_harvestable_ids)
        else:
            harvestable_qs = _restrict_to_harvestable_files(projects_qs)
            projects_qs = projects_qs.exclude(pk__in=harvestable_qs.values("pk"))

    paginator = Paginator(projects_qs, MEDIA_LINKS_PAGE_SIZE)
    page_obj = paginator.get_page(page_number)
    project_resources: List[Resource] = list(page_obj.object_list)
    page_obj.object_list = project_resources

    builder = OAIProjectBuilderTailored()
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

    _attach_s3_metadata(project_resources, organization)

    # Attach OAI publication metadata per project
    publication_by_id: Dict[Any, OAIProjectPublication] = {}
    if project_resources:
        publication_qs = OAIProjectPublication.objects.filter(project_id__in=[p.id for p in project_resources])
        publication_by_id = {pub.project_id: pub for pub in publication_qs}

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

    _attach_s3_metadata(project_resources, organization)

    for project_resource in project_resources:
        row = _build_project_row_context(
            project_resource,
            builder=builder,
            assembler=assembler,
            org_code=organization.code or "",
            is_s3_org=is_s3_org,
            label_lookup=label_lookup,
            publication_by_id=publication_by_id,
        )
        if row["builder_error"]:
            builder_errors.append(project_resource.uri)
        rows.append(row)

    return {
        "selected_org": organization,
        "selected_org_code": organization.code or "",
        "search_query": search_query,
        "summary": summary,
        "project_rows": rows,
        "project_total": paginator.count,
        "current_page": page_obj.number,
        "page_obj": page_obj,
        "per_page": MEDIA_LINKS_PAGE_SIZE,
        "builder_errors": builder_errors,
        "view_mode": "project",
        "oai_publish_filter": oai_publish_filter,
        "harvestable_filter": harvestable_filter,
        "include_summary_partial": False,
    }


def _build_single_project_row_context(
    *,
    organization: Organization,
    project_id: Any,
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

    builder = OAIProjectBuilderTailored()
    assembler = OAIProjectAssembler()
    label_lookup = _prefetch_resource_labels([resource])
    digital_resources: List[Resource] = []
    for link in getattr(resource, "prefetched_media_links", []) or []:
        digital = getattr(link, "digital_object", None)
        if digital:
            digital_resources.append(digital)
    if digital_resources:
        label_lookup = _prefetch_resource_labels(digital_resources, cache=label_lookup)

    _attach_s3_metadata([resource], organization)

    publication = OAIProjectPublication.objects.filter(project=resource).first()
    publication_by_id: Dict[Any, OAIProjectPublication] = {}
    if publication:
        publication_by_id[resource.id] = publication

    return _build_project_row_context(
        resource,
        builder=builder,
        assembler=assembler,
        org_code=organization.code or "",
        is_s3_org=_is_s3_org(organization),
        label_lookup=label_lookup,
        publication_by_id=publication_by_id,
    )


def _render_project_row_response(
    request,
    *,
    organization: Organization,
    project_id: Any,
    page_number: int,
):
    row = _build_single_project_row_context(
        organization=organization,
        project_id=project_id,
    )
    if row is None:
        return HttpResponseBadRequest("<div class='alert alert-error'>Unable to load project row.</div>")

    s3_harvestable_ids: Optional[Set[int]] = None
    curated_harvestable_ids: Optional[Set[int]] = None
    if _is_s3_org(organization):
        s3_harvestable_ids = _s3_harvestable_project_ids(organization)
    else:
        curated_harvestable_ids = _curated_harvestable_project_ids(organization)

    summary = _build_media_links_summary(
        organization,
        OAIProjectMediaLink.objects.filter(project__organization=organization),
        s3_harvestable_ids=s3_harvestable_ids,
        curated_harvestable_ids=curated_harvestable_ids,
    )
    context = {
        "row": row,
        "summary": summary,
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
        for idx, project in enumerate(project_queryset_for_org(org).iterator(chunk_size=100), start=1):
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

    project_access_filter = request.GET.get('project_access', 'all').strip().lower()
    if project_access_filter not in ['all', 'private', 'restricted', 'public']:
        project_access_filter = 'all'

    oai_publish_filter = request.GET.get('oai_publish', 'all').strip().lower()
    if oai_publish_filter not in ['all', 'approved', 'pending']:
        oai_publish_filter = 'all'

    harvestable_filter = request.GET.get('harvestable', 'all').strip().lower()
    if harvestable_filter not in ['all', 'harvestable', 'non_harvestable']:
        harvestable_filter = 'all'

    search_query = (request.GET.get('search') or '').strip()

    page_param = request.GET.get('page') or '1'
    try:
        page_number = max(int(page_param), 1)
    except ValueError:
        page_number = 1

    panel_context = _build_media_links_panel_context(
        organization=organization,
        page_number=page_number,
        project_access_filter=project_access_filter,
        oai_publish_filter=oai_publish_filter,
        harvestable_filter=harvestable_filter,
        search_query=search_query,
    )
    panel_context['include_summary_partial'] = True

    # If not an HTMX request, redirect to the full dashboard with params
    if not request.headers.get('HX-Request'):
        return redirect(f"{reverse('oai_admin:oai_media_links_dashboard')}?organization={organization.code}")

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

    updates: set[str] = set()

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
        if request.user.is_authenticated:
            link.last_reviewed_by = request.user
            link.last_reviewed_at = timezone.now()
            updates.update({'last_reviewed_by', 'last_reviewed_at'})
        updates.add('updated_at')
        link.save(update_fields=list(updates))
        messages.success(request, f"Updated media link for {link.project.uri}.")
    else:
        messages.info(request, 'No changes detected for the selected media link.')

    return _render_project_row_response(
        request,
        organization=organization,
        project_id=link.project_id,
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
    project_uri = getattr(link.project, "uri", "")
    digital_uri = getattr(link.digital_object, "uri", "")
    link.delete()
    messages.success(
        request,
        f"Removed digital object {digital_uri} from project {project_uri}.",
    )

    row_context = _build_single_project_row_context(
        organization=organization,
        project_id=project_id,
    )
    if not row_context or row_context["total_links"] == 0:
        panel_context = _build_media_links_panel_context(
            organization=organization,
            page_number=1,
        )
        panel_context['include_summary_partial'] = True
        return render(request, 'oai/partials/oai_media_links_panel.html', panel_context)

    return _render_project_row_response(
        request,
        organization=organization,
        project_id=project_id,
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
            page_number=page_number,
        )

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
        page_number=1,
    )
    panel_context['include_summary_partial'] = True
    return render(request, 'oai/partials/oai_media_links_panel.html', panel_context)


@general_login_required
@require_POST
def oai_media_link_clear_data(request):
    if not _has_oai_admin_access(request.user):
        return HttpResponseForbidden(
            "<div class='alert alert-error'>Access denied: system administrator permissions required</div>"
        )

    organization = _resolve_organization_by_code(request.POST.get('organization'))
    if not organization:
        return HttpResponseBadRequest("<div class='alert alert-error'>Select an organization.</div>")

    project_access_filter = (request.POST.get('project_access') or 'all').strip().lower()
    if project_access_filter not in ['all', 'private', 'restricted', 'public']:
        project_access_filter = 'all'

    oai_publish_filter = (request.POST.get('oai_publish') or 'all').strip().lower()
    if oai_publish_filter not in ['all', 'approved', 'pending']:
        oai_publish_filter = 'all'

    harvestable_filter = (request.POST.get('harvestable') or 'all').strip().lower()
    if harvestable_filter not in ['all', 'harvestable', 'non_harvestable']:
        harvestable_filter = 'all'

    search_query = (request.POST.get('search') or '').strip()

    links_deleted, _ = OAIProjectMediaLink.objects.filter(project__organization=organization).delete()
    pubs_deleted, _ = OAIProjectPublication.objects.filter(project__organization=organization).delete()

    messages.success(
        request,
        (
            f"Cleared {links_deleted} curated link(s) and "
            f"{pubs_deleted} OAI publication(s) for {organization.code.upper()}."
        ),
    )

    is_htmx = request.headers.get('HX-Request') == 'true'
    if is_htmx:
        panel_context = _build_media_links_panel_context(
            organization=organization,
            page_number=1,
            project_access_filter=project_access_filter,
            oai_publish_filter=oai_publish_filter,
            harvestable_filter=harvestable_filter,
            search_query=search_query,
        )
        panel_context['include_summary_partial'] = True
        return render(request, 'oai/partials/oai_media_links_panel.html', panel_context)

    return redirect('metadata:metadata_dashboard')


@general_login_required
@require_http_methods(["POST"])
def oai_media_link_seed_and_sync(request):
    if not _has_oai_admin_access(request.user):
        return HttpResponseForbidden(
            "<div class='alert alert-error'>Access denied: system administrator permissions required</div>"
        )

    organization = _resolve_organization_by_code(request.POST.get('organization'))
    if not organization:
        return HttpResponseBadRequest("<div class='alert alert-error'>Select an organization.</div>")

    project_access_filter = (request.POST.get('project_access') or 'all').strip().lower()
    if project_access_filter not in ['all', 'private', 'restricted', 'public']:
        project_access_filter = 'all'

    oai_publish_filter = (request.POST.get('oai_publish') or 'all').strip().lower()
    if oai_publish_filter not in ['all', 'approved', 'pending']:
        oai_publish_filter = 'all'

    harvestable_filter = (request.POST.get('harvestable') or 'all').strip().lower()
    if harvestable_filter not in ['all', 'harvestable', 'non_harvestable']:
        harvestable_filter = 'all'

    search_query = (request.POST.get('search') or '').strip()

    page_param = request.POST.get('page') or '1'
    try:
        page_number = max(int(page_param), 1)
    except ValueError:
        page_number = 1

    filters = {
        "project_access_filter": project_access_filter,
        "oai_publish_filter": oai_publish_filter,
        "harvestable_filter": harvestable_filter,
        "search_query": search_query,
        "page_number": page_number,
    }

    job_id = media_sync_jobs.create_job(
        organization_code=organization.code,
        user_id=request.user.id if request.user.is_authenticated else None,
        filters=filters,
    )

    from arkumu.oaipmh.tasks import run_media_link_seed_and_sync_job  # noqa: WPS433 - local import to avoid cycles

    run_media_link_seed_and_sync_job.schedule(args=(job_id,), delay=0)

    context = {
        "job_id": job_id,
        "status": "pending",
        "message": "Sync job queued…",
        "organization": organization,
    }
    return render(request, 'oai/partials/oai_media_links_job_status.html', context)


@general_login_required
@require_http_methods(["GET"])
def oai_media_sync_status(request):
    if not _has_oai_admin_access(request.user):
        return HttpResponseForbidden(
            "<div class='alert alert-error'>Access denied: system administrator permissions required</div>"
        )

    job_id = (request.GET.get('job_id') or '').strip()
    if not job_id:
        return HttpResponseBadRequest("<div class='alert alert-error'>Missing job identifier.</div>")

    state = media_sync_jobs.get_job(job_id)
    if not state:
        return HttpResponseBadRequest(
            "<div class='alert alert-error'>Sync job no longer exists. Please retry.</div>"
        )

    organization = _resolve_organization_by_code(state.get('organization_code'))
    if not organization:
        media_sync_jobs.delete_job(job_id)
        return HttpResponseBadRequest(
            "<div class='alert alert-error'>Organization not found for sync job.</div>"
        )

    status = state.get('status') or 'pending'
    if status in {'pending', 'running'}:
        context = {
            "job_id": job_id,
            "status": status,
            "message": state.get('message', ''),
            "organization": organization,
        }
        return render(request, 'oai/partials/oai_media_links_job_status.html', context)

    filters = state.get('filters') or {}

    project_access_filter = (filters.get('project_access_filter') or 'all').strip().lower()
    if project_access_filter not in ['all', 'private', 'restricted', 'public']:
        project_access_filter = 'all'

    oai_publish_filter = (filters.get('oai_publish_filter') or 'all').strip().lower()
    if oai_publish_filter not in ['all', 'approved', 'pending']:
        oai_publish_filter = 'all'

    harvestable_filter = (filters.get('harvestable_filter') or 'all').strip().lower()
    if harvestable_filter not in ['all', 'harvestable', 'non_harvestable']:
        harvestable_filter = 'all'

    search_query = (filters.get('search_query') or '').strip()

    page_number = filters.get('page_number', 1)
    try:
        page_number = max(int(page_number), 1)
    except (TypeError, ValueError):
        page_number = 1

    if status == 'failed':
        messages.error(request, f"Media sync failed: {state.get('message', 'Unknown error.')}")
    else:
        _emit_media_sync_messages(request, state, organization)

    panel_context = _build_media_links_panel_context(
        organization=organization,
        page_number=page_number,
        project_access_filter=project_access_filter,
        oai_publish_filter=oai_publish_filter,
        harvestable_filter=harvestable_filter,
        search_query=search_query,
    )
    panel_context['include_summary_partial'] = True

    media_sync_jobs.delete_job(job_id)
    return render(request, 'oai/partials/oai_media_links_panel.html', panel_context)


def _build_digital_object_centric_context(
    *,
    organization: Organization,
    page_number: int,
    project_access_filter: str = "all",
    shared_filter: str = "all",
    search_query: str = "",
    oai_publish_filter: str = "all",
) -> dict[str, Any]:
    """Build context for digital object-centric view (groups by digital object, shows projects)."""

    search_query = (search_query or "").strip()
    link_base_qs = OAIProjectMediaLink.objects.filter(project__organization=organization)
    is_s3_org = _is_s3_org(organization)
    harvestable_kwargs: dict[str, Any] = {}
    if is_s3_org:
        harvestable_kwargs["s3_harvestable_ids"] = _s3_harvestable_project_ids(organization)
    else:
        harvestable_kwargs["curated_harvestable_ids"] = _curated_harvestable_project_ids(organization)

    # Apply filters to the link queryset
    filtered_qs = link_base_qs
    if project_access_filter != "all":
        filtered_qs = filtered_qs.filter(project__public_access_level=project_access_filter)
    if oai_publish_filter == "approved":
        filtered_qs = filtered_qs.filter(project__oai_publication__is_approved=True)
    elif oai_publish_filter == "pending":
        filtered_qs = filtered_qs.filter(
            models.Q(project__oai_publication__isnull=True)
            | models.Q(project__oai_publication__is_approved=False)
        )
    if search_query:
        digital_match_filter = (
            Q(uri__icontains=search_query)
            | Q(name__icontains=search_query)
            | Q(value__icontains=search_query)
            | Q(subject_triples__object__value__icontains=search_query)
        )
        matching_digital_object_ids = (
            Resource.objects.filter(id__in=filtered_qs.values('digital_object_id'))
            .filter(digital_match_filter)
            .values_list('id', flat=True)
            .distinct()
        )
        filtered_qs = filtered_qs.filter(digital_object_id__in=matching_digital_object_ids)

    # Group by digital object and aggregate project information
    digital_objects_data = (
        filtered_qs
        .values('digital_object_id')
        .annotate(
            project_count=Count('project_id', distinct=True),
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

    # Determine S3 presence for digital objects (FUK/DET/RSH orgs)
    s3_file_by_resource: Dict[Any, S3FileObject] = {}
    if digital_object_ids:
        s3_qs = (
            S3FileObject.objects.filter(
                related_resource_id__in=digital_object_ids,
                status__in=HARVESTABLE_STORAGE_STATUSES,
                s3_key__isnull=False,
            )
            .exclude(s3_key="")
        )
        for file_obj in s3_qs:
            rid = file_obj.related_resource_id
            existing = s3_file_by_resource.get(rid)
            if existing is None:
                s3_file_by_resource[rid] = file_obj
                continue
            if existing.status != "verified" and file_obj.status == "verified":
                s3_file_by_resource[rid] = file_obj

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

    if project_access_filter != "all":
        links_for_page = links_for_page.filter(project__public_access_level=project_access_filter)
    if oai_publish_filter == "approved":
        links_for_page = links_for_page.filter(project__oai_publication__is_approved=True)
    elif oai_publish_filter == "pending":
        links_for_page = links_for_page.filter(
            models.Q(project__oai_publication__isnull=True)
            | models.Q(project__oai_publication__is_approved=False)
        )

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

        s3_file = s3_file_by_resource.get(digital_object_id)
        has_s3_file = s3_file is not None
        s3_key_preview = s3_file.s3_key if s3_file else ""

        # Add display labels and S3 info to links
        for link in links:
            link.project_display_label = _resource_display_label(  # type: ignore[attr-defined]
                link.project,
                fallback="Untitled project",
                label_lookup=label_lookup,
            )
            setattr(link, "has_s3_file", has_s3_file)
            setattr(link, "s3_key_preview", s3_key_preview)

        digital_object_label = _resource_display_label(
            digital_resource,
            fallback="Untitled digital object",
            label_lookup=label_lookup,
        )

        digital_object_rows.append({
            "digital_object": digital_resource,
            "digital_object_uri": digital_resource.uri,
            "digital_object_label": digital_object_label,
            "has_s3_file": has_s3_file,
            "s3_key_preview": s3_key_preview,
            "project_count": item['project_count'],
            "is_shared": item['project_count'] > 1,
            "has_stale": item['has_stale'] > 0,
            "links": links,
        })

    # Build summary stats (same as project view)
    summary = _build_media_links_summary(
        organization,
        link_base_qs,
        project_access_filter=project_access_filter,
        oai_publish_filter=oai_publish_filter,
        **harvestable_kwargs,
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
        "view_mode": "digital",
        "include_summary_partial": False,
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

    project_access_filter = request.GET.get('project_access', 'all').strip().lower()
    if project_access_filter not in ['all', 'private', 'restricted', 'public']:
        project_access_filter = 'all'

    shared_filter = request.GET.get('shared', 'all').strip().lower()
    if shared_filter not in ['all', 'shared', 'single']:
        shared_filter = 'all'

    oai_publish_filter = request.GET.get('oai_publish', 'all').strip().lower()
    if oai_publish_filter not in ['all', 'approved', 'pending']:
        oai_publish_filter = 'all'

    search_query = (request.GET.get('search') or '').strip()

    page_param = request.GET.get('page') or '1'
    try:
        page_number = max(int(page_param), 1)
    except ValueError:
        page_number = 1

    context = _build_digital_object_centric_context(
        organization=organization,
        page_number=page_number,
        project_access_filter=project_access_filter,
        shared_filter=shared_filter,
        search_query=search_query,
        oai_publish_filter=oai_publish_filter,
    )
    context['include_summary_partial'] = True

    # If not an HTMX request, redirect to the full dashboard with params
    if not request.headers.get('HX-Request'):
        return redirect(
            f"{reverse('oai_admin:oai_media_links_dashboard')}?organization={organization.code}"
            f"&view=digital&shared={shared_filter}"
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

    organization = resource.organization
    if not organization:
        return HttpResponseBadRequest("<div class='alert alert-error'>Project organization missing.</div>")

    page_number = 1
    page_param = request.POST.get('page')
    if page_param:
        try:
            page_number = max(int(page_param), 1)
        except ValueError:
            page_number = 1

    oai_publish_action = (request.POST.get('oai_publish_action') or '').strip().lower()
    if oai_publish_action:
        row_context = _build_single_project_row_context(
            organization=organization,
            project_id=resource.id,
        )
        if row_context is None:
            return HttpResponseBadRequest("<div class='alert alert-error'>Unable to load project context.</div>")

        has_harvestable = bool(row_context.get("has_harvestable_files"))

        publication, _ = OAIProjectPublication.objects.get_or_create(project=resource)

        if oai_publish_action == 'approve':
            publication.is_approved = True
            publication.approved_at = timezone.now()
            publication.approved_by = request.user if request.user.is_authenticated else None
            publication.save()
        elif oai_publish_action == 'revoke':
            publication.is_approved = False
            publication.approved_at = None
            publication.approved_by = None
            publication.save()
        else:
            return HttpResponseBadRequest("<div class='alert alert-error'>Invalid OAI publish action.</div>")

        # Refresh only the affected project row and summary via OOB swap
        return _render_project_row_response(
            request,
            organization=organization,
            project_id=resource.id,
            page_number=page_number,
        )

    return HttpResponseBadRequest("<div class='alert alert-error'>Invalid request.</div>")


@general_login_required
@require_http_methods(["POST"])
def oai_publication_sync(request):
    if not _has_oai_admin_access(request.user):
        return HttpResponseForbidden(
            "<div class='alert alert-error'>Access denied: system administrator permissions required</div>"
        )

    organization = _resolve_organization_by_code(request.POST.get('organization'))
    if not organization:
        return HttpResponseBadRequest("<div class='alert alert-error'>Select an organization.</div>")

    project_access_filter = (request.POST.get('project_access') or 'all').strip().lower()
    if project_access_filter not in ['all', 'private', 'restricted', 'public']:
        project_access_filter = 'all'

    oai_publish_filter = (request.POST.get('oai_publish') or 'all').strip().lower()
    if oai_publish_filter not in ['all', 'approved', 'pending']:
        oai_publish_filter = 'all'

    page_param = request.POST.get('page') or '1'
    try:
        page_number = max(int(page_param), 1)
    except ValueError:
        page_number = 1

    summary = _sync_oai_publication_for_org(organization, user=request.user)
    if summary["auto_approved"]:
        messages.success(
            request,
            f"Auto-approved OAI publication for {summary['auto_approved']} project(s).",
        )
    else:
        messages.info(request, "No additional projects were auto-approved for OAI.")

    panel_context = _build_media_links_panel_context(
        organization=organization,
        page_number=page_number,
        project_access_filter=project_access_filter,
        oai_publish_filter=oai_publish_filter,
    )
    panel_context['include_summary_partial'] = True
    return render(request, 'oai/partials/oai_media_links_panel.html', panel_context)
