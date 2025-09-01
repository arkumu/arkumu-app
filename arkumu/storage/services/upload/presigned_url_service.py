"""
Presigned URL Service for direct browser-to-S3 uploads.
Generates secure, time-limited URLs for direct uploads.
"""
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
import json

from ..base_storage_service import BaseStorageService

logger = logging.getLogger(__name__)


class PresignedURLService:
    """Service for generating presigned URLs for S3 operations."""
    
    def __init__(self):
        """Initialize with singleton BaseStorageService."""
        self.base_service = BaseStorageService()
        # Use presigned_client for browser-accessible URLs instead of s3_client
        self.s3_client = getattr(self.base_service, 'presigned_client', self.base_service.s3_client)
        logger.info(f"🔗 PresignedURLService initialized with client endpoint: {getattr(self.s3_client, '_endpoint', 'Unknown')}")
        
    def generate_upload_url(
        self, 
        key: str, 
        bucket_name: Optional[str] = None,
        content_type: Optional[str] = None,
        metadata: Optional[Dict] = None,
        expiry: Optional[int] = None,
        max_file_size: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Generate presigned POST URL for direct upload.
        
        Args:
            key: S3 object key
            bucket_name: Target bucket (uses default if None)
            content_type: Expected content type
            metadata: Custom metadata to attach
            expiry: URL expiration in seconds (default: 3600)
            max_file_size: Maximum allowed file size in bytes
            
        Returns:
            Dict containing URL and required fields for upload
        """
        try:
            bucket_name = bucket_name or self.base_service.production_bucket
            expiry = expiry or 3600  # Default 1 hour
            
            conditions = []
            fields = {}
            
            # Add content type condition
            if content_type:
                conditions.append({"Content-Type": content_type})
                fields["Content-Type"] = content_type
            
            # Add file size limit
            if max_file_size:
                conditions.append(["content-length-range", 0, max_file_size])
            
            # Add metadata
            if metadata:
                for k, v in metadata.items():
                    key_name = f"x-amz-meta-{k}"
                    fields[key_name] = str(v)
                    conditions.append({key_name: str(v)})
            
            # Add server-side encryption if not MinIO
            if not self.base_service.is_minio:
                fields["x-amz-server-side-encryption"] = "AES256"
                conditions.append({"x-amz-server-side-encryption": "AES256"})
            
            # Generate presigned POST data
            response = self.s3_client.generate_presigned_post(
                Bucket=bucket_name,
                Key=key,
                Fields=fields,
                Conditions=conditions,
                ExpiresIn=expiry
            )
            
            logger.info(f"Generated presigned URL for {key} in {bucket_name}, expires in {expiry}s")
            
            return {
                'success': True,
                'url': response['url'],
                'fields': response['fields'],
                'key': key,
                'bucket': bucket_name,
                'expires_at': (datetime.now() + timedelta(seconds=expiry)).isoformat(),
                'max_file_size': max_file_size
            }
            
        except Exception as e:
            logger.error(f"Error generating presigned URL for {key}: {str(e)}")
            return {
                'success': False,
                'error': str(e)
            }
    
    def generate_multipart_urls(
        self,
        key: str,
        upload_id: str,
        parts: List[int],
        bucket_name: Optional[str] = None,
        expiry: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Generate presigned URLs for multipart upload parts.
        
        Args:
            key: S3 object key
            upload_id: Multipart upload ID
            parts: List of part numbers to generate URLs for
            bucket_name: Target bucket
            expiry: URL expiration in seconds
            
        Returns:
            Dict containing URLs for each part
        """
        try:
            bucket_name = bucket_name or self.base_service.production_bucket
            expiry = expiry or 3600
            
            urls = []
            for part_number in parts:
                url = self.s3_client.generate_presigned_url(
                    'upload_part',
                    Params={
                        'Bucket': bucket_name,
                        'Key': key,
                        'UploadId': upload_id,
                        'PartNumber': part_number
                    },
                    ExpiresIn=expiry
                )
                urls.append({
                    'part_number': part_number,
                    'presigned_url': url
                })
            
            logger.info(f"Generated {len(urls)} presigned URLs for multipart upload {upload_id}")
            
            return {
                'success': True,
                'upload_id': upload_id,
                'presigned_urls': urls,
                'key': key,
                'bucket': bucket_name,
                'expires_at': (datetime.now() + timedelta(seconds=expiry)).isoformat()
            }
            
        except Exception as e:
            logger.error(f"Error generating multipart URLs: {str(e)}")
            return {
                'success': False,
                'error': str(e)
            }
    
    def generate_download_url(
        self,
        key: str,
        bucket_name: Optional[str] = None,
        expiry: Optional[int] = None,
        response_content_disposition: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Generate presigned URL for downloading an object.
        
        Args:
            key: S3 object key
            bucket_name: Source bucket
            expiry: URL expiration in seconds
            response_content_disposition: Set Content-Disposition header
            
        Returns:
            Dict containing download URL
        """
        try:
            bucket_name = bucket_name or self.base_service.production_bucket
            expiry = expiry or 3600
            
            params = {
                'Bucket': bucket_name,
                'Key': key
            }
            
            if response_content_disposition:
                params['ResponseContentDisposition'] = response_content_disposition
            
            url = self.s3_client.generate_presigned_url(
                'get_object',
                Params=params,
                ExpiresIn=expiry
            )
            
            logger.info(f"Generated download URL for {key} in {bucket_name}")
            
            return {
                'success': True,
                'url': url,
                'key': key,
                'bucket': bucket_name,
                'expires_at': (datetime.now() + timedelta(seconds=expiry)).isoformat()
            }
            
        except Exception as e:
            logger.error(f"Error generating download URL: {str(e)}")
            return {
                'success': False,
                'error': str(e)
            }
    
    def batch_generate_upload_urls(
        self,
        files: List[Dict[str, Any]],
        bucket_name: Optional[str] = None,
        expiry: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Generate presigned URLs for multiple files.
        
        Args:
            files: List of dicts with 'key', 'content_type', 'metadata'
            bucket_name: Target bucket
            expiry: URL expiration in seconds
            
        Returns:
            Dict containing URLs for all files
        """
        results = []
        errors = []
        
        for file_info in files:
            result = self.generate_upload_url(
                key=file_info.get('key'),
                bucket_name=bucket_name,
                content_type=file_info.get('content_type'),
                metadata=file_info.get('metadata'),
                expiry=expiry,
                max_file_size=file_info.get('max_file_size')
            )
            
            if result['success']:
                results.append(result)
            else:
                errors.append({
                    'key': file_info.get('key'),
                    'error': result.get('error')
                })
        
        return {
            'success': len(errors) == 0,
            'results': results,
            'errors': errors,
            'total': len(files),
            'successful': len(results)
        }
    
    def initiate_multipart_upload(
        self,
        key: str,
        content_type: str = 'application/octet-stream',
        bucket_name: Optional[str] = None,
        metadata: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """
        Initiate a multipart upload for large files.
        
        Args:
            key: S3 object key
            content_type: MIME type of the file
            bucket_name: Target bucket (uses default if None)
            metadata: Custom metadata to attach
            
        Returns:
            Dict containing upload_id and S3 key
        """
        try:
            bucket_name = bucket_name or self.base_service.production_bucket
            
            # Prepare create multipart upload parameters
            params = {
                'Bucket': bucket_name,
                'Key': key,
                'ContentType': content_type
            }
            
            # Add server-side encryption if not MinIO
            if not self.base_service.is_minio:
                params['ServerSideEncryption'] = 'AES256'
            
            # Add metadata
            if metadata:
                params['Metadata'] = metadata
                
            # Create multipart upload
            response = self.s3_client.create_multipart_upload(**params)
            upload_id = response['UploadId']
            
            logger.info(f"Initiated multipart upload {upload_id} for {key} in {bucket_name}")
            
            return {
                'success': True,
                'upload_id': upload_id,
                's3_key': key,
                'bucket': bucket_name,
                'content_type': content_type
            }
            
        except Exception as e:
            logger.error(f"Error initiating multipart upload for {key}: {str(e)}")
            return {
                'success': False,
                'error': str(e)
            }
    
    def complete_multipart_upload(
        self,
        key: str,
        upload_id: str,
        parts: List[Dict[str, Any]],
        bucket_name: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Complete a multipart upload.
        
        Args:
            key: S3 object key
            upload_id: Multipart upload ID
            parts: List of completed parts with ETag and PartNumber
            bucket_name: Target bucket
            
        Returns:
            Dict with completion result
        """
        try:
            bucket_name = bucket_name or self.base_service.production_bucket
            
            # Format parts for S3 API
            multipart_upload = {
                'Parts': [
                    {
                        'ETag': part['ETag'],
                        'PartNumber': part['PartNumber']
                    }
                    for part in parts
                ]
            }
            
            # Complete multipart upload
            response = self.s3_client.complete_multipart_upload(
                Bucket=bucket_name,
                Key=key,
                UploadId=upload_id,
                MultipartUpload=multipart_upload
            )
            
            logger.info(f"Completed multipart upload {upload_id} for {key}")
            
            return {
                'success': True,
                'upload_id': upload_id,
                's3_key': key,
                'bucket': bucket_name,
                'etag': response.get('ETag'),
                'location': response.get('Location')
            }
            
        except Exception as e:
            logger.error(f"Error completing multipart upload {upload_id}: {str(e)}")
            return {
                'success': False,
                'error': str(e)
            }
    
    def abort_multipart_upload(
        self,
        key: str,
        upload_id: str,
        bucket_name: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Abort a multipart upload.
        
        Args:
            key: S3 object key  
            upload_id: Multipart upload ID to abort
            bucket_name: Target bucket
            
        Returns:
            Dict with abort result
        """
        try:
            bucket_name = bucket_name or self.base_service.production_bucket
            
            # Abort multipart upload
            self.s3_client.abort_multipart_upload(
                Bucket=bucket_name,
                Key=key,
                UploadId=upload_id
            )
            
            logger.info(f"Aborted multipart upload {upload_id} for {key}")
            
            return {
                'success': True,
                'upload_id': upload_id,
                's3_key': key,
                'bucket': bucket_name,
                'message': 'Multipart upload aborted successfully'
            }
            
        except Exception as e:
            logger.error(f"Error aborting multipart upload {upload_id}: {str(e)}")
            return {
                'success': False,
                'error': str(e)
            }
    
    def calculate_multipart_parts(
        self,
        file_size: int,
        chunk_size: int = 10 * 1024 * 1024
    ) -> Dict[str, Any]:
        """
        Calculate optimal multipart upload parameters for browser uploads.
        
        Args:
            file_size: Size of the file in bytes
            chunk_size: Desired chunk size in bytes (default: 10MB)
            
        Returns:
            Dict with multipart calculation results
        """
        # S3 limits for multipart uploads
        min_part_size = 5 * 1024 * 1024  # 5MB minimum
        max_parts = 10000  # Maximum number of parts
        
        # Adjust chunk size if needed
        if chunk_size < min_part_size:
            chunk_size = min_part_size
        
        # Calculate number of parts
        part_count = (file_size + chunk_size - 1) // chunk_size
        
        # If too many parts, increase chunk size
        if part_count > max_parts:
            chunk_size = (file_size + max_parts - 1) // max_parts
            # Round up to nearest MB for efficiency
            chunk_size = ((chunk_size + 1024 * 1024 - 1) // (1024 * 1024)) * 1024 * 1024
            part_count = (file_size + chunk_size - 1) // chunk_size
        
        return {
            'should_use_multipart': file_size > 100 * 1024 * 1024,  # 100MB threshold
            'part_count': part_count,
            'chunk_size': chunk_size,
            'last_part_size': file_size % chunk_size if file_size % chunk_size > 0 else chunk_size,
            'total_size': file_size,
            'part_numbers': list(range(1, part_count + 1))
        }
    
    def validate_file_upload(
        self,
        file_name: str,
        file_size: int,
        content_type: str,
        allowed_types: Optional[List[str]] = None,
        max_file_size: Optional[int] = None,
        min_file_size: int = 1
    ) -> Dict[str, Any]:
        """
        Validate file upload parameters.
        
        Args:
            file_name: Name of the file
            file_size: Size of the file in bytes
            content_type: MIME type of the file
            allowed_types: List of allowed MIME types
            max_file_size: Maximum file size in bytes
            min_file_size: Minimum file size in bytes
            
        Returns:
            Dict with validation result
        """
        errors = []
        warnings = []
        
        # File size validation
        if file_size < min_file_size:
            errors.append(f"File size must be at least {min_file_size} bytes")
        
        if max_file_size and file_size > max_file_size:
            errors.append(f"File size {file_size} exceeds maximum allowed size of {max_file_size} bytes")
        
        # File name validation
        if not file_name or file_name.strip() == '':
            errors.append("File name cannot be empty")
        
        # Content type validation
        if allowed_types and content_type not in allowed_types:
            errors.append(f"Content type '{content_type}' not allowed. Allowed types: {', '.join(allowed_types)}")
        
        # Large file recommendation
        single_upload_limit = 5 * 1024 * 1024 * 1024  # 5GB
        if file_size > single_upload_limit:
            warnings.append(f"File size {file_size} exceeds single upload limit. Consider using multipart upload.")
        
        return {
            'valid': len(errors) == 0,
            'errors': errors,
            'warnings': warnings,
            'should_use_multipart': file_size > 100 * 1024 * 1024  # 100MB threshold
        }