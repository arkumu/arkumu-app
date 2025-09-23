"""Admin configuration for external entities."""

from __future__ import annotations

from django.contrib import admin

from arkumu.metadata.models import ExternalSourcesEntity


@admin.register(ExternalSourcesEntity)
class ExternalSourcesEntityAdmin(admin.ModelAdmin):
    list_display = (
        "data_id",
        "property",
        "datum",
        "source",
    )
    search_fields = (
        "data_id",
        "property",
        "datum",
        "source",
    )
    list_filter = (
        "updated_at",
        "property",
        "source",
    )
    readonly_fields = (
        "created_at",
        "updated_at",
    )
    ordering = ("data_id",)
