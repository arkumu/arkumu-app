"""Tailored variant of the OAIProjectBuilder that bypasses shared-event filtering."""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, replace
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple
from uuid import UUID

from django.core.cache import cache
from django.db.models import Count, Q

from arkumu.catalog.services.project_views import ProjectURIs
from arkumu.metadata.models import Resource
from arkumu.metadata.models.triples import Triple
from arkumu.projects import ProjectDigitalObjectLicense
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
    _DCP_FOLDER_CACHE,
    _load_dcp_folder_cache,
)
from arkumu.oaipmh.models import OAIProjectMediaLink
from arkumu.oaipmh.services import dcp_index


# License cache key and TTL
_LICENSE_CACHE_KEY = "oai:license_entities:all"
_LICENSE_CACHE_TTL = 3600  # 1 hour

# License predicate URIs (canonical)
_LIZENZSTATUS_URI = "http://arkumu.org/data/properties/lizenzstatus"
_LICENSE_PROPERTY_URIS = {
    "uri": "http://arkumu.org/data/properties/uri",
    "label_de": "http://arkumu.org/data/properties/deutscher-anzeigetext",
    "label_en": "http://arkumu.org/data/properties/englischer-anzeigetext",
    "name_de": "http://arkumu.org/data/properties/deutscher-name-der-lizenz",
    "name_en": "http://arkumu.org/data/properties/englischer-name-der-lizenz",
    "rights_statement": "http://arkumu.org/data/properties/zugehoeriges-rechtestatement",
    "identifier": "http://arkumu.org/data/properties/digitales-objekt-lizenz-id",
}


def _load_all_licenses() -> Dict[UUID, ProjectDigitalObjectLicense]:
    """Load all license entities from DB into a dict keyed by license resource ID."""
    # Find all unique license entity IDs
    license_triples = Triple.objects.filter(
        predicate__canonical_uri=_LIZENZSTATUS_URI
    ).values_list("object_id", flat=True).distinct()
    license_ids = set(license_triples)

    if not license_ids:
        return {}

    # Fetch all properties for these license entities
    property_uris = list(_LICENSE_PROPERTY_URIS.values())
    prop_filter = Q(predicate__canonical_uri__in=property_uris) | Q(predicate__uri__in=property_uris)
    license_props = Triple.objects.filter(
        subject_id__in=license_ids
    ).filter(prop_filter).select_related("predicate", "object")

    # Build license objects
    props_by_license: Dict[UUID, Dict[str, str]] = defaultdict(dict)
    for triple in license_props:
        pred_uri = triple.predicate.canonical_uri or triple.predicate.uri
        value = getattr(triple.object, "value", None)
        if not value:
            continue

        # Map predicate URI to property name
        for prop_name, prop_uri in _LICENSE_PROPERTY_URIS.items():
            if pred_uri == prop_uri:
                props_by_license[triple.subject_id][prop_name] = str(value)
                break

    result: Dict[UUID, ProjectDigitalObjectLicense] = {}
    for license_id, props in props_by_license.items():
        result[license_id] = ProjectDigitalObjectLicense(
            uri=props.get("uri"),
            label_de=props.get("label_de") or props.get("name_de"),
            label_en=props.get("label_en") or props.get("name_en"),
            rights_statement=props.get("rights_statement"),
            identifier=props.get("identifier"),
        )

    return result


def _get_cached_licenses() -> Dict[UUID, ProjectDigitalObjectLicense]:
    """Get all licenses from Redis cache, loading from DB if needed."""
    cached = cache.get(_LICENSE_CACHE_KEY)
    if cached is not None:
        return cached

    licenses = _load_all_licenses()
    cache.set(_LICENSE_CACHE_KEY, licenses, _LICENSE_CACHE_TTL)
    return licenses


def batch_fetch_licenses(resource_ids: Sequence[UUID]) -> Dict[UUID, ProjectDigitalObjectLicense]:
    """Batch fetch licenses for digital objects.

    Returns dict mapping digital_object_resource_id -> ProjectDigitalObjectLicense.
    Uses Redis-cached license entities for fast lookup.
    """
    if not resource_ids:
        return {}

    # Get all licenses from cache
    all_licenses = _get_cached_licenses()
    if not all_licenses:
        return {}

    # Query lizenzstatus triples for these digital objects (one query)
    lizenz_triples = Triple.objects.filter(
        subject_id__in=list(resource_ids),
        predicate__canonical_uri=_LIZENZSTATUS_URI,
    ).values_list("subject_id", "object_id")

    result: Dict[UUID, ProjectDigitalObjectLicense] = {}
    for do_id, license_id in lizenz_triples:
        if license_id in all_licenses:
            result[do_id] = all_licenses[license_id]

    return result


