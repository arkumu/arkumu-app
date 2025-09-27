"""Storage-related background tasks."""

import logging
from typing import Optional

from huey.contrib.djhuey import db_task
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

    for upload_file in session.files.all():
        if upload_file.status == 'completed':
            continue

        try:
            file_info = upload_service.get_file_info(upload_file.s3_key, bucket_name=bucket_name)
            if not file_info.get('success'):
                raise ValueError(f"File {upload_file.s3_key} not found in storage")

            resolved_size = file_info.get('file_size', upload_file.file_size)
            resolved_completed_at = timezone.now()

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
        """Ensure sessions that finished uploading still get verified."""
        from arkumu.storage.models.upload_tracking import AsyncUploadSession

        pending_sessions = AsyncUploadSession.objects.filter(status='uploading')
        for session in pending_sessions:
            remaining = session.files.exclude(status__in=['uploaded', 'completed', 'failed']).exists()
            if not remaining:
                logger.info("⏱️ Scheduling verification for session %s", session.id)
                session.mark_processing()
                verify_upload_session(str(session.id))
