import base64
import json

from django.contrib import admin
from django.template.defaultfilters import filesizeformat, truncatechars
from django.utils.html import format_html

from arkumu.catalog.models import PreviewImages, ProjectIndex


@admin.register(PreviewImages)
class PreviewImagesAdmin(admin.ModelAdmin):
    search_fields = ["path", "bucket"]
    list_display = [
        "path_truncated",
        "bucket",
        "content_type",
        "human_filesize",
        "last_download",
        "thumbnail_preview",
    ]
    readonly_fields = ["image_preview", "human_filesize", "last_download"]
    ordering = ("bucket", "path")
    list_filter = ("bucket", "content_type")
    list_per_page = 50
    fields = (
        "bucket",
        "path",
        "content_type",
        "human_filesize",
        "last_download",
        "image_preview",
    )

    @admin.display(description="Path")
    def path_truncated(self, obj):
        return truncatechars(obj.path, 60)

    @admin.display(description="Thumb")
    def thumbnail_preview(self, obj):
        if not obj.img:
            return "-"
        try:
            encoded = base64.b64encode(obj.img).decode("utf-8")
            return format_html(
                '<img src="data:{};base64,{}" style="max-height: 40px; width: auto;" />',
                obj.content_type,
                encoded,
            )
        except Exception:
            return "-"

    @admin.display(description="Preview")
    def image_preview(self, obj):
        if not obj.img:
            return "(No image data)"
        try:
            encoded = base64.b64encode(obj.img).decode("utf-8")
            return format_html(
                '<img src="data:{};base64,{}" style="max-width: 50%; height: auto;" />',
                obj.content_type,
                encoded,
            )
        except Exception as e:
            return format_html(
                "<span style='color:red;'>(Error displaying image: {})</span>", e
            )

    @admin.display(description="Size")
    def human_filesize(self, obj):
        if not obj.content_length:
            return "-"
        return filesizeformat(obj.content_length)


