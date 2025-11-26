from __future__ import annotations

from typing import List, Optional

from django.contrib.postgres.fields import ArrayField
from django.contrib.postgres.indexes import GinIndex
from django.db import models
from django.utils import timezone

from arkumu.metadata.models.resource import PublicAccessLevel, Resource


class ProjectIndex(models.Model):
    """Derived, searchable projection for catalog cards."""

    project_resource = models.OneToOneField(
        Resource,
        on_delete=models.CASCADE,
        primary_key=True,
        related_name="project_index",
    )
    uri = models.URLField(max_length=512, unique=True)
    org_code = models.CharField(max_length=50, blank=True, db_index=True)
    public_access_level = models.CharField(
        max_length=20,
        choices=PublicAccessLevel.choices,
        default=PublicAccessLevel.RESTRICTED,
    )
    is_public_approved = models.BooleanField(default=False)
    is_derived = models.BooleanField(default=False)

    title = models.TextField(blank=True, default="")
    subtitle = models.TextField(blank=True, default="")
    image = models.TextField(blank=True, default="")
    institution_label = models.TextField(blank=True, default="")
    categories = ArrayField(models.TextField(), default=list, blank=True)
    actor_names = ArrayField(models.TextField(), default=list, blank=True)
    digital_object_paths = ArrayField(models.TextField(), default=list, blank=True)
    year_range = models.CharField(max_length=64, blank=True, default="")

    source_updated_at = models.DateTimeField(null=True, blank=True)
    built_at = models.DateTimeField(default=timezone.now)
    source_version = models.CharField(max_length=128, blank=True, default="")

    class Meta:
        db_table = "projects_index"
        indexes = [
            models.Index(
                fields=["org_code", "public_access_level", "is_public_approved"],
                name="projects_index_visibility_idx",
            ),
            GinIndex(
                fields=["title"],
                name="projects_index_title_trgm",
                opclasses=["gin_trgm_ops"],
            ),
            GinIndex(
                fields=["subtitle"],
                name="projects_index_subtitle_trgm",
                opclasses=["gin_trgm_ops"],
            ),
            GinIndex(
                fields=["categories"],
                name="projects_index_categories_gin",
            ),
            GinIndex(
                fields=["actor_names"],
                name="projects_index_actor_names_gin",
            ),
        ]
        ordering = ["org_code", "title"]

    def __str__(self) -> str:  # pragma: no cover - trivial representation
        return f"{self.uri or self.project_resource_id}"

    def to_card_dict(self) -> dict:
        """Materialize the stored projection into the public card payload."""

        def _preferred_image() -> str:
            if self.image:
                return self.image
            if self.digital_object_paths:
                return self.digital_object_paths[0]
            return "images/main/card_1.png"

        card = {
            "uri": self.uri,
            "title": self.title or "",
            "subtitle": self.subtitle or "",
            "image": _preferred_image(),
            "institution": self.institution_label or "",
            "categories": list(self.categories or []),
            "year_range": self.year_range or "",
            "digital_objects": list(self.digital_object_paths or []),
        }

        if self.actor_names:
            # Keep contributor hints compatible with ProjectRecord cards.
            for idx, name in enumerate(self.actor_names[:4]):
                if not name:
                    continue
                card[f"contributor{idx + 1}_name"] = name
            if len(self.actor_names) > 4:
                card["additional_contributors"] = f"{len(self.actor_names) - 4} weitere"

        if self.categories and len(self.categories) > 4:
            card["additional_categories"] = f"{len(self.categories) - 4} weitere"

        for idx, category in enumerate(self.categories[:4]):
            card[f"category{idx + 1}"] = category

        return card


class ProjectRecordIndex(models.Model):
    """Full ProjectRecord cache with helper columns for search."""

    project_resource = models.OneToOneField(
        Resource,
        on_delete=models.CASCADE,
        primary_key=True,
        related_name="project_record_index",
    )
    uri = models.URLField(max_length=512, unique=True)
    org_code = models.CharField(max_length=50, blank=True, db_index=True)
    public_access_level = models.CharField(
        max_length=20,
        choices=PublicAccessLevel.choices,
        default=PublicAccessLevel.RESTRICTED,
    )
    is_public_approved = models.BooleanField(default=False)
    is_derived = models.BooleanField(default=False)

    title = models.TextField(blank=True, default="")
    subtitle = models.TextField(blank=True, default="")
    description = models.TextField(blank=True, default="")
    institution_label = models.TextField(blank=True, default="")
    institution_codes = ArrayField(models.TextField(), default=list, blank=True)
    category_labels = ArrayField(models.TextField(), default=list, blank=True)
    category_slugs = ArrayField(models.TextField(), default=list, blank=True)
    actor_names = ArrayField(models.TextField(), default=list, blank=True)
    year_values = ArrayField(models.IntegerField(), default=list, blank=True)
    project_type_label = models.TextField(blank=True, default="")
    catchphrase_labels = ArrayField(models.TextField(), default=list, blank=True)
    image = models.TextField(blank=True, default="")
    digital_object_paths = ArrayField(models.TextField(), default=list, blank=True)
    reference_only = models.BooleanField(default=False)
    harvestable = models.BooleanField(default=True)
    ownership_filtered = models.BooleanField(default=False)

    record_jsonb = models.JSONField()

    source_updated_at = models.DateTimeField(null=True, blank=True)
    built_at = models.DateTimeField(default=timezone.now)
    source_version = models.CharField(max_length=128, blank=True, default="")

    class Meta:
        db_table = "project_records"
        indexes = [
            models.Index(
                fields=["org_code", "public_access_level", "is_public_approved"],
                name="project_records_visibility_idx",
            ),
            GinIndex(
                fields=["title"],
                name="project_records_title_trgm",
                opclasses=["gin_trgm_ops"],
            ),
            GinIndex(
                fields=["subtitle"],
                name="project_records_subtitle_trgm",
                opclasses=["gin_trgm_ops"],
            ),
            GinIndex(
                fields=["category_labels"],
                name="prj_rec_cat_labels_gin",
            ),
            GinIndex(
                fields=["category_slugs"],
                name="prj_rec_cat_slugs_gin",
            ),
            GinIndex(
                fields=["actor_names"],
                name="prj_rec_actr_names_gin",
            ),
            GinIndex(
                fields=["institution_codes"],
                name="prj_rec_inst_codes_gin",
            ),
            GinIndex(
                fields=["year_values"],
                name="prj_rec_year_vals_gin",
            ),
        ]
        ordering = ["org_code", "title"]

    def __str__(self) -> str:  # pragma: no cover - trivial representation
        return f"{self.uri or self.project_resource_id}"

    def to_record(self) -> Optional["ProjectRecord"]:
        """Materialize the stored JSON into a ProjectRecord."""
        try:
            from arkumu.projects import ProjectRecord

            return ProjectRecord.from_dict(self.record_jsonb)
        except Exception:
            return None


