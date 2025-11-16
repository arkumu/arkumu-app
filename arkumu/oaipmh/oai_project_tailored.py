"""Tailored variant of the OAIProjectBuilder that bypasses shared-event filtering."""

from __future__ import annotations

from dataclasses import replace
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple
from uuid import UUID

from django.db.models import Count, Q

from arkumu.catalog.services.project_views import ProjectURIs
from arkumu.metadata.models import Resource
from arkumu.metadata.models.triples import Triple
from arkumu.storage.models.s3_file_objects import S3FileObject
from arkumu.projects.services.snapshot_service import ProjectSnapshotService

from .oai_project import (
    CuratedLinkWarning,
    CuratedMediaSelection,
    NormalizedDigitalObject,
    OAIProject,
    OAIProjectBuilder,
    ProjectDigitalObject,
    ProjectRecord,
    _clean,
    _guess_mime_type,
    _infer_file_name,
    HARVESTABLE_STORAGE_STATUSES,
    parse_fixity,
)
from arkumu.oaipmh.models import OAIProjectMediaLink

_DIGITAL_OBJECT_FALLBACK_PREDICATES: Mapping[str, Sequence[str]] = getattr(
    ProjectSnapshotService,
    "DIGITAL_OBJECT_FALLBACK_PREDICATES",
    {},
)


