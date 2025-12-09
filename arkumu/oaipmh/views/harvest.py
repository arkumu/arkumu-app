"""Harvest helpers and paging logic for Arkumu OAI views."""

from __future__ import annotations

import logging
from collections import Counter
import re
from dataclasses import dataclass
from datetime import datetime, timezone as dt_timezone, timedelta
from typing import Dict, List, Optional, Sequence, Tuple, Any

from django.conf import settings
from django.db.models import Exists, OuterRef, Q
from django.utils import timezone

from arkumu.metadata.models.resource import PublicAccessLevel, Resource
from arkumu.metadata.models.triples import Triple
from arkumu.metadata.services.oai_stats import classify_project_access
from arkumu.projects import ProjectRecord, ProjectSnapshot
from arkumu.storage.models.s3_file_objects import S3FileObject
from arkumu.oaipmh.models import OAIProjectMediaLink

from .config import (
    HARVESTABLE_FILE_STATUSES,
    _PROJECT_TYPE_URIS,
    _RDF_TYPE_URI,
    _curated_media_links_active,
    _db_mode_enabled,
)
from .projects import (
    _build_project_hint_from_resource,
    _fallback_record_from_storage,
    _project_ids_with_dump_digital_objects,
    _digital_object_orgs,
    project_builder,
    snapshot_service,
)

logger = logging.getLogger(__name__)

@dataclass
class HarvestPageResult:
    resources: List[Resource]
    project_hints: Dict[str, OAIProject]
    has_more: bool
    cursor_position: Optional[str]


def _parse_from_datestamp(date_str: str) -> datetime:
    """Parse a 'from' datestamp into an inclusive datetime."""
    if 'T' in date_str:
        return datetime.fromisoformat(date_str.replace('Z', '+00:00'))
    dt = datetime.strptime(date_str, '%Y-%m-%d').replace(tzinfo=dt_timezone.utc)
    return dt


def _parse_until_datestamp(date_str: str) -> datetime:
    """Parse an 'until' datestamp and return an exclusive upper bound."""
    if 'T' in date_str:
        base = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
        return base + timedelta(seconds=1)
    base = datetime.strptime(date_str, '%Y-%m-%d').replace(tzinfo=dt_timezone.utc)
    return base + timedelta(days=1)


