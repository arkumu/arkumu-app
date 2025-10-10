"""
Pure HTMX Upload Views for Direct Browser-to-S3 Uploads.
Implements the simplified upload system using presigned URLs.
"""
import logging
import json
from collections import Counter

from django.db.models import Count
from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from arkumu.storage.services.upload_service import UploadService
from arkumu.storage.services.async_upload_manager import AsyncUploadManager
from arkumu.users.mixins import general_login_required
from arkumu.storage.models.upload_tracking import AsyncUploadSession, AsyncUploadFile
from arkumu.metadata.views.dashboard_helpers import (
    build_session_entry,
    summarize_upload_stats,
)

logger = logging.getLogger(__name__)


@general_login_required
def upload_form(request):
    """Main upload form with file selection."""
    return render(request, 'upload/upload_form.html')


@general_login_required
@require_http_methods(["POST"])
def batch_presigned_urls(request):
    """
    HTMX-compatible endpoint that returns JSON with multiple presigned URLs.
    Called via htmx.ajax() or fetch() with JSON response.
    
    POST /storage/upload/presigned/batch/
    
    Request body:
    {
        "files": [
            {"name": "doc.pdf", "size": 1024000, "type": "application/pdf"},
            {"name": "img.jpg", "size": 512000, "type": "image/jpeg"}
        ],
        "folder": "optional/path"
    }
    """
    logger.info(f"🔗 BATCH_PRESIGNED_URLS: Starting batch request for user {request.user.id}")
    
    try:
        data = json.loads(request.body)
        files = data.get('files', [])
        folder = data.get('folder', '')
        organization = data.get('organization', '')
        session_id = data.get('session_id')
        total_files_override = data.get('total_files')
        
        if not files:
            logger.error("❌ No files provided in batch request")
            return JsonResponse({
                'success': False,
                'error': 'No files provided'
            }, status=400)
        
        logger.info(f"📁 Processing {len(files)} files with folder='{folder}' for organization='{organization}'")
        
        manager = AsyncUploadManager()

        try:
            batch_result = manager.prepare_presigned_uploads(
                user=request.user,
                files=files,
                folder=folder,
                organization=organization,
                session_id=session_id,
                total_files_override=total_files_override,
            )
        except ValueError as exc:
            logger.error(f"❌ Invalid batch upload request: {exc}")
            return JsonResponse({'success': False, 'error': str(exc)}, status=400)

        response_data = {
            'success': batch_result.success,
            'uploads': batch_result.uploads,
            'session_id': str(batch_result.session.id),
        }

        if batch_result.errors:
            response_data['errors'] = batch_result.errors

        if batch_result.created_files:
            logger.info(
                "🚀 Session %s prepared with %s uploads (%s errors)",
                batch_result.session.id,
                len(batch_result.uploads),
                len(batch_result.errors),
            )

        logger.info(
            "✅ BATCH_PRESIGNED_URLS: %s successful, %s errors",
            len(batch_result.uploads),
            len(batch_result.errors),
        )
        return JsonResponse(response_data)
        
    except json.JSONDecodeError:
        logger.error("❌ Invalid JSON in batch request")
        return JsonResponse({
            'success': False,
            'error': 'Invalid JSON'
        }, status=400)
    except Exception as e:
        logger.error(f"❌ BATCH_PRESIGNED_URLS: Unexpected error: {str(e)}")
        return JsonResponse({
            'success': False,
            'error': 'Internal server error'
        }, status=500)


