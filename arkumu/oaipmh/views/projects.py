"""Project assembly helpers shared across OAI views."""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any, Dict, List, Optional

from django.conf import settings
from django.utils.module_loading import import_string

from arkumu.catalog.services.project_views import ProjectURIs
from arkumu.metadata.models.resource import Resource
from arkumu.metadata.models.triples import Triple
from arkumu.oaipmh.oai_project import OAIProject, OAIProjectBuilder
from arkumu.oaipmh.oai_project_tailored import OAIProjectBuilderTailored
from arkumu.oaipmh.services import AssemblyContext, OAIProjectAssembler
from arkumu.projects import ProjectDigitalObject, ProjectRecord, ProjectSnapshot
from arkumu.projects.fixity import parse_fixity
from arkumu.projects.services import ProjectSnapshotService
from arkumu.projects.services.s3_key_index import lookup_dump_storage_key
from arkumu.storage.models.s3_file_objects import S3FileObject

from .config import (
    HARVESTABLE_FILE_STATUSES,
    _DIGITAL_OBJECT_ORG_DEFAULT,
    _curated_media_links_active,
    _db_mode_enabled,
)

logger = logging.getLogger(__name__)

project_builder = OAIProjectBuilder()
_tailored_project_builder = OAIProjectBuilderTailored()
_db_project_assembler_instance: Optional[OAIProjectAssembler] = None


def get_project_builder() -> OAIProjectBuilder:
    """Return the baseline project builder for non-tailored consumers."""
    return project_builder


def _digital_object_orgs() -> set[str]:
    configured = getattr(settings, "OAI_DIGITAL_OBJECT_LINK_ORGS", _DIGITAL_OBJECT_ORG_DEFAULT)
    return {
        str(code).lower().strip()
        for code in configured
        if code
    }


def _get_db_project_assembler() -> Optional[OAIProjectAssembler]:
    if not _db_mode_enabled():
        return None
    global _db_project_assembler_instance
    if _db_project_assembler_instance is None:
        _db_project_assembler_instance = OAIProjectAssembler()
    return _db_project_assembler_instance

def _get_db_project_assembler() -> Optional[OAIProjectAssembler]:
    if not _db_mode_enabled():
        return None
    global _db_project_assembler_instance
    if _db_project_assembler_instance is None:
        _db_project_assembler_instance = OAIProjectAssembler()
    return _db_project_assembler_instance
def _build_project_hint_from_resource(resource: Resource) -> Optional[OAIProject]:
    record = _assemble_record_from_db(resource)
    if record is None and not _db_mode_enabled():
        record = snapshot_service.get_record_by_uri(resource.uri)
    if record is None:
        return None
    try:
        builder = get_project_builder()
        return builder.from_project_record(
            record,
            skip_shared_event_filter=_db_mode_enabled(),
            skip_format_exclusion=_db_mode_enabled(),
            use_curated_media_links=_curated_media_links_active(),
        )
    except Exception:
        logger.exception("Failed to build OAI project for %s", resource.uri)
        return None


def _build_tailored_project_hint_from_resource(resource: Resource) -> Optional[OAIProject]:
    """Build a tailored project using the tailored-only builder."""

    record = _assemble_record_from_db(resource)
    if record is None and not _db_mode_enabled():
        record = snapshot_service.get_record_by_uri(resource.uri)
    if record is None:
        return None

    try:
        return _tailored_project_builder.from_project_record(
            record,
            skip_shared_event_filter=False,
            skip_format_exclusion=_db_mode_enabled(),
            use_curated_media_links=True,
        )
    except Exception:
        logger.exception("Failed to build tailored OAI project for %s", resource.uri)
        return None
def _assemble_record_from_db(resource: Optional[Resource]) -> Optional[ProjectRecord]:
    """Attempt to assemble a ProjectRecord via the DB-backed assembler."""
    assembler = _get_db_project_assembler()
    if not assembler or not resource:
        return None

    try:
        context = AssemblyContext(resource=resource)
        return assembler.build_record(context)
    except Exception:  # pragma: no cover - defensive logging
        logger.exception("DB-backed OAI assembler failed for %s", getattr(resource, "uri", "unknown"))
    return None
