"""Upload status view for HTMX polling."""

import logging
from django.http import HttpResponse
from django.template.loader import render_to_string
from django.utils import timezone

from arkumu.users.mixins import general_login_required
from arkumu.storage.models.upload_tracking import AsyncUploadSession
from arkumu.storage.services.bucket_service import BucketService
from arkumu.metadata.views.csv_mapping.mixins.template_helpers import CSVMappingTemplateHelperMixin

logger = logging.getLogger(__name__)


class UploadStatusHelper(CSVMappingTemplateHelperMixin):
    """Helper for OOB responses."""
    pass


def _format_size(bytes_total: int) -> str:
    """Return human-readable file size."""
    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(bytes_total)
    for unit in units:
        if size < 1024 or unit == units[-1]:
            return f"{size:.1f} {unit}"
        size /= 1024


@general_login_required
def upload_status(request, session_id):
    """HTMX polling endpoint for upload progress."""
    logger.info("📊 POLL: Checking status for session %s", session_id)

    try:
        session = (
            AsyncUploadSession.objects
            .prefetch_related('files')
            .get(id=session_id, user=request.user)
        )
    except AsyncUploadSession.DoesNotExist:
        logger.error("❌ POLL: Session %s not found!", session_id)
        return HttpResponse(
            '<div class="alert alert-error">'
            '<span>Upload session not found</span>'
            '</div>'
        )
    except Exception as exc:
        logger.error("Error loading upload session %s: %s", session_id, exc)
        return HttpResponse(
            f'<div class="alert alert-error"><span>Error checking status: {exc}</span></div>'
        )

    files = list(session.files.all())
    organization = request.GET.get('organization') or session.organization or ''

    total_files = session.total_files or len(files)
    completed_files = sum(1 for f in files if f.status == 'completed')
    failed_files = sum(1 for f in files if f.status == 'failed')
    uploaded_files = sum(1 for f in files if f.status in {'uploaded', 'processing', 'completed'})
    total_size_bytes = sum(file.file_size for file in files if file.file_size)

    logger.info(
        "📊 POLL: Session %s status=%s total=%s completed=%s failed=%s",
        session_id,
        session.status,
        total_files,
        completed_files,
        failed_files,
    )

    # Completed --------------------------------------------------------------
    if session.status == 'completed' or (total_files and completed_files == total_files):
        helper = UploadStatusHelper()

        total_size = _format_size(total_size_bytes) if total_size_bytes else '0 B'
        start_time = session.started_at or session.created_at
        end_time = session.completed_at or timezone.now()
        duration_seconds = max((end_time - start_time).total_seconds(), 0)
        duration = f"{duration_seconds:.1f}"

        success_html = f'''
            <div class="alert alert-success"
                 id="upload-status"
                 hx-trigger="load delay:5s"
                 hx-delete="/storage/upload/dismiss-banner/"
                 hx-swap="outerHTML"
                 hx-target="this">
                <div class="flex items-center justify-between w-full">
                    <div class="flex items-center gap-3">
                        <div class="text-success text-2xl">✅</div>
                        <div>
                            <div class="font-bold text-lg">Upload Complete!</div>
                            <div class="text-sm">
                                <span class="font-medium">{completed_files} files</span>
                                {f' • <span class="font-medium">{total_size}</span>' if total_size_bytes else ''} •
                                <span class="font-medium">{duration}s</span>
                            </div>
                        </div>
                    </div>
                    <button class="btn btn-sm btn-ghost text-lg"
                            hx-delete="/storage/upload/dismiss-banner/"
                            hx-swap="outerHTML"
                            hx-target="#upload-status">×</button>
                </div>
            </div>
        '''

        if not organization:
            logger.warning("⚠️ POLL: Organization missing, skipping file browser refresh")
            return HttpResponse(success_html)

        bucket_service = BucketService()
        bucket_name = bucket_service.get_organization_bucket(organization)
        contents = bucket_service.list_bucket_contents(bucket_name, '', force_fresh=True)
        for item in contents:
            if item['type'] == 'folder' and item['name'] in ['data', 'metadata']:
                item['file_count'] = bucket_service.count_files_in_folder(
                    bucket_name, item['path'], force_fresh=True
                )

        file_browser_html = render_to_string(
            'dashboard/organization_files_partial.html',
            {
                'organization': organization,
                'bucket_name': bucket_name,
                'contents': contents,
                'selected_org_slug': organization,
                'prefix': ''
            },
            request=request
        )

        response_html = helper.build_oob_response(
            success_html,
            {'file-browser-content': file_browser_html}
        )
        return HttpResponse(response_html)

    # Failed -----------------------------------------------------------------
    if session.status == 'failed':
        error_message = session.error_message or 'Unknown error'
        logger.error("❌ POLL: Upload failed! %s", error_message)
        return HttpResponse(
            f'<div class="alert alert-error"><span>Upload failed: {error_message}</span></div>'
        )

    # In progress ------------------------------------------------------------
    status_messages = {
        'initialized': 'Preparing upload…',
        'presigned_generated': 'Awaiting uploads…',
        'uploading': f'Uploading files… ({uploaded_files}/{total_files})',
        'processing': f'Processing uploaded files… ({completed_files}/{total_files})',
    }
    status_text = status_messages.get(session.status, f'Processing… ({session.status})')

    progress_percent = 0
    if total_files:
        progress_percent = int((completed_files / total_files) * 100)

    return HttpResponse(f'''
        <div hx-get="/storage/upload/status/{session_id}/?organization={organization}"
             hx-trigger="every 2s"
             hx-swap="outerHTML"
             class="upload-progress-container">
            <div class="alert alert-info">
                <div class="flex items-center gap-3">
                    <span class="loading loading-spinner loading-sm"></span>
                    <div class="flex-1">
                        <div class="font-medium">{status_text}</div>
                        <div class="text-sm opacity-70">
                            {total_files} files total • {completed_files} completed • {failed_files} failed
                        </div>
                    </div>
                </div>
                {f'<progress class="progress progress-primary w-full mt-2" value="{progress_percent}" max="100"></progress>' if progress_percent > 0 else ''}
            </div>
        </div>
    ''')


@general_login_required
def dismiss_upload_banner(request):
    """Dismiss upload success banner - returns empty content for HTMX replacement."""
    return HttpResponse('')
