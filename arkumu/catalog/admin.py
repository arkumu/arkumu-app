from django.contrib import admin
from django.utils.html import format_html
import base64

from arkumu.catalog.models import PreviewImages


@admin.register(PreviewImages)
class PreviewImagesAdmin(admin.ModelAdmin):
    search_fields = ['path']
    list_display = [
        'bucket',
        'path',
        'content_type',
        'content_length',
        'last_download',
    ]
    readonly_fields = ['image_preview', 'content_length', 'last_download']
    ordering = ('bucket', 'path',)
    list_filter = ('bucket', 'content_type',)

    def image_preview(self, obj):
        """Render the binary image as an inline preview."""
        if not obj.img:
            return "(No image data)"
        try:
            encoded = base64.b64encode(obj.img).decode('utf-8')
            return format_html(
                '<img src="data:{};base64,{}" style="max-width: 50%; height: auto;" />',
                obj.content_type,
                encoded,
            )
        except Exception as e:
            return format_html("<span style='color:red;'>(Error displaying image: {})</span>", e)

    image_preview.short_description = "Preview"
