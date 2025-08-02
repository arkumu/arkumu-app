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
            
            # Get stats from import_stats with better size handling
            total_size = import_stats.get('total_size_formatted') or import_stats.get('total_size', '0 B')
            if total_size == '0 B' and hasattr(upload_session, 'total_size'):
                # Try to get size from session
                total_size = upload_session.total_size_formatted if hasattr(upload_session, 'total_size_formatted') else f"{upload_session.total_size / (1024*1024):.1f} MB"
            
            duration = import_stats.get('duration', '0.00')
            
            # Success message with close button and auto-remove
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
                                    <span class="font-medium">{file_count} files</span>{f' • <span class="font-medium">{total_size}</span>' if total_size != '0 B' else ''} • 
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
            
            # Get file browser content
            logger.info(f"🔍 OOB DEBUG: organization = '{organization}'")
            
            if not organization:
                logger.warning("⚠️ OOB DEBUG: No organization provided, cannot refresh file browser")
                # Return success without OOB update
                return HttpResponse(success_html)
            
            bucket_service = BucketService()
            bucket_name = bucket_service.get_organization_bucket(organization)
            logger.info(f"🔍 OOB DEBUG: bucket_name = '{bucket_name}'")
            
            # List all contents like in the dashboard
            contents = bucket_service.list_bucket_contents(bucket_name, '')
            logger.info(f"🔍 OOB DEBUG: Found {len(contents)} items in bucket")
            
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
            logger.info(f"🔍 OOB DEBUG: Rendered template, length = {len(file_browser_html)} chars")
            
            # Return success with file browser refresh
            oob_updates = {
                'file-browser-content': file_browser_html
            }
            
            response_html = helper.build_oob_response(success_html, oob_updates)
            logger.info(f"🔄 UPLOAD STATUS: Built OOB response with file browser refresh for organization: {organization}")
            logger.info(f"📏 RESPONSE LENGTH: {len(response_html)} characters")
            
            # Debug: Log the OOB part to see what's being sent
            if 'hx-swap-oob' in response_html:
                oob_start = response_html.find('<div id="file-browser-content"')
                if oob_start > -1:
                    oob_end = response_html.find('</div>', oob_start + 100) + 6
                    oob_snippet = response_html[oob_start:oob_end]
                    logger.info(f"🔍 OOB CONTENT: {oob_snippet[:200]}...")
                else:
                    logger.warning("⚠️ OOB DEBUG: No file-browser-content div found in response")
            else:
                logger.warning("⚠️ OOB DEBUG: No hx-swap-oob found in response")
            
            return HttpResponse(response_html)
            
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
            # Still processing - continue polling with better feedback
            logger.info(f"⏳ POLL: Still processing... status = {upload_session.status}, files = {file_count}")
            
            # Get progress info
            total_files = upload_session.total_files or file_count
            processed_files = file_count if upload_session.status == 'processing' else 0
            progress_percent = int((processed_files / total_files) * 100) if total_files > 0 else 0
            
            # More informative status based on session status
            status_messages = {
                'pending': 'Preparing upload...',
                'processing': f'Uploading files... ({processed_files}/{total_files})',
                'validating': 'Validating uploaded files...',
                'finalizing': 'Finalizing upload...'
            }
            
            status_text = status_messages.get(upload_session.status, f'Processing... ({upload_session.status})')
            
            return HttpResponse(f'''
                <div hx-get="/storage/upload/status/{session_id}/?organization={organization}"
                     hx-trigger="every 500ms"
                     hx-swap="outerHTML"
                     class="upload-progress-container">
                    <div class="alert alert-info">
                        <div class="flex items-center gap-3">
                            <span class="loading loading-spinner loading-sm"></span>
                            <div class="flex-1">
                                <div class="font-medium">{status_text}</div>
                                {f'<div class="text-sm opacity-70">{file_count} files, {import_stats.get("total_size_formatted", "calculating size...")}</div>' if import_stats else ''}
                            </div>
                        </div>
                        {f'<progress class="progress progress-primary w-full mt-2" value="{progress_percent}" max="100"></progress>' if progress_percent > 0 else ''}
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


@general_login_required
def dismiss_upload_banner(request):
    """Dismiss upload success banner - returns empty content for HTMX replacement"""
    return HttpResponse("")  # Empty content to replace the banner