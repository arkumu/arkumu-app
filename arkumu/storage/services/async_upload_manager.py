"""Async upload management helpers for generating presigned URLs and tracking sessions."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from django.utils import timezone

from arkumu.storage.models.upload_tracking import AsyncUploadFile, AsyncUploadSession
from arkumu.storage.services.bucket_service import BucketService
from arkumu.storage.services.upload_service import UploadService

logger = logging.getLogger(__name__)


@dataclass
class PresignedUploadBatchResult:
    """Container for batch presigned URL results."""

    session: AsyncUploadSession
    uploads: List[Dict[str, Any]]
    errors: List[Dict[str, Any]]
    created_files: List[AsyncUploadFile]

    @property
    def success(self) -> bool:
        return not self.errors and bool(self.uploads)


class AsyncUploadManager:
    """Coordinate async upload session setup and presigned URL generation."""

    def __init__(self) -> None:
        self.upload_service = UploadService()
        self.bucket_service = BucketService()

    def prepare_presigned_uploads(
        self,
        *,
        user,
        files: List[Dict[str, Any]],
        folder: str = "",
        organization: Optional[str] = None,
        session_id: Optional[str] = None,
        total_files_override: Optional[int] = None,
    ) -> PresignedUploadBatchResult:
        """Prepare an async upload session and generate presigned URLs for files."""

        if not files:
            raise ValueError("No files supplied for presigned upload generation")

        organization = organization or self._derive_organization_from_folder(folder)
        base_folder = self._derive_base_folder(folder)
        bucket_name = self._resolve_bucket(organization)

        session = self._get_or_create_session(
            user=user,
            session_id=session_id,
            organization=organization,
            base_folder=base_folder,
            total_files_override=total_files_override,
            incoming_file_count=len(files),
        )

        uploads: List[Dict[str, Any]] = []
        errors: List[Dict[str, Any]] = []
        created_files: List[AsyncUploadFile] = []

        for file_info in files:
            name = file_info.get("name") or file_info.get("filename")
            if not name:
                errors.append({
                    "filename": name or "<unknown>",
                    "errors": ["File name is required"],
                })
                continue

            relative_path = file_info.get("relativePath", name)
            file_size = int(file_info.get("size", 0) or 0)
            content_type = file_info.get("type", "application/octet-stream")

            logger.info(
                "Processing upload candidate name=%s relative=%s size=%s type=%s",
                name,
                relative_path,
                file_size,
                content_type,
            )

            validation = self.upload_service.validate_upload_request(
                file_name=name,
                file_size=file_size,
                content_type=content_type,
                user_id=getattr(user, "id", None),
            )

            if not validation["valid"]:
                allow_zero_byte = (
                    file_size == 0
                    and len(validation["errors"]) == 1
                    and "File size must be greater than 0" in validation["errors"]
                )
                if allow_zero_byte:
                    validation = {
                        **validation,
                        "valid": True,
                        "errors": [],
                        "warnings": validation.get("warnings", []) + ["Zero-byte file allowed"],
                    }
                else:
                    errors.append({
                        "filename": name,
                        "errors": validation["errors"],
                    })
                    continue

            full_path = f"{folder}/{relative_path}" if folder else relative_path
            directory = os.path.dirname(full_path) or None
            file_basename = os.path.basename(full_path)

            if validation["should_use_multipart"]:
                init_result = self.upload_service.initiate_multipart_upload(
                    file_name=file_basename,
                    content_type=content_type,
                    path_prefix=directory,
                    organization=organization,
                )

                if not init_result.get("success"):
                    errors.append({
                        "filename": name,
                        "errors": [
                            init_result.get(
                                "error",
                                "Multipart upload initialization failed",
                            )
                        ],
                    })
                    continue

                upload_file = AsyncUploadFile.objects.create(
                    session=session,
                    filename=name,
                    s3_key=init_result["s3_key"],
                    file_size=file_size,
                    content_type=content_type,
                    relative_path=relative_path,
                    status="pending",
                    presigned_url="",
                    presigned_fields={},
                )
                created_files.append(upload_file)

                uploads.append(
                    {
                        "filename": name,
                        "type": "multipart",
                        "upload_id": init_result.get("upload_id"),
                        "s3_key": init_result["s3_key"],
                        "filesize": file_size,
                        "filetype": content_type,
                        "folder": directory,
                        "organization": organization,
                        "base_folder": base_folder,
                        "upload_file_id": str(upload_file.id),
                        "relativePath": relative_path,
                    }
                )
                continue

            presigned_result = self.upload_service.generate_presigned_upload_url(
                file_name=file_basename,
                content_type=content_type,
                path_prefix=directory,
                max_file_size=file_size,
                bucket_name=bucket_name,
            )

            if not presigned_result.get("success"):
                errors.append(
                    {
                        "filename": name,
                        "errors": [
                            presigned_result.get(
                                "error", "Presigned URL generation failed"
                            )
                        ],
                    }
                )
                continue

            upload_file = AsyncUploadFile.objects.create(
                session=session,
                filename=name,
                s3_key=presigned_result["key"],
                file_size=file_size,
                content_type=content_type,
                relative_path=relative_path,
                status="pending",
                presigned_url=presigned_result.get("url", ""),
                presigned_fields=presigned_result.get("fields", {}),
            )
            created_files.append(upload_file)

            uploads.append(
                {
                    "filename": name,
                    "type": presigned_result.get("type", "single"),
                    "url": presigned_result["url"],
                    "method": presigned_result.get("method", "PUT"),
                    "fields": presigned_result.get("fields", {}),
                    "s3_key": presigned_result["key"],
                    "filesize": file_size,
                    "filetype": content_type,
                    "max_file_size": presigned_result.get("max_file_size"),
                    "upload_file_id": str(upload_file.id),
                    "relativePath": relative_path,
                }
            )

        if uploads:
            session.status = "presigned_generated"
            session.updated_at = timezone.now()
            session.save(update_fields=["status", "updated_at"])

        return PresignedUploadBatchResult(
            session=session,
            uploads=uploads,
            errors=errors,
            created_files=created_files,
        )

    # Helpers -----------------------------------------------------------------

    def _derive_base_folder(self, folder: str) -> str:
        if not folder:
            return "data"
        base = folder.split("/", 1)[0].strip()
        return base or "data"

    def _derive_organization_from_folder(self, folder: str) -> str:
        if not folder:
            return ""
        parts = [part for part in folder.split("/") if part]
        if len(parts) >= 2:
            return parts[1]
        return parts[0] if parts else ""

    def _resolve_bucket(self, organization: Optional[str]) -> Optional[str]:
        if not organization:
            return None
        try:
            return self.bucket_service.get_organization_bucket(organization)
        except Exception as exc:
            logger.warning(
                "Unable to resolve bucket for organization %s: %s",
                organization,
                exc,
            )
            return None

    def _get_or_create_session(
        self,
        *,
        user,
        session_id: Optional[str],
        organization: Optional[str],
        base_folder: str,
        total_files_override: Optional[int],
        incoming_file_count: int,
    ) -> AsyncUploadSession:
        if session_id:
            try:
                session = AsyncUploadSession.objects.get(id=session_id, user=user)
            except AsyncUploadSession.DoesNotExist as exc:
                raise ValueError("Invalid upload session") from exc
            session.organization = organization or session.organization
            session.base_folder = base_folder or session.base_folder
            if total_files_override is not None:
                session.total_files = total_files_override
            elif incoming_file_count:
                session.total_files = incoming_file_count
            session.save(update_fields=["organization", "base_folder", "total_files", "updated_at"])
            return session

        total_files = total_files_override if total_files_override is not None else incoming_file_count
        return AsyncUploadSession.objects.create(
            user=user,
            total_files=total_files,
            organization=organization or "",
            base_folder=base_folder,
        )
