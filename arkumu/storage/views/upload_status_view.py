"""Upload status view for HTMX polling"""
import logging
from django.http import HttpResponse
from django.template.loader import render_to_string
from arkumu.users.mixins import general_login_required
from arkumu.storage.models import UploadSession
from arkumu.storage.services.bucket_service import BucketService
from arkumu.metadata.views.csv_mapping.mixins.template_helpers import CSVMappingTemplateHelperMixin

logger = logging.getLogger(__name__)


class UploadStatusHelper(CSVMappingTemplateHelperMixin):
    """Helper for OOB responses"""
    pass


@general_login_required
def upload_status(request, session_id):
    """
    Check upload status and return appropriate response.
    Called via HTMX polling every second.
    """
    logger.info(f"📊 POLL: Checking status for session {session_id}")
    
    try:
        # Get upload session
        upload_session = UploadSession.objects.get(id=session_id, user=request.user)
        organization = request.GET.get('organization', '')
        
        # Get progress from Redis and session metadata
        from django.core.cache import cache
        progress_data = cache.get(f"upload_progress_{upload_session.id}", {})
        file_count = upload_session.files.count() if hasattr(upload_session, 'files') else upload_session.total_files
        import_stats = upload_session.import_stats or {}
        
        logger.info(f"📊 POLL: Session status = {upload_session.status}, files = {file_count}")
        
        # If still in progress, check Redis for real-time progress
        if upload_session.status == 'in_progress' and progress_data:
            progress_pct = progress_data.get('percentage', 0)
            progress_msg = progress_data.get('message', 'Processing...')
            logger.info(f"📊 POLL: Upload progress = {progress_pct}% - {progress_msg}")
            
            return HttpResponse(f'''
                <div hx-get="/storage/upload/status/{session_id}/?organization={organization}"
                     hx-trigger="every 1s"
                     hx-swap="outerHTML">
                    <div class="alert alert-info">
                        <span class="loading loading-spinner"></span>
                        {progress_msg} ({progress_pct}%)
                        <progress class="progress progress-primary w-56" value="{progress_pct}" max="100"></progress>
                    </div>
                </div>
            ''')
        
        if upload_session.status == 'completed':
            logger.info(f"✅ POLL: Upload completed! Returning success response with file browser refresh")
            # Stop polling and show success
            helper = UploadStatusHelper()
            
            # Get stats from import_stats
            total_size = import_stats.get('total_size_formatted', '0 B')
            duration = import_stats.get('duration', '0.00')
            
            # Success message
            success_html = render_to_string(
                'dashboard/partials/upload_results.html',
                {
                    'success': True,
                    'files_count': file_count,
                    'total_size': total_size,
                    'duration': duration
                },
                request=request
            )
            
            # Get file browser content
            bucket_service = BucketService()
            bucket_name = bucket_service.get_organization_bucket(organization)
            
            # List only top-level folders
            all_contents = bucket_service.list_bucket_contents(bucket_name, '')
            contents = [item for item in all_contents if item.get('type') == 'folder' and '/' not in item.get('name', '').strip('/')]
            
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
            
            # Return success with file browser refresh
            oob_updates = {
                'file-browser-content': file_browser_html
            }
            
            return HttpResponse(helper.build_oob_response(success_html, oob_updates))
            
        elif upload_session.status == 'failed':
            error_message = import_stats.get('error', 'Unknown error')
            logger.error(f"❌ POLL: Upload failed! Error: {error_message}")
            # Stop polling and show error
            return HttpResponse(f'''
                <div class="alert alert-error">
                    <span>Upload failed: {error_message}</span>
                </div>
            ''')
            
        else:
            # Still processing - continue polling
            logger.info(f"⏳ POLL: Still processing... status = {upload_session.status}, files = {file_count}")
            return HttpResponse(f'''
                <div hx-get="/storage/upload/status/{session_id}/?organization={organization}"
                     hx-trigger="every 1s"
                     hx-swap="outerHTML">
                    <div class="alert alert-info">
                        <span class="loading loading-spinner"></span>
                        Processing upload... ({file_count} files)
                    </div>
                </div>
            ''')
            
    except UploadSession.DoesNotExist:
        logger.error(f"❌ POLL: Session {session_id} not found!")
        return HttpResponse('''
            <div class="alert alert-error">
                <span>Upload session not found</span>
            </div>
        ''')
    except Exception as e:
        logger.error(f"Error checking upload status: {str(e)}")
        return HttpResponse(f'''
            <div class="alert alert-error">
                <span>Error checking status: {str(e)}</span>
            </div>
        ''')