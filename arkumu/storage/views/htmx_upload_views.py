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

logger = logging.getLogger(__name__)


@general_login_required
def upload_form(request):
    """Main upload form with file selection."""
    return render(request, 'upload/upload_form.html')


@general_login_required
@require_http_methods(["GET"])
def get_presigned_url(request):
    """
    Get presigned URL for a single file and return upload form.
    Pure HTMX endpoint that returns HTML.
    """
    # Get file parameters from query string
    filename = request.GET.get('filename')
    filetype = request.GET.get('filetype', 'application/octet-stream')
    filesize = request.GET.get('filesize', '0')
    folder_name = request.GET.get('folder', '')
    
    if not filename:
        return render(request, 'upload/htmx_upload_error.html', {
            'error': 'Filename is required'
        })
    
    try:
        filesize = int(filesize)
    except (ValueError, TypeError):
        return render(request, 'upload/htmx_upload_error.html', {
            'error': 'Invalid file size'
        })
    
    # Initialize upload service
    upload_service = UploadService()
    
    # Validate upload request
    validation = upload_service.validate_upload_request(
        file_name=filename,
        file_size=filesize,
        content_type=filetype,
        user_id=request.user.id
    )
    
    if not validation['valid']:
        return render(request, 'upload/upload_error.html', {
            'error': validation['errors'][0] if validation['errors'] else 'Validation failed',
            'filename': filename
        })
    
    # Check if should use multipart upload
    if validation['should_use_multipart']:
        return get_multipart_upload(request, filename, filetype, filesize, folder_name)
    
    # Generate presigned URL for single upload
    result = upload_service.generate_presigned_upload_url(
        file_name=filename,
        content_type=filetype,
        path_prefix=folder_name,
        max_file_size=filesize
    )
    
    if not result['success']:
        return render(request, 'upload/upload_error.html', {
            'error': result.get('error', 'Failed to generate upload URL'),
            'filename': filename
        })
    
    # Return upload form with presigned URL
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
    # S3 sends back the key and other info
    s3_key = request.POST.get('key', '')
    filename = s3_key.split('/')[-1] if s3_key else 'Unknown file'
    
    # Log successful upload
    logger.info(f"Successful S3 upload: {s3_key}")
    
    # Optional: Save to database or trigger other actions
    # FileUpload.objects.create(s3_key=s3_key, user=request.user)
    
    return render(request, 'upload/upload_success.html', {
        'filename': filename,
        's3_key': s3_key,
        'is_multipart': False
    })


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