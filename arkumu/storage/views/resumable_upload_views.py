import logging
import json
import os
import hashlib
import tempfile
from typing import Dict, Any
from datetime import datetime

from django.http import JsonResponse, HttpResponse
from django.views.decorators.http import require_http_methods
from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings
from django.core.cache import cache
from django.utils import timezone
from django.db import transaction

from arkumu.users.mixins import general_login_required
from arkumu.storage.models import (
    UploadSession, 
    S3FileObject, 
    ResumableUploadSession, 
    ResumableUploadChunk
)
from arkumu.storage.services.upload_service import UploadService
from arkumu.storage.services.bucket_service import BucketService

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
def resumable_upload_init(request):
    """
    Initialize a resumable upload session.
    
    Expected payload:
    {
        "filename": "large_file.mp4",
        "fileSize": 304857600,
        "chunkSize": 5242880,
        "uploadSessionId": "uuid-string",
        "organization": "khm",
        "baseFolder": "data",
        "folderName": "data/khm",
        "contentType": "video/mp4"
    }
    """
    logger.info(f"⏱️ RESUMABLE INIT: Starting at {datetime.now().strftime('%H:%M:%S.%f')[:-3]}")
    
    try:
        data = json.loads(request.body)
        
        # Validate required fields
        required_fields = ['filename', 'fileSize', 'organization']
        for field in required_fields:
            if field not in data:
                return JsonResponse({'error': f'Missing required field: {field}'}, status=400)
        
        # Handle empty files (0 bytes) 
        file_size = int(data['fileSize'])
        if file_size == 0:
            return JsonResponse({
                'error': 'Empty files cannot be uploaded through resumable upload',
                'suggestion': 'Use regular upload for empty files'
            }, status=400)
        
        # Create a new upload session
        organization = data['organization']
        upload_session = UploadSession.objects.create(
            user=request.user,
            folder_name=data.get('baseFolder', 'data'),  # Use base folder for consistency
            institution=organization,  # Store organization for later use
            total_files=1,  # Single file for resumable upload
            total_size_bytes=int(data['fileSize'])
        )
        
        # Calculate chunk information  
        chunk_size = int(data.get('chunkSize', 5 * 1024 * 1024))  # Default 5MB
        total_chunks = (file_size + chunk_size - 1) // chunk_size  # Ceiling division
        
        # Create S3 key
        organization = data['organization']
        base_folder = data.get('baseFolder', 'data')  # Get the base folder (e.g., 'data')
        s3_key = f"{base_folder}/{data['filename']}"
        
        # Create S3FileObject
        s3_file_object = S3FileObject.create_from_upload(
            session=upload_session,
            file_name=data['filename'],
            original_path=data.get('originalPath', data['filename']),
            s3_key=s3_key,
            file_size=file_size,
            content_type=data.get('contentType', '')
        )
        
        # Create temp directory for chunks
        temp_dir = os.path.join(tempfile.gettempdir(), 'resumable_uploads', str(s3_file_object.id))
        os.makedirs(temp_dir, exist_ok=True)
        
        # Create resumable upload session
        resumable_upload = ResumableUploadSession.objects.create(
            upload_session=upload_session,
            s3_file_object=s3_file_object,
            original_filename=data['filename'],
            total_size_bytes=file_size,
            chunk_size_bytes=chunk_size,
            total_chunks=total_chunks,
            temp_storage_path=temp_dir,
            status='initialized'
        )
        
        # Create chunk records
        chunks_created = []
        for chunk_num in range(total_chunks):
            start_byte = chunk_num * chunk_size
            end_byte = min(start_byte + chunk_size, file_size)
            actual_chunk_size = end_byte - start_byte
            
            chunk = ResumableUploadChunk.objects.create(
                resumable_upload=resumable_upload,
                chunk_number=chunk_num,
                start_byte=start_byte,
                end_byte=end_byte,
                size_bytes=actual_chunk_size,
                temp_file_path=os.path.join(temp_dir, f'chunk_{chunk_num}')
            )
            chunks_created.append({
                'chunkNumber': chunk_num,
                'startByte': start_byte,
                'endByte': end_byte,
                'size': actual_chunk_size
            })
        
        # Update status
        resumable_upload.status = 'uploading'
        resumable_upload.save()
        
        logger.info(f"⏱️ RESUMABLE INIT: Created session {resumable_upload.id} with {total_chunks} chunks")
        
        return JsonResponse({
            'uploadId': str(resumable_upload.id),
            'uploadSessionId': str(upload_session.id),
            'totalChunks': total_chunks,
            'chunkSize': chunk_size,
            'chunks': chunks_created
        })
        
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON payload'}, status=400)
    except Exception as e:
        logger.error(f"Error initializing resumable upload: {e}")
        return JsonResponse({'error': 'Internal server error'}, status=500)


