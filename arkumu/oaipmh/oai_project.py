"""Domain models that adapt `ProjectRecord` instances for OAI-PMH exports."""

from __future__ import annotations

from dataclasses import dataclass
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
            # Fall back to final URL/path segment when Path parsing fails
            name = candidate.split("/")[-1]
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
        normalized_objects = self._normalize_objects(record, institution_code)

        return OAIProject(
            record=record,
            institution_code=institution_code,
            digital_objects=tuple(normalized_objects),
        )

    # Internal helpers -----------------------------------------------------

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
            normalized = self._normalize_object(obj, institution_code)
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
                    continue
                seen.add(identity_key)
            objects.append(normalized)

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
        if storage_key:
            storage_key = storage_key.replace("\\", "/")
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

        dump_matched = getattr(obj, "_dump_matched", None)
        if (
            institution_code
            and institution_code in self._s3_orgs
            and dump_matched is False
        ):
            logger.info(
                "OAI digital object skipped: no dump match (org=%s path=%s storage_key=%s)",
                institution_code,
                original_path,
                storage_key,
            )
            return None

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
