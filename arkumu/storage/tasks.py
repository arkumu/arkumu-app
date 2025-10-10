"""Storage-related background tasks."""

import logging
from typing import Any, Optional

from huey.contrib.djhuey import db_task
from django.apps import apps
from django.db import models
from django.utils import timezone

try:
    from huey.contrib.djhuey import db_periodic_task, crontab
    HUEY_PERIODIC_AVAILABLE = True
except ImportError:
    HUEY_PERIODIC_AVAILABLE = False

logger = logging.getLogger(__name__)


@db_task(retries=3, retry_delay=30)
def verify_upload_session(session_id: str) -> None:
    """Verify every file in an async upload session after uploads finish."""
    from arkumu.storage.models.upload_tracking import AsyncUploadSession, AsyncUploadFile
    from arkumu.storage.models import S3FileObject
    from arkumu.storage.services.bucket_service import BucketService
    from arkumu.storage.services.upload_service import UploadService

    try:
        session = AsyncUploadSession.objects.get(id=session_id)
    except AsyncUploadSession.DoesNotExist:
        logger.warning("⚠️ verify_upload_session: session %s not found", session_id)
        return

    upload_service = UploadService()
    bucket_service = BucketService()
    bucket_name = bucket_service.get_organization_bucket(session.organization)

    failures = 0

    from collections import defaultdict
    from botocore.exceptions import ClientError

    prefix_groups: dict[str, list[AsyncUploadFile]] = defaultdict(list)

    pending_files = session.files.exclude(status='completed')
    if not pending_files.exists():
        logger.info("ℹ️ verify_upload_session: session %s already completed", session_id)
        session.status = 'completed'
        session.error_message = ''
        session.completed_at = timezone.now()
        session.save(update_fields=['status', 'error_message', 'completed_at', 'updated_at'])
        trigger_ui_refresh(str(session.id), session.organization)
        return

    for upload_file in pending_files:
        prefix = upload_file.s3_key.rpartition('/')[0]
        prefix_groups[prefix].append(upload_file)

    s3_client = bucket_service.base_s3_service.s3_client

    for prefix, files in prefix_groups.items():
        s3_prefix = prefix + '/' if prefix else ''
        objects_by_key: dict[str, dict[str, Any]] = {}

        try:
            paginator = s3_client.get_paginator('list_objects_v2')
            for page in paginator.paginate(Bucket=bucket_name, Prefix=s3_prefix):
                for obj in page.get('Contents', []):
                    objects_by_key[obj['Key']] = obj
        except ClientError as exc:
            logger.error(
                "❌ verify_upload_session: failed to list prefix '%s' in %s: %s",
                s3_prefix or '<root>',
                bucket_name,
                exc,
            )

        for upload_file in files:
            try:
                obj_meta = objects_by_key.get(upload_file.s3_key)

                etag = None

                if obj_meta is None:
                    file_info = upload_service.get_file_info(upload_file.s3_key, bucket_name=bucket_name)
                    if not file_info.get('success'):
                        raise ValueError(f"File {upload_file.s3_key} not found in storage")

                    resolved_size = file_info.get('file_size', upload_file.file_size)
                    resolved_completed_at = file_info.get('last_modified') or timezone.now()
                    etag = file_info.get('etag')
                else:
                    resolved_size = obj_meta.get('Size', upload_file.file_size)
                    resolved_completed_at = obj_meta.get('LastModified') or timezone.now()
                    etag = obj_meta.get('ETag')

                if S3FileObject.objects.filter(s3_key=upload_file.s3_key).exists():
                    logger.info(
                        "ℹ️ verify_upload_session: creating additional S3FileObject for duplicate key %s",
                        upload_file.s3_key,
                    )

                s3_file_object = S3FileObject.objects.create(
                    s3_key=upload_file.s3_key,
                    file_name=upload_file.filename,
                    file_size_bytes=resolved_size,
                    content_type=upload_file.content_type,
                    base_folder=session.base_folder,
                    organization=session.organization,
                    etag=etag,
                    status='completed',
                    upload_completed_at=resolved_completed_at,
                )

                upload_file.status = 'completed'
                upload_file.upload_completed_at = resolved_completed_at
                upload_file.s3_file_object = s3_file_object
                upload_file.error_message = ''
                upload_file.save(update_fields=['status', 'upload_completed_at', 's3_file_object', 'error_message', 'updated_at'])

            except Exception as exc:  # noqa: BLE001
                failures += 1
                upload_file.mark_failed(str(exc))
                logger.error("❌ verify_upload_session: %s", exc)

    session.completed_files = session.files.filter(status='completed').count()
    session.failed_files = session.files.filter(status='failed').count()

    if failures:
        session.status = 'failed'
        session.error_message = f"{failures} file(s) failed verification"
    else:
        session.status = 'completed'
        session.error_message = ''

    session.completed_at = timezone.now()
    session.save(update_fields=['status', 'error_message', 'completed_files', 'failed_files', 'completed_at', 'updated_at'])

    trigger_ui_refresh(str(session.id), session.organization)


