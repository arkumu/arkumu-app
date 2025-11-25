from __future__ import annotations

import logging
import re
import uuid
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from django.db import transaction
from django.utils import timezone

from arkumu.catalog.models import ProjectIndex, ProjectRecordIndex
from arkumu.catalog.services.project_detail_index_service import ProjectDetailIndexService
from arkumu.common.hash_utils import generate_value_hash
from arkumu.metadata.models import PublicAccessLevel, Resource
from arkumu.projects import ProjectDigitalObject, ProjectRecord
from arkumu.projects.services import ProjectSnapshotService

logger = logging.getLogger(__name__)


def _as_uuid(value: Optional[str]) -> Optional[uuid.UUID]:
    if not value:
        return None
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError):
        return None


def _display_path(obj: ProjectDigitalObject) -> Optional[str]:
    if obj.access_url:
        return obj.access_url
    if obj.path:
        return obj.path
    if obj.storage_key:
        return obj.storage_key
    return None


def _coerce_year(raw: Optional[str]) -> Optional[int]:
    if not raw:
        return None
    token = str(raw).strip()
    if not token:
        return None
    # Trim ISO date parts if present
    if "-" in token:
        token = token.split("-")[0]
    match = re.search(r"\d{4}", token)
    if not match:
        return None
    try:
        return int(match.group(0))
    except ValueError:
        return None