def _project_ids_with_dump_digital_objects(org_codes: set[str]) -> set[Any]:
    if not org_codes:
        return set()

    normalized_codes = {
        code.strip().lower()
        for code in org_codes
        if code and str(code).strip()
    }
    if not normalized_codes:
        return set()

    project_to_digital: dict[Any, set[Any]] = defaultdict(set)
    project_to_org: dict[Any, str] = {}

    digital_links = Triple.objects.filter(
        predicate__uri__endswith="/properties/digitales-objekt",
        subject__uri__contains="/entities/projekt/",
        subject__organization__code__in=normalized_codes,
    ).values_list("subject_id", "object_id", "subject__organization__code")

    for project_id, digital_id, org_code in digital_links:
        project_to_digital[project_id].add(digital_id)
        if org_code:
            project_to_org.setdefault(project_id, org_code.lower().strip())

    event_links = Triple.objects.filter(
        predicate__uri__endswith="/properties/digitales-objekt",
        subject__uri__contains="/entities/ereignis/",
        subject__organization__code__in=normalized_codes,
    ).values_list("subject_id", "object_id")

    event_to_digital: dict[Any, set[Any]] = defaultdict(set)
    for event_id, digital_id in event_links:
        event_to_digital[event_id].add(digital_id)

    if event_to_digital:
        project_event_links = Triple.objects.filter(
            predicate__uri__endswith="/properties/ereignis",
            object_id__in=list(event_to_digital.keys()),
            subject__uri__contains="/entities/projekt/",
            subject__organization__code__in=normalized_codes,
        ).values_list("subject_id", "object_id", "subject__organization__code")

        for project_id, event_id, org_code in project_event_links:
            digital_candidates = event_to_digital.get(event_id)
            if not digital_candidates:
                continue
            project_to_digital[project_id].update(digital_candidates)
            if org_code:
                project_to_org.setdefault(project_id, org_code.lower().strip())

    if not project_to_digital:
        return set()

    digital_ids: set[Any] = set()
    for values in project_to_digital.values():
        digital_ids.update(values)

    if not digital_ids:
        return set()

    digital_paths: dict[Any, List[str]] = defaultdict(list)
    path_triples = Triple.objects.filter(
        predicate__uri=ProjectURIs.DIGITAL_OBJECT_PATH,
        subject_id__in=list(digital_ids),
    ).values_list("subject_id", "object__value")
    for digital_id, literal_value in path_triples:
        if literal_value:
            digital_paths[digital_id].append(literal_value)

    if not digital_paths:
        return set()

    project_ids = list(project_to_digital.keys())
    project_org_lookup = {
        project_id: (code or "").lower().strip()
        for project_id, code in Resource.objects.filter(id__in=project_ids).values_list(
            "id", "organization__code"
        )
    }

    matched_projects: set[Any] = set()
    for project_id, digital_candidates in project_to_digital.items():
        org_code = project_org_lookup.get(project_id) or project_to_org.get(project_id)
        normalized_org = (org_code or "").strip().lower()
        if normalized_org not in normalized_codes:
            continue
        for digital_id in digital_candidates:
            path_values = digital_paths.get(digital_id)
            if not path_values:
                continue
            matched = lookup_dump_storage_key(normalized_org, path_values)
            if matched:
                matched_projects.add(project_id)
                break

    return matched_projects
def _fallback_record_from_storage(resource: Resource) -> Optional[ProjectRecord]:
    """Construct a minimal ProjectRecord using linked S3 files."""

    if not isinstance(resource, Resource) or getattr(resource, 'pk', None) is None:
        return None

    direct_files = S3FileObject.objects.filter(
        related_resource=resource,
        status__in=HARVESTABLE_FILE_STATUSES,
        s3_key__isnull=False,
    ).exclude(s3_key="")

    resource_org_code = None
    if getattr(resource, "organization", None) and getattr(resource.organization, "code", None):
        resource_org_code = resource.organization.code.lower().strip()

    digital_files = S3FileObject.objects.none()
    digital_object_ids: set[int] = set(
        Triple.objects.filter(
            subject=resource,
            predicate__uri__endswith='/properties/digitales-objekt',
        ).values_list('object_id', flat=True)
    )
    digital_object_orgs = _digital_object_orgs()
    is_digital_only = resource_org_code and resource_org_code in digital_object_orgs
    if is_digital_only:
        event_ids_linked_to_project = list(
            Triple.objects.filter(
                subject=resource,
                predicate__uri__endswith='/properties/ereignis',
            ).values_list('object_id', flat=True)
        )
        if event_ids_linked_to_project:
            event_digital_ids = Triple.objects.filter(
                subject_id__in=event_ids_linked_to_project,
                predicate__uri__endswith='/properties/digitales-objekt',
            ).values_list('object_id', flat=True)
            digital_object_ids.update(event_digital_ids)

    if digital_object_ids:
        digital_files = S3FileObject.objects.filter(
            related_resource_id__in=list(digital_object_ids),
            status__in=HARVESTABLE_FILE_STATUSES,
            s3_key__isnull=False,
        ).exclude(s3_key="")

    event_ids = Triple.objects.filter(
        subject=resource,
        predicate__uri__endswith='/properties/ereignis',
    ).values_list('object_id', flat=True)

    event_files = S3FileObject.objects.none()
    if not is_digital_only:
        event_files = S3FileObject.objects.filter(
            related_resource_id__in=event_ids,
            status__in=HARVESTABLE_FILE_STATUSES,
            s3_key__isnull=False,
        ).exclude(s3_key="")

    files = list(direct_files)
    if is_digital_only and digital_files.exists():
        files.extend(
            list(
                digital_files.exclude(
                    id__in=direct_files.values('id')
                )
            )
        )
    if not is_digital_only:
        files.extend(
            list(
                event_files.exclude(
                    id__in=direct_files.values('id')
                ).exclude(
                    id__in=digital_files.values('id')
                )
            )
        )

    if not files:
        return None

    digital_objects: List[ProjectDigitalObject] = []
    for file_obj in files:
        fixity = parse_fixity(getattr(file_obj, 'sha256_checksum', None))
        digital_objects.append(
            ProjectDigitalObject(
                path=file_obj.s3_key,
                storage_key=file_obj.s3_key,
                file_name=file_obj.file_name,
                content_type=file_obj.content_type,
                size_bytes=file_obj.file_size_bytes,
                checksum=fixity.digest,
                checksum_algorithm=fixity.algorithm,
                checksum_provenance='s3' if fixity.digest else None,
                access_url=file_obj.s3_url,
            )
        )

    title = getattr(resource, 'value', None) or getattr(resource, 'name', None) or resource.uri

    return ProjectRecord(
        subject_id=str(resource.id),
        uri=resource.uri,
        title=title,
        digital_objects=digital_objects,
        institution_codes=[resource.organization.code] if resource.organization else [],
    )
