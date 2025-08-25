import logging
import json
import uuid
from typing import Dict, Any
from django.shortcuts import render
from django.views.decorators.http import require_http_methods
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
import time

from arkumu.users.mixins import general_login_required
from arkumu.storage.services.upload_service import UploadService
from arkumu.storage.services.bucket_service import BucketService
from arkumu.storage.models import UploadSession, S3FileObject

logger = logging.getLogger(__name__)

# Cache services
_upload_service = None
_bucket_service = None

def get_cached_upload_service():
    """Get cached upload service to avoid repeated initialization."""
    global _upload_service
    if _upload_service is None:
        _upload_service = UploadService()
    return _upload_service

def get_cached_bucket_service():
    """Get cached bucket service to avoid repeated initialization."""
    global _bucket_service
    if _bucket_service is None:
        _bucket_service = BucketService()
    return _bucket_service


@require_http_methods(["POST"])
@general_login_required
def multipart_upload_init(request):
    """
    Initialize S3 multipart upload for a single file.
    
    Expected form data:
    - filename: Original filename
    - fileSize: File size in bytes
    - contentType: MIME type
    - folderName: Target folder
    - organization: Organization slug
    - baseFolder: Base folder (data/metadata)
    """
    try:
        # Get form data
        filename = request.POST.get('filename')
        file_size = int(request.POST.get('fileSize', 0))
        content_type = request.POST.get('contentType', 'application/octet-stream')
        folder_name = request.POST.get('folderName', '')
        organization = request.POST.get('organization', '')
        base_folder = request.POST.get('baseFolder', 'data')
        
        if not filename:
            return JsonResponse({
                'error': 'Invalid filename'
            }, status=400)
        
        # S3 multipart uploads require minimum 5MB per part (except last part)
        # For small files, we should use regular upload instead
        if file_size == 0:
            return JsonResponse({
                'error': 'Empty files should use regular upload, not multipart upload'
            }, status=400)
        
        if file_size < 5 * 1024 * 1024:  # Less than 5MB
            return JsonResponse({
                'error': 'Files smaller than 5MB should use regular upload, not multipart upload'
            }, status=400)
        
        logger.info(f"🚀 MULTIPART INIT: {filename} ({file_size} bytes) for org {organization}")
        
        # Get services
        upload_service = get_cached_upload_service()
        bucket_service = get_cached_bucket_service()
        
        # Ensure organization bucket exists
        if organization:
            bucket_result = bucket_service.ensure_organization_bucket_exists(organization)
            if not bucket_result.get("success", False):
                return JsonResponse({
                    'error': f'Failed to access organization bucket: {bucket_result.get("error", "Unknown error")}'
                }, status=500)
            target_bucket = bucket_result["bucket_name"]
        else:
            target_bucket = upload_service.base_s3_service.production_bucket
        
        # Create upload session
        upload_session = UploadSession.objects.create(
            user=request.user,
            folder_name=folder_name,
            institution=organization,
            total_files=1,
            total_size_bytes=file_size
        )
        
        # Create S3 file object
        from arkumu.common.uri_utils import normalize_string_nfc
        import os
        
        # Preserve file extension while normalizing filename (NFC for umlauts)
        filename_without_ext, file_extension = os.path.splitext(filename)
        normalized_filename_part = normalize_string_nfc(filename_without_ext)
        sanitized_filename = normalized_filename_part + file_extension
        
        # Build S3 key with folder structure preservation
        preserve_structure = request.POST.get('preserve_folder_structure', '') == 'true'
        
        if preserve_structure:
            # Look up path using filename as key (same as streaming upload)
            path_key = f"path_{filename}"
            relative_path = request.POST.get(path_key)
            
            if relative_path and folder_name:
                # webkitRelativePath includes the root folder name, strip it
                if '/' in relative_path:
                    clean_relative_path = relative_path.split('/', 1)[1]
                else:
                    clean_relative_path = sanitized_filename
                
                s3_key = f"{folder_name}/{clean_relative_path}"
                logger.info(f"📁 MULTIPART FOLDER: {filename} -> {s3_key}")
            else:
                # Fallback to flat structure
                s3_key = f"{folder_name}/{sanitized_filename}" if folder_name else sanitized_filename
                logger.info(f"📁 MULTIPART FLAT: {filename} -> {s3_key}")
        else:
            # Regular flat structure
            s3_key = f"{folder_name}/{sanitized_filename}" if folder_name else sanitized_filename
        
        s3_file_object = S3FileObject.objects.create(
            session=upload_session,
            file_name=sanitized_filename,
            s3_key=s3_key,
            file_size_bytes=file_size,
            content_type=content_type
        )
        
        # Initialize S3 multipart upload
        s3_client = upload_service.base_s3_service.s3_client
        
        # Prepare extra args for encryption
        extra_args = {}
        if not upload_service.base_s3_service.is_minio:
            extra_args['ServerSideEncryption'] = 'AES256'
        
        # Add metadata
        extra_args['Metadata'] = {
            'uploaded_by': request.user.username,
            'original_filename': sanitized_filename,
            'upload_method': 's3_multipart'
        }
        
        if content_type:
            extra_args['ContentType'] = content_type
        
        response = s3_client.create_multipart_upload(
            Bucket=target_bucket,
            Key=s3_key,
            **extra_args
        )
        
        upload_id = response['UploadId']
        
        logger.info(f"✅ MULTIPART INIT: Created upload_id {upload_id} for {filename}")
        
        # Store multipart info in session
        upload_session.import_stats = {
            'multipart_upload_id': upload_id,
            's3_bucket': target_bucket,
            's3_key': s3_key,
            'total_parts': 0,
            'completed_parts': []
        }
        upload_session.save()
        
        return JsonResponse({
            'success': True,
            'uploadId': upload_id,
            's3Key': s3_key,
            'bucket': target_bucket,
            'uploadSessionId': str(upload_session.id),
            's3FileObjectId': str(s3_file_object.id)
        })
        
    except Exception as e:
        logger.exception(f"Error initializing multipart upload: {str(e)}")
        return JsonResponse({
            'error': str(e)
        }, status=500)