@admin.register(ProjectIndex)
class ProjectIndexAdmin(admin.ModelAdmin):
    """Unified admin for the consolidated ProjectIndex model."""

    list_display = (
        "title_short",
        "org_code",
        "institution_label",
        "project_type_label",
        "category_count",
        "actor_count",
        "event_count",
        "public_access_level",
        "is_public_approved",
        "built_at",
    )
    list_display_links = ("title_short",)
    search_fields = (
        "uri",
        "title",
        "subtitle",
        "description",
        "institution_label",
        "project_type_label",
        "category_labels",
        "actor_names",
    )
    list_filter = (
        "org_code",
        "public_access_level",
        "is_public_approved",
        "is_derived",
        "reference_only",
        "harvestable",
        "ownership_filtered",
    )
    readonly_fields = (
        "project_resource",
        "uri_link",
        "source_updated_at",
        "built_at",
        "source_version",
        "category_labels_display",
        "actors_display",
        "years_display",
        "categories_json_display",
        "actors_json_display",
        "events_json_display",
        "digital_objects_json_display",
        "properties_display",
        "authority_display",
        "record_json_preview",
    )
    ordering = ("org_code", "title")
    list_per_page = 50
    date_hierarchy = "built_at"

    fieldsets = (
        (None, {
            "fields": ("project_resource", "uri_link", "org_code")
        }),
        ("Content", {
            "fields": (
                "title",
                "subtitle",
                "description",
                "image",
                "institution_label",
                "institution_uri",
                "project_type_label",
                "year_range",
            )
        }),
        ("Search Arrays (flat)", {
            "fields": ("category_labels_display", "actors_display", "years_display"),
            "classes": ("collapse",),
        }),
        ("Structured Data (JSON)", {
            "fields": (
                "categories_json_display",
                "actors_json_display",
                "events_json_display",
                "digital_objects_json_display",
            ),
            "classes": ("collapse",),
        }),
        ("Properties & Authority", {
            "fields": ("properties_display", "authority_display"),
            "classes": ("collapse",),
        }),
        ("Full Record JSON", {
            "fields": ("record_json_preview",),
            "classes": ("collapse",),
        }),
        ("Visibility", {
            "fields": (
                "public_access_level",
                "is_public_approved",
                "is_derived",
                "reference_only",
                "harvestable",
                "ownership_filtered",
            )
        }),
        ("Metadata", {
            "fields": ("source_updated_at", "built_at", "source_version"),
            "classes": ("collapse",),
        }),
    )

    @admin.display(description="Title")
    def title_short(self, obj):
        return truncatechars(obj.title, 50) or "(untitled)"

    @admin.display(description="URI")
    def uri_link(self, obj):
        if obj.uri:
            return format_html(
                '<a href="{}" target="_blank">{}</a>',
                obj.uri,
                truncatechars(obj.uri, 60),
            )
        return "-"

    @admin.display(description="Cat.")
    def category_count(self, obj):
        return len(obj.category_labels) if obj.category_labels else 0

    @admin.display(description="Act.")
    def actor_count(self, obj):
        return len(obj.actor_names) if obj.actor_names else 0

    @admin.display(description="Evt.")
    def event_count(self, obj):
        return len(obj.events) if obj.events else 0

    @admin.display(description="Categories (flat)")
    def category_labels_display(self, obj):
        if not obj.category_labels:
            return "-"
        return format_html("<br>".join(obj.category_labels[:20]))

    @admin.display(description="Actors (flat)")
    def actors_display(self, obj):
        if not obj.actor_names:
            return "-"
        return format_html("<br>".join(obj.actor_names[:20]))

    @admin.display(description="Years")
    def years_display(self, obj):
        if not obj.year_values:
            return "-"
        return ", ".join(str(y) for y in sorted(obj.year_values))

    @admin.display(description="Categories (structured)")
    def categories_json_display(self, obj):
        if not obj.categories:
            return "-"
        return format_html(
            '<pre style="max-height: 200px; overflow: auto; background: #f5f5f5; padding: 8px; font-size: 11px;">{}</pre>',
            json.dumps(obj.categories, indent=2, ensure_ascii=False),
        )

    @admin.display(description="Actors (structured)")
    def actors_json_display(self, obj):
        if not obj.actors:
            return "-"
        return format_html(
            '<pre style="max-height: 200px; overflow: auto; background: #f5f5f5; padding: 8px; font-size: 11px;">{}</pre>',
            json.dumps(obj.actors, indent=2, ensure_ascii=False),
        )

    @admin.display(description="Events")
    def events_json_display(self, obj):
        if not obj.events:
            return "-"
        return format_html(
            '<pre style="max-height: 300px; overflow: auto; background: #f5f5f5; padding: 8px; font-size: 11px;">{}</pre>',
            json.dumps(obj.events, indent=2, ensure_ascii=False),
        )

    @admin.display(description="Digital Objects")
    def digital_objects_json_display(self, obj):
        if not obj.digital_objects:
            return "-"
        return format_html(
            '<pre style="max-height: 200px; overflow: auto; background: #f5f5f5; padding: 8px; font-size: 11px;">{}</pre>',
            json.dumps(obj.digital_objects, indent=2, ensure_ascii=False),
        )

    @admin.display(description="Properties")
    def properties_display(self, obj):
        if not obj.properties:
            return "-"
        return format_html(
            '<pre style="max-height: 200px; overflow: auto; background: #f5f5f5; padding: 8px; font-size: 11px;">{}</pre>',
            json.dumps(obj.properties, indent=2, ensure_ascii=False),
        )

    @admin.display(description="Authority IDs")
    def authority_display(self, obj):
        if not obj.authority:
            return "-"
        return format_html(
            '<pre style="max-height: 200px; overflow: auto; background: #f5f5f5; padding: 8px; font-size: 11px;">{}</pre>',
            json.dumps(obj.authority, indent=2, ensure_ascii=False),
        )

    @admin.display(description="Record JSON (preview)")
    def record_json_preview(self, obj):
        if not obj.record_jsonb:
            return "-"
        try:
            formatted = json.dumps(obj.record_jsonb, indent=2, ensure_ascii=False)
            return format_html(
                '<pre style="max-height: 400px; overflow: auto; background: #f5f5f5; padding: 10px; font-size: 11px;">{}</pre>',
                formatted[:10000],
            )
        except Exception:
            return "(Error formatting JSON)"
