"""Admin configuration for Wikidata entities."""

from __future__ import annotations

from django.contrib import admin

from arkumu.metadata.models import WikidataEntity


@admin.register(WikidataEntity)
class WikidataEntityAdmin(admin.ModelAdmin):
    list_display = (
        "wikidata_id",
        "label_de",
        "label_en",
        "last_resolved_at",
    )
    search_fields = (
        "wikidata_id",
        "label_de",
        "label_en",
        "aliases_de",
    )
    list_filter = ("last_resolved_at",)
    readonly_fields = (
        "created_at",
        "updated_at",
        "last_resolved_at",
    )
    ordering = ("wikidata_id",)
