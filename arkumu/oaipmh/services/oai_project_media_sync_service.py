"""Sync curated OAI media links from the canonical project graph."""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Dict, Iterable, List, Optional, Sequence
from uuid import UUID

from django.db import IntegrityError, transaction

from arkumu.metadata.models.resource import PublicAccessLevel, Resource, ResourceType
from arkumu.metadata.models.triples import Triple
from arkumu.metadata.canonical import canonical_uri
from arkumu.oaipmh.models import OAIProjectMediaLink
from arkumu.projects import ProjectDigitalObject, ProjectRecord

from .oai_project_assembler import AssemblyContext, OAIProjectAssembler


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MediaLinkCandidate:
    """Normalized payload describing a project-to-digital-object relation."""

    resource: Resource
    source: str
    uri: Optional[str]
    path: Optional[str]


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
        self._digital_predicate_uri = canonical_uri("digital_object")
        self._direct_only_orgs = {"khm", "hmt"}

    # ------------------------------------------------------------------
    def sync_project(
        self,
        project: Resource,
        *,
        record: Optional[ProjectRecord] = None,
    ) -> SyncResult:
        """Discover and upsert curated links for a single project resource."""

        if not isinstance(project, Resource):
            raise TypeError("sync_project expects a Resource instance")

        org_code = (getattr(getattr(project, "organization", None), "code", None) or "").strip().lower()

        if org_code in self._direct_only_orgs:
            candidates = self._candidates_from_shared_subject_triples(project)
            if not candidates:
                return SyncResult(skipped=1)
            return self._upsert_links(project, candidates)

        if record is None:
            record = self._assemble_record(project)
        if record is None:
            return SyncResult(skipped=1)

        candidates = self._candidates_from_record(record, project)
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

    def _candidates_from_record(
        self,
        record: ProjectRecord,
        project: Resource,
    ) -> List[MediaLinkCandidate]:
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
                resource = self._ensure_digital_object_resource(project, obj)
            if resource is None:
                continue

            if not getattr(obj, "resource_id", None):
                obj.resource_id = str(resource.id)
            if not getattr(obj, "uri", None):
                obj.uri = resource.uri

            source = self._normalize_source(getattr(obj, "source", None))
            candidates.append(
                MediaLinkCandidate(
                    resource=resource,
                    source=source,
                    uri=getattr(obj, "uri", None),
                    path=getattr(obj, "path", None),
                )
            )

        return candidates

    def _candidates_from_shared_subject_triples(
        self,
        project: Resource,
    ) -> List[MediaLinkCandidate]:
        """Return candidates from shared-subject project/digital edges (KHM)."""

        org = getattr(project, "organization", None)
        if not org:
            return []

        # Find bridge rows that point to this project via project predicate, then grab their digital edges.
        bridge_subject_ids = set(
            Triple.objects.filter(
                predicate__canonical_uri=canonical_uri("project"),
                object=project,
            ).values_list("subject_id", flat=True)
        )
        if not bridge_subject_ids:
            return []

        qs = Triple.objects.filter(
            subject_id__in=bridge_subject_ids,
            predicate__canonical_uri=self._digital_predicate_uri,
            object__resource_type=ResourceType.ENTITY,
        ).select_related("object")

        results: List[MediaLinkCandidate] = []
        for triple in qs:
            digital = getattr(triple, "object", None)
            subject = getattr(triple, "subject", None)
            if not digital or not subject:
                continue
            # Shared-subject rows carry project_id in their own edges.
            project_id = str(subject.id)
            if project_id != str(project.id):
                continue
            results.append(
                MediaLinkCandidate(
                    resource=digital,
                    source=OAIProjectMediaLink.SOURCE_PROJECT,
                    uri=getattr(digital, "uri", None),
                    path=getattr(digital, "value", None),
                )
            )

        return results

    # ------------------------------------------------------------------
    def _ensure_digital_object_resource(
        self,
        project: Resource,
        obj: ProjectDigitalObject,
    ) -> Optional[Resource]:
        """Promote literal-only digital objects into lightweight Resource rows."""

        path = (getattr(obj, "path", None) or getattr(obj, "access_url", None) or "").strip()
        if not path:
            return None

        organization = getattr(project, "organization", None)
        org_code = (getattr(organization, "code", None) or "").strip().lower()
        if not organization or not org_code:
            return None

        uri = self._digital_object_uri(org_code, path)
        existing = Resource.objects.filter(uri=uri).first()
        if existing:
            return existing

        name = (getattr(obj, "file_name", None) or self._infer_file_name(path) or uri.rsplit("/", 1)[-1])[:255]
        defaults = {
            "organization": organization,
            "resource_type": ResourceType.ENTITY,
            "name": name,
            "value": path,
            "canonical_uri": uri,
            "public_access_level": getattr(project, "public_access_level", PublicAccessLevel.RESTRICTED),
            "is_public_approved": getattr(project, "is_public_approved", False),
        }

        try:
            resource = Resource.objects.create(uri=uri, **defaults)
        except IntegrityError:
            resource = Resource.objects.filter(uri=uri).first()

        if resource:
            logger.debug("Promoted literal path to digital object resource uri=%s project=%s", uri, project.uri)
        return resource

    @staticmethod
    def _digital_object_uri(org_code: str, path: str) -> str:
        digest = hashlib.sha256(path.encode("utf-8")).hexdigest()
        return f"http://arkumu.org/data/{org_code}/entities/digitales-objekt/{digest}"

    @staticmethod
    def _infer_file_name(path: str) -> str:
        try:
            name = PurePosixPath(path).name
            return name or path
        except Exception:
            return path

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
        existing_by_uri: Dict[str, OAIProjectMediaLink] = {}
        existing_by_value: Dict[str, OAIProjectMediaLink] = {}
        for link in existing_links.values():
            digital = getattr(link, "digital_object", None)
            if not digital:
                continue
            uri = getattr(digital, "uri", None)
            if uri and uri not in existing_by_uri:
                existing_by_uri[uri] = link
            value = getattr(digital, "value", None)
            if value:
                normalized_value = value.strip()
                if normalized_value and normalized_value not in existing_by_value:
                    existing_by_value[normalized_value] = link

        next_order = 1
        if existing_links:
            next_order = max((link.order_index or 0) for link in existing_links.values()) + 1

        seen: set[UUID] = set()
        seen_uris: set[str] = set()
        seen_paths: set[str] = set()
        created = 0
        refreshed = 0

        for candidate in candidates:
            digital_pk = candidate.resource.id
            candidate_uri = (candidate.uri or getattr(candidate.resource, "uri", None) or "").strip()
            candidate_path = (candidate.path or getattr(candidate.resource, "value", None) or "").strip()
            if candidate_uri:
                seen_uris.add(candidate_uri)
            if candidate_path:
                seen_paths.add(candidate_path)

            link = existing_links.get(digital_pk)
            if link is None and candidate_uri:
                link = existing_by_uri.get(candidate_uri)
            if link is None and candidate_path:
                link = existing_by_value.get(candidate_path)

            if link is None:
                seen.add(digital_pk)
            else:
                seen.add(link.digital_object_id)
            if link is None:
                OAIProjectMediaLink.objects.create(
                    project=project,
                    digital_object=candidate.resource,
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

        stale = self._mark_missing_as_stale(project, existing_links, seen, seen_uris, seen_paths)
        return SyncResult(created=created, refreshed=refreshed, stale=stale)

    def _mark_missing_as_stale(
        self,
        project: Resource,
        existing: Dict[UUID, OAIProjectMediaLink],
        seen: Iterable[UUID],
        seen_uris: Iterable[str],
        seen_paths: Iterable[str],
    ) -> int:
        seen_ids = {pk for pk in seen}
        seen_uri_set = {uri.strip() for uri in seen_uris if uri and uri.strip()}
        seen_path_set = {path.strip() for path in seen_paths if path and path.strip()}
        stale_links = []
        for pk, link in existing.items():
            if pk in seen_ids or link.is_stale:
                continue
            digital = getattr(link, "digital_object", None)
            link_uri = getattr(digital, "uri", None) if digital else None
            link_value = getattr(digital, "value", None) if digital else None
            if link_uri and link_uri in seen_uri_set:
                continue
            if link_value and link_value.strip() in seen_path_set:
                continue
            stale_links.append(link)
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
            .filter(
                project=project,
                is_stale=False,
            )
        )
        count = 0
        for link in links:
            link.is_stale = True
            link.save(update_fields=["is_stale", "updated_at"])
            count += 1
        return SyncResult(stale=count, skipped=1 if count == 0 else 0)