@general_login_required
@require_http_methods(["GET"])
def get_presigned_url(request):
    """
    Get presigned URL for a single file and return upload form.
    Pure HTMX endpoint that returns HTML.
    """
    logger.info(f"🔗 GET_PRESIGNED_URL: Starting request for user {request.user.id}")
    logger.info(f"📋 Request params: {dict(request.GET)}")
    
    # Get file parameters from query string
    filename = request.GET.get('filename')
    filetype = request.GET.get('filetype', 'application/octet-stream')
    filesize = request.GET.get('filesize', '0')
    folder_name = request.GET.get('folder', '')
    
    logger.info(f"📄 Processing file: {filename} ({filesize} bytes, {filetype}) -> {folder_name}")
    
    if not filename:
        logger.error("❌ Missing filename parameter")
        return render(request, 'upload/htmx_upload_error.html', {
            'error': 'Filename is required'
        })
    
    try:
        filesize = int(filesize)
        logger.info(f"✅ Parsed filesize: {filesize}")
    except (ValueError, TypeError):
        logger.error(f"❌ Invalid filesize: {filesize}")
        return render(request, 'upload/htmx_upload_error.html', {
            'error': 'Invalid file size'
        })
    
    # Initialize upload service
    logger.info("🔧 Initializing upload service...")
    upload_service = UploadService()
    
    # Validate upload request
    logger.info("🔍 Validating upload request...")
    validation = upload_service.validate_upload_request(
        file_name=filename,
        file_size=filesize,
        content_type=filetype,
        user_id=request.user.id
    )
    logger.info(f"📝 Validation result: {validation}")
    
    if not validation['valid']:
        logger.error(f"❌ Validation failed: {validation.get('errors', 'Unknown error')}")
        return render(request, 'upload/upload_error.html', {
            'error': validation['errors'][0] if validation['errors'] else 'Validation failed',
            'filename': filename
        })
    
    # Check if should use multipart upload
    if validation['should_use_multipart']:
        logger.info("📦 Using multipart upload for large file")
        return get_multipart_upload(request, filename, filetype, filesize, folder_name)
    
    # Generate presigned URL for single upload
    logger.info("🔗 Generating presigned URL for single upload...")
    result = upload_service.generate_presigned_upload_url(
        file_name=filename,
        content_type=filetype,
        path_prefix=folder_name,
        max_file_size=filesize
    )
    logger.info(f"🔗 Presigned URL result: success={result.get('success', False)}")
    
    if not result['success']:
        logger.error(f"❌ Failed to generate presigned URL: {result.get('error', 'Unknown error')}")
        return render(request, 'upload/upload_error.html', {
            'error': result.get('error', 'Failed to generate upload URL'),
            'filename': filename
        })
    
    logger.info(f"✅ Generated presigned URL for S3 key: {result.get('key', 'N/A')}")
    
    # Return upload form with presigned URL
    logger.info("📄 Returning S3 form template")
    return render(request, 'upload/s3_form.html', {
        'presigned_url': result['url'],
        'fields': result['fields'],
        'filename': filename,
        's3_key': result['key'],
        'filesize': filesize,
        'filetype': filetype,
        'max_file_size': result.get('max_file_size'),
        'method': result.get('method', 'POST')
    })


def get_multipart_upload(request, filename, filetype, filesize, folder_name):
    """
    Initialize multipart upload for large files.
    Returns HTMX form for multipart upload.
    """
    upload_service = UploadService()
    
    # Initialize multipart upload
    init_result = upload_service.initiate_multipart_upload(
        file_name=filename,
        content_type=filetype,
        path_prefix=folder_name
    )
    
    if not init_result['success']:
        return render(request, 'upload/upload_error.html', {
            'error': init_result.get('error', 'Failed to initialize multipart upload'),
            'filename': filename
        })
    
    # Calculate parts and generate URLs
    parts_info = upload_service.presigned_url_service.calculate_multipart_parts(filesize)
    
    urls_result = upload_service.generate_presigned_multipart_urls(
        s3_key=init_result['s3_key'],
        upload_id=init_result['upload_id'],
        part_numbers=parts_info['part_numbers']
    )
    
    if not urls_result['success']:
        return render(request, 'upload/upload_error.html', {
            'error': 'Failed to generate multipart URLs',
            'filename': filename
        })
    
    # Return multipart upload form
    return render(request, 'upload/multipart_form.html', {
        'filename': filename,
        's3_key': init_result['s3_key'],
        'upload_id': init_result['upload_id'],
        'part_urls': urls_result['presigned_urls'],
        'part_info': parts_info,
        'filesize': filesize,
        'filetype': filetype
    })


@general_login_required
@require_http_methods(["POST"])
def presigned_multipart_init(request):
    """API: Initialize multipart upload and return part plan (JSON)."""
    try:
        data = json.loads(request.body)
    except Exception:
        data = request.POST

    filename = data.get('filename') or data.get('name')
    filetype = data.get('filetype') or data.get('type') or 'application/octet-stream'
    try:
        filesize = int(data.get('filesize') or data.get('size') or 0)
    except Exception:
        filesize = 0
    folder = data.get('folder') or data.get('path_prefix') or None
    organization = data.get('organization') or ''

    if not filename or not filesize:
        return JsonResponse({'success': False, 'error': 'filename and filesize are required'}, status=400)

    upload_service = UploadService()
    init_result = upload_service.initiate_multipart_upload(
        file_name=filename,
        content_type=filetype,
        path_prefix=folder,
        organization=organization
    )

    if not init_result.get('success'):
        return JsonResponse({'success': False, 'error': init_result.get('error', 'init failed')}, status=400)

    parts_info = upload_service.presigned_url_service.calculate_multipart_parts(filesize)

    return JsonResponse({
        'success': True,
        'upload_id': init_result['upload_id'],
        's3_key': init_result['s3_key'],
        'bucket': init_result.get('bucket'),
        'part_info': parts_info
    })