def _validate_datestamp(date_str: Optional[str]) -> Optional[str]:
    """Validate OAI-PMH datestamp format. Returns error message if invalid."""
    if date_str is None or date_str == "":
        return None

    if date_str.strip() != date_str or not date_str.strip():
        return "Invalid date format. Use YYYY-MM-DD or YYYY-MM-DDThh:mm:ssZ"

    try:
        if 'T' in date_str:
            if not date_str.endswith('Z'):
                return "Invalid date format. Use YYYY-MM-DD or YYYY-MM-DDThh:mm:ssZ"
            dt_part = date_str[:-1]
            import re
            if not re.match(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$', dt_part):
                raise ValueError("Invalid format")
            datetime.strptime(dt_part, '%Y-%m-%dT%H:%M:%S')
        else:
            import re
            if not re.match(r'^\d{4}-\d{2}-\d{2}$', date_str):
                raise ValueError("Invalid format")
            datetime.strptime(date_str, '%Y-%m-%d')
        return None
    except ValueError:
        return "Invalid date format. Use YYYY-MM-DD or YYYY-MM-DDThh:mm:ssZ"


def _project_type_filter() -> Optional[Q]:
    if not _PROJECT_TYPE_URIS:
        return None
    predicate_filter = (
        Q(subject_triples__predicate__uri=_RDF_TYPE_URI)
        | Q(subject_triples__predicate__canonical_uri=_RDF_TYPE_URI)
    )
    object_filter = (
        Q(subject_triples__object__uri__in=_PROJECT_TYPE_URIS)
        | Q(subject_triples__object__canonical_uri__in=_PROJECT_TYPE_URIS)
    )
    return predicate_filter & object_filter
def _format_cursor_position(resource: Resource, *, field_name: str = "updated_at") -> str:
    timestamp = getattr(resource, field_name, None)
    if timestamp is None:
        timestamp = getattr(resource, "updated_at", None)
    if timestamp is None:
        timestamp = timezone.now()
    return f"{timestamp.isoformat()}|{resource.pk}"
def _parse_cursor_position(token: Optional[str]) -> Optional[tuple[datetime, str]]:
    if not token:
        return None
    try:
        timestamp_str, pk_str = token.rsplit("|", 1)
        return datetime.fromisoformat(timestamp_str), pk_str
    except ValueError:
        return None
def _apply_cursor_filter(
    queryset,
    cursor_state: Optional[tuple[datetime, str]],
    *,
    field_name: str = "updated_at",
):
    if not cursor_state:
        return queryset
    timestamp, pk = cursor_state
    return queryset.filter(
        Q(**{f"{field_name}__gt": timestamp})
        | (Q(**{f"{field_name}": timestamp}) & Q(id__gt=pk))
    )
def _dataset_marker_for_queryset(queryset, *, field_name: str = "updated_at") -> str:
    latest = (
        queryset
        .order_by(f"-{field_name}", "-id")
        .values_list(field_name, "id")
        .first()
    )
    if not latest or latest[0] is None:
        return "empty"
    updated_at, _ = latest
    return updated_at.isoformat()
def _has_more_db_harvestables(queryset, cursor_position: Optional[str]) -> bool:
    cursor_state = _parse_cursor_position(cursor_position)
    if cursor_state is None:
        return False

    lookahead_qs = _apply_cursor_filter(
        queryset.order_by("updated_at", "id"),
        cursor_state,
    )
    iterator = lookahead_qs.iterator(chunk_size=100)
    for resource in iterator:
        project_hint = _build_project_hint_from_resource(resource)
        if project_hint and project_hint.harvestable:
            return True
    return False
def _harvestable_page_from_db(
    queryset,
    *,
    cursor_position: Optional[str],
    page_size: int,
    include_hints: bool,
) -> HarvestPageResult:
    ordered = queryset.order_by("updated_at", "id")
    ordered = _apply_cursor_filter(ordered, _parse_cursor_position(cursor_position))

    iterator = ordered.iterator(chunk_size=max(page_size * 10, 100))
    resources: List[Resource] = []
    project_hints: Dict[str, OAIProject] = {}
    last_cursor_position = cursor_position

    for resource in iterator:
        last_cursor_position = _format_cursor_position(resource)
        project_hint = _build_project_hint_from_resource(resource)
        if not project_hint or not project_hint.harvestable:
            continue
        if include_hints:
            project_hints[resource.uri] = project_hint
        resources.append(resource)
        if len(resources) == page_size:
            break

    has_more = False
    if resources:
        has_more = _has_more_db_harvestables(ordered, last_cursor_position)  # type: ignore[arg-type]

    return HarvestPageResult(
        resources=resources,
        project_hints=project_hints,
        has_more=has_more,
        cursor_position=last_cursor_position,
    )
def _restrict_to_harvestable_files(queryset):
    """Limit queryset to resources with at least one linked S3 object ready for harvest."""

    s3_condition = (
        Q(s3fileobject__status__in=HARVESTABLE_FILE_STATUSES)
        & Q(s3fileobject__s3_key__isnull=False)
        & ~Q(s3fileobject__s3_key__exact="")
    )

    rosetta_orgs = {
        code.lower().strip()
        for code in getattr(settings, "OAI_ROSETTA_HARVESTABLE_ORGS", ())
        if code
    }
    s3_harvestable_orgs = {
        code.lower().strip()
        for code in getattr(settings, "OAI_S3_HARVESTABLE_ORGS", ())
        if code
    }

    event_file_event_ids = S3FileObject.objects.filter(
        status__in=HARVESTABLE_FILE_STATUSES,
        related_resource__uri__regex=r'/entities/ereignis/[0-9]+$',
    ).values('related_resource_id')

    project_ids_via_events = Triple.objects.filter(
        predicate__uri__endswith='/properties/ereignis',
        object_id__in=event_file_event_ids,
    ).values('subject_id')

    project_event_condition = Q(pk__in=project_ids_via_events)

    digital_object_orgs = _digital_object_orgs()
    dump_project_ids: set[Any] = set()
    if digital_object_orgs:
        dump_project_ids = _project_ids_with_dump_digital_objects(digital_object_orgs)

    event_condition = project_event_condition
    if digital_object_orgs:
        event_condition = project_event_condition & ~Q(organization__code__in=digital_object_orgs)

    # Digital-object S3 linkage: project -> digital object -> S3FileObject
    digital_object_files = Triple.objects.filter(
        predicate__uri__endswith="/properties/digitales-objekt",
        subject_id=OuterRef("pk"),
    ).values("object_id")

    event_ids_for_project = Triple.objects.filter(
        predicate__uri__endswith="/properties/ereignis",
        subject_id=OuterRef("pk"),
    ).values("object_id")

    digital_object_files_via_events = Triple.objects.filter(
        predicate__uri__endswith="/properties/digitales-objekt",
        subject_id__in=event_ids_for_project,
    ).values("object_id")

    digital_object_s3_condition = Exists(
        S3FileObject.objects.filter(
            status__in=HARVESTABLE_FILE_STATUSES,
            s3_key__isnull=False,
        )
        .exclude(s3_key="")
        .filter(
            Q(related_resource_id__in=digital_object_files)
            | Q(related_resource_id__in=digital_object_files_via_events)
        )
    )

    curated_links = OAIProjectMediaLink.objects.filter(
        project_id=OuterRef('pk'),
        digital_object__isnull=False,
    )

    curated_condition = None
    if s3_harvestable_orgs:
        s3_link_condition = Exists(
            curated_links.filter(
                project__organization__code__in=s3_harvestable_orgs,
                digital_object__s3fileobject__status__in=HARVESTABLE_FILE_STATUSES,
                digital_object__s3fileobject__s3_key__isnull=False,
            ).exclude(digital_object__s3fileobject__s3_key="")
        )
        curated_condition = s3_link_condition

    if rosetta_orgs:
        rosetta_link_condition = Exists(
            curated_links.filter(project__organization__code__in=rosetta_orgs)
        )
        curated_condition = (
            rosetta_link_condition
            if curated_condition is None
            else (curated_condition | rosetta_link_condition)
        )

    combined_condition = s3_condition | event_condition | digital_object_s3_condition
    if curated_condition is not None:
        combined_condition |= curated_condition
    if dump_project_ids:
        combined_condition |= Q(pk__in=list(dump_project_ids))

    queryset = queryset.filter(combined_condition)

    return queryset.distinct()
def _get_resources_queryset(
    set_spec: Optional[str] = None,
    from_date: Optional[str] = None,
    until_date: Optional[str] = None,
    metadata_prefix: Optional[str] = None,
    allowed_uris: Optional[Sequence[str]] = None,
):
    """Build a filtered queryset for harvestable resources."""
    # For both Dublin Core and METS: expose only project entities as primary records
    # Each project will have rich metadata assembled from its complete graph
    access_clause = Q(public_access_level=PublicAccessLevel.RESTRICTED) | (
        Q(public_access_level=PublicAccessLevel.PUBLIC) & Q(is_public_approved=True)
    )

    project_type_clause = _project_type_filter()

    if allowed_uris is not None:
        uris = list(dict.fromkeys(allowed_uris))
        if not uris:
            return Resource.objects.none()
        queryset = (
            Resource.objects.filter(uri__in=uris)
            .filter(access_clause)
            .select_related('organization', 'project_index')
            .order_by('updated_at', 'id')
        )
    else:
        queryset = Resource.objects.filter(access_clause).select_related('organization', 'project_index')
        if project_type_clause is not None:
            typed_queryset = queryset.filter(project_type_clause).distinct()
            if typed_queryset.exists():
                queryset = typed_queryset
            else:
                queryset = queryset.filter(uri__regex=r'/entities/projekt/[0-9]+$')
        else:
            queryset = queryset.filter(uri__regex=r'/entities/projekt/[0-9]+$')
        queryset = queryset.order_by('updated_at', 'id')

    if allowed_uris is None:
        queryset = _restrict_to_harvestable_files(queryset)

    # Filter by set (organization)
    if set_spec:
        queryset = queryset.filter(organization__code__iexact=set_spec, organization__is_active=True)

    # Temporal filtering with proper OAI-PMH date validation
    if from_date:
        try:
            from_dt = _parse_from_datestamp(from_date)
            queryset = queryset.filter(updated_at__gte=from_dt)
        except ValueError:
            pass  # Invalid date format, ignore

    if until_date:
        try:
            until_dt = _parse_until_datestamp(until_date)
            queryset = queryset.filter(updated_at__lt=until_dt)
        except ValueError:
            pass  # Invalid date format, ignore

    return queryset
def _harvestable_snapshot_projects() -> tuple[ProjectSnapshot, Dict[str, OAIProject]]:
    """Build a mapping of harvestable projects keyed by project URI."""

    snapshot = snapshot_service.get_cross_institutional_snapshot()
    harvestable: Dict[str, OAIProject] = {}

    for record in snapshot.projects:
        project = project_builder.from_project_record(
            record,
            skip_shared_event_filter=_db_mode_enabled(),
            skip_format_exclusion=_db_mode_enabled(),
            use_curated_media_links=_curated_media_links_active(),
        )
        if project.harvestable:
            harvestable[project.uri] = project

    org_counts = {}
    for proj in harvestable.values():
        org = proj.institution_code or 'unknown'
        org_counts[org] = org_counts.get(org, 0) + 1

    accessible_uris, blocked_uris, missing_resource_uris = classify_project_access(harvestable.values())

    accessible_counts = Counter()
    blocked_counts = Counter()

    for uri in accessible_uris:
        project = harvestable.get(uri)
        if not project:
            continue
        code = (project.institution_code or 'unknown').lower()
        accessible_counts[code] += 1

    for uri in blocked_uris:
        project = harvestable.get(uri)
        if not project:
            continue
        code = (project.institution_code or 'unknown').lower()
        blocked_counts[code] += 1

    logger.info(
        "OAI harvestable projects: %d total (accessible=%d, blocked=%d, missing_resources=%d), by org total=%s accessible=%s blocked=%s",
        len(harvestable),
        len(accessible_uris),
        len(blocked_uris),
        len(missing_resource_uris),
        dict(sorted(org_counts.items())),
        dict(sorted(accessible_counts.items())),
        dict(sorted(blocked_counts.items())),
    )

    if not harvestable:
        fallback_records: List[ProjectRecord] = []
        fallback_resources = (
            Resource.objects.filter(
                s3fileobject__status__in=HARVESTABLE_FILE_STATUSES,
                s3fileobject__s3_key__isnull=False,
            )
            .exclude(s3fileobject__s3_key="")
            .distinct()
        )

        for resource in fallback_resources:
            record = _fallback_record_from_storage(resource)
            if not record:
                continue
            project = project_builder.from_project_record(
                record,
                skip_shared_event_filter=_db_mode_enabled(),
                skip_format_exclusion=_db_mode_enabled(),
                use_curated_media_links=_curated_media_links_active(),
            )
            if not project.harvestable:
                continue
            harvestable[project.uri] = project
            fallback_records.append(record)

        if fallback_records:
            snapshot = ProjectSnapshot(
                projects=list(snapshot.projects) + fallback_records,
                counts=snapshot.counts,
                generated_at=snapshot.generated_at,
            )

    return snapshot, harvestable
