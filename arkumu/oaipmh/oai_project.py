"""Domain models that adapt `ProjectRecord` instances for OAI-PMH exports."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable, List, Optional, Sequence, Tuple

import logging
import mimetypes

from django.conf import settings

from arkumu.projects import ProjectDigitalObject, ProjectDigitalObjectLicense, ProjectRecord
from arkumu.projects.fixity import FixityInfo, parse_fixity

from .path_mapping import resolve_external_paths


HARVESTABLE_STORAGE_STATUSES = {"completed", "verified"}


logger = logging.getLogger(__name__)


def _clean(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    normalized = str(value).strip()
    return normalized or None


def _guess_mime_type(obj: ProjectDigitalObject) -> Optional[str]:
    """Derive a MIME type from explicit metadata or file extension."""

    if getattr(obj, "content_type", None):
        return obj.content_type

    candidates = [obj.file_name, obj.access_url, obj.path, obj.storage_key]
    for candidate in candidates:
        candidate = _clean(candidate)
        if not candidate:
            continue
        guess = mimetypes.guess_type(candidate)[0]
        if guess:
            return guess
    return None


def _infer_file_name(obj: ProjectDigitalObject) -> Optional[str]:
    """Return the most likely filename for a digital object."""

    if getattr(obj, "file_name", None):
        return _clean(obj.file_name)

    candidates = [obj.path, obj.storage_key, obj.access_url]
    for candidate in candidates:
        candidate = _clean(candidate)
        if not candidate:
            continue
        try:
            name = Path(candidate).name
        except ValueError:
            name = candidate
        if name == candidate:
            for separator in ("/", "\\"):
                if separator in candidate:
                    name = candidate.split(separator)[-1]
                    break
        name = _clean(name)
        if name:
            return name
    return None


def _status_token(status: Optional[str]) -> Optional[str]:
    if not status:
        return None
    return status.lower().strip() or None


@dataclass(frozen=True)
class NormalizedDigitalObject:
    """Normalized digital object enriched with Rosetta/S3 metadata."""

    original_path: Optional[str]
    storage_key: Optional[str]
    rosetta_path: Optional[str]
    rosetta_candidates: Tuple[str, ...]
    file_name: Optional[str]
    content_type: Optional[str]
    size_bytes: Optional[int]
    checksum: Optional[str]
    checksum_algorithm: Optional[str]
    checksum_provenance: Optional[str]
    access_url: Optional[str]
    storage_status: Optional[str]
    source: str
    uuid: Optional[str] = None
    genesis_type: Optional[str] = None
    media_type: Optional[str] = None
    significant_properties_de: Optional[str] = None
    significant_properties_en: Optional[str] = None
    license: Optional[ProjectDigitalObjectLicense] = None

    @property
    def harvestable(self) -> bool:
        """Return True when the object is eligible for OAI dissemination."""

        if self.source == "rosetta":
            return bool(self.rosetta_path)

        if self.source == "s3":
            if not self.storage_key:
                return False
            status = _status_token(self.storage_status)
            return status in HARVESTABLE_STORAGE_STATUSES

        # Default fallback for objects with limited metadata
        return bool(self.rosetta_path or self.storage_key)

    @property
    def preferred_location(self) -> Optional[str]:
        """Return the location that should appear in METS FLocat."""

        if self.rosetta_path:
            return self.rosetta_path
        if self.storage_key:
            return self.storage_key
        return self.original_path or self.access_url

    def checksum_tuple(self) -> Tuple[Optional[str], Optional[str]]:
        return self.checksum_algorithm, self.checksum

    def checksum_label(self) -> Optional[str]:
        if not self.checksum_algorithm:
            return None
        normalized = self.checksum_algorithm.lower().replace('-', '')
        mapping = {
            'sha256': 'SHA-256',
            'sha1': 'SHA-1',
            'sha512': 'SHA-512',
            'md5': 'MD5',
        }
        return mapping.get(normalized, self.checksum_algorithm.upper())


@dataclass(frozen=True)
class OAIProject:
    """Immutable view over a `ProjectRecord` tailored for OAI-PMH."""

    record: ProjectRecord
    institution_code: Optional[str]
    digital_objects: Tuple[NormalizedDigitalObject, ...]

    @property
    def harvestable(self) -> bool:
        return any(obj.harvestable for obj in self.digital_objects)

    @property
    def uri(self) -> str:
        return self.record.uri

    def primary_object(self) -> Optional[NormalizedDigitalObject]:
        for obj in self.digital_objects:
            if obj.harvestable:
                return obj
        return None

    def mime_types(self) -> Tuple[str, ...]:
        values: List[str] = []
        seen: set[str] = set()
        for obj in self.digital_objects:
            mime = _clean(obj.content_type)
            if not mime or mime in seen:
                continue
            seen.add(mime)
            values.append(mime)
        return tuple(values)


class OAIProjectBuilder:
    """Factory that enriches snapshot records with harvest metadata."""

    def __init__(
        self,
        *,
        s3_orgs: Optional[Sequence[str]] = None,
        rosetta_orgs: Optional[Sequence[str]] = None,
        path_resolver: Callable[..., List[str]] = resolve_external_paths,
        code_aliases: Optional[dict[str, str]] = None,
        label_aliases: Optional[dict[str, str]] = None,
    ) -> None:
        self._s3_orgs = {
            code.lower().strip()
            for code in (
                s3_orgs
                if s3_orgs is not None
                else getattr(settings, "OAI_S3_HARVESTABLE_ORGS", ())
            )
            if code
        }
        self._rosetta_orgs = {
            code.lower().strip()
            for code in (
                rosetta_orgs
                if rosetta_orgs is not None
                else getattr(settings, "OAI_ROSETTA_HARVESTABLE_ORGS", ())
            )
            if code
        }
        self._path_resolver = path_resolver
        alias_cfg = code_aliases if code_aliases is not None else getattr(settings, 'OAI_INSTITUTION_CODE_ALIASES', {})
        self._code_aliases = {
            str(alias).lower().strip(): str(target).lower().strip()
            for alias, target in alias_cfg.items()
            if alias and target
        }
        label_cfg = label_aliases if label_aliases is not None else getattr(settings, 'OAI_INSTITUTION_LABEL_ALIASES', {})
        self._label_aliases = {
            str(label).lower().strip(): str(code).lower().strip()
            for label, code in label_cfg.items()
            if label and code
        }
        base_cfg = getattr(settings, 'OAI_S3_ROSETTA_BASE_PATHS', {})
        self._s3_rosetta_bases = {
            str(code).lower().strip(): str(path).rstrip('/')
            for code, path in base_cfg.items()
            if code and path
        }

    def from_project_record(self, record: ProjectRecord) -> OAIProject:
        institution_code = self._resolve_institution_code(record)

        # For KHM/HMT: Filter out digital objects from shared events to prevent cross-project contamination
        filtered_record = self._filter_shared_event_objects(record, institution_code)
        filtered_record = self._filter_flagged_digital_objects(filtered_record)
        filtered_record = self._filter_overarching_projects(filtered_record, institution_code)

        normalized_objects = self._normalize_objects(filtered_record, institution_code)

        return OAIProject(
            record=filtered_record,
            institution_code=institution_code,
            digital_objects=tuple(normalized_objects),
        )

    # Internal helpers -----------------------------------------------------

    def _filter_shared_event_objects(
        self,
        record: ProjectRecord,
        institution_code: Optional[str],
    ) -> ProjectRecord:

        if getattr(record, "ownership_filtered", False):
            return record
        """
        For KHM/HMT only: Filter out digital objects from events that are shared with other projects.

        This prevents cross-project contamination where projects sharing the same event
        (e.g., "Showcase 2007" linked to multiple projects) would incorrectly include
        each other's digital objects.

        Rule: Only include digital objects from events that are exclusively linked to this project.

        Performance: Uses a single aggregation query instead of N queries (one per event).
        """
        # Only apply filtering for KHM and HMT organizations
        if not institution_code or institution_code.lower() not in {'khm', 'hmt'}:
            return record

        # If there are no events or digital objects, nothing to filter
        events = getattr(record, 'events', None)
        digital_objects = getattr(record, 'digital_objects', None)
        if not events or not digital_objects:
            return record

        # Import here to avoid circular dependencies
        from arkumu.metadata.models.triples import Triple

        # Get the canonical event predicate URI
        event_predicate = "http://arkumu.org/data/properties/ereignis"

        # Find which events are exclusive to this project
        project_id = getattr(record, 'subject_id', None)
        if not project_id:
            return record

        # Collect all event IDs
        event_ids = [str(getattr(event, 'id', None)) for event in events if getattr(event, 'id', None)]
        if not event_ids:
            return record

        # OPTIMIZED: Single query to get all event-project relationships
        # Instead of N queries (one per event), we fetch all relationships at once
        event_project_relationships = Triple.objects.filter(
            predicate__canonical_uri=event_predicate,
            object_id__in=event_ids
        ).values('object_id', 'subject_id')

        # Build a mapping of event_id -> set of project_ids that reference it
        event_to_projects = {}
        for relationship in event_project_relationships:
            event_id = str(relationship['object_id'])
            proj_id = str(relationship['subject_id'])
            if event_id not in event_to_projects:
                event_to_projects[event_id] = set()
            event_to_projects[event_id].add(proj_id)

        # Filter to find exclusive events (only linked to this project)
        exclusive_event_ids = set()
        for event_id in event_ids:
            project_refs = event_to_projects.get(event_id, set())

            # Only include events exclusively linked to this project
            if len(project_refs) == 1 and str(project_id) in project_refs:
                exclusive_event_ids.add(event_id)
            elif len(project_refs) == 0:
                # Orphaned event - include it since it was in get_detailed_event_data
                exclusive_event_ids.add(event_id)
            else:
                logger.info(
                    "OAI: Excluding shared event %s from project %s (shared with %d other projects)",
                    event_id,
                    project_id,
                    len(project_refs) - 1,
                )

        # If no exclusive events, return record as-is (no filtering needed)
        if not exclusive_event_ids:
            return record

        # Filter the events list to only include exclusive events
        filtered_events = [
            event for event in events
            if str(getattr(event, 'id', None)) in exclusive_event_ids
        ]

        # Create a new record with filtered events
        # We need to create a new ProjectRecord instance with the filtered events
        filtered_record = replace(record, events=filtered_events)

        return filtered_record

    def _filter_flagged_digital_objects(self, record: ProjectRecord) -> ProjectRecord:
        """
        Remove digital objects that snapshot generation marked as filtered.

        Snapshot service retains the original resources for auditing via
        `filtered_digital_object_ids`. When we build OAI views we must ensure
        those resources are not exported to downstream consumers.
        """

        filtered_ids = {
            str(identifier).strip()
            for identifier in getattr(record, "filtered_digital_object_ids", []) or []
            if identifier is not None and str(identifier).strip()
        }
        if not filtered_ids:
            return record

        objects = list(getattr(record, "digital_objects", []) or [])
        if not objects:
            return record

        retained: List[ProjectDigitalObject] = []
        removed = False

        for obj in objects:
            resource_id = getattr(obj, "resource_id", None)
            if resource_id is not None and str(resource_id) in filtered_ids:
                removed = True
                continue
            retained.append(obj)

        if not removed:
            return record

        sources = getattr(record, "digital_object_sources", None)
        updated_sources = sources
        if isinstance(sources, dict):
            updated_sources = {
                key: value
                for key, value in sources.items()
                if str(key) not in filtered_ids
            }

        harvestable_flag = bool(retained)
        reference_only_flag = getattr(record, "ownership_filtered", False) and not harvestable_flag

        return replace(
            record,
            digital_objects=retained,
            digital_object_sources=updated_sources,
            harvestable=harvestable_flag,
            reference_only=reference_only_flag,
        )

    def _filter_overarching_projects(
        self,
        record: ProjectRecord,
        institution_code: Optional[str],
    ) -> ProjectRecord:
        """
        Prevent overarching HMT works (Oberwerke) from exporting digital objects.

        These umbrella records aggregate subordinate projects but should only
        reference them. They are identifiable by their slug/URI pattern
        (`hfmt-ow-*`). Any digital objects present on such records are shared
        with their sub-projects and must not be emitted to hbz.
        """

        if (institution_code or "").lower() != "hmt":
            return record

        uri = getattr(record, "uri", "") or ""
        slug = record.slug if hasattr(record, "slug") else uri.rstrip("/").split("/")[-1]
        if not slug.startswith("hfmt-ow-"):
            return record

        if not getattr(record, "digital_objects", None):
            return record

        sources = getattr(record, "digital_object_sources", None)
        updated_sources = {}
        if isinstance(sources, dict):
            updated_sources = {}

        return replace(
            record,
            digital_objects=[],
            digital_object_sources=updated_sources,
            harvestable=False,
            reference_only=True,
        )

    @staticmethod
    def _should_skip_digital_object(
        obj: ProjectDigitalObject,
        institution_code: Optional[str],
    ) -> bool:
        code = (institution_code or "").lower().strip()
        if code != "hmt":
            return False

        def _matches(candidate: Optional[str]) -> bool:
            if not candidate:
                return False
            candidate_lower = str(candidate).lower()
            return candidate_lower.endswith(".mp3")

        return any(
            _matches(candidate)
            for candidate in (
                getattr(obj, "file_name", None),
                getattr(obj, "path", None),
                getattr(obj, "storage_key", None),
            )
        )

    def _resolve_institution_code(self, record: ProjectRecord) -> Optional[str]:
        institution = getattr(record, "institution", None)
        if institution and getattr(institution, "code", None):
            code = institution.code
            if code:
                normalized = str(code).lower().strip()
                return self._code_aliases.get(normalized, normalized)

        label = getattr(institution, 'label', None) if institution else None
        if label:
            label_normalized = str(label).lower().strip()
            alias_code = self._label_aliases.get(label_normalized)
            if alias_code:
                return alias_code

        for candidate in getattr(record, "institution_codes", []) or []:
            candidate = _clean(candidate)
            if candidate:
                normalized = candidate.lower()
                return self._code_aliases.get(normalized, normalized)
        return None

    def _normalize_objects(
        self,
        record: ProjectRecord,
        institution_code: Optional[str],
    ) -> List[NormalizedDigitalObject]:
        objects: List[NormalizedDigitalObject] = []
        seen: set[str] = set()

        for obj in getattr(record, "digital_objects", []) or []:
            if self._should_skip_digital_object(obj, institution_code):
                logger.info(
                    "OAI digital object skipped: format excluded (org=%s path=%s file=%s)",
                    institution_code,
                    getattr(obj, "path", None),
                    getattr(obj, "file_name", None),
                )
                continue
            # Check if this object represents a DCP folder
            expanded_objects = self._expand_dcp_folder_if_needed(obj, institution_code)

            # If DCP folder was expanded, use all files; otherwise use single object
            objects_to_process = expanded_objects if expanded_objects else [obj]

            if expanded_objects:
                logger.info(f"Processing {len(expanded_objects)} expanded DCP files for object {getattr(obj, 'uri', 'N/A')}")

            for current_obj in objects_to_process:
                normalized = self._normalize_object(current_obj, institution_code)
                if not normalized:
                    continue
                if not self._is_harvestable(normalized):
                    logger.info(
                        "OAI digital object dropped: not harvestable (org=%s source=%s status=%s storage_key=%s rosetta_path=%s)",
                        institution_code,
                        normalized.source,
                        normalized.storage_status,
                        normalized.storage_key,
                        normalized.rosetta_path,
                    )
                    continue
                identity = normalized.preferred_location
                if identity:
                    identity_key = identity.lower()
                    if identity_key in seen:
                        if expanded_objects and '.dcp/' in identity:
                            logger.info(f"DCP file deduplicated: {identity}")
                        continue
                    seen.add(identity_key)
                objects.append(normalized)
                if expanded_objects and '.dcp/' in identity:
                    logger.info(f"DCP file added: {identity}")

        return objects

    def _normalize_object(
        self,
        obj: ProjectDigitalObject,
        institution_code: Optional[str],
    ) -> Optional[NormalizedDigitalObject]:
        original_path = _clean(getattr(obj, "path", None))
        storage_key = _clean(getattr(obj, "storage_key", None))
        if original_path:
            original_path = original_path.replace("\\", "/")
            obj.path = original_path
        if storage_key:
            storage_key = storage_key.replace("\\", "/")
            obj.storage_key = storage_key
        if not storage_key and original_path:
            storage_key = original_path
        access_url = _clean(getattr(obj, "access_url", None))
        file_name = _infer_file_name(obj)
        content_type = _guess_mime_type(obj)
        checksum_value = _clean(getattr(obj, "checksum", None))
        checksum_algorithm_attr = _clean(getattr(obj, "checksum_algorithm", None))
        provenance = _clean(getattr(obj, "checksum_provenance", None))
        fixity = parse_fixity(checksum_value)
        if checksum_algorithm_attr:
            normalized_algorithm = checksum_algorithm_attr.lower().replace('-', '')
            fixity = FixityInfo(
                normalized_algorithm,
                fixity.digest or checksum_value,
                provenance,
            )
        else:
            fixity = fixity.with_provenance(provenance)

        storage_status = _clean(getattr(obj, "storage_status", None))

        rosetta_candidates: Tuple[str, ...] = ()
        rosetta_path: Optional[str] = None

        # For S3 orgs (FUK, DET, RSH): check if file exists in dump/fixity index
        if institution_code and institution_code in self._s3_orgs:
            from arkumu.projects.services.dump_fixity_index import find_fixity

            candidates = [original_path, storage_key, access_url, file_name]
            fixity_record = find_fixity(institution_code, candidates)

            if not fixity_record:
                logger.info(
                    "OAI digital object skipped: no dump match (org=%s path=%s storage_key=%s)",
                    institution_code,
                    original_path,
                    storage_key,
                )
                return None

            # Update storage_key and fixity info from dump index
            if fixity_record.storage_key and not storage_key:
                storage_key = fixity_record.storage_key
            if fixity_record.status and not storage_status:
                storage_status = fixity_record.status
            if fixity_record.checksum_or_etag and not fixity.digest:
                fixity = parse_fixity(fixity_record.checksum_or_etag)

        if institution_code and institution_code in self._rosetta_orgs:
            resolved = self._path_resolver(
                institution_code,
                path=original_path or storage_key,
                file_name=file_name,
            )
            if resolved:
                rosetta_candidates = tuple(resolved)
                rosetta_path = resolved[0]
            else:
                logger.info(
                    "OAI Rosetta object skipped: no candidate path (org=%s path=%s storage_key=%s file=%s)",
                    institution_code,
                    original_path,
                    storage_key,
                    file_name,
                )
                return None

        if not rosetta_path and institution_code and institution_code in self._s3_rosetta_bases and storage_key:
            base = self._s3_rosetta_bases[institution_code]
            candidate = f"{base}/{storage_key.lstrip('/')}"
            rosetta_path = candidate
            rosetta_candidates = (candidate,)

        if not rosetta_path and original_path and original_path.startswith("/rosetta/"):
            rosetta_candidates = (original_path,)
            rosetta_path = original_path

        source = "unknown"
        if rosetta_path:
            source = "rosetta"
        elif institution_code and institution_code in self._s3_orgs:
            source = "s3"

        size_bytes = getattr(obj, "size_bytes", None)
        if isinstance(size_bytes, str) and size_bytes.isdigit():
            size_bytes = int(size_bytes)

        uuid_value = _clean(getattr(obj, "uuid", None))
        genesis_type = _clean(getattr(obj, "genesis_type", None))
        media_type = _clean(getattr(obj, "media_type", None))
        significant_de = _clean(getattr(obj, "significant_properties_de", None))
        significant_en = _clean(getattr(obj, "significant_properties_en", None))
        license_info = getattr(obj, "license", None)
        if license_info and not isinstance(license_info, ProjectDigitalObjectLicense):
            try:
                license_info = ProjectDigitalObjectLicense(**license_info)  # type: ignore[call-arg]
            except TypeError:
                license_info = None

        return NormalizedDigitalObject(
            original_path=original_path,
            storage_key=storage_key,
            rosetta_path=rosetta_path,
            rosetta_candidates=rosetta_candidates,
            file_name=file_name,
            content_type=content_type,
            size_bytes=size_bytes,
            checksum=fixity.digest,
            checksum_algorithm=fixity.algorithm,
            checksum_provenance=fixity.provenance or (source if source in {"rosetta", "s3"} else None),
            access_url=access_url,
            storage_status=storage_status,
            source=source,
            uuid=uuid_value,
            genesis_type=genesis_type,
            media_type=media_type,
            significant_properties_de=significant_de,
            significant_properties_en=significant_en,
            license=license_info,
        )

    def _expand_dcp_folder_if_needed(
        self,
        obj: ProjectDigitalObject,
        institution_code: Optional[str],
    ) -> Optional[List[ProjectDigitalObject]]:
        """
        Check if digital object represents a DCP folder and expand to all files.
        Returns None if not a DCP folder, or list of ProjectDigitalObject for all files in folder.
        """
        # Only check for KHM institution
        if institution_code != 'khm':
            return None

        # Import here to avoid circular dependencies
        from arkumu.metadata.models import Triple

        # Get the digital object URI
        obj_uri = getattr(obj, 'uri', None)
        if not obj_uri:
            return None

        # Query for the DCP folder property
        try:
            dcp_folder_triples = Triple.objects.filter(
                subject__uri=obj_uri,
                predicate__uri='http://arkumu.org/data/khm/properties/dateipfad-dcp-ordner'
            ).select_related('object')

            if not dcp_folder_triples.exists():
                return None

            # Get the folder path
            dcp_triple = dcp_folder_triples.first()
            folder_path = dcp_triple.object.value if dcp_triple.object else None

            if not folder_path:
                return None

        except Exception as e:
            logger.error(f"Error querying DCP folder property: {e}")
            return None

        # Clean and normalize the folder path
        folder_path = folder_path.strip().replace('\\', '/')

        # Extract just the folder name (last component of the path)
        # E.g., "/Volumes/.../Deflower_de_UT_170529.dcp/" -> "Deflower_de_UT_170529.dcp"
        folder_path = folder_path.rstrip('/')
        folder_name = folder_path.split('/')[-1] if '/' in folder_path else folder_path

        logger.info(f"Looking for DCP folder: {folder_name} (from path: {folder_path})")

        # Load the path index and find all files in this folder
        path_index_file = getattr(settings, 'OAI_EXTERNAL_PATH_FILES', {}).get('khm')
        if not path_index_file:
            logger.warning("No path index file configured for KHM")
            return None

        try:
            with open(path_index_file, 'r', encoding='utf-8') as f:
                all_paths = [line.strip() for line in f if line.strip()]
        except (IOError, OSError) as e:
            logger.error(f"Failed to read path index: {e}")
            return None

        # Find all files that are direct children of this folder
        matching_files = []
        for path in all_paths:
            # Normalize path for comparison
            normalized_path = path.replace('\\', '/')

            # Check if the folder name appears in the path
            if folder_name not in normalized_path:
                continue

            # Find the position of the folder in the path
            folder_idx = normalized_path.find(folder_name)
            if folder_idx == -1:
                continue

            # Get the part after the folder name
            after_folder = normalized_path[folder_idx + len(folder_name):]

            # Check if this is a direct child file (starts with / and has no more /)
            if after_folder.startswith('/'):
                filename = after_folder[1:]  # Remove leading /
                if filename and '/' not in filename:  # No subdirectories
                    matching_files.append(path)

        if not matching_files:
            logger.info(f"No files found in DCP folder: {folder_name}")
            return None

        # Create ProjectDigitalObject instances for each file
        expanded_objects = []
        for file_path in matching_files:
            # Create a new object based on the original
            new_obj = ProjectDigitalObject(
                path=file_path,
                uri=obj.uri,  # Same logical entity
            )

            # Copy other relevant attributes from the original object
            # Don't copy path-specific attributes like file_name, storage_key
            for attr in ['content_type', 'size_bytes', 'checksum',
                         'checksum_algorithm', 'checksum_provenance',
                         'access_url', 'storage_status', 'created_at', 'updated_at',
                         'license', 'uuid', 'genesis_type', 'media_type',
                         'significant_properties_de', 'significant_properties_en']:
                if hasattr(obj, attr):
                    value = getattr(obj, attr)
                    if value is not None:
                        setattr(new_obj, attr, value)

            expanded_objects.append(new_obj)

        logger.info(f"Expanded DCP folder {folder_name} to {len(expanded_objects)} files")
        return expanded_objects

    @staticmethod
    def _is_harvestable(obj: NormalizedDigitalObject) -> bool:
        """Return True only for objects that meet dissemination rules."""

        if obj.source == "rosetta":
            return bool(obj.rosetta_path)

        if obj.source == "s3":
            if not obj.storage_key:
                return False
            key_normalized = obj.storage_key.lower()
            if key_normalized.startswith("metadata/"):
                return False
            status = _status_token(obj.storage_status)
            if status is None:
                return True
            return status in HARVESTABLE_STORAGE_STATUSES

        if obj.storage_key or obj.rosetta_path:
            return True

        return False