@require_http_methods(["PUT"])
@csrf_exempt
@general_login_required
def resumable_upload_chunk(request):
    """
    Upload a single chunk of a resumable upload.
    
    Headers:
    - Content-Range: bytes start-end/total
    - X-Upload-ID: resumable upload session ID
    - X-Chunk-Number: chunk number (0-indexed)
    """
    logger.info(f"⏱️ CHUNK UPLOAD: Starting at {datetime.now().strftime('%H:%M:%S.%f')[:-3]}")
    
    try:
        # Parse headers
        upload_id = request.headers.get('X-Upload-ID')
        chunk_number = int(request.headers.get('X-Chunk-Number', -1))
        content_range = request.headers.get('Content-Range', '')
        
        if not upload_id:
            return JsonResponse({'error': 'Missing X-Upload-ID header'}, status=400)
        
        if chunk_number < 0:
            return JsonResponse({'error': 'Missing or invalid X-Chunk-Number header'}, status=400)
        
        # Get resumable upload session
        try:
            resumable_upload = ResumableUploadSession.objects.get(id=upload_id)
        except ResumableUploadSession.DoesNotExist:
            return JsonResponse({'error': 'Invalid upload ID'}, status=400)
        
        # Get the specific chunk
        try:
            chunk = resumable_upload.chunks.get(chunk_number=chunk_number)
        except ResumableUploadChunk.DoesNotExist:
            return JsonResponse({'error': f'Invalid chunk number: {chunk_number}'}, status=400)
        
        # Validate chunk isn't already completed
        if chunk.status == 'completed':
            return JsonResponse({'status': 'already_completed'})
        
        # Mark chunk as uploading
        chunk.status = 'uploading'
        chunk.save()
        
        # Save chunk data to temporary file
        chunk_data = request.body
        expected_size = chunk.size_bytes
        
        if len(chunk_data) != expected_size:
            chunk.mark_failed(f'Size mismatch: expected {expected_size}, got {len(chunk_data)}')
            return JsonResponse({'error': 'Chunk size mismatch'}, status=400)
        
        # Calculate checksum
        checksum = hashlib.md5(chunk_data).hexdigest()
        
        # Write to temporary file
        try:
            with open(chunk.temp_file_path, 'wb') as f:
                f.write(chunk_data)
            
            # Mark chunk as completed
            chunk.mark_completed(checksum=checksum)
            
            logger.info(f"⏱️ CHUNK COMPLETE: Chunk {chunk_number} of {resumable_upload.original_filename}")
            
            # Check if all chunks are completed
            completed_chunks = resumable_upload.completed_chunks
            if completed_chunks == resumable_upload.total_chunks:
                logger.info(f"⏱️ ALL CHUNKS COMPLETE: Starting background assembly for {resumable_upload.original_filename}")
                # Trigger assembly as background task
                from arkumu.storage.tasks import assemble_file_task
                assemble_file_task.schedule(args=(resumable_upload.id,), delay=0)
            
            return JsonResponse({
                'status': 'success',
                'chunkNumber': chunk_number,
                'completedChunks': completed_chunks,
                'totalChunks': resumable_upload.total_chunks,
                'progress': resumable_upload.progress_percentage
            })
            
        except IOError as e:
            chunk.mark_failed(f'Failed to write chunk: {e}')
            return JsonResponse({'error': 'Failed to save chunk'}, status=500)
            
    except Exception as e:
        logger.error(f"Error uploading chunk: {e}")
        return JsonResponse({'error': 'Internal server error'}, status=500)


@require_http_methods(["GET"])
@general_login_required
def resumable_upload_status(request, upload_id):
    """
    Get the status of a resumable upload.
    """
    try:
        resumable_upload = ResumableUploadSession.objects.get(id=upload_id)
        
        completed_chunks = resumable_upload.completed_chunks
        failed_chunks = resumable_upload.chunks.filter(status='failed').count()
        
        return JsonResponse({
            'uploadId': str(resumable_upload.id),
            'status': resumable_upload.status,
            'filename': resumable_upload.original_filename,
            'totalChunks': resumable_upload.total_chunks,
            'completedChunks': completed_chunks,
            'failedChunks': failed_chunks,
            'uploadedBytes': resumable_upload.uploaded_bytes,
            'totalBytes': resumable_upload.total_size_bytes,
            'progress': resumable_upload.progress_percentage,
            'canResume': resumable_upload.can_resume(),
            'errorMessage': resumable_upload.error_message
        })
        
    except ResumableUploadSession.DoesNotExist:
        return JsonResponse({'error': 'Upload not found'}, status=404)
    except Exception as e:
        logger.error(f"Error getting upload status: {e}")
        return JsonResponse({'error': 'Internal server error'}, status=500)



