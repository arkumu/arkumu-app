"""Admin registrations for storage models."""

from __future__ import annotations

from django.contrib import admin
from django.template.defaultfilters import filesizeformat
from django.urls import reverse
from django.utils.html import format_html

from .models import S3FileObject
from .models.upload_tracking import AsyncUploadSession, AsyncUploadFile


@admin.register(AsyncUploadSession)
class AsyncUploadSessionAdmin(admin.ModelAdmin):
    search_fields = ["id", "organization", "user__username", "user__email"]
    list_display = (
        "short_id",
        "user",
        "organization",
        "base_folder",
        "status",
        "file_progress",
        "created_at",
        "updated_at",
    )
    list_filter = (
        "status",
        "base_folder",
        "organization",
        "created_at",
        "user",
    )
    date_hierarchy = "created_at"
    ordering = ("-created_at",)
    readonly_fields = (
        "id",
        "user",
        "organization",
        "base_folder",
        "status",
        "total_files",
        "completed_files",
        "failed_files",
        "created_at",
        "updated_at",
        "started_at",
        "completed_at",
        "error_message",
    )
    fieldsets = (
        (
            None,
            {
                "fields": (
                    "id",
                    "user",
                    "organization",
                    "base_folder",
                    "status",
                    "total_files",
                    "completed_files",
                    "failed_files",
                    "error_message",
                )
            },
        ),
        (
            "Timestamps",
            {"fields": ("created_at", "updated_at", "started_at", "completed_at")},
        ),
    )

    @admin.display(description="ID")
    def short_id(self, obj: AsyncUploadSession) -> str:
        return str(obj.id)[:8]

    @admin.display(description="Progress")
    def file_progress(self, obj: AsyncUploadSession) -> str:
        total = obj.total_files or 0
        completed = obj.completed_files or 0
        failed = obj.failed_files or 0
        if not total:
            total = obj.files.count()
        return f"{completed}/{total} (+{failed} failed)" if failed else f"{completed}/{total}"


@admin.register(AsyncUploadFile)
class AsyncUploadFileAdmin(admin.ModelAdmin):
    search_fields = ["filename", "session__id", "session__user__username", "s3_key"]
    list_display = (
        "filename",
        "session_short_id",
        "status",
        "content_type",
        "file_size",
        "created_at",
    )
    list_filter = (
        "status",
        "content_type",
        "session__organization",
        "session__base_folder",
        "created_at",
    )
    ordering = ("-created_at",)
    autocomplete_fields = ["session", "s3_file_object"]
    readonly_fields = (
        "session",
        "filename",
        "s3_key",
        "file_size",
        "content_type",
        "relative_path",
        "status",
        "presigned_url",
        "presigned_fields",
        "upload_started_at",
        "upload_completed_at",
        "error_message",
        "s3_file_object",
        "created_at",
        "updated_at",
    )
    fieldsets = (
        (
            None,
            {
                "fields": (
                    "session",
                    "filename",
                    "s3_key",
                    "relative_path",
                    "status",
                    "content_type",
                    "file_size",
                    "error_message",
                    "s3_file_object",
                )
            },
        ),
        (
            "Upload State",
            {
                "fields": (
                    "presigned_url",
                    "presigned_fields",
                    "upload_started_at",
                    "upload_completed_at",
                )
            },
        ),
        (
            "Timestamps",
            {"fields": ("created_at", "updated_at")},
        ),
    )

    @admin.display(description="Session")
    def session_short_id(self, obj: AsyncUploadFile) -> str:
        return str(obj.session_id)[:8]


@admin.register(S3FileObject)
class S3FileObjectAdmin(admin.ModelAdmin):
    search_fields = [
        "file_name",
        "s3_key",
        "organization",
        "session__institution",
        "session__user__username",
        "related_resource__uri",
        "related_resource__name",
    ]
    list_display = (
        "file_name",
        "short_key",
        "storage_org",
        "base_folder",
        "linked_resource",
        "resource_org",
        "status",
        "file_size",
        "upload_completed_at",
    )
    list_filter = (
        "status",
        "organization",
        "base_folder",
        "created_at",
        "upload_completed_at",
        ("related_resource__organization", admin.RelatedOnlyFieldListFilter),
    )
    ordering = ("-created_at",)
    list_select_related = ("related_resource", "related_resource__organization", "session",)
    readonly_fields = (
        "id",
        "session",
        "file_name",
        "original_path",
        "s3_key",
        "status",
        "file_size_bytes",
        "content_type",
        "etag",
        "sha256_checksum",
        "checksum_calculated_at",
        "error_message",
        "source_csv_file",
        "source_row_number",
        "source_column_name",
        "related_resource",
        "s3_url",
        "upload_completed_at",
        "created_at",
        "updated_at",
    )
    fieldsets = (
        (
            None,
            {
                "fields": (
                    "id",
                    "session",
                    "file_name",
                    "original_path",
                    "s3_key",
                    "base_folder",
                    "organization",
                    "status",
                    "file_size_bytes",
                    "content_type",
                )
            },
        ),
        (
            "Checksums & Metadata",
            {
                "fields": (
                    "etag",
                    "sha256_checksum",
                    "checksum_calculated_at",
                    "error_message",
                    "source_csv_file",
                    "source_row_number",
                    "source_column_name",
                    "related_resource",
                    "s3_url",
                )
            },
        ),
        (
            "Timestamps",
            {
                "fields": (
                    "upload_completed_at",
                    "created_at",
                    "updated_at",
                )
            },
        ),
    )

    @admin.display(description="S3 key")
    def short_key(self, obj: S3FileObject) -> str:
        return obj.s3_key[:48] + ("…" if len(obj.s3_key) > 48 else "")

    @admin.display(description="Size")
    def file_size(self, obj: S3FileObject) -> str:
        return filesizeformat(obj.file_size_bytes or 0)

    @admin.display(description="Storage Org")
    def storage_org(self, obj: S3FileObject) -> str:
        if obj.organization:
            return obj.organization
        if obj.session_id:
            session_org = getattr(obj.session, "organization", None) or getattr(obj.session, "institution", None)
            if session_org:
                return str(session_org)
        return "—"

    @admin.display(description="Linked Resource", ordering="related_resource__name")
    def linked_resource(self, obj: S3FileObject) -> str:
        resource = obj.related_resource
        if not resource:
            return "—"
        display_name = resource.name or resource.uri or resource.value or str(resource.pk)
        url = reverse("admin:metadata_resource_change", args=[resource.pk])
        return format_html('<a href="{}">{}</a>', url, display_name)

    @admin.display(description="Resource Org", ordering="related_resource__organization__name")
    def resource_org(self, obj: S3FileObject) -> str:
        resource = obj.related_resource
        if not resource or not resource.organization:
            return "—"
        organization = resource.organization
        return getattr(organization, "name", None) or getattr(organization, "code", None) or str(organization)
