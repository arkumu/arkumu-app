"""Database model for caching External entities locally."""

from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from arkumu.metadata.models.base import UUIDModel


class ExternalSourcesEntity(UUIDModel):
    """Locally cached External entity metadata."""

    class SourceEnum(models.TextChoices):
        WIKIDATA = "WD", _("WikiData")



    data_id = models.CharField(
        max_length=32,
        help_text="Identifier (e.g. Q42)",
    )
    property = models.CharField(
        max_length=255,
        help_text="Property",
    )
    datum = models.CharField(
        default=dict,
        help_text="Datum retrieved from Source",
    )
    source = models.CharField(
        max_length=2,
        choices=SourceEnum,
        help_text="DataSource",
    )

    class Meta:
        ordering = ["source", "data_id", "property"]
        verbose_name = "External Entity"
        verbose_name_plural = "External Entities"
        indexes = [
            models.Index(fields=["data_id"]),
        ]

    def __str__(self) -> str:  # pragma: no cover - human readable helper
        return f"{self.source}:{self.data_id} + {self.property} -> {self.datum}"