class OAIProjectBuilderTailored(OAIProjectBuilder):
    """Customized builder used exclusively for the tailored OAI profile."""

    def from_project_record(
        self,
        record: ProjectRecord,
        *,
        skip_shared_event_filter: bool = False,
        skip_format_exclusion: bool = False,
        use_curated_media_links: bool = False,
    ) -> OAIProject:
        institution_code = self._resolve_institution_code(record)
        original_digital_objects = list(getattr(record, "digital_objects", []) or [])

        filtered_record = record
        # Tailored feeds intentionally keep shared-event objects, so skip the shared-event filter.
        filtered_record = self._filter_flagged_digital_objects(filtered_record)
        filtered_record = self._filter_overarching_projects(filtered_record, institution_code)

        curated_selection: Optional[CuratedMediaSelection] = None
        if use_curated_media_links:
            curated_selection = self._resolve_curated_selection(filtered_record)

        normalized_objects = self._normalize_objects(
            filtered_record,
            institution_code,
            skip_format_exclusion=skip_format_exclusion,
            curated_selection=curated_selection,
            extra_objects=original_digital_objects,
        )

        return OAIProject(
            record=filtered_record,
            institution_code=institution_code,
            digital_objects=tuple(normalized_objects),
            curated_selection=curated_selection,
        )

    def _resolve_curated_selection(
        self,
        record: ProjectRecord,
    ) -> Optional[CuratedMediaSelection]:
        return self._resolve_curated_selection_with_all_statuses(record)

    def _normalize_objects(
        self,
        record: ProjectRecord,
        institution_code: Optional[str],
        *,
        skip_format_exclusion: bool = False,
        curated_selection: Optional[CuratedMediaSelection] = None,
        extra_objects: Optional[Sequence[ProjectDigitalObject]] = None,
    ) -> List[NormalizedDigitalObject]:
        objects: List[NormalizedDigitalObject] = []
        seen: set[str] = set()
        label_by_id: Dict[str, str] = {}
        label_by_uri: Dict[str, str] = {}
        allowed_resource_ids: Optional[set[str]] = None
        allowed_uris: Optional[set[str]] = None
        capture_groups = curated_selection is not None
        grouped_by_resource: Dict[str, List[NormalizedDigitalObject]] = {}
        grouped_by_uri: Dict[str, List[NormalizedDigitalObject]] = {}

        if curated_selection:
            allowed_resource_ids = {rid for rid in curated_selection.ordered_resource_ids if rid}
            allowed_uris = {uri for uri in curated_selection.ordered_object_uris if uri}
            label_by_id = dict(curated_selection.label_overrides_by_id)
            label_by_uri = dict(curated_selection.label_overrides_by_uri)

        extra_by_resource: Dict[str, List[ProjectDigitalObject]] = {}
        if extra_objects:
            for obj in extra_objects:
                rid = getattr(obj, "resource_id", None)
                if rid:
                    extra_by_resource.setdefault(str(rid), []).append(obj)

        for obj in getattr(record, "digital_objects", []) or []:
            if not skip_format_exclusion and self._should_skip_digital_object(obj, institution_code):
                continue
            expanded_objects = self._expand_dcp_folder_if_needed(obj, institution_code)
            objects_to_process = expanded_objects if expanded_objects else [obj]

            for current_obj in objects_to_process:
                resource_identifier = getattr(current_obj, "resource_id", None)
                normalized_resource_id = str(resource_identifier) if resource_identifier else None
                obj_uri = _clean(getattr(current_obj, "uri", None))
                if allowed_resource_ids is not None:
                    include = False
                    if normalized_resource_id and normalized_resource_id in allowed_resource_ids:
                        include = True
                    elif obj_uri and allowed_uris and obj_uri in allowed_uris:
                        include = True
                    if not include:
                        continue

                normalized = self._normalize_object(current_obj, institution_code)
                if not normalized or not self._is_harvestable(normalized):
                    continue

                identity = normalized.preferred_location
                if identity:
                    identity_key = identity.lower()
                    if identity_key in seen:
                        continue
                    seen.add(identity_key)

                if curated_selection:
                    label_override = None
                    if normalized.resource_id and normalized.resource_id in label_by_id:
                        label_override = label_by_id[normalized.resource_id]
                    elif normalized.uri and normalized.uri in label_by_uri:
                        label_override = label_by_uri[normalized.uri]
                    if label_override:
                        normalized = replace(normalized, label_override=label_override)

                objects.append(normalized)

                if capture_groups:
                    if normalized.resource_id:
                        grouped_by_resource.setdefault(normalized.resource_id, []).append(normalized)
                    if normalized.uri:
                        grouped_by_uri.setdefault(normalized.uri, []).append(normalized)

        if not curated_selection:
            return objects

        missing_resource_ids = [
            rid for rid in curated_selection.ordered_resource_ids if rid and rid not in grouped_by_resource
        ]
        if missing_resource_ids:
            uri_by_resource = {
                pair[0]: pair[1]
                for pair in curated_selection.resource_uri_pairs
                if pair[0]
            }
            curated_objects = self._load_curated_project_objects(
                missing_resource_ids,
                uri_by_resource,
                institution_code,
            )
            for rid in missing_resource_ids:
                project_objects = list(extra_by_resource.get(rid, []))
                if not project_objects and rid in curated_objects:
                    project_objects.extend(curated_objects.get(rid, []))
                if not project_objects:
                    continue

                normalized_items: List[NormalizedDigitalObject] = []
                for project_obj in project_objects:
                    normalized = self._normalize_object(project_obj, institution_code)
                    if not normalized or not self._is_harvestable(normalized):
                        continue
                    identity = normalized.preferred_location
                    if identity:
                        identity_key = identity.lower()
                        if identity_key in seen:
                            continue
                        seen.add(identity_key)

                    label_override = None
                    if normalized.resource_id and normalized.resource_id in label_by_id:
                        label_override = label_by_id[normalized.resource_id]
                    elif normalized.uri and normalized.uri in label_by_uri:
                        label_override = label_by_uri[normalized.uri]
                    if label_override:
                        normalized = replace(normalized, label_override=label_override)

                    normalized_items.append(normalized)

                if not normalized_items:
                    continue
                grouped_by_resource.setdefault(rid, []).extend(normalized_items)
                for normalized in normalized_items:
                    if normalized.uri:
                        grouped_by_uri.setdefault(normalized.uri, []).append(normalized)

        ordered_objects: List[NormalizedDigitalObject] = []
        consumed_ids: set[int] = set()

        def _extend_with_candidates(candidates: Iterable[NormalizedDigitalObject]) -> None:
            for candidate in candidates:
                candidate_id = id(candidate)
                if candidate_id in consumed_ids:
                    continue
                ordered_objects.append(candidate)
                consumed_ids.add(candidate_id)

        for resource_id in curated_selection.ordered_resource_ids:
            matches = grouped_by_resource.get(resource_id, [])
            _extend_with_candidates(matches)

        for uri in curated_selection.ordered_object_uris:
            matches = grouped_by_uri.get(uri, [])
            _extend_with_candidates(matches)

        return ordered_objects

    def _load_curated_project_objects(
        self,
        resource_ids: Sequence[str],
        uri_by_resource: Mapping[str, Optional[str]],
        institution_code: Optional[str],
    ) -> Dict[str, List[ProjectDigitalObject]]:
        """Load curated media by consulting storage for S3 orgs and the canonical graph otherwise."""

        curated_objects: Dict[str, List[ProjectDigitalObject]] = {}
        s3_objects = self._load_curated_objects_from_s3(
            resource_ids,
            uri_by_resource,
            institution_code,
        )
        curated_objects.update(s3_objects)

        for rid in resource_ids:
            if rid in curated_objects:
                continue
            graph_obj = self._graph_digital_object(
                rid,
                uri_by_resource.get(rid),
                institution_code,
            )
            if graph_obj:
                curated_objects[rid] = [graph_obj]

        return curated_objects

    def _load_curated_objects_from_s3(
        self,
        resource_ids: Sequence[str],
        uri_by_resource: Mapping[str, Optional[str]],
        institution_code: Optional[str],
    ) -> Dict[str, List[ProjectDigitalObject]]:
        normalized_code = (institution_code or "").lower().strip()
        if normalized_code not in self._s3_orgs:
            return {}

        uuid_map: Dict[UUID, str] = {}
        for rid in resource_ids:
            try:
                uuid_map[UUID(str(rid))] = str(rid)
            except (TypeError, ValueError):
                continue

        if not uuid_map:
            return {}

        files = (
            S3FileObject.objects.filter(
                related_resource_id__in=list(uuid_map.keys()),
                status__in=HARVESTABLE_STORAGE_STATUSES,
                s3_key__isnull=False,
            )
            .exclude(s3_key="")
            .select_related("related_resource")
        )

        curated_objects: Dict[str, List[ProjectDigitalObject]] = {}
        for file_obj in files:
            rid_uuid = getattr(file_obj, "related_resource_id", None)
            if rid_uuid not in uuid_map:
                continue
            rid_str = uuid_map[rid_uuid]
            fixity = parse_fixity(getattr(file_obj, "sha256_checksum", None))
            resource_uri = uri_by_resource.get(rid_str)
            if not resource_uri and getattr(file_obj, "related_resource", None):
                resource_uri = getattr(file_obj.related_resource, "uri", None)

            project_obj = ProjectDigitalObject(
                path=file_obj.s3_key,
                storage_key=file_obj.s3_key,
                file_name=file_obj.file_name,
                content_type=file_obj.content_type,
                size_bytes=file_obj.file_size_bytes,
                checksum=fixity.digest,
                checksum_algorithm=fixity.algorithm,
                checksum_provenance='s3' if fixity.digest else None,
                access_url=file_obj.s3_url,
                storage_status=file_obj.status,
                resource_id=rid_str,
                uri=resource_uri,
            )
            curated_objects.setdefault(rid_str, []).append(project_obj)

        return curated_objects

    def _graph_digital_object(
        self,
        resource_id: str,
        uri_hint: Optional[str],
        institution_code: Optional[str],
    ) -> Optional[ProjectDigitalObject]:
        try:
            resource = Resource.objects.select_related("organization").get(pk=resource_id)
        except Resource.DoesNotExist:
            return None

        predicate_candidates: List[str] = [ProjectURIs.DIGITAL_OBJECT_PATH]
        organization = getattr(resource, "organization", None)
        org_code = (getattr(organization, "code", "") or "").lower().strip()
        for candidate in _DIGITAL_OBJECT_FALLBACK_PREDICATES.get(org_code, ()):
            if candidate and candidate not in predicate_candidates:
                predicate_candidates.append(candidate)

        path_literal = self._literal_from_subject(resource.id, predicate_candidates)
        if not path_literal:
            return None

        project_obj = ProjectDigitalObject(
            path=path_literal,
            storage_key=path_literal,
            file_name=None,
            content_type=None,
            storage_status="completed",
            resource_id=str(resource.id),
            uri=resource.uri or uri_hint,
        )
        file_name = _infer_file_name(project_obj)
        if file_name:
            project_obj.file_name = file_name
        project_obj.content_type = _guess_mime_type(project_obj)
        project_obj.source = "graph"

        checksum_code = institution_code
        organization = getattr(resource, "organization", None)
        if organization and getattr(organization, "code", None):
            checksum_code = organization.code
        checksum_predicate = None
        if checksum_code:
            checksum_predicate = ProjectSnapshotService.ROSETTA_CHECKSUM_PREDICATES.get(
                str(checksum_code).lower().strip()
            )
        if checksum_predicate:
            checksum_literal = self._literal_from_subject(resource.id, [checksum_predicate])
            if checksum_literal:
                fixity = parse_fixity(checksum_literal)
                if fixity.digest:
                    project_obj.checksum = fixity.digest
                    project_obj.checksum_algorithm = fixity.algorithm or "sha256"
                    project_obj.checksum_provenance = fixity.provenance or "metadata"

        event_filter = Q(predicate__canonical_uri=ProjectURIs.DIGITAL_OBJECT_LINK) | Q(
            predicate__uri=ProjectURIs.DIGITAL_OBJECT_LINK
        )
        event_links = (
            Triple.objects.filter(object_id=resource.id)
            .filter(event_filter)
            .select_related("subject")
        )
        event_ids: List[str] = []
        event_uris: List[str] = []
        for link in event_links:
            event_ids.append(str(link.subject_id))
            subject = getattr(link, "subject", None)
            if subject and getattr(subject, "uri", None):
                event_uris.append(subject.uri)
        if event_ids:
            project_obj.source_event_ids = event_ids
        if event_uris:
            project_obj.source_event_uris = event_uris

        return project_obj

    def _literal_from_subject(
        self,
        subject_id: UUID,
        predicate_uris: Sequence[str],
    ) -> Optional[str]:
        if not predicate_uris:
            return None

        predicate_filter = Q(predicate__canonical_uri__in=predicate_uris) | Q(predicate__uri__in=predicate_uris)
        triple = (
            Triple.objects.filter(subject_id=subject_id)
            .filter(predicate_filter)
            .select_related("object")
            .order_by("id")
            .first()
        )
        if triple and triple.object:
            return getattr(triple.object, "value", None)
        return None

    def _resolve_curated_selection_with_all_statuses(
        self,
        record: ProjectRecord,
    ) -> Optional[CuratedMediaSelection]:
        subject_id = getattr(record, "subject_id", None)
        if not subject_id:
            return None

        try:
            project_uuid = UUID(str(subject_id))
        except (TypeError, ValueError):
            return None

        links = list(
            OAIProjectMediaLink.objects.for_project(project_uuid)
            .ordered()
            .select_related("digital_object")
            .annotate(
                other_project_refs=Count(
                    "digital_object__oai_media_references",
                    filter=~Q(digital_object__oai_media_references__project_id=project_uuid),
                    distinct=True,
                )
            )
        )
        if not links:
            return None

        record_objects = getattr(record, "digital_objects", []) or []
        record_resource_ids: set[str] = set()
        graph_only_candidates: List[str] = []
        for obj in record_objects:
            rid = getattr(obj, "resource_id", None)
            uri = getattr(obj, "uri", None)
            if rid:
                record_resource_ids.add(str(rid))
            elif uri:
                graph_only_candidates.append(uri)

        ordered_resource_ids = tuple(str(link.digital_object_id) for link in links)
        ordered_object_uris = tuple(
            link.digital_object.uri
            for link in links
            if getattr(link.digital_object, "uri", None)
        )
        resource_uri_pairs: List[Tuple[str, Optional[str]]] = []

        curated_missing: List[str] = []
        label_overrides_by_id: Dict[str, str] = {}
        label_overrides_by_uri: Dict[str, str] = {}
        warnings: List[CuratedLinkWarning] = []

        for link in links:
            resource_key = str(link.digital_object_id)
            digital_uri = getattr(link.digital_object, "uri", None)
            resource_uri_pairs.append((resource_key, digital_uri))
            if link.label_override:
                label_overrides_by_id[resource_key] = link.label_override
                if digital_uri:
                    label_overrides_by_uri[digital_uri] = link.label_override
            if resource_key not in record_resource_ids:
                curated_missing.append(digital_uri or resource_key)
            if link.is_stale:
                warnings.append(
                    CuratedLinkWarning(
                        code="curated_stale",
                        digital_object_uri=digital_uri,
                        message="Curated link marked stale; canonical graph no longer references this object.",
                    )
                )
            other_refs = getattr(link, "other_project_refs", 0)
            if other_refs:
                warnings.append(
                    CuratedLinkWarning(
                        code="digital_object_multi_project",
                        digital_object_uri=digital_uri,
                        message="Digital object approved for multiple projects.",
                    )
                )

        curated_set = set(ordered_resource_ids)
        uncategorized_graph_uris: List[str] = list(dict.fromkeys(graph_only_candidates))
        for obj in record_objects:
            rid = getattr(obj, "resource_id", None)
            uri = getattr(obj, "uri", None)
            if not rid or not uri:
                continue
            if str(rid) not in curated_set:
                uncategorized_graph_uris.append(uri)

        if curated_missing:
            warnings.append(
                CuratedLinkWarning(
                    code="curated_missing_in_graph",
                    message=f"{len(curated_missing)} curated object(s) missing from canonical graph.",
                )
            )
        if uncategorized_graph_uris:
            warnings.append(
                CuratedLinkWarning(
                    code="graph_objects_uncurated",
                    message=f"{len(uncategorized_graph_uris)} canonical object(s) lack curated approvals.",
                )
            )

        ordered_uri_tuple = tuple(uri for uri in ordered_object_uris if uri)
        curated_missing_tuple = tuple(dict.fromkeys(curated_missing))
        uncategorized_tuple = tuple(dict.fromkeys(uncategorized_graph_uris))

        return CuratedMediaSelection(
            ordered_resource_ids=ordered_resource_ids,
            ordered_object_uris=ordered_uri_tuple,
            resource_uri_pairs=tuple(resource_uri_pairs),
            label_overrides_by_id=label_overrides_by_id,
            label_overrides_by_uri=label_overrides_by_uri,
            curated_missing_uris=curated_missing_tuple,
            graph_only_uris=uncategorized_tuple,
            warnings=tuple(warnings),
        )