class ProjectDetailIndex(models.Model):
    """Structured detail data for project detail views.

    Replaces the JSON blob approach with typed columns for fast SQL queries
    and predictable schema.
    """

    project_resource = models.OneToOneField(
        Resource,
        on_delete=models.CASCADE,
        primary_key=True,
        related_name="project_detail_index",
    )
    uri = models.URLField(max_length=512, unique=True)
    org_code = models.CharField(max_length=50, blank=True, db_index=True)
    public_access_level = models.CharField(
        max_length=20,
        choices=PublicAccessLevel.choices,
        default=PublicAccessLevel.RESTRICTED,
    )
    is_public_approved = models.BooleanField(default=False)

    # Core fields
    title = models.TextField(blank=True, default="")
    subtitle = models.TextField(blank=True, default="")
    description = models.TextField(blank=True, default="")
    image = models.TextField(blank=True, default="")

    # Relationships (denormalized)
    institution_label = models.TextField(blank=True, default="")
    institution_uri = models.URLField(max_length=512, blank=True, default="")
    project_type_label = models.TextField(blank=True, default="")

    # Year info
    year_range = models.CharField(max_length=64, blank=True, default="")

    # Structured arrays as JSON for complex nested data
    categories = models.JSONField(default=list)  # [{label, uri, slug}]
    actors = models.JSONField(default=list)  # [{name, roles, uri}]
    events = models.JSONField(default=list)  # [{id, name, start, end, location, actors, ...}]
    digital_objects = models.JSONField(default=list)  # [{path, access_url, ...}]
    alternative_titles = models.JSONField(default=list)  # [{value}]
    catchphrases = models.JSONField(default=list)  # [{label}]

    # Metadata bundles (structured JSON)
    properties = models.JSONField(default=dict)  # dauer, tonarten, etc.
    status = models.JSONField(default=dict)  # signatur, etc.
    authority = models.JSONField(default=dict)  # wikidata_ids, gnd_ids
    submitter = models.JSONField(default=dict)
    licenses = models.JSONField(default=dict)
    rights_status = models.JSONField(default=dict)

    # Flags
    reference_only = models.BooleanField(default=False)
    harvestable = models.BooleanField(default=True)
    ownership_filtered = models.BooleanField(default=False)

    # Index metadata
    source_updated_at = models.DateTimeField(null=True, blank=True)
    built_at = models.DateTimeField(default=timezone.now)
    source_version = models.CharField(max_length=128, blank=True, default="")

    class Meta:
        db_table = "project_detail_index"
        indexes = [
            models.Index(
                fields=["org_code", "public_access_level", "is_public_approved"],
                name="prj_detail_visibility_idx",
            ),
        ]
        ordering = ["org_code", "title"]

    def __str__(self) -> str:  # pragma: no cover
        return f"{self.uri or self.project_resource_id}"

    def to_view_context(self) -> dict:
        """Build the context dict for project detail view templates."""
        return {
            "uri": self.uri,
            "title": self.title or "Untitled Project",
            "subtitle": self.subtitle or "",
            "alternative_title": self.alternative_titles[0].get("value", "") if self.alternative_titles else "",
            "descriptions": [self.description] if self.description else [],
            "image": self._resolve_images(),
            "institution": self.institution_label or "",
            "projektart": self.project_type_label or "",
            "year_range": self.year_range or "",
            "categories": self.categories or [],
            "actors": self.actors or [],
            "catchphrases": self.catchphrases or [],
            "digital_objects": [obj.get("path") for obj in (self.digital_objects or []) if obj.get("path")],
            "events": self.events or [],
        }

    def _resolve_images(self) -> List[str]:
        """Extract image paths with preview availability."""
        from arkumu.catalog.models import PreviewImages

        candidates = []
        if self.image:
            candidates.append(self.image)
        for obj in self.digital_objects or []:
            path = obj.get("path")
            if path:
                candidates.append(path)

        # Filter to paths that have previews
        preview_paths = []
        for candidate in candidates:
            if PreviewImages.objects.filter(path=candidate).exists():
                preview_paths.append(candidate)

        return preview_paths or candidates
