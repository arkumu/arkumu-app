"""
Pure HTMX Upload Views for Direct Browser-to-S3 Uploads.
Implements the simplified upload system using presigned URLs.
"""
import logging
import json
from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from arkumu.storage.services.upload_service import UploadService
from arkumu.users.mixins import general_login_required
from arkumu.storage.models.upload_tracking import AsyncUploadSession, AsyncUploadFile

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
        
        if not files:
            logger.error("❌ No files provided in batch request")
            return JsonResponse({
                'success': False,
                'error': 'No files provided'
            }, status=400)
        
        logger.info(f"📁 Processing {len(files)} files with folder='{folder}' for organization='{organization}'")
        
        # Get the correct bucket for the organization
        from arkumu.storage.services.bucket_service import BucketService
        bucket_service = BucketService()
        bucket_name = bucket_service.get_organization_bucket(organization) if organization else None
        
        # Create upload session for tracking
        session = AsyncUploadSession.objects.create(
            user=request.user,
            total_files=len(files),
            organization=organization  # Store organization in session
        )
        logger.info(f"📝 Created upload session {session.id} for {len(files)} files in bucket {bucket_name}")
        
        upload_service = UploadService()
        results = []
        errors = []
        upload_files_created = []
        
        for file_info in files:
            filename = file_info.get('name')
            # Use relative path if provided (for folder uploads with structure)
            relative_path = file_info.get('relativePath', filename)
            filesize = file_info.get('size', 0)
            filetype = file_info.get('type', 'application/octet-stream')
            
            logger.info(f"📄 Processing: {filename} -> {relative_path} ({filesize} bytes, {filetype})")
            
            try:
                # Validate upload request
                validation = upload_service.validate_upload_request(
                    file_name=filename,
                    file_size=filesize,
                    content_type=filetype,
                    user_id=request.user.id
                )
                
                if not validation['valid']:
                    # Allow zero-byte files (like .gitkeep) - they're valid
                    if filesize == 0 and len(validation['errors']) == 1 and 'File size must be greater than 0' in validation['errors']:
                        logger.info(f"⚪ Allowing zero-byte file: {filename}")
                        # Override validation for zero-byte files
                        validation = {
                            'valid': True,
                            'errors': [],
                            'warnings': validation.get('warnings', []) + ['Zero-byte file allowed'],
                            'should_use_multipart': False
                        }
                    else:
                        errors.append({
                            'filename': filename,
                            'errors': validation['errors']
                        })
                        continue
                
                # Generate presigned URL (same logic as individual request)
                if validation['should_use_multipart']:
                    # For large files, initialize multipart upload
                    # Create full path: base_folder + relative_path
                    full_path = f"{folder}/{relative_path}" if folder else relative_path
                    # Extract directory from full path for multipart
                    import os
                    file_dir = os.path.dirname(full_path) if os.path.dirname(full_path) else None
                    
                    init_result = upload_service.initiate_multipart_upload(
                        file_name=os.path.basename(full_path),  # Just filename for multipart
                        content_type=filetype,
                        path_prefix=file_dir  # Directory path
                    )
                    
                    if init_result['success']:
                        results.append({
                            'filename': filename,
                            'type': 'multipart',
                            'upload_id': init_result['upload_id'],
                            's3_key': init_result['s3_key'],
                            'filesize': filesize,
                            'filetype': filetype
                        })
                    else:
                        errors.append({
                            'filename': filename,
                            'errors': [init_result.get('error', 'Multipart initialization failed')]
                        })
                else:
                    # Single upload
                    # Create full path: base_folder + relative_path  
                    full_path = f"{folder}/{relative_path}" if folder else relative_path
                    # Extract directory and filename
                    import os
                    file_dir = os.path.dirname(full_path) if os.path.dirname(full_path) else None
                    
                    result = upload_service.generate_presigned_upload_url(
                        file_name=os.path.basename(full_path),  # Just filename
                        content_type=filetype,
                        path_prefix=file_dir,  # Full directory path preserves structure
                        max_file_size=filesize,
                        bucket_name=bucket_name  # Use organization bucket
                    )
                    
                    if result['success']:
                        # Create AsyncUploadFile record for tracking
                        upload_file = AsyncUploadFile.objects.create(
                            session=session,
                            filename=filename,
                            s3_key=result['key'],
                            file_size=filesize,
                            content_type=filetype,
                            status='pending'
                        )
                        upload_files_created.append(upload_file)
                        logger.info(f"📄 Created upload file record {upload_file.id} for {filename}")
                        
                        results.append({
                            'filename': filename,
                            'type': 'single',
                            'url': result['url'],
                            'fields': result['fields'],
                            's3_key': result['key'],
                            'filesize': filesize,
                            'filetype': filetype,
                            'max_file_size': result.get('max_file_size'),
                            'upload_file_id': str(upload_file.id)
                        })
                    else:
                        errors.append({
                            'filename': filename,
                            'errors': [result.get('error', 'Presigned URL generation failed')]
                        })
                        
            except Exception as e:
                logger.error(f"❌ Error processing file {filename}: {str(e)}")
                errors.append({
                    'filename': filename,
                    'errors': [f"Processing error: {str(e)}"]
                })
        
        response_data = {
            'success': len(errors) == 0,
            'uploads': results,
            'session_id': str(session.id)
        }
        
        if errors:
            response_data['errors'] = errors
        
        # Start monitoring the upload session if files were created
        if upload_files_created:
            logger.info(f"🚀 Starting monitoring for session {session.id}")
            # Import here to avoid circular import issues
            from arkumu.storage.tasks import monitor_upload_session
            # In Django Huey, call the task directly (no .delay() needed)
            monitor_upload_session(str(session.id))
        
        logger.info(f"✅ BATCH_PRESIGNED_URLS: {len(results)} successful, {len(errors)} errors")
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
        'max_file_size': result.get('max_file_size')
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
        
        # Check if all files in session are uploaded
        session = upload_file.session
        if session.files.filter(status='uploaded').count() == session.total_files:
            logger.info(f"🎉 All files in session {session.id} uploaded, triggering verification")
            # Monitor will handle verification
        
        return JsonResponse({'success': True})
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
        
        # Build OOB response to update the file browser
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