@require_http_methods(["POST"])
@csrf_exempt  # We'll handle CSRF manually for file uploads
@general_login_required
def multipart_upload_chunk(request):
    """
    Upload a single chunk to S3 multipart upload.
    
    Expected form data:
    - uploadId: S3 multipart upload ID
    - s3Key: S3 object key
    - partNumber: Part number (1-based)
    - chunk: File chunk data
    """
    try:
        # Get form data
        upload_id = request.POST.get('uploadId')
        s3_key = request.POST.get('s3Key')
        part_number = int(request.POST.get('partNumber', 0))
        
        if not upload_id or not s3_key or part_number <= 0:
            return JsonResponse({
                'error': 'Missing required parameters'
            }, status=400)
        
        # Get chunk data
        if 'chunk' not in request.FILES:
            return JsonResponse({
                'error': 'No chunk data provided'
            }, status=400)
        
        chunk_file = request.FILES['chunk']
        chunk_size = chunk_file.size
        
        logger.info(f"📦 MULTIPART CHUNK: Part {part_number} of {s3_key} ({chunk_size} bytes)")
        
        # Find the upload session
        try:
            upload_session = UploadSession.objects.get(
                import_stats__multipart_upload_id=upload_id,
                user=request.user
            )
        except UploadSession.DoesNotExist:
            return JsonResponse({
                'error': 'Upload session not found'
            }, status=404)
        
        # Get S3 client and bucket
        upload_service = get_cached_upload_service()
        s3_client = upload_service.base_s3_service.s3_client
        bucket = upload_session.import_stats.get('s3_bucket')
        
        # Upload the part to S3
        response = s3_client.upload_part(
            Bucket=bucket,
            Key=s3_key,
            PartNumber=part_number,
            UploadId=upload_id,
            Body=chunk_file
        )
        
        etag = response['ETag']
        
        # Update session import_stats
        import_stats = upload_session.import_stats
        if 'completed_parts' not in import_stats:
            import_stats['completed_parts'] = []
        
        # Add or update this part
        completed_parts = import_stats['completed_parts']
        part_info = {'PartNumber': part_number, 'ETag': etag}
        
        # Remove any existing entry for this part number
        completed_parts = [p for p in completed_parts if p['PartNumber'] != part_number]
        completed_parts.append(part_info)
        
        import_stats['completed_parts'] = completed_parts
        import_stats['total_parts'] = max(import_stats.get('total_parts', 0), part_number)
        
        upload_session.import_stats = import_stats
        upload_session.save()
        
        logger.info(f"✅ MULTIPART CHUNK: Part {part_number} uploaded with etag {etag}")
        
        return JsonResponse({
            'success': True,
            'partNumber': part_number,
            'etag': etag,
            'completedParts': len(completed_parts)
        })
        
    except Exception as e:
        logger.exception(f"Error uploading chunk: {str(e)}")
        return JsonResponse({
            'error': str(e)
        }, status=500)


