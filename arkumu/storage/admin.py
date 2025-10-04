from django.contrib import admin
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _

from .models import S3ResourceLocation, S3FileObject, UploadSession, ACLPermissions


class RelatedResourceFilter(admin.SimpleListFilter):
    title = _("Has related resource")
    parameter_name = "has_related_resource"

    def lookups(self, request, model_admin):
        return (("yes", _("Yes")), ("no", _("No")))

    def queryset(self, request, queryset):
        if self.value() == "yes":
            return queryset.exclude(related_resource__isnull=True)
        if self.value() == "no":
            return queryset.filter(related_resource__isnull=True)
        return queryset


class SessionBucketFilter(admin.SimpleListFilter):
    title = _("Upload bucket")
    parameter_name = "session_bucket"

    def lookups(self, request, model_admin):
        buckets = (
            S3FileObject.objects.filter(session__isnull=False)
            .values_list("session__s3_bucket", flat=True)
            .distinct()
        )
        return tuple((b, b or _("(unset)")) for b in buckets if b is not None) or ((),)

    def queryset(self, request, queryset):
        if self.value():
            return queryset.filter(session__s3_bucket=self.value())
        return queryset

@admin.register(S3ResourceLocation)
class S3ResourceLocationAdmin(admin.ModelAdmin):
    list_display = ('resource_pid', 's3_bucket', 's3_key', 'content_type', 'object_id')
    search_fields = ('resource_pid', 's3_bucket', 's3_key')
    list_filter = ('s3_bucket',)

@admin.register(S3FileObject)
class S3FileObjectAdmin(admin.ModelAdmin):
    list_display = (
        'file_name',
        'status',
        'content_type',
        'file_size_bytes',
        's3_key',
        'session_bucket',
        'related_resource_link',
    )
    search_fields = (
        'file_name',
        's3_key',
        'session__s3_bucket',
        'related_resource__uri',
        'related_resource__value',
    )
    list_filter = (
        'status',
        'content_type',
        SessionBucketFilter,
        RelatedResourceFilter,
    )
    readonly_fields = (
        'id',
        'created_at',
        'updated_at',
        'upload_completed_at',
        'size_display',
        'url_preview',
    )

    fieldsets = (
        (None, {
            'fields': (
                'file_name',
                'content_type',
                'status',
                'size_display',
                's3_key',
                'related_resource',
                'session',
                'url_preview',
            )
        }),
        (_('Timestamps'), {
            'classes': ('collapse',),
            'fields': ('created_at', 'updated_at', 'upload_completed_at'),
        }),
    )

    def size_display(self, obj):
        if obj.file_size_bytes is None:
            return '-'
        value = obj.file_size_bytes
        for unit in ['bytes', 'KB', 'MB', 'GB', 'TB']:
            if value < 1024 or unit == 'TB':
                break
            value /= 1024
        return f"{value:.1f} {unit}"
    size_display.short_description = _('Size')

    def session_bucket(self, obj):
        return getattr(obj.session, 's3_bucket', None) or _('(unset)')
    session_bucket.short_description = _('Bucket')

    def related_resource_link(self, obj):
        resource = obj.related_resource
        if not resource:
            return _('(none)')
        url = f"/metadata/resource/{resource.id}/"
        label = resource.uri or resource.value or resource.id
        return format_html('<a href="{}">{}</a>', url, label)
    related_resource_link.short_description = _('Related resource')

    def url_preview(self, obj):
        if not obj.s3_key:
            return _('(no key)')
        if obj.session and obj.session.s3_bucket:
            bucket = obj.session.s3_bucket
        else:
            bucket = _('(unknown bucket)')
        return format_html('<code>{}/{}</code>', bucket, obj.s3_key)
    url_preview.short_description = _('S3 object')

@admin.register(UploadSession)
class UploadSessionAdmin(admin.ModelAdmin):
    list_display = ('id', 'created_at', 'user', 'status')
    search_fields = ('id', 'user__username')
    list_filter = ('status',)

@admin.register(ACLPermissions)
class ACLPermissionsAdmin(admin.ModelAdmin):
    list_display = ('id', 'content_type', 'object_id')
    list_filter = ('content_type',)