def batch_fetch_curated_links(project_ids: Sequence[UUID]) -> Dict[UUID, List]:
    """
    Batch fetch curated media links for multiple projects.

    Returns a dict mapping project_id -> list of OAIProjectMediaLink objects
    with digital_object pre-loaded.
    """
    if not project_ids:
        return {}

    links = (
        OAIProjectMediaLink.objects.filter(project_id__in=list(project_ids))
        .select_related("digital_object")
        .order_by("project_id", "order_index", "created_at", "id")
    )

    result: Dict[UUID, List] = defaultdict(list)
    for link in links:
        result[link.project_id].append(link)

    return dict(result)


@dataclass
class BatchedDcpData:
    """Pre-fetched DCP folder paths and expanded file lists."""
    folder_paths: Dict[str, str]  # uri -> folder_path
    file_lists: Dict[str, Tuple[str, ...]]  # folder_name -> (relative_file_paths,)


def batch_fetch_dcp_folders(curated_links_by_project: Dict[UUID, List]) -> BatchedDcpData:
    """
    Batch fetch DCP file lists using in-memory cache (no per-request Triple query).

    Returns BatchedDcpData with:
    - folder_paths: dict mapping digital_object_uri -> folder_name
    - file_lists: dict mapping folder_name -> tuple of relative file paths
    """
    if not curated_links_by_project:
        return BatchedDcpData(folder_paths={}, file_lists={})

    # Load cache once
    _load_dcp_folder_cache()

    folder_paths: Dict[str, str] = {}
    folder_names: List[str] = []

    for links in curated_links_by_project.values():
        for link in links:
            digital_obj = getattr(link, "digital_object", None)
            if digital_obj:
                obj_uri = getattr(digital_obj, "uri", None)
                if obj_uri:
                    folder_name = _DCP_FOLDER_CACHE.get(obj_uri)
                    if folder_name:
                        folder_paths[obj_uri] = folder_name
                        if folder_name not in folder_names:
                            folder_names.append(folder_name)

    # Batch fetch file lists for all folders
    file_lists: Dict[str, Tuple[str, ...]] = {}
    if folder_names:
        file_lists = dcp_index.batch_get_bundle_members("khm", folder_names)

    return BatchedDcpData(folder_paths=folder_paths, file_lists=file_lists)


@dataclass
class BatchedGraphData:
    """Pre-fetched data for building graph digital objects."""
    resources: Dict[str, Resource]  # resource_id -> Resource
    path_literals: Dict[str, str]   # resource_id -> path
    checksum_literals: Dict[str, str]  # resource_id -> checksum
    event_links: Dict[str, List[Tuple[str, str]]]  # resource_id -> [(event_id, event_uri), ...]


def batch_fetch_graph_data(
    resource_ids: Sequence[str],
    org_code: Optional[str] = None,
) -> BatchedGraphData:
    """
    Batch fetch all data needed for _graph_digital_object for Rosetta orgs.

    This replaces 4 queries per resource with 4 total queries.
    """
    result = BatchedGraphData(
        resources={},
        path_literals={},
        checksum_literals={},
        event_links={},
    )

    if not resource_ids:
        return result

    # Convert to UUIDs
    uuid_list = []
    id_map: Dict[UUID, str] = {}
    for rid in resource_ids:
        try:
            uuid_val = UUID(str(rid))
            uuid_list.append(uuid_val)
            id_map[uuid_val] = str(rid)
        except (TypeError, ValueError):
            continue

    if not uuid_list:
        return result

    # 1. Batch fetch Resources
    resources = Resource.objects.filter(pk__in=uuid_list).select_related("organization")
    for r in resources:
        result.resources[str(r.id)] = r

    # 2. Batch fetch path literals
    path_predicates = [ProjectURIs.DIGITAL_OBJECT_PATH]
    normalized_org = (org_code or "").lower().strip()
    for candidate in _DIGITAL_OBJECT_FALLBACK_PREDICATES.get(normalized_org, ()):
        if candidate and candidate not in path_predicates:
            path_predicates.append(candidate)

    path_filter = Q(predicate__canonical_uri__in=path_predicates) | Q(predicate__uri__in=path_predicates)
    path_triples = Triple.objects.filter(
        subject_id__in=uuid_list
    ).filter(path_filter).select_related("object")

    for triple in path_triples:
        rid = str(triple.subject_id)
        if rid not in result.path_literals:  # Take first match
            value = getattr(triple.object, "value", None)
            if value:
                result.path_literals[rid] = str(value)

    # 3. Batch fetch checksum literals
    checksum_predicate = ProjectSnapshotService.ROSETTA_CHECKSUM_PREDICATES.get(normalized_org)
    if checksum_predicate:
        checksum_filter = Q(predicate__canonical_uri=checksum_predicate) | Q(predicate__uri=checksum_predicate)
        checksum_triples = Triple.objects.filter(
            subject_id__in=uuid_list
        ).filter(checksum_filter).select_related("object")

        for triple in checksum_triples:
            rid = str(triple.subject_id)
            if rid not in result.checksum_literals:
                value = getattr(triple.object, "value", None)
                if value:
                    result.checksum_literals[rid] = str(value)

    # 4. Batch fetch event links
    event_filter = Q(predicate__canonical_uri=ProjectURIs.DIGITAL_OBJECT_LINK) | Q(
        predicate__uri=ProjectURIs.DIGITAL_OBJECT_LINK
    )
    event_triples = Triple.objects.filter(
        object_id__in=uuid_list
    ).filter(event_filter).select_related("subject")

    for triple in event_triples:
        rid = str(triple.object_id)
        event_id = str(triple.subject_id)
        event_uri = getattr(triple.subject, "uri", None) or ""
        if rid not in result.event_links:
            result.event_links[rid] = []
        result.event_links[rid].append((event_id, event_uri))

    return result