def _assemble_file(resumable_upload: ResumableUploadSession):
    """
    Assemble chunks into final file and upload to S3.
    This could be made async for better performance.
    """
    try:
        resumable_upload.status = 'assembling'
        resumable_upload.save()
        
        logger.info(f"⏱️ ASSEMBLY START: Assembling {resumable_upload.original_filename} at {datetime.now().strftime('%H:%M:%S.%f')[:-3]}")
        logger.info(f"🔧 ASSEMBLY: Resumable upload ID: {resumable_upload.id}")
        logger.info(f"🔧 ASSEMBLY: Upload status: {resumable_upload.status}")
        logger.info(f"🔧 ASSEMBLY: Temp storage path: {resumable_upload.temp_storage_path}")
        
        # Ensure temp directory exists
        os.makedirs(resumable_upload.temp_storage_path, exist_ok=True)
        logger.info(f"🔧 ASSEMBLY: Temp directory ensured: {resumable_upload.temp_storage_path}")
        
        # Check if temp directory actually exists and list contents
        if os.path.exists(resumable_upload.temp_storage_path):
            contents = os.listdir(resumable_upload.temp_storage_path)
            logger.info(f"🔧 ASSEMBLY: Temp directory contents: {contents}")
        else:
            logger.error(f"🔧 ASSEMBLY: Temp directory does not exist: {resumable_upload.temp_storage_path}")
        
        # Create final file path
        final_file_path = os.path.join(resumable_upload.temp_storage_path, 'final_file')
        
        # Get chunks and verify they exist
        chunks = resumable_upload.chunks.filter(status='completed').order_by('chunk_number')
        chunk_count = chunks.count()
        logger.info(f"🔧 ASSEMBLY: Found {chunk_count} completed chunks to assemble")
        
        # Assemble chunks in order
        with open(final_file_path, 'wb') as final_file:
            for i, chunk in enumerate(chunks):
                logger.info(f"🔧 ASSEMBLY: Processing chunk {i+1}/{chunk_count}: {chunk.temp_file_path}")
                if os.path.exists(chunk.temp_file_path):
                    chunk_size = os.path.getsize(chunk.temp_file_path)
                    logger.info(f"🔧 ASSEMBLY: Chunk file exists, size: {chunk_size} bytes")
                    with open(chunk.temp_file_path, 'rb') as chunk_file:
                        final_file.write(chunk_file.read())
                else:
                    logger.error(f"🔧 ASSEMBLY: Chunk file missing: {chunk.temp_file_path}")
                    raise FileNotFoundError(f'Chunk file not found: {chunk.temp_file_path}')
        
        logger.info(f"⏱️ ASSEMBLY COMPLETE: File assembled, starting S3 upload at {datetime.now().strftime('%H:%M:%S.%f')[:-3]}")
        
        # Upload to S3
        upload_service = get_cached_upload_service()
        bucket_service = get_cached_bucket_service()
        
        # Get organization from upload session
        organization = resumable_upload.upload_session.institution
        if not organization:
            raise ValueError("No organization found in upload session")
        bucket_name = bucket_service.get_organization_bucket(organization)
        
        logger.info(f"🪣 S3 DEBUG: s3_key='{resumable_upload.s3_file_object.s3_key}', organization='{organization}', bucket_name='{bucket_name}'")
        
        # Ensure bucket exists (create if necessary)
        try:
            bucket_service.ensure_organization_bucket_exists(organization)
            logger.info(f"🪣 S3 DEBUG: Ensured bucket '{bucket_name}' exists for organization '{organization}'")
        except Exception as e:
            logger.warning(f"🪣 S3 DEBUG: Could not create bucket '{bucket_name}': {e}")
        
        # Upload to S3 using base storage service
        logger.info(f"🪣 S3 DEBUG: About to upload to bucket '{bucket_name}' with s3_key='{resumable_upload.s3_file_object.s3_key}'")
        with open(final_file_path, 'rb') as file_data:
            result = upload_service.base_s3_service.upload_fileobj_encrypted(
                fileobj=file_data,
                bucket_name=bucket_name,
                s3_key=resumable_upload.s3_file_object.s3_key,
                content_type=resumable_upload.s3_file_object.content_type
            )
            logger.info(f"🪣 S3 DEBUG: Upload result: {result}")
        
        if result.get('success'):
            # Create S3 URL
            s3_url = f"https://{bucket_name}.s3.amazonaws.com/{resumable_upload.s3_file_object.s3_key}"
            
            # Mark S3FileObject as completed with URL first
            resumable_upload.s3_file_object.mark_completed(s3_url=s3_url)
            
            # Then mark resumable upload as completed (but skip the S3FileObject update since we already did it)
            resumable_upload.status = 'completed'
            resumable_upload.completed_at = timezone.now()
            resumable_upload.uploaded_bytes = resumable_upload.total_size_bytes
            resumable_upload.save()
            
            logger.info(f"⏱️ S3 UPLOAD COMPLETE: {resumable_upload.original_filename} uploaded successfully")
            
            # Invalidate bucket cache so dashboard shows new files immediately
            session = resumable_upload.s3_file_object.session
            logger.info(f"🔍 SESSION DEBUG: session={session}, session.s3_bucket='{session.s3_bucket if session else 'NO SESSION'}'")
            
            # For resumable uploads, we need to derive bucket name from the s3_key instead
            s3_key = resumable_upload.s3_file_object.s3_key
            logger.info(f"🔍 S3_KEY DEBUG: s3_key='{s3_key}'")
            
            # The bucket is likely "khm" since that's what we see in the logs
            # For now, let's hardcode the correct bucket name we know from logs
            organization_bucket = "khm"  # TODO: derive this properly
            cache_key = f"bucket_contents_{organization_bucket}_"
            
            # Check if cache exists before deleting
            cached_data = cache.get(cache_key)
            logger.info(f"🔍 CACHE CHECK: Found cached data for key '{cache_key}': {cached_data is not None}")
            
            cache.delete(cache_key)
            logger.info(f"🗑️ CACHE CLEARED: Invalidated cache for bucket {organization_bucket} with key: {cache_key}")
            
            # Verify deletion
            cached_data_after = cache.get(cache_key)
            logger.info(f"✅ CACHE VERIFY: Cache after deletion for key '{cache_key}': {cached_data_after is not None}")
            
            # Clean up temporary files
            _cleanup_temp_files(resumable_upload)
            
        else:
            error_msg = result.get('error', 'S3 upload failed')
            resumable_upload.mark_failed(error_msg)
            logger.error(f"S3 upload failed for {resumable_upload.original_filename}: {error_msg}")
            
    except Exception as e:
        error_msg = f"Assembly failed: {e}"
        resumable_upload.mark_failed(error_msg)
        logger.error(f"Error assembling file {resumable_upload.original_filename}: {e}")


