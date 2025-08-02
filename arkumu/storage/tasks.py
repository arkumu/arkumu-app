"""
Storage Tasks

Huey background tasks for file operations.
"""

import logging
from huey.contrib.djhuey import db_task

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