"""
Upload tracking models for async upload sessions.

This module provides models to track async upload sessions with multiple files,
allowing for proper completion handling, database tracking, and automatic UI updates.
"""

from django.db import models
from django.utils import timezone
import uuid


class AsyncUploadSession(models.Model):
    """Track async upload sessions with multiple files"""
    
    UPLOAD_STATUS_CHOICES = [
        ('initialized', 'Initialized'),
        ('presigned_generated', 'Presigned URLs Generated'),
        ('uploading', 'Uploading to S3'),
        ('processing', 'Processing Files'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    user = models.ForeignKey('users.User', on_delete=models.CASCADE)
    organization = models.CharField(max_length=255)
    base_folder = models.CharField(max_length=50)  # 'data' or 'metadata'
    status = models.CharField(max_length=20, choices=UPLOAD_STATUS_CHOICES, default='initialized')
    total_files = models.IntegerField(default=0)
    completed_files = models.IntegerField(default=0)
    failed_files = models.IntegerField(default=0)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    
    error_message = models.TextField(blank=True)
    
    class Meta:
        db_table = 'storage_async_upload_session'
        ordering = ['-created_at']
    
    def __str__(self):
        return f"Upload Session {self.id} - {self.status} ({self.completed_files}/{self.total_files})"
    
    def mark_uploading(self):
        self.status = 'uploading'
        self.started_at = timezone.now()
        self.save()
    
    def mark_processing(self):
        self.status = 'processing'
        self.save()
    
    def mark_completed(self):
        self.status = 'completed'
        self.completed_at = timezone.now()
        self.save()
    
    def mark_failed(self, error_message):
        self.status = 'failed'
        self.error_message = error_message
        self.completed_at = timezone.now()
        self.save()
    
    @property
    def progress_percentage(self):
        if self.total_files == 0:
            return 0
        return (self.completed_files / self.total_files) * 100


class AsyncUploadFile(models.Model):
    """Track individual files within an upload session"""
    
    FILE_STATUS_CHOICES = [
        ('pending', 'Pending Upload'),
        ('uploading', 'Uploading to S3'),
        ('uploaded', 'Uploaded to S3'),
        ('processing', 'Processing'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
    ]
    
    session = models.ForeignKey(AsyncUploadSession, on_delete=models.CASCADE, related_name='files')
    filename = models.CharField(max_length=512)
    s3_key = models.CharField(max_length=1024)
    file_size = models.BigIntegerField()
    content_type = models.CharField(max_length=255)
    relative_path = models.CharField(max_length=1024, blank=True)  # For folder uploads
    
    status = models.CharField(max_length=20, choices=FILE_STATUS_CHOICES, default='pending')
    presigned_url = models.TextField()
    presigned_fields = models.JSONField(default=dict)
    
    upload_started_at = models.DateTimeField(null=True, blank=True)
    upload_completed_at = models.DateTimeField(null=True, blank=True)
    error_message = models.TextField(blank=True)
    
    # Link to final S3FileObject after processing
    s3_file_object = models.OneToOneField(
        'storage.S3FileObject', 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True
    )
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'storage_async_upload_file'
        ordering = ['created_at']
    
    def __str__(self):
        return f"{self.filename} - {self.status}"
    
    def mark_uploading(self):
        self.status = 'uploading'
        self.upload_started_at = timezone.now()
        self.save()
    
    def mark_uploaded(self):
        self.status = 'uploaded'
        self.upload_completed_at = timezone.now()
        self.save()
    
    def mark_processing(self):
        self.status = 'processing'
        self.save()
    
    def mark_completed(self, s3_file_object=None):
        self.status = 'completed'
        if s3_file_object:
            self.s3_file_object = s3_file_object
        self.save()
    
    def mark_failed(self, error_message):
        self.status = 'failed'
        self.error_message = error_message
        self.save()