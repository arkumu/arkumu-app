from django.db import models
import uuid
import logging
from django.utils import timezone
from .upload_sessions import UploadSession
from arkumu.metadata.models.resource import Resource

logger = logging.getLogger(__name__)

class S3FileObject(models.Model):
    """Represents a file in S3"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    session = models.ForeignKey(UploadSession, related_name='files', on_delete=models.CASCADE, null=True, blank=True)
    file_name = models.CharField(max_length=255)
    original_path = models.CharField(max_length=1024, blank=True)
    s3_key = models.CharField(max_length=1024)
    file_size_bytes = models.BigIntegerField(default=0)
    content_type = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    upload_completed_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(
        max_length=20,
        choices=[
            ('pending', 'Pending'),
            ('uploading', 'Uploading'),
            ('completed', 'Completed'),
            ('failed', 'Failed'),
            ('verified', 'Verified'),
        ],
        default='pending'
    )
    etag = models.CharField(max_length=255, blank=True)  # S3 ETag for verification
    sha256_checksum = models.CharField(max_length=64, blank=True, help_text="SHA256 checksum of the file content")
    checksum_calculated_at = models.DateTimeField(null=True, blank=True, help_text="When the checksum was calculated")
    error_message = models.TextField(blank=True)
    
    # New fields for tracking import context
    source_csv_file = models.CharField(max_length=512, blank=True, help_text="Name of the CSV file this file was referenced from")
    source_row_number = models.IntegerField(null=True, blank=True, help_text="Row number in the CSV where this file was referenced")
    source_column_name = models.CharField(max_length=255, blank=True, help_text="Column name in the CSV that contained this file reference")
    related_resource = models.ForeignKey(
        Resource,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text="Direct link to the metadata resource this file is associated with"
    )
    s3_url = models.URLField(max_length=1024, blank=True, help_text="Full S3 URL to access this file")

    class Meta:
        verbose_name = "S3 File Object"
        verbose_name_plural = "S3 File Objects"
        indexes = [
            models.Index(fields=['session']),
            models.Index(fields=['status']),
            models.Index(fields=['s3_key']),
            models.Index(fields=['source_csv_file', 'source_row_number']),
            models.Index(fields=['related_resource']),
        ]

    def __str__(self):
        return f"{self.file_name} ({self.status})"
    
    def mark_completed(self, etag=None, s3_url=None):
        """Mark the file as successfully uploaded"""
        self.status = 'completed'
        self.upload_completed_at = timezone.now()
        if etag:
            self.etag = etag
        if s3_url:
            self.s3_url = s3_url
        self.save()
    
    def mark_failed(self, error_message):
        """Mark the file as failed with an error message"""
        self.status = 'failed'
        self.error_message = error_message
        self.save()
    
    def mark_verified(self):
        """Mark the file as verified in S3"""
        self.status = 'verified'
        self.save()
    
    def calculate_checksum(self, storage_service=None):
        """Calculate SHA256 checksum for this file in S3"""
        if not storage_service:
            from arkumu.storage.services.base_storage_service import BaseStorageService
            storage_service = BaseStorageService()
        
        try:
            # Extract bucket and key from s3_key
            if self.s3_key.startswith('s3://'):
                # Handle full S3 URL
                parts = self.s3_key[5:].split('/', 1)
                bucket = parts[0]
                key = parts[1] if len(parts) > 1 else ''
            else:
                # Assume it's just the key and use default bucket logic
                bucket = self.session.organization if hasattr(self.session, 'organization') else 'fuk'  # fallback
                key = self.s3_key
            
            checksum = storage_service._calculate_file_checksum(bucket, key)
            if checksum:
                self.sha256_checksum = checksum
                self.checksum_calculated_at = timezone.now()
                self.save()
                return checksum
        except Exception as e:
            logger.error(f"Failed to calculate checksum for {self.s3_key}: {e}")
        
        return None
    
    def exists_in_s3(self, storage_service=None):
        """Check if this file actually exists in S3"""
        if not storage_service:
            from arkumu.storage.services.base_storage_service import BaseStorageService
            storage_service = BaseStorageService()
        
        try:
            # Extract bucket and key from s3_key
            if self.s3_key.startswith('s3://'):
                parts = self.s3_key[5:].split('/', 1)
                bucket = parts[0]
                key = parts[1] if len(parts) > 1 else ''
            else:
                bucket = self.session.organization if hasattr(self.session, 'organization') else 'fuk'
                key = self.s3_key
            
            return storage_service.s3_client.head_object(Bucket=bucket, Key=key)
        except Exception:
            return False
    
    @classmethod
    def create_from_upload(cls, session, file_name, original_path, s3_key, 
                          file_size=0, content_type='', source_csv_file='',
                          source_row_number=None, source_column_name='', 
                          related_resource=None):
        """Create an S3FileObject from an upload operation"""
        if session is None:
            raise ValueError("A session must be provided when creating S3FileObject via create_from_upload.")
        return cls.objects.create(
            session=session,
            file_name=file_name,
            original_path=original_path,
            s3_key=s3_key,
            file_size_bytes=file_size,
            content_type=content_type,
            source_csv_file=source_csv_file,
            source_row_number=source_row_number,
            source_column_name=source_column_name,
            related_resource=related_resource,
            status='uploading'
        ) 