@general_login_required
@require_http_methods(["POST"])
def presigned_multipart_part_urls(request):
    """API: Generate presigned URLs for specific multipart part numbers (JSON)."""
    try:
        data = json.loads(request.body)
    except Exception:
        data = request.POST

    upload_id = data.get('upload_id') or data.get('uploadId')
    s3_key = data.get('s3_key') or data.get('s3Key')
    part_numbers = data.get('part_numbers') or data.get('parts')
    organization = data.get('organization', '')
    
    if not upload_id or not s3_key:
        return JsonResponse({'success': False, 'error': 'upload_id and s3_key are required'}, status=400)

    plan = None
    # If client didn't pass part_numbers, compute a default plan from file_size
    if not part_numbers:
        try:
            filesize = int(data.get('filesize') or 0)
        except Exception:
            filesize = 0
        if not filesize:
            return JsonResponse({'success': False, 'error': 'part_numbers or filesize required'}, status=400)
        from arkumu.storage.services.upload.presigned_url_service import PresignedURLService
        svc = PresignedURLService()
        plan = svc.calculate_multipart_parts(filesize)
        part_numbers = plan['part_numbers']

    # Normalize to list of ints
    try:
        part_numbers = [int(p) for p in part_numbers]
    except Exception:
        return JsonResponse({'success': False, 'error': 'invalid part_numbers'}, status=400)

    # Get bucket for organization
    bucket_name = None
    if organization:
        from arkumu.storage.services.bucket_service import BucketService
        bucket_service = BucketService()
        bucket_name = bucket_service.get_organization_bucket(organization)
        logger.debug(f"🪣 MULTIPART_PARTS: organization='{organization}' -> bucket='{bucket_name}'")
    else:
        logger.debug(f"🪣 MULTIPART_PARTS: no organization provided, will use fallback bucket")

    from arkumu.storage.services.upload.presigned_url_service import PresignedURLService
    svc = PresignedURLService()
    logger.debug(f"🔗 MULTIPART_PARTS: Generating URLs for key='{s3_key}', upload_id='{upload_id}', bucket='{bucket_name}'")
    urls_result = svc.generate_multipart_urls(key=s3_key, upload_id=upload_id, parts=part_numbers, bucket_name=bucket_name)
    if not urls_result.get('success'):
        return JsonResponse({'success': False, 'error': urls_result.get('error', 'url generation failed')}, status=400)

    resp = {
        'success': True,
        'presigned_urls': urls_result['presigned_urls']
    }
    if plan:
        resp['part_info'] = plan
    return JsonResponse(resp)


@general_login_required
@require_http_methods(["POST"])
def complete_multipart_upload(request):
    """Complete multipart upload."""
    upload_id = request.POST.get('upload_id')
    s3_key = request.POST.get('s3_key')
    filename = request.POST.get('filename')
    parts_json = request.POST.get('parts')
    
    if not all([upload_id, s3_key, filename, parts_json]):
        return render(request, 'upload/upload_error.html', {
            'error': 'Missing required parameters for multipart completion',
            'filename': filename
        })
    
    try:
        parts = json.loads(parts_json)
    except json.JSONDecodeError:
        return render(request, 'upload/upload_error.html', {
            'error': 'Invalid parts data',
            'filename': filename
        })
    
    # Complete multipart upload
    upload_service = UploadService()
    result = upload_service.complete_multipart_upload(
        s3_key=s3_key,
        upload_id=upload_id,
        parts=parts
    )
    
    if result['success']:
        return render(request, 'upload/upload_success.html', {
            'filename': filename,
            's3_key': s3_key,
            'is_multipart': True
        })
    else:
        return render(request, 'upload/upload_error.html', {
            'error': result.get('error', 'Failed to complete multipart upload'),
            'filename': filename
        })


@general_login_required
@require_http_methods(["POST"])  
def abort_multipart_upload(request):
    """Abort multipart upload."""
    upload_id = request.POST.get('upload_id')
    s3_key = request.POST.get('s3_key')
    filename = request.POST.get('filename')
    
    if not all([upload_id, s3_key]):
        return HttpResponse("Missing parameters", status=400)
    
    # Abort multipart upload
    upload_service = UploadService()
    upload_service.abort_multipart_upload(s3_key=s3_key, upload_id=upload_id)
    
    return render(request, 'upload/upload_cancelled.html', {
        'filename': filename
    })


