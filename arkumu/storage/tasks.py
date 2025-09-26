"""
Storage Tasks

Huey background tasks for file operations, including async upload monitoring.
"""

import logging
import time
from huey.contrib.djhuey import db_task
from django.utils import timezone

try:
    from huey.contrib.djhuey import db_periodic_task, crontab
    HUEY_PERIODIC_AVAILABLE = True
except ImportError:
    HUEY_PERIODIC_AVAILABLE = False

logger = logging.getLogger(__name__)


@db_task(retries=1, retry_delay=30)
def assemble_file_task(resumable_upload_id: int):
    """
    Background task to assemble uploaded chunks into final file.
    This runs asynchronously to avoid blocking the upload response.
    """
    try:
        # Import inside function to avoid circular imports
        from arkumu.storage.models import ResumableUploadSession
        
        resumable_upload = ResumableUploadSession.objects.get(id=resumable_upload_id)
        logger.info(f"🔧 BACKGROUND TASK: Starting assembly for {resumable_upload.original_filename}")
        
        # Import here to avoid circular imports
        from arkumu.storage.views.resumable_upload_views import _assemble_file
        _assemble_file(resumable_upload)
        
        logger.info(f"✅ BACKGROUND TASK: Assembly completed for {resumable_upload.original_filename}")
    except Exception as e:
        logger.error(f"❌ BACKGROUND TASK: Assembly failed for upload {resumable_upload_id}: {str(e)}")
        # Try to mark the upload as failed if we can still find it
        try:
            from arkumu.storage.models import ResumableUploadSession
            resumable_upload = ResumableUploadSession.objects.get(id=resumable_upload_id)
            if hasattr(resumable_upload, 'mark_failed'):
                resumable_upload.mark_failed(f"Assembly failed: {str(e)}")
        except:
            pass


# Async Upload Tasks

# DISABLED: Replaced with direct event trigger in mark_file_uploaded view
# @db_task(retries=3, retry_delay=60)
def monitor_upload_session_DISABLED(session_id: str):
    """
    DISABLED: This polling task is replaced with direct triggers.
    Now mark_file_uploaded directly triggers verification when all files uploaded.
    """
    try:
        from arkumu.storage.models.upload_tracking import AsyncUploadSession
        
        session = AsyncUploadSession.objects.get(id=session_id)
        logger.info(f"🔍 MONITOR: Checking upload session {session_id}")
        
        # Check if all files have been reported as uploaded
        total_files = session.files.count()
        uploaded_files = session.files.filter(status='uploaded').count()
        
        if uploaded_files == total_files and total_files > 0:
            logger.info(f"✅ MONITOR: All {total_files} files uploaded, starting processing")
            session.mark_processing()
            
            # Trigger processing for all uploaded files
            for upload_file in session.files.filter(status='uploaded'):
                # In Django Huey, call tasks directly (no .delay() needed)
                verify_and_process_upload(str(upload_file.id))
            
        else:
            logger.info(f"⏳ MONITOR: {uploaded_files}/{total_files} files uploaded, continuing monitoring")
            
            # Re-schedule monitoring if not complete and session is recent
            if session.created_at > timezone.now() - timezone.timedelta(hours=2):
                # Schedule next check (Django Huey uses schedule() method)
                monitor_upload_session.schedule(args=(session_id,), delay=30)
            else:
                logger.warning(f"⚠️ MONITOR: Session {session_id} timed out after 2 hours")
                session.mark_failed("Session timed out - files not uploaded within 2 hours")
                
    except Exception as e:
        logger.error(f"❌ MONITOR: Error monitoring session {session_id}: {str(e)}")


