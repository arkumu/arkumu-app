from django.db import models
import uuid
import logging
from django.utils import timezone
from .upload_sessions import UploadSession
from arkumu.metadata.models.resource import Resource
import hashlib

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
    base_folder = models.CharField(max_length=50, blank=True)
    organization = models.CharField(max_length=255, blank=True)
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
            ('missing', 'Missing'),
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
        related_name='s3fileobject',
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
            models.Index(fields=['base_folder']),
            models.Index(fields=['organization']),
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
    
    def get_checksum(self) -> tuple[str | None, str | None]:
        if not self.sha256_checksum:
            return None, None

        value = self.sha256_checksum
        if ':' in value:
            algorithm, digest = value.split(':', 1)
            return algorithm or None, digest or None
        return 'sha256', value

    def _store_checksum(self, algorithm: str | None, digest: str | None) -> None:
        if not digest:
            return

        stored = digest
        if algorithm:
            stored = f"{algorithm}:{digest}"

        self.sha256_checksum = stored
        self.checksum_calculated_at = timezone.now()
        self.save(update_fields=['sha256_checksum', 'checksum_calculated_at', 'updated_at'])

    def is_multipart_upload(self, etag: str | None = None) -> bool:
        etag = etag or self.etag
        if not etag:
            return False
        return '-' in etag.strip('"')

    def _refresh_etag(self, storage_service=None) -> str | None:
        if self.etag:
            return self.etag

        if not storage_service:
            from arkumu.storage.services.base_storage_service import BaseStorageService
            storage_service = BaseStorageService()

        bucket = self.organization or getattr(self.session, 'organization', None) or 'fuk'
        key = self.s3_key

        try:
            head = storage_service.s3_client.head_object(Bucket=bucket, Key=key)
            etag = head.get('ETag')
            if etag and etag != self.etag:
                self.etag = etag
                self.save(update_fields=['etag', 'updated_at'])
            return etag
        except Exception as exc:  # noqa: BLE001
            logger.debug("Failed to fetch ETag for %s: %s", key, exc)
            return None

    def calculate_checksum(self, storage_service=None, *, algorithm: str = 'sha256'):
        """Calculate checksum for this file in S3 using the given algorithm."""
        if not storage_service:
            from arkumu.storage.services.base_storage_service import BaseStorageService
            storage_service = BaseStorageService()

        try:
            if self.s3_key.startswith('s3://'):
                parts = self.s3_key[5:].split('/', 1)
                bucket = parts[0]
                key = parts[1] if len(parts) > 1 else ''
            else:
                bucket = self.organization or getattr(self.session, 'organization', None) or 'fuk'
                key = self.s3_key

            checksum = storage_service._calculate_file_checksum(bucket, key, algorithm=algorithm)
            if checksum:
                self._store_checksum(algorithm, checksum)
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
                bucket = self.organization or getattr(self.session, 'organization', None) or 'fuk'
                key = self.s3_key
            
            return storage_service.s3_client.head_object(Bucket=bucket, Key=key)
        except Exception:
            return False
        finally:
            if storage_service and hasattr(storage_service, "close"):
                try:
                    storage_service.close()  # type: ignore[attr-defined]
                except Exception:  # noqa: BLE001
                    pass
    
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
            base_folder=getattr(session, 'base_folder', ''),
            organization=getattr(session, 'organization', ''),
            source_csv_file=source_csv_file,
            source_row_number=source_row_number,
            source_column_name=source_column_name,
            related_resource=related_resource,
            status='uploading'
        ) 
