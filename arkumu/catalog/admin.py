from django.contrib import admin
from django.template.defaultfilters import filesizeformat
from django.utils.html import format_html
import base64

from arkumu.catalog.models import PreviewImages, ProjectIndex, ProjectRecordIndex


@admin.register(PreviewImages)
class PreviewImagesAdmin(admin.ModelAdmin):
    search_fields = ['path']
    list_display = [
        'bucket',
        'path',
        'content_type',
        'human_filesize',
        'last_download',
    ]
    readonly_fields = ['image_preview', 'human_filesize', 'last_download']
    ordering = ('bucket', 'path',)
    list_filter = ('bucket', 'content_type',)
    fields = (
        'bucket',
        'path',
        'content_type',
        'human_filesize',
        'last_download',
        'image_preview',
    )

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

    def human_filesize(self, obj):
        if not obj.content_length:
            return "(No content length provided)"
        return filesizeformat(obj.content_length)
    human_filesize.short_description = "Content length"


@admin.register(ProjectIndex)
class ProjectIndexAdmin(admin.ModelAdmin):
    list_display = (
        "uri",
        "org_code",
        "public_access_level",
        "is_public_approved",
        "built_at",
    )
    search_fields = ("uri", "title", "subtitle", "institution_label")
    list_filter = ("org_code", "public_access_level", "is_public_approved")
    readonly_fields = ("source_updated_at", "built_at", "source_version")
    ordering = ("org_code", "title")


@admin.register(ProjectRecordIndex)
class ProjectRecordIndexAdmin(admin.ModelAdmin):
    list_display = (
        "uri",
        "org_code",
        "public_access_level",
        "is_public_approved",
        "built_at",
    )
    search_fields = ("uri", "title", "subtitle", "institution_label", "project_type_label")
    list_filter = ("org_code", "public_access_level", "is_public_approved", "reference_only", "harvestable")
    readonly_fields = ("source_updated_at", "built_at", "source_version")
    ordering = ("org_code", "title")