@db_task(retries=3, retry_delay=30)
def verify_and_process_upload(file_id: str):
    """
    Verify file exists in S3 and create S3FileObject record.
    This runs after client reports upload completion.
    """
    try:
        from arkumu.storage.models.upload_tracking import AsyncUploadFile
        from arkumu.storage.models import S3FileObject
        from arkumu.storage.services.bucket_service import BucketService
        
        upload_file = AsyncUploadFile.objects.get(id=file_id)
        logger.info(f"🔍 VERIFY: Checking S3 for file {upload_file.filename}")
        
        upload_file.mark_processing()
        
        # Verify file exists in S3 with retry for eventual consistency
        from arkumu.storage.services.upload_service import UploadService
        from arkumu.storage.services.bucket_service import BucketService
        import time
        
        # Get the organization bucket name
        bucket_service = BucketService()
        bucket_name = bucket_service.get_organization_bucket(upload_file.session.organization)
        
        upload_service = UploadService()
        
        # Retry logic for S3 eventual consistency
        max_retries = 3
        for attempt in range(max_retries):
            file_info = upload_service.get_file_info(upload_file.s3_key, bucket_name=bucket_name)
            
            if file_info and file_info.get('success', False):
                logger.info(f"✅ File verified in S3 on attempt {attempt + 1}: {upload_file.s3_key}")
                break
            
            if attempt < max_retries - 1:
                wait_time = (attempt + 1) * 2  # 2s, 4s, 6s
                logger.warning(f"⏳ File not found in S3 (attempt {attempt + 1}), retrying in {wait_time}s: {upload_file.s3_key}")
                time.sleep(wait_time)
            else:
                raise Exception(f"File not found in S3 after {max_retries} attempts: {upload_file.s3_key}")
        
        # Create S3FileObject record
        s3_file_object = S3FileObject.objects.create(
            s3_key=upload_file.s3_key,
            file_name=upload_file.filename,
            file_size_bytes=file_info.get('file_size', upload_file.file_size),
            content_type=upload_file.content_type,
            status='completed',
            upload_completed_at=timezone.now()
        )
        
        upload_file.mark_completed(s3_file_object)
        logger.info(f"✅ VERIFY: File {upload_file.filename} verified and processed")
        
        # Check session completion synchronously (not as a separate task)
        session = upload_file.session
        total_files = session.files.count()
        completed_files = session.files.filter(status='completed').count()
        failed_files = session.files.filter(status='failed').count()
        
        logger.debug(f"📊 SESSION: {completed_files}/{total_files} files completed, {failed_files} failed")
        
        # Update session counts
        session.completed_files = completed_files
        session.failed_files = failed_files
        session.save()
        
        # If all files are processed, mark session complete
        if completed_files + failed_files == total_files:
            if failed_files == 0:
                session.mark_completed()
                logger.info(f"🎉 SESSION: Upload session {session.id} completed successfully - all {total_files} files verified")
            else:
                session.mark_failed(f"{failed_files} files failed to process")
                logger.warning(f"⚠️ SESSION: Upload session {session.id} completed with {failed_files} failures")
            
            # Note: UI refresh happens client-side via JavaScript polling or manual refresh
            logger.debug(f"💡 SESSION: Client should refresh file browser for organization: {session.organization}")
            trigger_ui_refresh.delay(str(session.id), session.organization)
        
    except Exception as e:
        logger.error(f"❌ VERIFY: Error processing file {file_id}: {str(e)}")
        try:
            upload_file = AsyncUploadFile.objects.get(id=file_id)
            upload_file.mark_failed(str(e))
        except:
            pass


@db_task(retries=1, retry_delay=10)
def check_session_completion(session_id: str):
    """
    Check if upload session is complete and trigger UI refresh.
    """
    try:
        from arkumu.storage.models.upload_tracking import AsyncUploadSession
        
        session = AsyncUploadSession.objects.get(id=session_id)
        
        total_files = session.files.count()
        completed_files = session.files.filter(status='completed').count()
        failed_files = session.files.filter(status='failed').count()
        
        session.completed_files = completed_files
        session.failed_files = failed_files
        session.save()
        
        if completed_files + failed_files == total_files:
            if failed_files == 0:
                session.mark_completed()
                logger.info(f"🎉 SESSION: Upload session {session_id} completed successfully")
            else:
                session.mark_failed(f"{failed_files} files failed to process")
                logger.warning(f"⚠️ SESSION: Upload session {session_id} completed with {failed_files} failures")
            
            # Trigger UI refresh via OOB updates
            trigger_ui_refresh.delay(str(session_id), session.organization)
            
    except Exception as e:
        logger.error(f"❌ SESSION: Error checking completion for {session_id}: {str(e)}")