@require_http_methods(["POST"])
@general_login_required
def multipart_upload_complete(request):
    """
    Complete S3 multipart upload.
    
    Expected form data:
    - uploadId: S3 multipart upload ID
    - s3Key: S3 object key
    - parts: JSON array of parts with partNumber and etag
    """
    try:
        # Get form data
        upload_id = request.POST.get('uploadId')
        s3_key = request.POST.get('s3Key')
        parts_json = request.POST.get('parts')
        
        if not upload_id or not s3_key or not parts_json:
            return JsonResponse({
                'error': 'Missing required parameters'
            }, status=400)
        
        parts = json.loads(parts_json)
        
        logger.info(f"🏁 MULTIPART COMPLETE: {s3_key} with {len(parts)} parts")
        
        # Find the upload session
        try:
            upload_session = UploadSession.objects.get(
                import_stats__multipart_upload_id=upload_id,
                user=request.user
            )
        except UploadSession.DoesNotExist:
            return JsonResponse({
                'error': 'Upload session not found'
            }, status=404)
        
        # Get S3 client and bucket
        upload_service = get_cached_upload_service()
        s3_client = upload_service.base_s3_service.s3_client
        bucket = upload_session.import_stats.get('s3_bucket')
        
        # Normalize parts format for S3 API (ensure proper capitalization)
        normalized_parts = []
        for part in parts:
            normalized_part = {
                'PartNumber': part.get('partNumber') or part.get('PartNumber'),
                'ETag': part.get('etag') or part.get('ETag')
            }
            normalized_parts.append(normalized_part)
        
        # Sort parts by part number
        normalized_parts.sort(key=lambda x: x['PartNumber'])
        
        # Complete the multipart upload
        response = s3_client.complete_multipart_upload(
            Bucket=bucket,
            Key=s3_key,
            UploadId=upload_id,
            MultipartUpload={'Parts': normalized_parts}
        )
        
        # Mark upload session as completed
        upload_session.mark_completed()
        
        # Update S3FileObject
        try:
            s3_file_object = upload_session.files.first()
            if s3_file_object:
                s3_file_object.status = 'completed'
                s3_file_object.upload_completed_at = upload_session.completed_at
                s3_file_object.save()
        except Exception as e:
            logger.warning(f"Failed to update S3FileObject: {e}")
        
        # Clear cache to ensure fresh file listings and file counts
        from django.core.cache import cache
        if upload_session.institution:
            org_slug = upload_session.institution
            bucket_name = upload_session.import_stats.get('s3_bucket', upload_session.institution)
            
            cache_keys_to_delete = [
                f"bucket_contents_{org_slug}_",
                f"bucket_contents_{org_slug}_{upload_session.folder_name.replace('/', '_')}_",
                # Clear file count caches for data and metadata folders
                f"file_count_{bucket_name}_data_",
                f"file_count_{bucket_name}_metadata_",
                f"file_count_{bucket_name}_data",
                f"file_count_{bucket_name}_metadata"
            ]
            for cache_key in cache_keys_to_delete:
                cache.delete(cache_key)
                logger.info(f"🗑️ CACHE CLEAR: Deleted cache key: {cache_key}")
        
        logger.info(f"✅ MULTIPART COMPLETE: {s3_key} completed successfully")
        
        # Check if this is an HTMX request and return OOB updates like chunked upload
        if request.headers.get('HX-Request'):
            from arkumu.metadata.views.csv_mapping.mixins.template_helpers import CSVMappingTemplateHelperMixin
            from django.template.loader import render_to_string
            
            helper = CSVMappingTemplateHelperMixin()
            
            # Create success toast
            toast_html = render_to_string(
                "partials/toast_notification.html",
                {
                    "message": f"File {upload_session.files.first().file_name} uploaded successfully!",
                    "type": "success"
                },
                request=request
            )
            
            # OOB updates for progress, toast and file browser refresh
            oob_updates = {
                'upload-status': '',  # Clear status
                'upload-progress': '<div class="mt-4 hidden"></div>',  # Hide progress  
                'toast-container': toast_html
            }
            
            # Add file browser refresh if we have an organization
            if upload_session.institution:
                # Small delay and cache clearing like chunked upload
                import time as time_module
                time_module.sleep(0.5)
                
                file_browser_html = helper.render_file_browser_template(request, upload_session.institution)
                oob_updates['file-browser-content'] = file_browser_html
                logger.info(f"🔄 MULTIPART OOB: Added file browser refresh for {upload_session.institution}")
            
            # Return HTMX response with OOB updates
            response_html = helper.build_oob_response('', oob_updates)
            return HttpResponse(response_html)
        else:
            # Fallback JSON response for non-HTMX requests
            return JsonResponse({
                'success': True,
                'location': response.get('Location'),
                'etag': response.get('ETag'),
                'bucket': bucket,
                's3Key': s3_key,
                'uploadSessionId': str(upload_session.id),
                'organization': upload_session.institution
            })
        
    except Exception as e:
        logger.exception(f"Error completing multipart upload: {str(e)}")
        return JsonResponse({
            'error': str(e)
        }, status=500)


