from django.contrib import admin

from arkumu.oaipmh.models import OAIProjectMediaLink, OAIProjectPublication


@admin.register(OAIProjectMediaLink)
class OAIProjectMediaLinkAdmin(admin.ModelAdmin):
    """Admin for curated project ↔ digital object links."""

    list_display = (
        "project_uri",
        "digital_object_uri",
        "source",
        "is_stale",
        "order_index",
        "updated_at",
    )
    list_filter = (
        "source",
        "is_stale",
        ("project__organization", admin.RelatedOnlyFieldListFilter),
    )
    search_fields = (
        "project__uri",
        "project__canonical_uri",
        "digital_object__uri",
        "digital_object__canonical_uri",
    )
    raw_id_fields = ("project", "digital_object", "last_reviewed_by")
    readonly_fields = ("created_at", "updated_at", "last_reviewed_at")
    ordering = ("-updated_at",)
    list_select_related = (
        "project",
        "digital_object",
        "project__organization",
        "digital_object__organization",
        "last_reviewed_by",
    )
    autocomplete_fields = ("project", "digital_object", "last_reviewed_by")

    @admin.display(description="Project URI")
    def project_uri(self, obj: OAIProjectMediaLink) -> str:
        return getattr(obj.project, "uri", "") or getattr(obj.project, "canonical_uri", "")

    @admin.display(description="Digital Object URI")
    def digital_object_uri(self, obj: OAIProjectMediaLink) -> str:
        return getattr(obj.digital_object, "uri", "") or getattr(obj.digital_object, "canonical_uri", "")


@admin.register(OAIProjectPublication)
class OAIProjectPublicationAdmin(admin.ModelAdmin):
    """Admin for per-project OAI publication approvals."""

    list_display = (
        "project_uri",
        "is_approved",
        "approved_at",
        "approved_by",
        "updated_at",
    )
    list_filter = (
        "is_approved",
        ("project__organization", admin.RelatedOnlyFieldListFilter),
        ("approved_by", admin.RelatedOnlyFieldListFilter),
    )
    search_fields = (
        "project__uri",
        "project__canonical_uri",
        "project__name",
        "project__value",
    )
    raw_id_fields = ("project", "approved_by")
    readonly_fields = ("created_at", "updated_at", "approved_at")
    ordering = ("-updated_at",)
    list_select_related = ("project", "project__organization", "approved_by")
    autocomplete_fields = ("project", "approved_by")

    @admin.display(description="Project URI")
    def project_uri(self, obj: OAIProjectPublication) -> str:
        return getattr(obj.project, "uri", "") or getattr(obj.project, "canonical_uri", "")