def _resolve_record_builder():
    builder_path = getattr(settings, "OAI_SNAPSHOT_RECORD_BUILDER", "").strip()
    if builder_path:
        return import_string(builder_path)
    return _fallback_record_from_storage
def _build_snapshot_service():
    provider_path = getattr(settings, "OAI_SNAPSHOT_SERVICE_CLASS", "").strip()
    record_builder = _resolve_record_builder()
    harvestable_statuses = set(HARVESTABLE_FILE_STATUSES)
    if provider_path:
        provider_cls = import_string(provider_path)
        if hasattr(provider_cls, "from_view_settings"):
            return provider_cls.from_view_settings(
                record_builder=record_builder,
                harvestable_statuses=harvestable_statuses,
            )
        try:
            return provider_cls(
                record_builder=record_builder,
                harvestable_statuses=harvestable_statuses,
            )
        except TypeError:
            return provider_cls()
    return ProjectSnapshotService()
def _get_snapshot_record(resource: Resource) -> Optional[ProjectRecord]:
    """Lookup project record for the resource via cached snapshot."""

    project_uri = getattr(resource, 'uri', None)
    if not project_uri:
        return None

    assembled_record = _assemble_record_from_db(resource)
    if assembled_record:
        return assembled_record
    if _db_mode_enabled():
        return None

    record = snapshot_service.get_record_by_uri(project_uri)
    if record:
        return record

    try:
        snapshot_service.refresh_cross_institutional_snapshot()
    except Exception:
        logger.exception("Failed to refresh project snapshot while building OAI metadata for %s", project_uri)
        return None

    return snapshot_service.get_record_by_uri(project_uri)
def _candidate_projects_for_resource(
    resource: Resource,
    primary_project: Optional[OAIProject] = None,
) -> List[OAIProject]:
    """Return snapshot and fallback OAI projects in priority order."""

    candidates: List[OAIProject] = []
    seen: set[str] = set()

    if primary_project is not None:
        candidates.append(primary_project)
        seen.add(primary_project.uri)
    else:
        record = _get_snapshot_record(resource)
        if record:
            builder = get_project_builder()
            project = builder.from_project_record(
                record,
                skip_shared_event_filter=_db_mode_enabled(),
                skip_format_exclusion=_db_mode_enabled(),
                use_curated_media_links=_curated_media_links_active(),
            )
            candidates.append(project)
            seen.add(project.uri)

    if not _db_mode_enabled():
        fallback_record = _fallback_record_from_storage(resource)
        if fallback_record:
            builder = get_project_builder()
            fallback_project = builder.from_project_record(
                fallback_record,
                skip_shared_event_filter=_db_mode_enabled(),
                skip_format_exclusion=_db_mode_enabled(),
                use_curated_media_links=_curated_media_links_active(),
            )
            if fallback_project.uri not in seen:
                candidates.append(fallback_project)

    return candidates


snapshot_service = _build_snapshot_service()