_DIGITAL_OBJECT_FALLBACK_PREDICATES: Mapping[str, Sequence[str]] = getattr(
    ProjectSnapshotService,
    "DIGITAL_OBJECT_FALLBACK_PREDICATES",
    {},
)

logger = logging.getLogger(__name__)


class OAIProjectBuilderTailored(OAIProjectBuilder):
    """Customized builder used exclusively for the tailored OAI profile."""

    def __init__(self, **kwargs):
        def _passthrough_resolver(
            org_code: Optional[str],
            *,
            path: Optional[str] = None,
            file_name: Optional[str] = None,
        ) -> List[str]:
            normalized = (path or "").strip()
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Tailored path resolver bypass for org=%s raw_path=%s file=%s",
                    (org_code or "").strip(),
                    normalized or file_name or "",
                    file_name or "",
                )
            return [normalized] if normalized else []

        kwargs.setdefault("path_resolver", _passthrough_resolver)

        logger.debug("Tailored builder using passthrough path resolver for curated media links")
        super().__init__(**kwargs)
        # Normalize curated prefixes for Rosetta orgs (used to shorten FLocat paths)
        self._rosetta_curated_prefixes = {
            code: prefix.rstrip("/")
            for code, prefix in getattr(self, "_rosetta_curated_prefixes", {}).items()
            if prefix
        }

    def from_project_record(
        self,
        record: ProjectRecord,
        *,
        skip_shared_event_filter: bool = False,
        prefetched_curated_links: Optional[List] = None,
        prefetched_dcp_data: Optional[BatchedDcpData] = None,
        prefetched_graph_data: Optional[BatchedGraphData] = None,
    ) -> OAIProject:
        institution_code = self._resolve_institution_code(record)

        filtered_record = record
        # Tailored feeds intentionally keep shared-event objects, so skip the shared-event filter.
        filtered_record = self._filter_flagged_digital_objects(filtered_record)
        filtered_record = self._filter_overarching_projects(filtered_record, institution_code)

        # Store prefetched data for use in helper methods
        self._prefetched_dcp_data = prefetched_dcp_data
        self._prefetched_graph_data = prefetched_graph_data

        # Mark DCP bundle members upfront (before normalization)
        self._mark_dcp_bundle_members(filtered_record, institution_code)

        # Tailored feeds ALWAYS use curated media links as source of truth
        curated_selection = self._resolve_curated_selection(
            filtered_record, prefetched_links=prefetched_curated_links
        )

        # Always use curated links - they are the source of truth for tailored OAI
        # No fallback to graph digital objects
        normalized_objects = self._normalize_curated_only_objects(
            curated_selection,
            institution_code,
        )

        return OAIProject(
            record=filtered_record,
            institution_code=institution_code,
            digital_objects=tuple(normalized_objects),
            curated_selection=curated_selection,
        )

    # Tailored profile keeps "Oberwerk" umbrella assets so override the parent
    # suppression hook with a no-op. Canonical feeds still inherit base behavior.
    def _filter_overarching_projects(
        self,
        record: ProjectRecord,
        institution_code: Optional[str],
    ) -> ProjectRecord:  # pragma: no cover - trivial override
        return record

    def _expand_dcp_folder_if_needed(
        self,
        obj: ProjectDigitalObject,
        institution_code: Optional[str],
    ) -> Optional[List[ProjectDigitalObject]]:
        """
        Expand DCP folders using prefetched data or the path index.

        When a digital object has a `dateipfad-dcp-ordner` triple, look up all files
        in that folder from prefetched data or the path index.
        """
        # Only check for KHM institution
        if (institution_code or "").strip().lower() != "khm":
            return None

        obj_uri = getattr(obj, "uri", None)
        if not obj_uri:
            return None

        # Try to use prefetched data first (batch loaded at page level)
        prefetched = getattr(self, "_prefetched_dcp_data", None)
        if prefetched is not None:
            folder_path = prefetched.folder_paths.get(obj_uri)
            if not folder_path:
                return None

            folder_path_clean = folder_path.replace("\\", "/").rstrip("/")
            folder_name = folder_path_clean.split("/")[-1] if "/" in folder_path_clean else folder_path_clean

            # Use prefetched file lists
            relative_file_paths = prefetched.file_lists.get(folder_name, ())
            if not relative_file_paths:
                return None

            from django.conf import settings
            rosetta_root = getattr(settings, "OAI_EXTERNAL_ROSETTA_ROOTS", {}).get("khm") or ""
            rosetta_root = str(rosetta_root).rstrip("/")

            expanded_objects: List[ProjectDigitalObject] = []
            for rel_path in relative_file_paths:
                rel_path_clean = str(rel_path).lstrip("/")
                if not rel_path_clean:
                    continue
                abs_path = f"{rosetta_root}/{rel_path_clean}" if rosetta_root else rel_path_clean

                new_obj = ProjectDigitalObject(
                    path=abs_path,
                    uri=obj.uri,
                )
                new_obj.resource_id = getattr(obj, "resource_id", None)

                # Copy other relevant attributes from the original object
                for attr in [
                    "content_type", "size_bytes", "checksum", "checksum_algorithm",
                    "checksum_provenance", "access_url", "storage_status", "created_at",
                    "updated_at", "license", "uuid", "genesis_type", "media_type",
                    "significant_properties_de", "significant_properties_en",
                ]:
                    if hasattr(obj, attr):
                        value = getattr(obj, attr)
                        if value is not None:
                            setattr(new_obj, attr, value)

                # Mark as DCP bundle member
                setattr(new_obj, "_from_dcp_bundle", True)
                expanded_objects.append(new_obj)

            return expanded_objects if expanded_objects else None

        # Fall back to parent implementation with individual queries
        expanded = super()._expand_dcp_folder_if_needed(obj, institution_code)
        if expanded:
            for expanded_obj in expanded:
                setattr(expanded_obj, "_from_dcp_bundle", True)
        return expanded

    def _mark_dcp_bundle_members(
        self,
        record: ProjectRecord,
        institution_code: Optional[str],
    ) -> None:
        """
        Mark all DCP bundle members upfront before normalization.

        Queries DCP folder triples once and marks all matching digital objects.
        Also handles CPL/PKL filename heuristic for objects without triples.
        """
        # Only KHM uses DCP bundles
        if (institution_code or "").lower() != "khm":
            return

        digital_objects = list(getattr(record, "digital_objects", []) or [])
        if not digital_objects:
            return

        # Track which folders we've already processed
        processed_folders: set[str] = set()

        for obj in digital_objects:
            # Skip if already marked
            if getattr(obj, "_from_dcp_bundle", False):
                continue

            # Try to get DCP folder from triple
            folder_path = self._dcp_folder_from_triple(obj)
            if folder_path:
                normalized_folder = folder_path.replace("\\", "/").rstrip("/")
                folder_name = normalized_folder.split("/")[-1] if "/" in normalized_folder else normalized_folder

                if folder_name in processed_folders:
                    continue
                processed_folders.add(folder_name)

                # Mark all objects in this folder
                for candidate in digital_objects:
                    candidate_path = _clean(getattr(candidate, "path", None)) or _clean(getattr(candidate, "storage_key", None))
                    if not candidate_path:
                        continue
                    candidate_norm = candidate_path.replace("\\", "/")
                    if self._path_matches_folder(candidate_norm, folder_name):
                        setattr(candidate, "_from_dcp_bundle", True)
                        setattr(candidate, "_dcp_folder", folder_name)
                continue

            # Fallback: CPL/PKL filename heuristic
            file_name = (_clean(getattr(obj, "file_name", None)) or "").lower()
            if not file_name.endswith(".xml"):
                continue
            if not any(file_name.startswith(prefix) for prefix in ("cpl_", "pkl_", "assetmap", "volindex")):
                continue

            raw_path = _clean(getattr(obj, "path", None)) or _clean(getattr(obj, "storage_key", None))
            if not raw_path:
                continue
            normalized_path = raw_path.replace("\\", "/")
            if "/" not in normalized_path:
                continue
            folder = normalized_path.rsplit("/", 1)[0]
            if not folder or folder in processed_folders:
                continue
            processed_folders.add(folder)

            # Mark all objects in this folder
            for candidate in digital_objects:
                candidate_path = _clean(getattr(candidate, "path", None)) or _clean(getattr(candidate, "storage_key", None))
                if not candidate_path:
                    continue
                candidate_norm = candidate_path.replace("\\", "/")
                if candidate_norm.startswith(folder + "/") or candidate_norm == folder:
                    setattr(candidate, "_from_dcp_bundle", True)
                    setattr(candidate, "_dcp_folder", folder)

    def _path_matches_folder(self, path: str, folder_name: str) -> bool:
        """Check if a path is inside a folder with the given name."""
        if folder_name not in path:
            return False
        folder_idx = path.find(folder_name)
        if folder_idx == -1:
            return False
        after_folder = path[folder_idx + len(folder_name):]
        return after_folder.startswith("/") or after_folder == ""

    def _expand_dcp_folder_from_record(
        self,
        obj: ProjectDigitalObject,
        record: ProjectRecord,
    ) -> Optional[List[ProjectDigitalObject]]:
        """
        Return DCP bundle siblings if the object is marked as a DCP member.

        This method now relies on upfront marking by _mark_dcp_bundle_members.
        """
        if not getattr(obj, "_from_dcp_bundle", False):
            return None

        dcp_folder = getattr(obj, "_dcp_folder", None)
        if not dcp_folder:
            return None

        # Collect all objects in the same DCP folder
        siblings: List[ProjectDigitalObject] = []
        for candidate in getattr(record, "digital_objects", []) or []:
            if getattr(candidate, "_dcp_folder", None) == dcp_folder:
                siblings.append(candidate)

        if not siblings:
            return None

        # Ensure the trigger object is first
        if obj in siblings:
            siblings.remove(obj)
        siblings.insert(0, obj)

        return siblings

    def _dcp_folder_from_triple(self, obj: ProjectDigitalObject) -> Optional[str]:
        obj_uri = getattr(obj, "uri", None)
        if not obj_uri:
            return None

        # Use prefetched data if available
        prefetched = getattr(self, "_prefetched_dcp_data", None)
        if prefetched is not None:
            folder_path = prefetched.folder_paths.get(obj_uri)
            if folder_path:
                return folder_path.rstrip("/")
            return None

        # Fall back to database query
        from arkumu.metadata.models import Triple

        try:
            triple = (
                Triple.objects.filter(
                    subject__uri=obj_uri,
                    predicate__uri="http://arkumu.org/data/khm/properties/dateipfad-dcp-ordner",
                )
                .select_related("object")
                .first()
            )
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.error("Error resolving DCP folder triple for %s: %s", obj_uri, exc)
            return None

        if not triple or not getattr(triple, "object", None):
            return None

        folder_path = _clean(getattr(triple.object, "value", None))
        if not folder_path:
            return None

        return folder_path.replace("\\", "/").rstrip("/")

    def _resolve_curated_selection(
        self,
        record: ProjectRecord,
        prefetched_links: Optional[List] = None,
    ) -> Optional[CuratedMediaSelection]:
        return self._resolve_curated_selection_with_all_statuses(
            record, prefetched_links=prefetched_links
        )

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
            allowed_resource_ids = {str(rid) for rid in curated_selection.ordered_resource_ids if rid}
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
            record_dcp_expanded = self._expand_dcp_folder_from_record(obj, record)
            expanded_objects = record_dcp_expanded if record_dcp_expanded else self._expand_dcp_folder_if_needed(obj, institution_code)
            from_dcp_bundle = bool(expanded_objects and record_dcp_expanded)
            objects_to_process = expanded_objects if expanded_objects else [obj]

            for current_obj in objects_to_process:
                resource_identifier = getattr(current_obj, "resource_id", None)
                normalized_resource_id = str(resource_identifier) if resource_identifier else None
                obj_uri = _clean(getattr(current_obj, "uri", None))
                if allowed_resource_ids is not None and not (from_dcp_bundle or getattr(current_obj, "_from_dcp_bundle", False)):
                    include = False
                    if normalized_resource_id and normalized_resource_id in allowed_resource_ids:
                        include = True
                    elif obj_uri and allowed_uris and obj_uri in allowed_uris:
                        include = True
                    if not include:
                        continue

                if curated_selection:
                    # Don't set _from_curated_media_link for DCP bundle files - they already
                    # have correct paths from the index and don't need prefix rewriting
                    if not getattr(current_obj, "_from_dcp_bundle", False):
                        setattr(current_obj, "_from_curated_media_link", True)

                normalized = self._normalize_object(current_obj, institution_code)
                if not normalized or not self._is_harvestable(normalized):
                    continue
                if getattr(current_obj, "_from_dcp_bundle", False):
                    object.__setattr__(normalized, "_from_dcp_bundle", True)

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
            normalized_id
            for normalized_id in (
                str(rid) for rid in curated_selection.ordered_resource_ids if rid
            )
            if normalized_id and normalized_id not in grouped_by_resource
        ]
        if missing_resource_ids:
            uri_by_resource = {
                str(pair[0]): pair[1]
                for pair in curated_selection.resource_uri_pairs
                if pair[0]
            }
            curated_objects = self._load_curated_project_objects(
                missing_resource_ids,
                uri_by_resource,
                institution_code,
            )
            for rid in missing_resource_ids:
                project_objects = list(curated_objects.get(rid, []))
                if not project_objects:
                    project_objects = list(extra_by_resource.get(rid, []))
                if not project_objects:
                    continue

                normalized_items: List[NormalizedDigitalObject] = []
                for project_obj in project_objects:
                    expanded = self._expand_dcp_folder_if_needed(project_obj, institution_code)
                    objects_to_process = expanded if expanded else [project_obj]

                    for expanded_obj in objects_to_process:
                        # Don't set _from_curated_media_link for DCP bundle files - they already
                        # have correct paths from the index and don't need prefix rewriting
                        if not getattr(expanded_obj, "_from_dcp_bundle", False):
                            setattr(expanded_obj, "_from_curated_media_link", True)
                        normalized = self._normalize_object(expanded_obj, institution_code)
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
            matches = grouped_by_resource.get(str(resource_id), [])
            _extend_with_candidates(matches)

        for uri in curated_selection.ordered_object_uris:
            matches = grouped_by_uri.get(uri, [])
            _extend_with_candidates(matches)

        # Append any DCP bundle members that were not explicitly ordered by the curated selection.
        for candidate in objects:
            if not getattr(candidate, "_from_dcp_bundle", False):
                continue
            candidate_id = id(candidate)
            if candidate_id in consumed_ids:
                continue
            ordered_objects.append(candidate)
            consumed_ids.add(candidate_id)

        return ordered_objects

    def _normalize_curated_only_objects(
        self,
        curated_selection: CuratedMediaSelection,
        institution_code: Optional[str],
    ) -> List[NormalizedDigitalObject]:
        resource_ids = [str(rid) for rid in curated_selection.ordered_resource_ids if rid]
        if not resource_ids:
            return []

        uri_by_resource = {
            str(pair[0]): pair[1]
            for pair in curated_selection.resource_uri_pairs
            if pair[0]
        }
        curated_objects = self._load_curated_project_objects(
            resource_ids,
            uri_by_resource,
            institution_code,
        )
        if not curated_objects:
            return []

        label_by_id = dict(curated_selection.label_overrides_by_id)
        label_by_uri = dict(curated_selection.label_overrides_by_uri)
        normalized: List[NormalizedDigitalObject] = []
        seen: set[str] = set()

        for resource_id in resource_ids:
            for project_obj in curated_objects.get(resource_id, []):
                expanded = self._expand_dcp_folder_if_needed(project_obj, institution_code)
                objects_to_process = expanded if expanded else [project_obj]

                for expanded_obj in objects_to_process:
                    # Don't set _from_curated_media_link for DCP bundle files - they already
                    # have correct paths from the index and don't need prefix rewriting
                    if not getattr(expanded_obj, "_from_dcp_bundle", False):
                        setattr(expanded_obj, "_from_curated_media_link", True)
                    normalized_obj = self._normalize_object(expanded_obj, institution_code)
                    if not normalized_obj or not self._is_harvestable(normalized_obj):
                        continue
                    identity = normalized_obj.preferred_location
                    if identity:
                        identity_key = identity.lower()
                        if identity_key in seen:
                            continue
                        seen.add(identity_key)
                    label_override = None
                    if normalized_obj.resource_id and normalized_obj.resource_id in label_by_id:
                        label_override = label_by_id[normalized_obj.resource_id]
                    elif normalized_obj.uri and normalized_obj.uri in label_by_uri:
                        label_override = label_by_uri[normalized_obj.uri]
                    if label_override:
                        normalized_obj = replace(normalized_obj, label_override=label_override)
                    normalized.append(normalized_obj)

        return normalized

    def _load_curated_project_objects(
        self,
        resource_ids: Sequence[str],
        uri_by_resource: Mapping[str, Optional[str]],
        institution_code: Optional[str],
    ) -> Dict[str, List[ProjectDigitalObject]]:
        """Load curated media from OAIProjectMediaLink.

        S3 orgs (DET/RSH/FUK): S3FileObject only
        Rosetta orgs (KHM/HMT): dateipfad triple first, S3FileObject fallback
        """
        if not resource_ids:
            return {}

        uuid_map: Dict[UUID, str] = {}
        for rid in resource_ids:
            try:
                uuid_map[UUID(str(rid))] = str(rid)
            except (TypeError, ValueError):
                continue

        if not uuid_map:
            return {}

        normalized_code = (institution_code or "").lower().strip()
        is_s3_org = normalized_code in self._s3_orgs

        # Batch fetch licenses for all digital objects (uses Redis cache)
        licenses_by_id = batch_fetch_licenses(list(uuid_map.keys()))

        curated_objects: Dict[str, List[ProjectDigitalObject]] = {}

        # S3 orgs: use S3FileObject only
        if is_s3_org:
            files = (
                S3FileObject.objects.filter(
                    related_resource_id__in=list(uuid_map.keys()),
                    s3_key__isnull=False,
                )
                .exclude(s3_key="")
                .select_related("related_resource")
            )

            for file_obj in files:
                rid_uuid = getattr(file_obj, "related_resource_id", None)
                if rid_uuid not in uuid_map:
                    continue
                rid_str = uuid_map[rid_uuid]

                filename = file_obj.file_name
                if not filename and file_obj.s3_key:
                    filename = file_obj.s3_key.split("/")[-1]
                if not filename:
                    continue

                fixity = parse_fixity(getattr(file_obj, "sha256_checksum", None))
                resource_uri = uri_by_resource.get(rid_str)
                if not resource_uri and getattr(file_obj, "related_resource", None):
                    resource_uri = getattr(file_obj.related_resource, "uri", None)

                # Get license from batch-fetched data
                license_obj = licenses_by_id.get(rid_uuid)

                project_obj = ProjectDigitalObject(
                    path=filename,
                    storage_key=file_obj.s3_key,
                    file_name=filename,
                    content_type=file_obj.content_type,
                    size_bytes=file_obj.file_size_bytes,
                    checksum=fixity.digest,
                    checksum_algorithm=fixity.algorithm,
                    checksum_provenance='s3' if fixity.digest else None,
                    access_url=file_obj.s3_url,
                    storage_status=file_obj.status,
                    resource_id=rid_str,
                    uri=resource_uri,
                    license=license_obj,
                )
                setattr(project_obj, "_from_s3_file_object", True)
                curated_objects.setdefault(rid_str, []).append(project_obj)

            return curated_objects

        # Rosetta orgs (KHM/HMT): dateipfad first, S3 fallback
        DATEIPFAD_URI = "http://arkumu.org/data/properties/dateipfad"
        path_triples = Triple.objects.filter(
            subject_id__in=list(uuid_map.keys()),
            predicate__canonical_uri=DATEIPFAD_URI,
        ).select_related("object")

        filename_by_id: Dict[UUID, str] = {}
        for triple in path_triples:
            if triple.object and triple.object.value:
                path_value = str(triple.object.value)
                filename = path_value.replace("\\", "/").split("/")[-1]
                if filename:
                    filename_by_id[triple.subject_id] = filename

        # Get S3 data for fallback and metadata
        s3_by_id: Dict[UUID, S3FileObject] = {}
        files = (
            S3FileObject.objects.filter(
                related_resource_id__in=list(uuid_map.keys()),
                s3_key__isnull=False,
            )
            .exclude(s3_key="")
            .select_related("related_resource")
        )
        for file_obj in files:
            rid_uuid = getattr(file_obj, "related_resource_id", None)
            if rid_uuid:
                s3_by_id[rid_uuid] = file_obj

        # Batch fetch checksums from Triple table for Rosetta orgs
        checksum_by_id: Dict[UUID, str] = {}
        checksum_predicate = ProjectSnapshotService.ROSETTA_CHECKSUM_PREDICATES.get(normalized_code)
        if checksum_predicate:
            checksum_filter = Q(predicate__canonical_uri=checksum_predicate) | Q(predicate__uri=checksum_predicate)
            checksum_triples = Triple.objects.filter(
                subject_id__in=list(uuid_map.keys())
            ).filter(checksum_filter).select_related("object")
            for triple in checksum_triples:
                if triple.object and triple.object.value:
                    checksum_by_id[triple.subject_id] = str(triple.object.value)

        for rid_uuid, rid_str in uuid_map.items():
            filename = filename_by_id.get(rid_uuid)
            s3_obj = s3_by_id.get(rid_uuid)

            # Fallback to S3 filename if no dateipfad
            if not filename and s3_obj:
                filename = s3_obj.file_name
                if not filename and s3_obj.s3_key:
                    filename = s3_obj.s3_key.split("/")[-1]

            if not filename:
                continue

            resource_uri = uri_by_resource.get(rid_str)
            if not resource_uri and s3_obj and getattr(s3_obj, "related_resource", None):
                resource_uri = getattr(s3_obj.related_resource, "uri", None)

            # Get license from batch-fetched data
            license_obj = licenses_by_id.get(rid_uuid)

            if s3_obj:
                fixity = parse_fixity(getattr(s3_obj, "sha256_checksum", None))
                project_obj = ProjectDigitalObject(
                    path=filename,
                    storage_key=s3_obj.s3_key,
                    file_name=filename,
                    content_type=s3_obj.content_type,
                    size_bytes=s3_obj.file_size_bytes,
                    checksum=fixity.digest,
                    checksum_algorithm=fixity.algorithm,
                    checksum_provenance='s3' if fixity.digest else None,
                    access_url=s3_obj.s3_url,
                    storage_status=s3_obj.status,
                    resource_id=rid_str,
                    uri=resource_uri,
                    license=license_obj,
                )
            else:
                # Use checksum from Triple table for Rosetta orgs
                checksum_literal = checksum_by_id.get(rid_uuid)
                fixity = parse_fixity(checksum_literal) if checksum_literal else None
                project_obj = ProjectDigitalObject(
                    path=filename,
                    storage_key=None,
                    file_name=filename,
                    content_type=None,
                    storage_status="completed",
                    resource_id=rid_str,
                    uri=resource_uri,
                    checksum=fixity.digest if fixity else None,
                    checksum_algorithm=fixity.algorithm if fixity else None,
                    checksum_provenance="metadata" if fixity and fixity.digest else None,
                    license=license_obj,
                )

            setattr(project_obj, "_from_s3_file_object", True)
            curated_objects.setdefault(rid_str, []).append(project_obj)

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
            # Flag for downstream normalization so we can bypass dump lookups.
            setattr(project_obj, "_from_s3_file_object", True)
            curated_objects.setdefault(rid_str, []).append(project_obj)

        return curated_objects

    def _normalize_object(
        self,
        obj: ProjectDigitalObject,
        institution_code: Optional[str],
    ) -> Optional[NormalizedDigitalObject]:
        # Only process objects from S3FileObject, curated media links, or DCP bundles
        from_s3 = getattr(obj, "_from_s3_file_object", False)
        from_curated = getattr(obj, "_from_curated_media_link", False)
        from_dcp = getattr(obj, "_from_dcp_bundle", False)
        if not from_s3 and not from_curated and not from_dcp:
            return None

        setattr(obj, "_bypass_dump_fixity", True)
        normalized = super()._normalize_object(obj, institution_code)
        if not normalized:
            return None

        normalized_code = (institution_code or "").lower().strip()
        is_dcp_bundle = getattr(obj, "_from_dcp_bundle", False)
        is_s3_org = normalized_code in self._s3_orgs

        # S3 orgs: use base_path + storage_key
        if is_s3_org and normalized.storage_key:
            from django.conf import settings
            base_paths = getattr(settings, "OAI_S3_ROSETTA_BASE_PATHS", {})
            base_path = base_paths.get(normalized_code, "").rstrip("/")
            s3_key = normalized.storage_key.lstrip("/")
            rosetta_path = f"{base_path}/{s3_key}" if base_path else normalized.storage_key
            normalized = replace(
                normalized,
                rosetta_path=rosetta_path,
                rosetta_candidates=(rosetta_path,),
            )
        # Rosetta orgs: apply prefix + filename
        # DCP bundle files keep their folder structure
        elif normalized.file_name and not is_dcp_bundle:
            prefix = self._rosetta_curated_prefixes.get(normalized_code)
            if prefix:
                # HMT requires Tonbandarchiv subfolder
                if normalized_code == "hmt":
                    rosetta_path = f"{prefix}/Tonbandarchiv/{normalized.file_name}"
                else:
                    rosetta_path = f"{prefix}/{normalized.file_name}"
                normalized = replace(
                    normalized,
                    rosetta_path=rosetta_path,
                    rosetta_candidates=(rosetta_path,),
                )

        return normalized

    def _graph_digital_object(
        self,
        resource_id: str,
        uri_hint: Optional[str],
        institution_code: Optional[str],
    ) -> Optional[ProjectDigitalObject]:
        # Try prefetched data first (batch loaded at page level)
        prefetched = getattr(self, "_prefetched_graph_data", None)
        if prefetched is not None:
            return self._graph_digital_object_from_prefetched(
                resource_id, uri_hint, institution_code, prefetched
            )

        # Fallback to individual queries
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

    def _graph_digital_object_from_prefetched(
        self,
        resource_id: str,
        uri_hint: Optional[str],
        institution_code: Optional[str],
        prefetched: BatchedGraphData,
    ) -> Optional[ProjectDigitalObject]:
        """Build digital object from prefetched batch data (no DB queries)."""
        resource = prefetched.resources.get(resource_id)
        path_literal = prefetched.path_literals.get(resource_id)

        if not path_literal:
            return None

        resource_uri = uri_hint
        org_code = None
        if resource:
            resource_uri = getattr(resource, "uri", None) or uri_hint
            organization = getattr(resource, "organization", None)
            if organization:
                org_code = (getattr(organization, "code", "") or "").lower().strip()

        project_obj = ProjectDigitalObject(
            path=path_literal,
            storage_key=path_literal,
            file_name=None,
            content_type=None,
            storage_status="completed",
            resource_id=resource_id,
            uri=resource_uri,
        )
        file_name = _infer_file_name(project_obj)
        if file_name:
            project_obj.file_name = file_name
        project_obj.content_type = _guess_mime_type(project_obj)
        project_obj.source = "graph"

        # Use prefetched checksum
        checksum_literal = prefetched.checksum_literals.get(resource_id)
        if checksum_literal:
            fixity = parse_fixity(checksum_literal)
            if fixity.digest:
                project_obj.checksum = fixity.digest
                project_obj.checksum_algorithm = fixity.algorithm or "sha256"
                project_obj.checksum_provenance = fixity.provenance or "metadata"

        # Use prefetched event links
        event_links = prefetched.event_links.get(resource_id, [])
        if event_links:
            project_obj.source_event_ids = [link[0] for link in event_links]
            project_obj.source_event_uris = [link[1] for link in event_links if link[1]]

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
        prefetched_links: Optional[List] = None,
    ) -> Optional[CuratedMediaSelection]:
        subject_id = getattr(record, "subject_id", None)
        if not subject_id:
            return None

        try:
            project_uuid = UUID(str(subject_id))
        except (TypeError, ValueError):
            return None

        # Use prefetched links if available, otherwise query the database
        if prefetched_links is not None:
            links = prefetched_links
        else:
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
