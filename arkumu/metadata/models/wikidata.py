"""Database model for caching Wikidata entities locally."""

from django.db import models
from django.utils import timezone

from arkumu.metadata.models.base import UUIDModel


class WikidataEntity(UUIDModel):
    """Locally cached Wikidata entity metadata."""

    wikidata_id = models.CharField(
        max_length=32,
        unique=True,
        help_text="Wikidata identifier (e.g. Q42)",
    )
    label_de = models.CharField(
        max_length=255,
        blank=True,
        help_text="Preferred German label",
    )
    label_en = models.CharField(
        max_length=255,
        blank=True,
        help_text="Preferred English label",
    )
    description_de = models.TextField(
        blank=True,
        help_text="German description",
    )
    aliases_de = models.JSONField(
        default=list,
        blank=True,
        help_text="List of German aliases provided by Wikidata",
    )
    raw_payload = models.JSONField(
        default=dict,
        blank=True,
        help_text="Raw Wikidata entity payload used for debugging",
    )
    last_resolved_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Timestamp when this entity was last refreshed from Wikidata",
    )

    class Meta:
        ordering = ["wikidata_id"]
        indexes = [
            models.Index(fields=["wikidata_id"]),
        ]

    def touch(self):
        """Update the last_resolved_at timestamp to now."""
        self.last_resolved_at = timezone.now()
        self.save(update_fields=["last_resolved_at"]) 

    def __str__(self) -> str:  # pragma: no cover - human readable helper
        label = self.label_de or self.label_en or self.wikidata_id
        return f"{label} ({self.wikidata_id})"
