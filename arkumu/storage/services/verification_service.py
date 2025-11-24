from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Iterator, List, Optional

from botocore.exceptions import ClientError
from django.db.models import Q
from django.utils import timezone

from arkumu.storage.models import S3FileObject
from arkumu.storage.services.base_storage_service import BaseStorageService

logger = logging.getLogger(__name__)

_MISSING_CODES = {"404", "NoSuchKey", "NotFound"}


@dataclass(slots=True)
class VerificationResult:
    success: bool
    missing: bool = False
    error: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    file_object: Optional[S3FileObject] = None


def verify_single_object(
    bucket_name: str,
    key: str,
    organization: Optional[str] = None,
    *,
    missing_status: str = "missing",
    dry_run: bool = False,
) -> VerificationResult:
    """
    Perform a head_object call and reconcile the corresponding S3FileObject row.
    """
    normalized_key = _normalize_key(key)
    storage_service = BaseStorageService()

    try:
        head = storage_service.s3_client.head_object(Bucket=bucket_name, Key=normalized_key)
    except ClientError as exc:
        error_code = exc.response.get("Error", {}).get("Code")
        if error_code in _MISSING_CODES:
            file_obj = None
            if not dry_run:
                file_obj = _mark_missing(normalized_key, organization, missing_status=missing_status)
            logger.warning("S3 object missing during verification: %s/%s", bucket_name, normalized_key)
            return VerificationResult(success=False, missing=True, file_object=file_obj, error=str(exc))
        logger.error("verify_single_object failed for %s/%s: %s", bucket_name, normalized_key, exc)
        return VerificationResult(success=False, missing=False, error=str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.exception("Unexpected error verifying %s/%s", bucket_name, normalized_key)
        return VerificationResult(success=False, missing=False, error=str(exc))

    file_obj = None
    if not dry_run:
        file_obj = _upsert_file_object(
            normalized_key,
            head,
            bucket_name,
            organization or bucket_name,
        )

    return VerificationResult(
        success=True,
        metadata=head,
        file_object=file_obj,
    )


def iter_objects_under_prefix(bucket_name: str, prefix: str) -> Iterator[str]:
    """
    Yield keys under the provided prefix using list_objects_v2 pagination.
    """
    normalized_prefix = _normalize_prefix(prefix)
    storage_service = BaseStorageService()
    paginator = storage_service.s3_client.get_paginator("list_objects_v2")

    try:
        for page in paginator.paginate(Bucket=bucket_name, Prefix=normalized_prefix):
            for obj in page.get("Contents", []):
                key = obj.get("Key")
                if key and not key.endswith("/"):
                    yield key
    except ClientError as exc:
        logger.error(
            "Failed to iterate objects for %s prefix %s: %s",
            bucket_name,
            normalized_prefix,
            exc,
        )


def annotate_verified_flags(contents: Iterable[Dict[str, Any]], organization: Optional[str] = None) -> None:
    """
    Mutate bucket listing entries so file rows know whether they have been verified.
    """
    file_keys: List[str] = [
        item.get("path", "")
        for item in contents
        if isinstance(item, dict) and item.get("type") == "file" and item.get("path")
    ]

    if not file_keys:
        return

    query = Q(s3_key__in=file_keys) & Q(status__in=["completed", "verified"])
    if organization:
        query &= (
            Q(organization__iexact=organization)
            | Q(session__s3_bucket__iexact=organization)
        )

    verified_keys = set(
        S3FileObject.objects.filter(query).values_list("s3_key", flat=True)
    )

    for item in contents:
        if isinstance(item, dict) and item.get("type") == "file":
            item["verified"] = item.get("path") in verified_keys


def _normalize_key(key: str) -> str:
    return (key or "").lstrip("/")


def _normalize_prefix(prefix: str) -> str:
    value = (prefix or "").lstrip("/")
    if value and not value.endswith("/"):
        value = f"{value}/"
    return value


def _upsert_file_object(
    key: str,
    head: Dict[str, Any],
    bucket_name: str,
    organization: str,
) -> S3FileObject:
    qs = S3FileObject.objects.filter(s3_key=key)
    qs = qs.filter(
        Q(organization__iexact=organization)
        | Q(session__s3_bucket__iexact=organization)
        | Q(organization__iexact=bucket_name)
    )

    file_obj = qs.order_by("-updated_at").first()
    file_name = _derive_file_name(key)
    base_folder = _derive_base_folder(key)
    if not file_obj:
        file_obj = S3FileObject(
            s3_key=key,
            organization=organization,
            file_name=file_name,
            base_folder=base_folder,
        )

    updates: List[str] = []
    content_length = head.get("ContentLength")
    etag = head.get("ETag")
    content_type = head.get("ContentType")
    last_modified = head.get("LastModified") or timezone.now()

    if content_length is not None and file_obj.file_size_bytes != content_length:
        file_obj.file_size_bytes = content_length
        updates.append("file_size_bytes")

    if content_type and file_obj.content_type != content_type:
        file_obj.content_type = content_type
        updates.append("content_type")

    if etag and file_obj.etag != etag:
        file_obj.etag = etag
        updates.append("etag")

    if file_obj.base_folder != base_folder:
        file_obj.base_folder = base_folder
        updates.append("base_folder")

    if file_obj.file_name != file_name:
        file_obj.file_name = file_name
        updates.append("file_name")

    if file_obj.organization != organization:
        file_obj.organization = organization
        updates.append("organization")

    if not file_obj.upload_completed_at or file_obj.upload_completed_at != last_modified:
        file_obj.upload_completed_at = last_modified
        updates.append("upload_completed_at")

    if file_obj.status != "verified":
        file_obj.status = "verified"
        updates.append("status")

    if file_obj.error_message:
        file_obj.error_message = ""
        updates.append("error_message")

    if file_obj.pk is None:
        file_obj.save()
    elif updates:
        updates.append("updated_at")
        file_obj.save(update_fields=updates)

    return file_obj


def _mark_missing(
    key: str,
    organization: Optional[str],
    *,
    missing_status: str,
) -> Optional[S3FileObject]:
    qs = S3FileObject.objects.filter(s3_key=key)

    if organization:
        qs = qs.filter(
            Q(organization__iexact=organization)
            | Q(session__s3_bucket__iexact=organization)
        )

    file_obj = qs.order_by("-updated_at").first()

    if file_obj:
        fields: List[str] = []
        if file_obj.status != missing_status:
            file_obj.status = missing_status
            fields.append("status")
        if file_obj.error_message != "File missing in S3":
            file_obj.error_message = "File missing in S3"
            fields.append("error_message")
        if fields:
            fields.append("updated_at")
            file_obj.save(update_fields=fields)

    return file_obj


def _derive_file_name(key: str) -> str:
    return key.rstrip("/").split("/")[-1] if key else ""


def _derive_base_folder(key: str) -> str:
    if "/" not in key:
        return ""
    return key.split("/", 1)[0]