@db_task(retries=2, retry_delay=15)
def trigger_ui_refresh(session_id: str, organization: str) -> None:
    """Placeholder task for future UI refresh hooks."""
    logger.info("🔄 UI_REFRESH: Session %s for %s", session_id, organization)


if HUEY_PERIODIC_AVAILABLE:
    @db_periodic_task(crontab(minute='*/5'))
    def verify_pending_sessions():
        """Flag completed uploads so staff can manually trigger verification."""
        from arkumu.storage.models.upload_tracking import AsyncUploadSession

        pending_sessions = AsyncUploadSession.objects.filter(status='uploading')
        for session in pending_sessions:
            remaining = session.files.exclude(status__in=['uploaded', 'completed', 'failed']).exists()
            if remaining:
                continue

            if session.status != 'awaiting_verification':
                session.status = 'awaiting_verification'
                session.completed_files = session.files.filter(status='completed').count()
                session.failed_files = session.files.filter(status='failed').count()
                session.save(update_fields=['status', 'completed_files', 'failed_files', 'updated_at'])
                logger.info(
                    "🟡 verify_pending_sessions: session %s awaiting manual verification",
                    session.id,
                )
                trigger_ui_refresh(str(session.id), session.organization)

    @db_periodic_task(crontab(hour='*/6'))
    def flag_missing_s3_files():
        """Mark linked S3FileObjects as failed if they no longer exist in S3."""

        S3FileObject = apps.get_model('storage', 'S3FileObject')

        qs = (
            S3FileObject.objects
            .filter(related_resource__isnull=False)
            .exclude(status__in=['failed'])
            .order_by('-updated_at')
        )

        reviewed = 0
        missing = 0

        for obj in qs.iterator():
            reviewed += 1
            if obj.exists_in_s3():
                continue

            missing += 1
            obj.status = 'failed'
            obj.error_message = 'File missing in S3'
            obj.save(update_fields=['status', 'error_message', 'updated_at'])
            logger.warning("❌ Missing in S3: %s (resource=%s)", obj.s3_key, obj.related_resource_id)

            if missing >= 100:
                break

        if reviewed:
            logger.info(
                "🔍 flag_missing_s3_files: reviewed %s file(s), marked %s missing",
                reviewed,
                missing,
            )


@db_task(retries=1, retry_delay=30)
def recalculate_s3_checksums(organization: str | None = None, missing_only: bool = True, limit: int | None = None) -> None:
    """Recalculate checksums for S3 files, optionally scoped to an organization."""

    S3FileObject = apps.get_model('storage', 'S3FileObject')

    queryset = S3FileObject.objects.filter(status__in=['completed', 'verified'])

    if organization:
        queryset = queryset.filter(organization=organization)

    if missing_only:
        queryset = queryset.filter(models.Q(sha256_checksum="") | models.Q(sha256_checksum__isnull=True))

    queryset = queryset.order_by('-updated_at')

    if limit is not None:
        queryset = queryset[:limit]

    total = queryset.count()
    logger.info(
        "🔁 checksum: recalculating for %s file(s) %s",
        total,
        f"in {organization}" if organization else "(all orgs)",
    )

    processed = 0
    updated = 0

    from arkumu.storage.services.base_storage_service import BaseStorageService

    storage_service = BaseStorageService()

    for obj in queryset.iterator():
        processed += 1

        etag = obj._refresh_etag(storage_service)
        if not etag:
            logger.warning("⚠️ checksum: no ETag available for %s", obj.s3_key)
            continue

        stripped_etag = etag.strip('"')

        if obj.is_multipart_upload(etag):
            checksum = obj.calculate_checksum(storage_service, algorithm='sha256')
            if checksum:
                updated += 1
                logger.debug("✅ checksum: sha256 %s => %s", obj.s3_key, checksum[:16])
            else:
                logger.warning("⚠️ checksum: failed to calculate sha256 for %s", obj.s3_key)
        else:
            obj._store_checksum('md5', stripped_etag)
            updated += 1
            logger.debug("✅ checksum: md5 %s => %s", obj.s3_key, stripped_etag)

    logger.info(
        "🔁 checksum: processed %s file(s); updated %s checksum(s)",
        processed,
        updated,
    )