@csrf_exempt
@require_http_methods(["POST"])
def upload_success(request):
    """
    Handle successful S3 upload response.
    This gets called by S3 redirect after successful upload.
    """
    logger.info("🎉 UPLOAD_SUCCESS: S3 upload completed successfully!")
    logger.info(f"📋 POST data: {dict(request.POST)}")
    
    # S3 sends back the key and other info
    s3_key = request.POST.get('key', '')
    filename = s3_key.split('/')[-1] if s3_key else 'Unknown file'
    
    logger.info(f"✅ Successful S3 upload: key={s3_key}, filename={filename}")
    
    # Optional: Save to database or trigger other actions
    # FileUpload.objects.create(s3_key=s3_key, user=request.user)
    
    return render(request, 'upload/upload_success.html', {
        'filename': filename,
        's3_key': s3_key,
        'is_multipart': False
    })


@general_login_required
@require_http_methods(["POST"])
def mark_file_uploaded(request, file_id):
    """
    Mark a file as uploaded after successful S3 upload.
    This triggers the verification process.
    """
    try:
        upload_file = AsyncUploadFile.objects.get(id=file_id, session__user=request.user)
        upload_file.mark_uploaded()
        logger.info(f"✅ Marked file {upload_file.filename} as uploaded")

        session = upload_file.session
        if session.status not in ('uploading', 'processing', 'completed', 'failed', 'awaiting_verification'):
            session.mark_uploading()

        verification_triggered = False

        file_qs = AsyncUploadFile.objects.filter(session=session)
        status_counts = Counter(file_qs.values_list('status', flat=True))

        total_count = sum(status_counts.values())

        pending_exists = file_qs.exclude(status__in=['uploaded', 'completed', 'failed']).exists()
        all_uploaded = not pending_exists

        session.completed_files = status_counts.get('completed', 0)
        session.failed_files = status_counts.get('failed', 0)

        fields_to_update = ['completed_files', 'failed_files']

        if all_uploaded:
            logger.info("🟡 Upload session %s awaiting manual verification", session.id)
            session.status = 'awaiting_verification'
            fields_to_update.append('status')

        session.save(update_fields=fields_to_update)

        # Get organization for OOB refresh
        organization = session.organization

        # If this is an HTMX request, return OOB refresh instead of JSON
        if request.headers.get('HX-Request'):
            try:
                # Import template helpers for OOB refresh
                from arkumu.metadata.views.csv_mapping.mixins.template_helpers import CSVMappingTemplateHelperMixin
                
                # Create fresh file browser content
                template_helper = CSVMappingTemplateHelperMixin()
                file_browser_html = template_helper.render_file_browser_template(request, organization)
                
                # Build OOB response to refresh file browser
                oob_updates = {
                    'file-browser-content': file_browser_html
                }
                
                response_html = template_helper.build_oob_response('', oob_updates)
                
                from django.http import HttpResponse
                return HttpResponse(response_html)
                
            except Exception as e:
                logger.error(f"❌ OOB refresh failed in mark_file_uploaded: {e}")
                # Fall back to JSON response
        remaining_files_count = status_counts.get('pending', 0) + status_counts.get('uploading', 0)

        response_data = {
            'success': True,
            'session_id': str(session.id),
            'session_status': session.status,
            'total_files': session.total_files or total_count,
            'uploaded_files': status_counts.get('uploaded', 0),
            'processing_files': status_counts.get('processing', 0),
            'completed_files': status_counts.get('completed', 0),
            'failed_files': status_counts.get('failed', 0),
            'remaining_files': remaining_files_count,
            'pending_files': status_counts.get('pending', 0),
            'all_uploaded': all_uploaded,
            'verification_triggered': verification_triggered,
        }

        return JsonResponse(response_data)
    except AsyncUploadFile.DoesNotExist:
        logger.error(f"❌ Upload file {file_id} not found")
        return JsonResponse({'success': False, 'error': 'File not found'}, status=404)
    except Exception as e:
        logger.error(f"❌ Error marking file uploaded: {str(e)}")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)



@general_login_required
def cancel_upload(request):
    """Cancel upload."""
    filename = request.GET.get('filename', 'Unknown file')
    
    return render(request, 'upload/upload_cancelled.html', {
        'filename': filename
    })