class ProjectIndexDbService:
    """Materialize ProjectRecord data into derived DB-backed index tables."""

    def __init__(self, *, now=None) -> None:
        self.snapshot_service = ProjectSnapshotService()
        self.detail_service = ProjectDetailIndexService()
        self.now = now or timezone.now()

    # ------------------------------------------------------------------ #
    # Public API                                                         #
    # ------------------------------------------------------------------ #

    def rebuild(
        self,
        *,
        project_uris: Optional[Sequence[str]] = None,
        force_snapshot: bool = False,
    ) -> Dict[str, int]:
        """Rebuild index tables from ProjectRecord instances."""

        if project_uris:
            records = self._records_for_uris(project_uris)
        else:
            snapshot = self.snapshot_service.get_cross_institutional_snapshot(
                force_refresh=force_snapshot,
                include_non_public=True,
            )
            records = list(snapshot.projects)

        resources = self._resource_map(records)
        source_version = self._source_version(resources.values(), records)
        prune_missing = not bool(project_uris)

        return self._write_indexes(
            records,
            resources,
            source_version,
            prune_missing=prune_missing,
        )

    # ------------------------------------------------------------------ #
    # Internals                                                          #
    # ------------------------------------------------------------------ #

    def _records_for_uris(self, uris: Sequence[str]) -> List[ProjectRecord]:
        seen: set[str] = set()
        records: List[ProjectRecord] = []

        for uri in uris:
            normalized = (uri or "").strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            record = self.detail_service.get_record(normalized)
            if record:
                records.append(record)
            else:
                logger.warning("ProjectIndexDbService: record not found for uri=%s", normalized)
        return records

    def _resource_map(self, records: Sequence[ProjectRecord]) -> Dict[uuid.UUID, Resource]:
        ids: List[uuid.UUID] = []
        for record in records:
            subject_uuid = _as_uuid(getattr(record, "subject_id", None))
            if subject_uuid:
                ids.append(subject_uuid)

        if not ids:
            return {}

        return Resource.objects.in_bulk(ids)

    def _source_version(
        self,
        resources: Iterable[Resource],
        records: Sequence[ProjectRecord],
    ) -> str:
        tokens: List[str] = [str(len(records))]
        for resource in resources:
            updated = getattr(resource, "updated_at", None)
            token = f"{resource.id}"
            if updated:
                token = f"{token}:{updated.isoformat()}"
            tokens.append(token)

        if not tokens:
            return ""

        return generate_value_hash("|".join(sorted(tokens)))

    def _write_indexes(
        self,
        records: Sequence[ProjectRecord],
        resource_map: Dict[uuid.UUID, Resource],
        source_version: str,
        *,
        prune_missing: bool,
    ) -> Dict[str, int]:
        built_at = self.now
        seen_ids: set[uuid.UUID] = set()
        index_rows: List[ProjectIndex] = []
        record_rows: List[ProjectRecordIndex] = []

        for record in records:
            subject_uuid = _as_uuid(getattr(record, "subject_id", None))
            if not subject_uuid:
                logger.warning("ProjectIndexDbService: missing subject_id for uri=%s", record.uri)
                continue
            resource = resource_map.get(subject_uuid)
            if not resource:
                logger.warning(
                    "ProjectIndexDbService: resource not found for subject_id=%s (uri=%s)",
                    subject_uuid,
                    record.uri,
                )
                continue

            defaults_index = self._index_defaults(record, resource, built_at, source_version)
            defaults_record = self._record_defaults(record, resource, built_at, source_version)

            index_rows.append(ProjectIndex(project_resource=resource, **defaults_index))
            record_rows.append(ProjectRecordIndex(project_resource=resource, **defaults_record))
            seen_ids.add(resource.id)

        with transaction.atomic():
            if not index_rows and not record_rows:
                if prune_missing:
                    ProjectIndex.objects.all().delete()
                    ProjectRecordIndex.objects.all().delete()
                return {"projects_index": 0, "project_records": 0}

            if index_rows:
                ProjectIndex.objects.bulk_create(
                    index_rows,
                    update_conflicts=True,
                    unique_fields=["project_resource"],
                    update_fields=[
                        "uri",
                        "org_code",
                        "public_access_level",
                        "is_public_approved",
                        "is_derived",
                        "title",
                        "subtitle",
                        "image",
                        "institution_label",
                        "categories",
                        "actor_names",
                        "digital_object_paths",
                        "year_range",
                        "source_updated_at",
                        "built_at",
                        "source_version",
                    ],
                )

            if record_rows:
                ProjectRecordIndex.objects.bulk_create(
                    record_rows,
                    update_conflicts=True,
                    unique_fields=["project_resource"],
                    update_fields=[
                        "uri",
                        "org_code",
                        "public_access_level",
                        "is_public_approved",
                        "is_derived",
                        "title",
                        "subtitle",
                        "description",
                        "institution_label",
                        "institution_codes",
                        "category_labels",
                        "category_slugs",
                        "actor_names",
                        "year_values",
                        "project_type_label",
                        "catchphrase_labels",
                        "image",
                        "digital_object_paths",
                        "reference_only",
                        "harvestable",
                        "ownership_filtered",
                        "record_jsonb",
                        "source_updated_at",
                        "built_at",
                        "source_version",
                    ],
                )

            if prune_missing and seen_ids:
                ProjectIndex.objects.exclude(project_resource_id__in=seen_ids).delete()
                ProjectRecordIndex.objects.exclude(project_resource_id__in=seen_ids).delete()

        return {
            "projects_index": len(index_rows),
            "project_records": len(record_rows),
        }

    def _index_defaults(
        self,
        record: ProjectRecord,
        resource: Resource,
        built_at,
        source_version: str,
    ) -> Dict[str, object]:
        return {
            "uri": record.uri,
            "org_code": self._org_code(resource),
            "public_access_level": getattr(resource, "public_access_level", PublicAccessLevel.RESTRICTED),
            "is_public_approved": bool(getattr(resource, "is_public_approved", False)),
            "is_derived": bool(getattr(resource, "is_public", False)),
            "title": record.title or "",
            "subtitle": record.subtitle or "",
            "image": record.image or "",
            "institution_label": self._institution_label(record),
            "categories": self._category_tokens(record),
            "actor_names": self._actor_names(record),
            "digital_object_paths": self._digital_object_paths(record),
            "year_range": record.year_range or self._derive_year_range(record) or "",
            "source_updated_at": getattr(resource, "updated_at", None),
            "built_at": built_at,
            "source_version": source_version,
        }

    def _record_defaults(
        self,
        record: ProjectRecord,
        resource: Resource,
        built_at,
        source_version: str,
    ) -> Dict[str, object]:
        return {
            "uri": record.uri,
            "org_code": self._org_code(resource),
            "public_access_level": getattr(resource, "public_access_level", PublicAccessLevel.RESTRICTED),
            "is_public_approved": bool(getattr(resource, "is_public_approved", False)),
            "is_derived": bool(getattr(resource, "is_public", False)),
            "title": record.title or "",
            "subtitle": record.subtitle or "",
            "description": record.description or "",
            "institution_label": self._institution_label(record),
            "institution_codes": list(record.institution_codes or []),
            "category_labels": self._category_labels(record),
            "category_slugs": list(record.category_slugs or []),
            "actor_names": self._actor_names(record),
            "year_values": self._year_values(record),
            "project_type_label": getattr(getattr(record, "project_type", None), "label", "") or "",
            "catchphrase_labels": [cp.label for cp in (record.catchphrases or []) if getattr(cp, "label", None)],
            "image": record.image or "",
            "digital_object_paths": self._digital_object_paths(record),
            "reference_only": bool(getattr(record, "reference_only", False)),
            "harvestable": bool(getattr(record, "harvestable", True)),
            "ownership_filtered": bool(getattr(record, "ownership_filtered", False)),
            "record_jsonb": record.to_dict(),
            "source_updated_at": getattr(resource, "updated_at", None),
            "built_at": built_at,
            "source_version": source_version,
        }

    @staticmethod
    def _org_code(resource: Resource) -> str:
        organization = getattr(resource, "organization", None)
        code = getattr(organization, "code", "") if organization else ""
        return str(code or "").strip().lower()

    @staticmethod
    def _institution_label(record: ProjectRecord) -> str:
        institution = getattr(record, "institution", None)
        label = getattr(institution, "label", "") if institution else ""
        return str(label or "").strip()

    def _category_tokens(self, record: ProjectRecord) -> List[str]:
        tokens: List[str] = []
        for category in getattr(record, "categories", []) or []:
            label = getattr(category, "label", None)
            slug = getattr(category, "slug", None)
            token = label or slug
            if not token:
                continue
            normalized = str(token).strip()
            if normalized and normalized not in tokens:
                tokens.append(normalized)
        return tokens

    def _category_labels(self, record: ProjectRecord) -> List[str]:
        labels: List[str] = []
        for category in getattr(record, "categories", []) or []:
            label = getattr(category, "label", None)
            if not label:
                continue
            normalized = str(label).strip()
            if normalized and normalized not in labels:
                labels.append(normalized)
        return labels

    def _actor_names(self, record: ProjectRecord) -> List[str]:
        names: List[str] = []
        for actor in getattr(record, "actors", []) or []:
            name = getattr(actor, "name", None) if actor else None
            if not name:
                continue
            normalized = str(name).strip()
            if normalized and normalized not in names:
                names.append(normalized)
        return names

    def _digital_object_paths(self, record: ProjectRecord) -> List[str]:
        paths: List[str] = []
        for obj in getattr(record, "digital_objects", []) or []:
            path = _display_path(obj)
            if not path:
                continue
            normalized = str(path).strip()
            if normalized and normalized not in paths:
                paths.append(normalized)
        return paths

    def _year_values(self, record: ProjectRecord) -> List[int]:
        values: set[int] = set()
        for event in getattr(record, "events", []) or []:
            for candidate in (getattr(event, "start", None), getattr(event, "end", None)):
                year = _coerce_year(candidate)
                if year:
                    values.add(year)

        year_range = getattr(record, "year_range", None)
        if year_range:
            for match in re.findall(r"\d{4}", str(year_range)):
                try:
                    values.add(int(match))
                except ValueError:
                    continue

        return sorted(values)

    def _derive_year_range(self, record: ProjectRecord) -> Optional[str]:
        years = self._year_values(record)
        if not years:
            return None
        if len(years) == 1:
            return str(years[0])
        return f"{min(years)} bis {max(years)}"