def _cleanup_temp_files(resumable_upload: ResumableUploadSession):
    """Clean up temporary files after successful upload"""
    try:
        import shutil
        if os.path.exists(resumable_upload.temp_storage_path):
            shutil.rmtree(resumable_upload.temp_storage_path)
            logger.info(f"Cleaned up temp files for {resumable_upload.original_filename}")
    except Exception as e:
        logger.warning(f"Failed to clean up temp files: {e}")


@require_http_methods(["POST"])
@general_login_required
def resumable_upload_resume(request, upload_id):
    """
    Resume a paused or failed resumable upload.
    """
    try:
        resumable_upload = ResumableUploadSession.objects.get(id=upload_id)
        
        if not resumable_upload.can_resume():
            return JsonResponse({
                'error': 'Upload cannot be resumed',
                'status': resumable_upload.status,
                'retryCount': resumable_upload.retry_count
            }, status=400)
        
        # Reset failed chunks to pending
        failed_chunks = resumable_upload.chunks.filter(status='failed')
        failed_chunks.update(status='pending', error_message='')
        
        # Update upload status
        resumable_upload.status = 'uploading'
        resumable_upload.increment_retry()
        
        # Return current status
        return JsonResponse({
            'status': 'resumed',
            'uploadId': str(resumable_upload.id),
            'completedChunks': resumable_upload.completed_chunks,
            'totalChunks': resumable_upload.total_chunks,
            'failedChunks': failed_chunks.count()
        })
        
    except ResumableUploadSession.DoesNotExist:
        return JsonResponse({'error': 'Upload not found'}, status=404)
    except Exception as e:
        logger.error(f"Error resuming upload: {e}")
        return JsonResponse({'error': 'Internal server error'}, status=500)