@general_login_required
def batch_upload(request):
    """Handle batch file selection for multiple files."""
    if request.method == 'POST':
        # Get file metadata from form
        files_data = []
        file_count = int(request.POST.get('file_count', 0))
        folder_name = request.POST.get('folder_name', '')
        
        for i in range(file_count):
            filename = request.POST.get(f'file_{i}_name')
            filetype = request.POST.get(f'file_{i}_type', 'application/octet-stream')
            filesize = int(request.POST.get(f'file_{i}_size', 0))
            
            if filename:
                files_data.append({
                    'filename': filename,
                    'filetype': filetype,
                    'filesize': filesize
                })
        
        return render(request, 'upload/batch_upload_forms.html', {
            'files_data': files_data,
            'folder_name': folder_name
        })
    
    return render(request, 'upload/batch_upload.html')


@general_login_required
@require_http_methods(["GET"])
def upload_complete_oob_refresh(request, organization):
    """
    OOB refresh endpoint for file browser after upload completion.
    
    Uses the template helpers mixin to render fresh file browser content
    and returns it as an OOB update to refresh the UI.
    """
    logger.info(f"🔄 UPLOAD_OOB_REFRESH: Refreshing file browser for organization: {organization}")
    
    try:
        # Import template helpers mixin
        from arkumu.metadata.views.csv_mapping.mixins.template_helpers import CSVMappingTemplateHelperMixin
        
        # Create a temporary instance to use the mixin methods
        template_helper = CSVMappingTemplateHelperMixin()
        
        # Render fresh file browser content
        file_browser_html = template_helper.render_file_browser_template(request, organization)
        
        logger.info(f"✅ UPLOAD_OOB_REFRESH: Generated file browser HTML (length: {len(file_browser_html)})")
        
        # Build OOB response to update file browser only (bucket size has manual refresh button)
        oob_updates = {
            'file-browser-content': file_browser_html
        }
        
        # Return empty main content with OOB update
        response_html = template_helper.build_oob_response("", oob_updates)
        
        from django.http import HttpResponse
        return HttpResponse(response_html)
        
    except Exception as e:
        logger.error(f"❌ UPLOAD_OOB_REFRESH: Error refreshing file browser: {e}")
        return HttpResponse(
            f'<div id="file-browser-content" hx-swap-oob="innerHTML">'
            f'<div class="alert alert-error"><span>Error refreshing file browser: {str(e)}</span></div>'
            f'</div>'
        )


@general_login_required
@require_http_methods(["GET"])
def upload_session_status(request, session_id):
    """Return JSON status summary for an async upload session."""

    try:
        session = AsyncUploadSession.objects.get(id=session_id, user=request.user)
    except AsyncUploadSession.DoesNotExist:
        logger.warning("⚠️ upload_session_status: session %s not found for user %s", session_id, request.user.id)
        return JsonResponse({'success': False, 'error': 'Session not found'}, status=404)

    status_counts = {
        entry['status']: entry['count']
        for entry in session.files.values('status').annotate(count=Count('id'))
    }

    total_count = sum(status_counts.values())
    completed = status_counts.get('completed', 0)
    failed = status_counts.get('failed', 0)
    uploaded = status_counts.get('uploaded', 0)
    processing = status_counts.get('processing', 0)
    pending = status_counts.get('pending', 0)
    uploading = status_counts.get('uploading', 0)

    return JsonResponse(
        {
            'success': True,
            'session_id': str(session.id),
            'status': session.status,
            'total_files': session.total_files or total_count,
            'completed_files': completed,
            'failed_files': failed,
            'uploaded_files': uploaded,
            'processing_files': processing,
            'pending_files': pending + uploading,
        }
    )


@general_login_required
def uploads_dashboard(request):
    """Display consolidated async upload activity."""

    sessions_qs = (
        AsyncUploadSession.objects.select_related('user')
        .prefetch_related('files')
        .order_by('-created_at')
    )
    entries = [build_session_entry(session) for session in sessions_qs]
    stats = summarize_upload_stats(entries)

    return render(
        request,
        'dashboard/uploads_dashboard.html',
        {
            'sessions': entries,
            'stats': stats,
        },
    )


@general_login_required
def upload_session_stats(request, session_id):
    """Return upload session statistics for modal display."""

    try:
        session = AsyncUploadSession.objects.prefetch_related('files').get(pk=session_id)
    except AsyncUploadSession.DoesNotExist:
        return HttpResponse(
            '<div class="alert alert-error"><span>Upload session not found.</span></div>',
            status=404,
        )

    entry = build_session_entry(session)

    return render(
        request,
        'partials/upload_stats_modal_content.html',
        {
            'session': entry['session'],
            'files': entry['files'],
            'file_count': entry['file_count'],
            'completed_files': entry['completed_files'],
            'failed_files': entry['failed_files'],
        },
    )
