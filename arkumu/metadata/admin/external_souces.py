"""Admin configuration for external entities."""

from __future__ import annotations

from django.contrib import admin

from arkumu.metadata.models import ExternalSourcesEntity


@admin.register(ExternalSourcesEntity)
class ExternalSourcesEntityAdmin(admin.ModelAdmin):
    list_display = (
        "source",
        "data_id",
        "property",
        "datum",
        "updated_at",
    )
    search_fields = (
        "source",
        "data_id",
        "property",
        "datum",
        "updated_at",
    )
    list_filter = (
        "source",
        "property",
        "updated_at",
    )
    readonly_fields = (
        "created_at",
        "updated_at",
    )
    ordering = ("source", "data_id", "property")
