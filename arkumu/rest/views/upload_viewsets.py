"""
Upload API ViewSets for REST endpoints.

This module provides REST API endpoints for upload functionality using the existing
upload services from arkumu.storage.services.upload.
"""

import logging
from typing import Dict, Any, List

from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.authentication import SessionAuthentication, TokenAuthentication
from django.contrib.auth.decorators import login_required
from django.utils.decorators import method_decorator

from arkumu.storage.tasks import verify_upload_session
from arkumu.storage.services.upload_service import UploadService
from arkumu.storage.services.upload import upload_utils
from arkumu.storage.services.async_upload_manager import AsyncUploadManager

logger = logging.getLogger(__name__)


class UploadViewSet(viewsets.ViewSet):
    """
    REST API ViewSet for upload operations.
    
    Provides endpoints for:
    - Batch presigned URL generation
    - Upload validation
    - Multipart upload management
    
    Authentication is handled via session authentication for HTMX requests
    and can be extended to support token authentication for API clients.
    """
    
    authentication_classes = [SessionAuthentication, TokenAuthentication]
    permission_classes = [IsAuthenticated]
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.upload_service = UploadService()
    
    def _extract_org_from_folder(self, folder_path):
        """Extract organization from folder path like 'data/organization'"""
        if not folder_path:
            return ''
        parts = folder_path.split('/')
        return parts[1] if len(parts) > 1 else parts[0]
    
    def _extract_base_folder_from_folder(self, folder_path):
        """Extract base folder (data/metadata) from folder path like 'data/organization'"""
        if not folder_path:
            return ''
        parts = folder_path.split('/')
        return parts[0] if len(parts) > 0 else ''
    
    @action(detail=False, methods=['post'], url_path='batch-presigned-urls')
    def batch_presigned_urls(self, request):
        """
        Enhanced batch presigned URL generation with async tracking.
        
        POST /api/rest/upload/batch-presigned-urls/
        
        Request body:
        {
            "files": [
                {
                    "name": "document.pdf",
                    "size": 1024000,
                    "type": "application/pdf",
                    "relativePath": "folder/document.pdf"  # Optional
                },
                {
                    "name": "image.jpg", 
                    "size": 512000,
                    "type": "image/jpeg"
                }
            ],
            "folder": "data/organization" or "metadata/organization"
        }
        
        Response:
        {
            "session_id": "uuid-session-id",
            "success": true,
            "uploads": [
                {
                    "file_id": "uuid-file-id",
                    "filename": "document.pdf",
                    "type": "single",
                    "url": "https://s3.presigned.url",
                    "fields": {...},
                    "s3_key": "uploads/document.pdf"
                }
            ],
            "errors": []
        }
        """
        logger.info(f"🔗 ASYNC_BATCH_PRESIGNED_URLS: user={request.user.id}")
        
        try:
            files_data = request.data.get('files', [])
            folder = request.data.get('folder', '')
            
            if not files_data:
                return Response({'error': 'No files provided'}, status=400)
            
            manager = AsyncUploadManager()

            try:
                batch_result = manager.prepare_presigned_uploads(
                    user=request.user,
                    files=files_data,
                    folder=folder,
                    organization=self._extract_org_from_folder(folder),
                )
            except ValueError as exc:
                logger.error(f"❌ Invalid async upload request: {exc}")
                return Response({'success': False, 'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

            response_payload = {
                'session_id': str(batch_result.session.id),
                'uploads': batch_result.uploads,
                'errors': batch_result.errors,
                'success': batch_result.success,
            }

            return Response(response_payload)
            
        except Exception as e:
            logger.error(f"❌ ASYNC_BATCH_PRESIGNED_URLS: Unexpected error: {str(e)}")
            return Response({
                'success': False,
                'error': 'Internal server error'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    @action(detail=False, methods=['post'], url_path='multipart-part-urls')
    def multipart_part_urls(self, request):
        """
        Generate presigned URLs for multipart upload parts.
        
        POST /api/rest/upload/multipart-part-urls/
        
        Request body:
        {
            "s3_key": "uploads/largefile.zip",
            "upload_id": "abc123",
            "part_numbers": [1, 2, 3, 4, 5]
        }
        
        Response:
        {
            "success": true,
            "part_urls": {
                "1": "https://s3.presigned.url/part1",
                "2": "https://s3.presigned.url/part2",
                ...
            }
        }
        """
        logger.info(f"🔗 MULTIPART_PART_URLS: user={request.user.id}")
        
        try:
            s3_key = request.data.get('s3_key')
            upload_id = request.data.get('upload_id')
            part_numbers = request.data.get('part_numbers', [])
            
            if not all([s3_key, upload_id, part_numbers]):
                return Response({
                    'success': False,
                    'error': 'Missing required fields: s3_key, upload_id, part_numbers'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            result = self.upload_service.generate_presigned_multipart_urls(
                s3_key=s3_key,
                upload_id=upload_id,
                part_numbers=part_numbers
            )
            
            logger.info(f"📤 Generated URLs for {len(part_numbers)} parts")
            return Response(result)
            
        except Exception as e:
            logger.error(f"❌ MULTIPART_PART_URLS: Error: {str(e)}")
            return Response({
                'success': False,
                'error': 'Internal server error'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    @action(detail=False, methods=['post'], url_path='complete-multipart')
    def complete_multipart(self, request):
        """
        Complete a multipart upload.
        
        POST /api/rest/upload/complete-multipart/
        
        Request body:
        {
            "s3_key": "uploads/largefile.zip",
            "upload_id": "abc123",
            "parts": [
                {"PartNumber": 1, "ETag": "etag1"},
                {"PartNumber": 2, "ETag": "etag2"}
            ]
        }
        
        Response:
        {
            "success": true,
            "location": "https://bucket.s3.amazonaws.com/uploads/largefile.zip"
        }
        """
        logger.info(f"🔗 COMPLETE_MULTIPART: user={request.user.id}")
        
        try:
            s3_key = request.data.get('s3_key')
            upload_id = request.data.get('upload_id')
            parts = request.data.get('parts', [])
            
            if not all([s3_key, upload_id, parts]):
                return Response({
                    'success': False,
                    'error': 'Missing required fields: s3_key, upload_id, parts'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            result = self.upload_service.complete_multipart_upload(
                s3_key=s3_key,
                upload_id=upload_id,
                parts=parts
            )
            
            logger.info(f"✅ Completed multipart upload for {s3_key}")
            return Response(result)
            
        except Exception as e:
            logger.error(f"❌ COMPLETE_MULTIPART: Error: {str(e)}")
            return Response({
                'success': False,
                'error': 'Internal server error'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    @action(detail=False, methods=['post'], url_path='abort-multipart')
    def abort_multipart(self, request):
        """
        Abort a multipart upload.
        
        POST /api/rest/upload/abort-multipart/
        
        Request body:
        {
            "s3_key": "uploads/largefile.zip",
            "upload_id": "abc123"
        }
        
        Response:
        {
            "success": true
        }
        """
        logger.info(f"🔗 ABORT_MULTIPART: user={request.user.id}")
        
        try:
            s3_key = request.data.get('s3_key')
            upload_id = request.data.get('upload_id')
            
            if not all([s3_key, upload_id]):
                return Response({
                    'success': False,
                    'error': 'Missing required fields: s3_key, upload_id'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            result = self.upload_service.abort_multipart_upload(
                s3_key=s3_key,
                upload_id=upload_id
            )
            
            logger.info(f"🚫 Aborted multipart upload for {s3_key}")
            return Response(result)
            
        except Exception as e:
            logger.error(f"❌ ABORT_MULTIPART: Error: {str(e)}")
            return Response({
                'success': False,
                'error': 'Internal server error'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    @action(detail=False, methods=['post'], url_path='confirm')
    def confirm_upload(self, request):
        """
        Confirm a successful upload and trigger any post-upload processing.
        
        POST /api/rest/upload/confirm/
        
        Request body:
        {
            "filename": "document.pdf",
            "s3_key": "uploads/document.pdf",
            "file_size": 1024000,
            "content_type": "application/pdf"
        }
        
        Response:
        {
            "success": true,
            "message": "Upload confirmed"
        }
        """
        logger.info(f"🔗 CONFIRM_UPLOAD: user={request.user.id}")
        
        try:
            filename = request.data.get('filename')
            s3_key = request.data.get('s3_key')
            file_size = request.data.get('file_size')
            content_type = request.data.get('content_type')
            
            if not all([filename, s3_key]):
                return Response({
                    'success': False,
                    'error': 'Missing required fields: filename, s3_key'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Get file info from S3 to verify upload
            try:
                file_info = self.upload_service.get_file_info(s3_key)
                if file_info.get('success'):
                    logger.info(f"✅ Upload confirmed: {filename} -> {s3_key} ({file_info.get('file_size', 0)} bytes)")
                    
                    # Here you could add additional post-upload processing:
                    # - Log to database
                    # - Trigger async processing tasks
                    # - Send notifications
                    # - Update user quotas
                    
                    return Response({
                        'success': True,
                        'message': f'Upload of {filename} confirmed',
                        'file_info': file_info
                    })
                else:
                    return Response({
                        'success': False,
                        'error': 'File not found in S3 after upload'
                    }, status=status.HTTP_404_NOT_FOUND)
                    
            except Exception as e:
                logger.error(f"❌ Error verifying upload: {str(e)}")
                return Response({
                    'success': False,
                    'error': 'Could not verify upload'
                }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            
        except Exception as e:
            logger.error(f"❌ CONFIRM_UPLOAD: Error: {str(e)}")
            return Response({
                'success': False,
                'error': 'Internal server error'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    @action(detail=False, methods=['post'], url_path='validate')
    def validate_files(self, request):
        """
        Validate file upload requests without generating URLs.
        
        POST /api/rest/upload/validate/
        
        Request body:
        {
            "files": [
                {
                    "name": "document.pdf",
                    "size": 1024000,
                    "type": "application/pdf"
                }
            ]
        }
        
        Response:
        {
            "success": true,
            "results": [
                {
                    "filename": "document.pdf",
                    "valid": true,
                    "should_use_multipart": false,
                    "warnings": []
                }
            ]
        }
        """
        logger.info(f"🔗 VALIDATE_FILES: user={request.user.id}")
        
        try:
            files = request.data.get('files', [])
            
            if not files:
                return Response({
                    'success': False,
                    'error': 'No files provided'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            results = []
            
            for file_info in files:
                filename = file_info.get('name')
                file_size = file_info.get('size', 0)
                content_type = file_info.get('type', 'application/octet-stream')
                
                validation = self.upload_service.validate_upload_request(
                    file_name=filename,
                    file_size=file_size,
                    content_type=content_type,
                    user_id=request.user.id
                )
                
                results.append({
                    'filename': filename,
                    'valid': validation['valid'],
                    'should_use_multipart': validation['should_use_multipart'],
                    'errors': validation.get('errors', []),
                    'warnings': validation.get('warnings', [])
                })
            
            return Response({
                'success': True,
                'results': results
            })
            
        except Exception as e:
            logger.error(f"❌ VALIDATE_FILES: Error: {str(e)}")
            return Response({
                'success': False,
                'error': 'Internal server error'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    @action(detail=False, methods=['post'], url_path='upload-complete')
    def notify_upload_complete(self, request):
        """Notify server that client has completed uploading a file"""
        file_id = request.data.get('file_id')
        session_id = request.data.get('session_id')
        
        if not file_id or not session_id:
            return Response({'error': 'file_id and session_id required'}, status=400)
        
        try:
            from arkumu.storage.models.upload_tracking import AsyncUploadFile

            upload_file = AsyncUploadFile.objects.get(
                id=file_id,
                session_id=session_id,
            )

            upload_file.mark_uploaded()

            session = upload_file.session
            if session.status not in ('uploading', 'processing', 'completed', 'failed'):
                session.mark_uploading()

            all_uploaded = not session.files.exclude(status__in=['uploaded', 'completed', 'failed']).exists()
            if all_uploaded and session.status != 'processing':
                session.mark_processing()
                verify_upload_session(str(session.id))

            return Response({'status': session.status})

        except AsyncUploadFile.DoesNotExist:
            return Response({'error': 'Upload file not found'}, status=404)

    @action(detail=False, methods=['get'], url_path='session-status/(?P<session_id>[^/.]+)')
    def session_status(self, request, session_id):
        """Get upload session status for polling"""
        try:
            from arkumu.storage.models.upload_tracking import AsyncUploadSession
            session = AsyncUploadSession.objects.get(id=session_id, user=request.user)
            
            files_status = []
            for upload_file in session.files.all():
                files_status.append({
                    'filename': upload_file.filename,
                    'status': upload_file.status,
                    'error': upload_file.error_message
                })
            
            return Response({
                'session_id': str(session.id),
                'status': session.status,
                'progress': session.progress_percentage,
                'total_files': session.total_files,
                'completed_files': session.completed_files,
                'failed_files': session.failed_files,
                'files': files_status,
                'organization': session.organization,
                'error': session.error_message
            })
            
        except AsyncUploadSession.DoesNotExist:
            return Response({'error': 'Session not found'}, status=404)