@require_http_methods(["POST"])
@general_login_required  
def multipart_upload_abort(request):
    """
    Abort S3 multipart upload.
    
    Expected form data:
    - uploadId: S3 multipart upload ID
    - s3Key: S3 object key
    """
    try:
        upload_id = request.POST.get('uploadId')
        s3_key = request.POST.get('s3Key')
        
        if not upload_id or not s3_key:
            return JsonResponse({
                'error': 'Missing required parameters'
            }, status=400)
        
        logger.info(f"🛑 MULTIPART ABORT: {s3_key}")
        
        # Find the upload session
        try:
            upload_session = UploadSession.objects.get(
                import_stats__multipart_upload_id=upload_id,
                user=request.user
            )
        except UploadSession.DoesNotExist:
            return JsonResponse({
                'error': 'Upload session not found'
            }, status=404)
        
        # Get S3 client and bucket
        upload_service = get_cached_upload_service()
        s3_client = upload_service.base_s3_service.s3_client
        bucket = upload_session.import_stats.get('s3_bucket')
        
        # Abort the multipart upload
        s3_client.abort_multipart_upload(
            Bucket=bucket,
            Key=s3_key,
            UploadId=upload_id
        )
        
        # Mark upload session as failed
        upload_session.mark_failed("Multipart upload aborted")
        
        logger.info(f"✅ MULTIPART ABORT: {s3_key} aborted successfully")
        
        return JsonResponse({
            'success': True
        })
        
    except Exception as e:
        logger.exception(f"Error aborting multipart upload: {str(e)}")
        return JsonResponse({
            'error': str(e)
        }, status=500)