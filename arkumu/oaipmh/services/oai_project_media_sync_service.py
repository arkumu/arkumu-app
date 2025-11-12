"""Sync curated OAI media links from the canonical project graph."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence
from uuid import UUID

from django.db import transaction

from arkumu.metadata.models.resource import Resource, ResourceType
from arkumu.oaipmh.models import OAIProjectMediaLink
from arkumu.projects import ProjectRecord

from .oai_project_assembler import AssemblyContext, OAIProjectAssembler


@dataclass(frozen=True)
class MediaLinkCandidate:
    """Normalized payload describing a project-to-digital-object relation."""

    resource: Resource
    source: str


@dataclass
class SyncResult:
    """Return metadata for sync invocations."""

    created: int = 0
    refreshed: int = 0
    stale: int = 0
    skipped: int = 0


class OAIProjectMediaSyncService:
    """Populate ``OAIProjectMediaLink`` rows using the DB-backed assembler.

    The seed version intentionally reuses :class:`OAIProjectAssembler` so the
    curated table mirrors the selection logic currently powering ``/oai/db/``.
    Once curators approve or reject links, the tailored endpoint can trust this
    table instead of walking triples on every request.
    """

    def __init__(self, *, assembler: Optional[OAIProjectAssembler] = None) -> None:
        self._assembler = assembler or OAIProjectAssembler()

    # ------------------------------------------------------------------
    def sync_project(self, project: Resource) -> SyncResult:
        """Discover and upsert curated links for a single project resource."""

        if not isinstance(project, Resource):
            raise TypeError("sync_project expects a Resource instance")

        record = self._assemble_record(project)
        if record is None:
            return SyncResult(skipped=1)

        candidates = self._candidates_from_record(record)
        if not candidates:
            return self._mark_project_stale(project)

        return self._upsert_links(project, candidates)

    # ------------------------------------------------------------------
    def _assemble_record(self, project: Resource) -> Optional[ProjectRecord]:
        context = AssemblyContext(resource=project)
        try:
            return self._assembler.build_record(context)
        except Exception:  # pragma: no cover - defensive logging in assembler
            return None

    def _candidates_from_record(self, record: ProjectRecord) -> List[MediaLinkCandidate]:
        digital_objects = getattr(record, "digital_objects", None) or []
        if not digital_objects:
            return []

        ids = [obj.resource_id for obj in digital_objects if getattr(obj, "resource_id", None)]
        uris = [obj.uri for obj in digital_objects if getattr(obj, "uri", None)]

        resources_by_id = self._resources_by_id(ids)
        resources_by_uri = self._resources_by_uri(uris)

        candidates: List[MediaLinkCandidate] = []
        for obj in digital_objects:
            resource = None
            resource_id = getattr(obj, "resource_id", None)
            if resource_id:
                resource = resources_by_id.get(str(resource_id))
            if resource is None and obj.uri:
                resource = resources_by_uri.get(obj.uri)
            if resource is None:
                continue

            source = self._normalize_source(getattr(obj, "source", None))
            candidates.append(MediaLinkCandidate(resource=resource, source=source))

        return candidates

    def _resources_by_id(self, identifiers: Sequence[str]) -> Dict[str, Resource]:
        if not identifiers:
            return {}

        normalized: List[UUID] = []
        for value in identifiers:
            try:
                normalized.append(UUID(str(value)))
            except (TypeError, ValueError):
                continue

        if not normalized:
            return {}

        queryset = Resource.objects.filter(
            id__in=normalized,
            resource_type=ResourceType.ENTITY,
        )
        return {str(pk): resource for pk, resource in queryset.in_bulk(normalized).items()}

    def _resources_by_uri(self, uris: Sequence[str]) -> Dict[str, Resource]:
        if not uris:
            return {}
        queryset = Resource.objects.filter(
            uri__in=list({uri for uri in uris if uri}),
            resource_type=ResourceType.ENTITY,
        )
        return {resource.uri: resource for resource in queryset}

    def _normalize_source(self, source: Optional[str]) -> str:
        normalized = (source or "").strip().lower()
        if normalized in {
            OAIProjectMediaLink.SOURCE_PROJECT,
            OAIProjectMediaLink.SOURCE_EVENT,
            OAIProjectMediaLink.SOURCE_MANUAL,
            OAIProjectMediaLink.SOURCE_UNKNOWN,
        }:
            return normalized
        if normalized.startswith("project"):
            return OAIProjectMediaLink.SOURCE_PROJECT
        if normalized.startswith("event"):
            return OAIProjectMediaLink.SOURCE_EVENT
        return OAIProjectMediaLink.SOURCE_UNKNOWN

    # ------------------------------------------------------------------
    @transaction.atomic
    def _upsert_links(
        self,
        project: Resource,
        candidates: Sequence[MediaLinkCandidate],
    ) -> SyncResult:
        existing_links = {
            link.digital_object_id: link
            for link in (
                OAIProjectMediaLink.objects.select_for_update()
                .filter(project=project)
            )
        }

        next_order = 1
        if existing_links:
            next_order = max((link.order_index or 0) for link in existing_links.values()) + 1

        seen: set[UUID] = set()
        created = 0
        refreshed = 0

        for candidate in candidates:
            digital_pk = candidate.resource.id
            seen.add(digital_pk)
            link = existing_links.get(digital_pk)
            if link is None:
                OAIProjectMediaLink.objects.create(
                    project=project,
                    digital_object=candidate.resource,
                    status=OAIProjectMediaLink.STATUS_PENDING,
                    source=candidate.source,
                    order_index=next_order,
                )
                created += 1
                next_order += 1
                continue

            updates: List[str] = []
            if link.source != candidate.source:
                link.source = candidate.source
                updates.append("source")
            if link.is_stale:
                link.is_stale = False
                updates.append("is_stale")

            if updates:
                link.save(update_fields=[*updates, "updated_at"])
                refreshed += 1

        stale = self._mark_missing_as_stale(project, existing_links, seen)
        return SyncResult(created=created, refreshed=refreshed, stale=stale)

    def _mark_missing_as_stale(
        self,
        project: Resource,
        existing: Dict[UUID, OAIProjectMediaLink],
        seen: Iterable[UUID],
    ) -> int:
        seen_ids = {pk for pk in seen}
        stale_links = [
            link
            for pk, link in existing.items()
            if pk not in seen_ids
            and not link.is_stale
            and link.status == OAIProjectMediaLink.STATUS_APPROVED
        ]
        if not stale_links:
            return 0

        updated = 0
        for link in stale_links:
            link.is_stale = True
            link.save(update_fields=["is_stale", "updated_at"])
            updated += 1
        return updated

    @transaction.atomic
    def _mark_project_stale(self, project: Resource) -> SyncResult:
        links = (
            OAIProjectMediaLink.objects.select_for_update()
            .filter(project=project, status=OAIProjectMediaLink.STATUS_APPROVED, is_stale=False)
        )
        count = 0
        for link in links:
            link.is_stale = True
            link.save(update_fields=["is_stale", "updated_at"])
            count += 1
        return SyncResult(stale=count, skipped=1 if count == 0 else 0)
