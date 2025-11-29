from django.db import models
from django.utils import timezone


class PreviewImages(models.Model):
    bucket = models.CharField(
        help_text='Bucket in S3'
    )
    path = models.CharField(
        help_text='Path in S3'
    )
    img = models.BinaryField(
        help_text='Image Binary Data'
    )
    content_type = models.CharField(
        help_text='HTTP Content Type'
    )
    content_length = models.IntegerField(
        help_text='HTTP Content Length'
    )
    last_download = models.DateTimeField(
        help_text='Last Downloaded',
        default=timezone.now(),
    )

    class Meta:
        ordering = ['bucket', 'path']
        verbose_name = 'Preview Images'
        verbose_name_plural = 'Preview Images'
        indexes = [
            models.Index(fields=['bucket', 'path']),
        ]
        unique_together = ('bucket', 'path')

    def __str__(self):
        return self.bucket + self.path