@db_task(retries=2, retry_delay=15)
def trigger_ui_refresh(session_id: str, organization: str):
    """
    Trigger UI refresh after upload completion.
    Uses existing HTMX OOB refresh mechanism.
    """
    try:
        logger.info(f"🔄 UI_REFRESH: Triggering refresh for organization {organization}")
        
        # For now, just log that UI refresh should happen
        # In the future, this could integrate with WebSocket or SSE for real-time updates
        logger.info(f"✅ UI_REFRESH: Refresh triggered for {organization}")
        
    except Exception as e:
        logger.error(f"❌ UI_REFRESH: Error triggering refresh: {str(e)}")


# Cleanup task to remove old upload sessions
if HUEY_PERIODIC_AVAILABLE:
    @db_periodic_task(crontab(minute='0', hour='*/4'))  # Every 4 hours
    def cleanup_old_upload_sessions():
        """Clean up old upload sessions and failed uploads"""
        try:
            from arkumu.storage.models.upload_tracking import AsyncUploadSession
            
            # Delete sessions older than 24 hours
            cutoff_time = timezone.now() - timezone.timedelta(days=1)
            
            old_sessions = AsyncUploadSession.objects.filter(
                created_at__lt=cutoff_time
            ).exclude(status='completed')
            
            count = old_sessions.count()
            old_sessions.delete()
            
            logger.info(f"🧹 CLEANUP: Removed {count} old upload sessions")
            
        except Exception as e:
            logger.error(f"❌ CLEANUP: Error cleaning up sessions: {str(e)}")
else:
    @db_task()
    def cleanup_old_upload_sessions():
        """Clean up old upload sessions and failed uploads (manual trigger)"""
        try:
            from arkumu.storage.models.upload_tracking import AsyncUploadSession
            
            # Delete sessions older than 24 hours
            cutoff_time = timezone.now() - timezone.timedelta(days=1)
            
            old_sessions = AsyncUploadSession.objects.filter(
                created_at__lt=cutoff_time
            ).exclude(status='completed')
            
            count = old_sessions.count()
            old_sessions.delete()
            
            logger.info(f"🧹 CLEANUP: Removed {count} old upload sessions")
            
        except Exception as e:
            logger.error(f"❌ CLEANUP: Error cleaning up sessions: {str(e)}")


@db_task(retries=2, retry_delay=30)
def export_successful_imports_task(organization_id: str, user_id: int) -> dict:
    """
    Background task to export successful imports CSV for an organization.
    
    Args:
        organization_id: Organization ID (e.g., 'fuk', 'khm', 'det', etc.)
        user_id: ID of the user requesting the export
        
    Returns:
        dict: CSV export result with filename, content, and count
    """
    try:
        from arkumu.storage.services.bucket_service import BucketService
        from django.contrib.auth import get_user_model
        
        logger.info(f"📊 CSV EXPORT TASK: Starting export for organization '{organization_id}' (user: {user_id})")
        
        # Verify user exists
        User = get_user_model()
        user = User.objects.get(id=user_id)
        
        # Generate CSV using BucketService
        bucket_service = BucketService()
        result = bucket_service.export_successful_imports_csv(organization_id)
        
        if result.get("success"):
            logger.info(f"✅ CSV EXPORT TASK: Export completed for '{organization_id}' - {result['count']} records")
            return result
        else:
            error_msg = result.get("error", "Unknown error")
            logger.error(f"❌ CSV EXPORT TASK: Export failed for '{organization_id}': {error_msg}")
            raise Exception(f"Export failed: {error_msg}")
            
    except Exception as e:
        logger.error(f"❌ CSV EXPORT TASK: Unexpected error for organization '{organization_id}': {str(e)}")
        raise  # Re-raise to trigger Huey retries
