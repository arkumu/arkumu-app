import logging
import time
from typing import Dict, Any, List, Optional

from .base_storage_service import BaseStorageService
from .upload import PresignedURLService, upload_utils

logger = logging.getLogger(__name__)


class UploadService:
    """
    Simplified upload service for presigned URL-based file uploads.
    
    This service provides direct browser-to-S3 uploads using presigned URLs.
    File data never passes through the Django server, improving performance and scalability.
    
    Key features:
    - Generate presigned POST URLs for single uploads (≤5GB)
    - Generate presigned multipart URLs for large uploads (>5GB) 
    - File validation and user quota checking
    - Direct browser-to-S3 upload with zero server bandwidth usage
    """
    
    def __init__(self):
        """
        Initialize the simplified UploadService with presigned URL support only.
        """
        logger.info("Initializing simplified UploadService for presigned URL uploads...")
        
        # Get the singleton instance of BaseStorageService for S3 operations
        self.base_s3_service = BaseStorageService()
        
        # Initialize presigned URL service only
        self.presigned_url_service = PresignedURLService()
        
        logger.info(f"UploadService initialized with endpoint: {self.base_s3_service.endpoint_url}")

    # Utility methods
    
    def _generate_file_key(self, file_name: str, path_prefix: Optional[str] = None) -> str:
        """Generate S3 key from file name and path prefix."""
        return upload_utils.generate_file_key(file_name, path_prefix)
    
    def _safe_head_object(self, bucket_name: str, s3_key: str) -> Optional[Dict[str, Any]]:
        """Safely get object metadata with MinIO compatibility."""
        return upload_utils.safe_head_object(bucket_name, s3_key)
    
    def get_file_info(self, s3_key: str, bucket_name: Optional[str] = None) -> Dict[str, Any]:
        """Get file information from S3."""
        return upload_utils.get_file_info(s3_key, bucket_name)
    
    # Presigned URL methods
    
    def generate_presigned_upload_url(self, file_name: str, content_type: str = 'application/octet-stream',
                                    path_prefix: Optional[str] = None, 
                                    expiration: int = 3600,
                                    max_file_size: Optional[int] = None) -> Dict[str, Any]:
        """
        Generate presigned POST URL for single file upload.
        
        Args:
            file_name: Name of the file to upload
            content_type: MIME type of the file
            path_prefix: Optional path prefix for S3 key
            expiration: URL expiration time in seconds (default: 1 hour)
            max_file_size: Maximum file size in bytes (default: 5GB)
            
        Returns:
            Dictionary with presigned POST URL and form fields
        """
        s3_key = self._generate_file_key(file_name, path_prefix)
        
        # Default max file size to 5GB for single uploads
        if max_file_size is None:
            max_file_size = 5 * 1024 * 1024 * 1024  # 5GB
            
        return self.presigned_url_service.generate_upload_url(
            key=s3_key, 
            content_type=content_type, 
            expiry=expiration,
            max_file_size=max_file_size
        )
    
    def generate_batch_presigned_upload_urls(self, file_requests: List[Dict[str, Any]], 
                                           path_prefix: Optional[str] = None,
                                           expiration: int = 3600) -> Dict[str, Any]:
        """
        Generate multiple presigned POST URLs for batch uploads.
        
        Args:
            file_requests: List of file request dictionaries
            path_prefix: Optional path prefix for S3 keys
            expiration: URL expiration time in seconds
            
        Returns:
            Dictionary with batch presigned URLs
        """
        # Process file requests to generate S3 keys
        processed_files = []
        for req in file_requests:
            file_name = req.get('file_name') or req.get('name')
            s3_key = self._generate_file_key(file_name, path_prefix)
            
            # Default max file size to 5GB for single uploads
            max_file_size = req.get('max_file_size', 5 * 1024 * 1024 * 1024)
            
            processed_files.append({
                'key': s3_key,
                'content_type': req.get('content_type', 'application/octet-stream'),
                'metadata': req.get('metadata'),
                'max_file_size': max_file_size
            })
        
        return self.presigned_url_service.batch_generate_upload_urls(
            files=processed_files, 
            expiry=expiration
        )
    
    def initiate_multipart_upload(self, file_name: str, content_type: str = 'application/octet-stream',
                                 path_prefix: Optional[str] = None) -> Dict[str, Any]:
        """
        Initialize a browser-based multipart upload for large files.
        
        Args:
            file_name: Name of the file to upload
            content_type: MIME type of the file
            path_prefix: Optional path prefix for S3 key
            
        Returns:
            Dictionary with upload_id and S3 key
        """
        s3_key = self._generate_file_key(file_name, path_prefix)
        return self.presigned_url_service.initiate_multipart_upload(
            key=s3_key, 
            content_type=content_type
        )
    
    def generate_presigned_multipart_urls(self, s3_key: str, upload_id: str, 
                                        part_numbers: List[int],
                                        expiration: int = 3600) -> Dict[str, Any]:
        """
        Generate presigned URLs for multipart upload parts.
        
        Args:
            s3_key: S3 object key
            upload_id: Multipart upload ID from initiate_multipart_upload
            part_numbers: List of part numbers to generate URLs for
            expiration: URL expiration time in seconds
            
        Returns:
            Dictionary with presigned URLs for each part
        """
        return self.presigned_url_service.generate_multipart_urls(
            key=s3_key, 
            upload_id=upload_id, 
            parts=part_numbers, 
            expiry=expiration
        )
    
    def complete_multipart_upload(self, s3_key: str, upload_id: str, 
                                parts: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Complete a multipart upload.
        
        Args:
            s3_key: S3 object key
            upload_id: Multipart upload ID
            parts: List of completed parts with ETag and PartNumber
            
        Returns:
            Dictionary with upload completion result
        """
        return self.presigned_url_service.complete_multipart_upload(
            key=s3_key, 
            upload_id=upload_id, 
            parts=parts
        )
    
    def abort_multipart_upload(self, s3_key: str, upload_id: str) -> Dict[str, Any]:
        """
        Abort a multipart upload.
        
        Args:
            s3_key: S3 object key
            upload_id: Multipart upload ID to abort
            
        Returns:
            Dictionary with abort result
        """
        return self.presigned_url_service.abort_multipart_upload(
            key=s3_key, 
            upload_id=upload_id
        )
    
    # Validation and utility methods
    
    def validate_upload_request(self, file_name: str, file_size: int, content_type: str, 
                               user_id: Optional[int] = None) -> Dict[str, Any]:
        """
        Validate upload request parameters.
        
        Args:
            file_name: Name of the file
            file_size: Size of the file in bytes
            content_type: MIME type of the file
            user_id: Optional user ID for quota checking
            
        Returns:
            Dictionary with validation result
        """
        errors = []
        warnings = []
        
        # File size validation
        max_single_size = 5 * 1024 * 1024 * 1024  # 5GB
        if file_size > max_single_size:
            # Large files should use multipart upload
            warnings.append(f"File size {self.base_s3_service._format_size(file_size)} exceeds single upload limit. Use multipart upload.")
        
        if file_size <= 0:
            errors.append("File size must be greater than 0")
        
        # File name validation
        if not file_name or file_name.strip() == '':
            errors.append("File name cannot be empty")
        
        # Content type validation (basic)
        if not content_type:
            warnings.append("Content type not specified, using application/octet-stream")
        
        # S3 key validation
        s3_key = self._generate_file_key(file_name)
        key_validation = upload_utils.validate_s3_key(s3_key)
        if not key_validation['valid']:
            errors.extend(key_validation['errors'])
        warnings.extend(key_validation['warnings'])
        
        return {
            'valid': len(errors) == 0,
            'errors': errors,
            'warnings': warnings,
            'normalized_s3_key': upload_utils.normalize_s3_key(s3_key),
            'should_use_multipart': file_size > max_single_size
        }
    
    def validate_s3_key(self, s3_key: str) -> Dict[str, Any]:
        """Validate S3 key format and characters."""
        return upload_utils.validate_s3_key(s3_key)
    
    def normalize_s3_key(self, s3_key: str) -> str:
        """Normalize S3 key by fixing common issues."""
        return upload_utils.normalize_s3_key(s3_key)
    
    # Health check and monitoring
    
    def health_check(self) -> Dict[str, Any]:
        """
        Check the health of the simplified upload service.
        
        Returns:
            Dictionary with health status
        """
        logger.info("Performing health check on presigned URL upload service...")
        
        try:
            health_result = {
                'success': True,
                'timestamp': time.time(),
                'services': {}
            }
            
            # Test base S3 service connectivity
            try:
                self.base_s3_service.list_buckets()
                health_result['services']['base_s3_service'] = {'status': 'healthy'}
            except Exception as e:
                health_result['services']['base_s3_service'] = {
                    'status': 'unhealthy', 
                    'error': str(e)
                }
                health_result['success'] = False
            
            # Check ingest bucket accessibility
            try:
                self.base_s3_service.s3_client.head_bucket(
                    Bucket=self.base_s3_service.ingest_bucket
                )
                health_result['services']['ingest_bucket'] = {'status': 'accessible'}
            except Exception as e:
                health_result['services']['ingest_bucket'] = {
                    'status': 'inaccessible', 
                    'error': str(e)
                }
                health_result['success'] = False
            
            # Verify presigned URL service is initialized
            services_status = {
                'presigned_url_service': bool(self.presigned_url_service),
                'upload_utils_module': upload_utils is not None
            }
            
            health_result['services']['specialized_services'] = {
                'status': 'initialized' if all(services_status.values()) else 'incomplete',
                'details': services_status
            }
            
            if not all(services_status.values()):
                health_result['success'] = False
            
            status = 'healthy' if health_result['success'] else 'unhealthy'
            logger.info(f"Health check completed: {status}")
            return health_result
            
        except Exception as e:
            logger.error(f"Health check failed: {str(e)}")
            return {
                'success': False,
                'error': str(e),
                'timestamp': time.time()
            }