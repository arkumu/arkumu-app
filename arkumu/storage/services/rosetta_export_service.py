"""
Rosetta Export Service
Handles S3 file access for Rosetta harvesting via OAI-PMH
"""
import boto3
from datetime import timedelta
from django.conf import settings
from django.utils import timezone
from typing import Dict, List, Optional


class RosettaExportService:
    """
    Manages S3 file access for Rosetta harvesting system.
    Generates presigned URLs and manages export lifecycle.
    """
    
    def __init__(self):
        # Get endpoint URL for S3-compatible storage (MinIO in dev, proper S3 in production)
        endpoint_url = getattr(settings, 'AWS_S3_ENDPOINT_URL', None)

        # Build client config
        client_config = {
            'aws_access_key_id': settings.AWS_ACCESS_KEY_ID,
            'aws_secret_access_key': settings.AWS_SECRET_ACCESS_KEY,
            'region_name': settings.AWS_S3_REGION_NAME,
        }

        if endpoint_url:
            client_config['endpoint_url'] = endpoint_url

        self.s3_client = boto3.client('s3', **client_config)
        self.bucket_name = settings.AWS_STORAGE_BUCKET_NAME
        self.endpoint_url = endpoint_url

        # Configuration for Rosetta exports
        self.url_expiry_days = getattr(settings, 'ROSETTA_URL_EXPIRY_DAYS', 7)
        self.max_file_size = getattr(settings, 'ROSETTA_MAX_FILE_SIZE', 10 * 1024**3)  # 10GB
        self.enable_acceleration = getattr(settings, 'ROSETTA_USE_ACCELERATION', True)
    
    def prepare_file_for_harvest(self, s3_file_object) -> Dict:
        """
        Prepare a file for Rosetta harvesting by generating access URL.
        
        Args:
            s3_file_object: S3FileObject model instance
            
        Returns:
            Dict with access information for OAI-PMH
        """
        # Check file size for appropriate method
        if s3_file_object.file_size_bytes > self.max_file_size:
            return self._prepare_large_file(s3_file_object)
        else:
            return self._prepare_standard_file(s3_file_object)
    
    def _prepare_standard_file(self, s3_file_object) -> Dict:
        """
        Generate standard presigned URL for files under size limit.
        """
        # Generate presigned URL
        presigned_url = self.s3_client.generate_presigned_url(
            'get_object',
            Params={
                'Bucket': self.bucket_name,
                'Key': s3_file_object.s3_key,
                # Add response headers for better compatibility
                'ResponseContentDisposition': f'attachment; filename="{s3_file_object.file_name}"',
                'ResponseContentType': s3_file_object.mime_type or 'application/octet-stream'
            },
            ExpiresIn=self.url_expiry_days * 24 * 3600
        )
        
        return {
            'access_method': 'presigned_url',
            'url': presigned_url,
            'expires_at': timezone.now() + timedelta(days=self.url_expiry_days),
            'file_size': s3_file_object.file_size_bytes,
            'checksum': s3_file_object.sha256_checksum,
            'mime_type': s3_file_object.mime_type
        }
    
    def _prepare_large_file(self, s3_file_object) -> Dict:
        """
        Prepare large file access with optimization options.
        """
        if self.enable_acceleration:
            # Use S3 Transfer Acceleration endpoint
            client_config = {
                'aws_access_key_id': settings.AWS_ACCESS_KEY_ID,
                'aws_secret_access_key': settings.AWS_SECRET_ACCESS_KEY,
                'region_name': settings.AWS_S3_REGION_NAME,
                'config': boto3.session.Config(
                    s3={'use_accelerate_endpoint': True}
                )
            }

            if self.endpoint_url:
                client_config['endpoint_url'] = self.endpoint_url

            accelerated_client = boto3.client('s3', **client_config)
            
            presigned_url = accelerated_client.generate_presigned_url(
                'get_object',
                Params={
                    'Bucket': self.bucket_name,
                    'Key': s3_file_object.s3_key
                },
                ExpiresIn=self.url_expiry_days * 24 * 3600
            )
            
            access_method = 'accelerated_url'
        else:
            # Generate multiple part URLs for parallel download
            return self._generate_multipart_download_urls(s3_file_object)
        
        return {
            'access_method': access_method,
            'url': presigned_url,
            'expires_at': timezone.now() + timedelta(days=self.url_expiry_days),
            'file_size': s3_file_object.file_size_bytes,
            'checksum': s3_file_object.sha256_checksum,
            'mime_type': s3_file_object.mime_type,
            'acceleration_enabled': self.enable_acceleration
        }
    
    def _generate_multipart_download_urls(self, s3_file_object) -> Dict:
        """
        Generate multiple URLs for parallel downloading of large files.
        Rosetta can use Range requests to download in parallel.
        """
        chunk_size = 100 * 1024 * 1024  # 100MB chunks
        file_size = s3_file_object.file_size_bytes
        num_parts = (file_size + chunk_size - 1) // chunk_size
        
        parts = []
        for i in range(num_parts):
            start_byte = i * chunk_size
            end_byte = min(start_byte + chunk_size - 1, file_size - 1)
            
            # Generate presigned URL with Range header
            presigned_url = self.s3_client.generate_presigned_url(
                'get_object',
                Params={
                    'Bucket': self.bucket_name,
                    'Key': s3_file_object.s3_key,
                    'Range': f'bytes={start_byte}-{end_byte}'
                },
                ExpiresIn=self.url_expiry_days * 24 * 3600
            )
            
            parts.append({
                'part_number': i + 1,
                'url': presigned_url,
                'start_byte': start_byte,
                'end_byte': end_byte,
                'size': end_byte - start_byte + 1
            })
        
        return {
            'access_method': 'multipart_download',
            'parts': parts,
            'total_size': file_size,
            'chunk_size': chunk_size,
            'expires_at': timezone.now() + timedelta(days=self.url_expiry_days),
            'checksum': s3_file_object.sha256_checksum,
            'mime_type': s3_file_object.mime_type,
            'assembly_required': True
        }
    
    def generate_oai_pmh_metadata(self, s3_file_object) -> Dict:
        """
        Generate OAI-PMH compliant metadata including access information.
        """
        access_info = self.prepare_file_for_harvest(s3_file_object)
        
        # Build OAI-PMH metadata
        metadata = {
            # Dublin Core elements
            'dc:identifier': s3_file_object.s3_key,
            'dc:format': s3_file_object.mime_type or 'application/octet-stream',
            'dc:size': str(s3_file_object.file_size_bytes),
            
            # Custom elements for Rosetta
            'arkumu:access_method': access_info['access_method'],
            'arkumu:checksum': access_info.get('checksum', ''),
            'arkumu:expires': access_info['expires_at'].isoformat()
        }
        
        # Add access URLs based on method
        if access_info['access_method'] == 'multipart_download':
            # For multipart, provide manifest
            metadata['arkumu:download_manifest'] = access_info['parts']
        else:
            # Single URL access
            metadata['dc:relation'] = access_info['url']
        
        return metadata
    
    def batch_prepare_for_harvest(self, s3_file_objects: List) -> List[Dict]:
        """
        Prepare multiple files for harvest efficiently.
        """
        results = []
        for file_obj in s3_file_objects:
            try:
                result = self.prepare_file_for_harvest(file_obj)
                result['file_id'] = file_obj.id
                results.append(result)
            except Exception as e:
                results.append({
                    'file_id': file_obj.id,
                    'error': str(e),
                    'access_method': 'error'
                })
        
        return results
    
    def validate_rosetta_access(self, s3_file_object) -> bool:
        """
        Verify that Rosetta can access the file.
        """
        try:
            # Check if object exists and is accessible
            response = self.s3_client.head_object(
                Bucket=self.bucket_name,
                Key=s3_file_object.s3_key
            )
            
            # Verify size matches
            return response['ContentLength'] == s3_file_object.file_size_bytes
            
        except Exception as e:
            print(f"Access validation failed: {e}")
            return False
    
    def cleanup_expired_urls(self):
        """
        Clean up expired presigned URLs from database.
        Called periodically by background task.
        """
        from arkumu.storage.models import S3FileObject
        
        expired_files = S3FileObject.objects.filter(
            rosetta_url_expires__lt=timezone.now(),
            rosetta_exported=True
        )
        
        for file_obj in expired_files:
            # Regenerate URL if file is still needed
            if file_obj.rosetta_active:
                new_access = self.prepare_file_for_harvest(file_obj)
                file_obj.rosetta_url = new_access.get('url')
                file_obj.rosetta_url_expires = new_access['expires_at']
                file_obj.save()
            else:
                # Clear expired URL
                file_obj.rosetta_url = None
                file_obj.rosetta_url_expires = None
                file_obj.save()
        
        return expired_files.count()