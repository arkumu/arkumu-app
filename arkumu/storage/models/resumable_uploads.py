from django.db import models
import uuid
from django.utils import timezone
from .upload_sessions import UploadSession
from .s3_file_objects import S3FileObject


class ResumableUploadSession(models.Model):
    """
    Tracks resumable upload state for large files that need to be chunked.
    Integrates with existing UploadSession for overall batch tracking.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    upload_session = models.ForeignKey(
        UploadSession, 
        related_name='resumable_uploads', 
        on_delete=models.CASCADE
    )
    s3_file_object = models.OneToOneField(
        S3FileObject,
        related_name='resumable_upload',
        on_delete=models.CASCADE
    )
    
    # File information
    original_filename = models.CharField(max_length=255)
    total_size_bytes = models.BigIntegerField()
    uploaded_bytes = models.BigIntegerField(default=0)
    chunk_size_bytes = models.IntegerField(default=5242880)  # 5MB default
    total_chunks = models.IntegerField()
    
    # Upload state
    status = models.CharField(
        max_length=20,
        choices=[
            ('initialized', 'Initialized'),
            ('uploading', 'Uploading'),
            ('paused', 'Paused'),
            ('assembling', 'Assembling Chunks'),
            ('completed', 'Completed'),
            ('failed', 'Failed'),
        ],
        default='initialized'
    )
    
    # Tracking
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    last_chunk_uploaded_at = models.DateTimeField(null=True, blank=True)
    
    # Temporary storage path for chunks before S3 upload
    temp_storage_path = models.CharField(max_length=512, blank=True)
    
    # Error handling
    error_message = models.TextField(blank=True)
    retry_count = models.IntegerField(default=0)
    max_retries = models.IntegerField(default=3)

    class Meta:
        verbose_name = "Resumable Upload Session"
        verbose_name_plural = "Resumable Upload Sessions"
        indexes = [
            models.Index(fields=['upload_session']),
            models.Index(fields=['status']),
            models.Index(fields=['created_at']),
            models.Index(fields=['last_chunk_uploaded_at']),
        ]

    def __str__(self):
        return f"Resumable upload: {self.original_filename} ({self.status})"
    
    @property
    def progress_percentage(self):
        """Calculate upload progress as percentage"""
        if self.total_size_bytes == 0:
            return 0
        return (self.uploaded_bytes / self.total_size_bytes) * 100
    
    @property
    def completed_chunks(self):
        """Get count of completed chunks"""
        return self.chunks.filter(status='completed').count()
    
    def can_resume(self):
        """Check if upload can be resumed"""
        return self.status in ['paused', 'uploading'] and self.retry_count < self.max_retries
    
    def mark_completed(self):
        """Mark the resumable upload as completed"""
        self.status = 'completed'
        self.completed_at = timezone.now()
        self.uploaded_bytes = self.total_size_bytes
        self.save()
        
        # Also mark the associated S3FileObject as completed
        self.s3_file_object.mark_completed()
    
    def mark_failed(self, error_message):
        """Mark the resumable upload as failed"""
        self.status = 'failed'
        self.error_message = error_message
        self.save()
        
        # Also mark the associated S3FileObject as failed
        self.s3_file_object.mark_failed(error_message)
    
    def increment_retry(self):
        """Increment retry count"""
        self.retry_count += 1
        self.save()


class ResumableUploadChunk(models.Model):
    """
    Tracks individual chunks of a resumable upload.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    resumable_upload = models.ForeignKey(
        ResumableUploadSession,
        related_name='chunks',
        on_delete=models.CASCADE
    )
    
    # Chunk information
    chunk_number = models.IntegerField()  # 0-indexed
    start_byte = models.BigIntegerField()
    end_byte = models.BigIntegerField()
    size_bytes = models.IntegerField()
    
    # Status tracking
    status = models.CharField(
        max_length=20,
        choices=[
            ('pending', 'Pending'),
            ('uploading', 'Uploading'),
            ('completed', 'Completed'),
            ('failed', 'Failed'),
        ],
        default='pending'
    )
    
    # Storage information
    temp_file_path = models.CharField(max_length=512, blank=True)
    checksum = models.CharField(max_length=64, blank=True)  # MD5 or SHA256
    
    # Timing
    created_at = models.DateTimeField(auto_now_add=True)
    uploaded_at = models.DateTimeField(null=True, blank=True)
    
    # Error handling
    error_message = models.TextField(blank=True)
    retry_count = models.IntegerField(default=0)
    max_retries = models.IntegerField(default=3)

    class Meta:
        verbose_name = "Resumable Upload Chunk"
        verbose_name_plural = "Resumable Upload Chunks"
        unique_together = ['resumable_upload', 'chunk_number']
        indexes = [
            models.Index(fields=['resumable_upload', 'chunk_number']),
            models.Index(fields=['status']),
            models.Index(fields=['created_at']),
        ]
        ordering = ['chunk_number']

    def __str__(self):
        return f"Chunk {self.chunk_number} of {self.resumable_upload.original_filename}"
    
    @property
    def byte_range(self):
        """Return the byte range as a string for Content-Range header"""
        return f"bytes {self.start_byte}-{self.end_byte-1}/{self.resumable_upload.total_size_bytes}"
    
    def mark_completed(self, checksum=None):
        """Mark the chunk as completed"""
        self.status = 'completed'
        self.uploaded_at = timezone.now()
        if checksum:
            self.checksum = checksum
        self.save()
        
        # Update parent resumable upload progress
        self.resumable_upload.uploaded_bytes = self.resumable_upload.chunks.filter(
            status='completed'
        ).aggregate(
            total=models.Sum('size_bytes')
        )['total'] or 0
        self.resumable_upload.last_chunk_uploaded_at = timezone.now()
        self.resumable_upload.save()
    
    def mark_failed(self, error_message):
        """Mark the chunk as failed"""
        self.status = 'failed'
        self.error_message = error_message
        self.save()
    
    def can_retry(self):
        """Check if chunk can be retried"""
        return self.retry_count < self.max_retries
    
    def increment_retry(self):
        """Increment retry count"""
        self.retry_count += 1
        self.save()