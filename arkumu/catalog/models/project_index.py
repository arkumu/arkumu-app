from __future__ import annotations

from typing import TYPE_CHECKING, List, Optional

from django.contrib.postgres.fields import ArrayField
from django.contrib.postgres.indexes import GinIndex
from django.db import models
from django.utils import timezone

from arkumu.metadata.models.resource import PublicAccessLevel, Resource
from arkumu.catalog.models.preview_imgs import PreviewImages

if TYPE_CHECKING:
    from arkumu.projects import ProjectRecord


class ProjectIndex(models.Model):
    """Unified project index combining card, search, and detail data.

    This single table replaces the previous three-table design:
    - Card display fields (title, subtitle, image, etc.)
    - Search arrays (category_labels, actor_names, year_values)
    - Structured JSON for detail views (categories, actors, events)
    - Full record JSON blob (record_jsonb)
    """

    ORG_CODE_TO_NAME = {
        "fuk": "Folkwang Universität der Künste",
        "rsh": "Robert Schumann Hochschule Düsseldorf",
        "khm": "Kunsthochschule für Medien Köln",
        "det": "Hochschule für Musik Detmold",
        "hmt": "Hochschule für Musik und Tanz Köln",
    }

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

    # --- Core display fields ---
    title = models.TextField(blank=True, default="")
    subtitle = models.TextField(blank=True, default="")
    description = models.TextField(blank=True, default="")
    image = models.TextField(blank=True, default="")
    year_range = models.CharField(max_length=64, blank=True, default="")

    # --- Relationships (denormalized) ---
    institution_label = models.TextField(blank=True, default="")
    institution_uri = models.URLField(max_length=512, blank=True, default="")
    institution_codes = ArrayField(models.TextField(), default=list, blank=True)
    project_type_label = models.TextField(blank=True, default="")

    # --- Flat arrays for search/filtering (GIN indexed) ---
    category_labels = ArrayField(models.TextField(), default=list, blank=True)
    category_slugs = ArrayField(models.TextField(), default=list, blank=True)
    actor_names = ArrayField(models.TextField(), default=list, blank=True)
    year_values = ArrayField(models.IntegerField(), default=list, blank=True)
    catchphrase_labels = ArrayField(models.TextField(), default=list, blank=True)
    digital_object_paths = ArrayField(models.TextField(), default=list, blank=True)

    # --- Pre-computed DC metadata for OAI-PMH ---
    dc_creators = ArrayField(models.TextField(), default=list, blank=True)
    dc_contributors = ArrayField(models.TextField(), default=list, blank=True)
    has_copyright_holder = models.BooleanField(default=False)
    has_neighbouring_rights_holder = models.BooleanField(default=False)

    # --- Structured JSON for detail views ---
    categories = models.JSONField(default=list)  # [{label, uri, slug}]
    actors = models.JSONField(default=list)  # [{name, roles, uri}]
    events = models.JSONField(default=list)  # [{id, name, start, end, location, actors}]
    digital_objects = models.JSONField(default=list)  # [{path, access_url}]
    alternative_titles = models.JSONField(default=list)  # [{value}]
    catchphrases = models.JSONField(default=list)  # [{label}]

    # --- Metadata bundles (structured JSON) ---
    properties = models.JSONField(default=dict)  # dauer, tonarten, etc.
    status = models.JSONField(default=dict)  # signatur, etc.
    authority = models.JSONField(default=dict)  # wikidata_ids, gnd_ids
    submitter = models.JSONField(default=dict)
    licenses = models.JSONField(default=dict)
    rights_status = models.JSONField(default=dict)

    # --- Full record JSON blob ---
    record_jsonb = models.JSONField(default=dict)

    # --- Pre-computed RDF/XML for OAI-PMH ---
    canonical_rdf_xml = models.TextField(
        blank=True,
        default="",
        help_text="Pre-serialized RDF/XML of the canonical entity graph",
    )
    institutional_rdf_xml = models.TextField(
        blank=True,
        default="",
        help_text="Pre-serialized RDF/XML of the institutional/org-specific entity graph",
    )

    # --- Flags ---
    reference_only = models.BooleanField(default=False)
    harvestable = models.BooleanField(default=True)
    ownership_filtered = models.BooleanField(default=False)

    # --- Index metadata ---
    source_updated_at = models.DateTimeField(null=True, blank=True)
    built_at = models.DateTimeField(default=timezone.now)
    source_version = models.CharField(max_length=128, blank=True, default="")

    class Meta:
        db_table = "project_index"
        indexes = [
            models.Index(
                fields=["org_code", "public_access_level", "is_public_approved"],
                name="project_index_visibility_idx",
            ),
            GinIndex(
                fields=["title"],
                name="project_index_title_trgm",
                opclasses=["gin_trgm_ops"],
            ),
            GinIndex(
                fields=["subtitle"],
                name="project_index_subtitle_trgm",
                opclasses=["gin_trgm_ops"],
            ),
            GinIndex(
                fields=["category_labels"],
                name="project_index_cat_labels_gin",
            ),
            GinIndex(
                fields=["category_slugs"],
                name="project_index_cat_slugs_gin",
            ),
            GinIndex(
                fields=["actor_names"],
                name="project_index_actor_names_gin",
            ),
            GinIndex(
                fields=["institution_codes"],
                name="project_index_inst_codes_gin",
            ),
            GinIndex(
                fields=["year_values"],
                name="project_index_year_vals_gin",
            ),
        ]
        ordering = ["org_code", "title"]

    def __str__(self) -> str:
        return f"{self.uri or self.project_resource_id}"

    # --- Card methods ---

    def to_card_dict(self) -> dict:
        """Materialize the stored projection into the public card payload."""

        def _preferred_image() -> str:
            # Return first digital_object_path that exists in PreviewImages
            for path in (self.digital_object_paths or []):
                if not path:
                    continue
                # Normalize backslashes to forward slashes
                normalized = path.replace("\\", "/")
                if not normalized.startswith("/"):
                    normalized = "/" + normalized
                if PreviewImages.objects.filter(path=normalized).exists():
                    return normalized
            return ""

        card = {
            "uri": self.uri,
            "title": self.title or "",
            "subtitle": self.subtitle or "",
            "image": _preferred_image(),
            "institution": self.ORG_CODE_TO_NAME.get(self.org_code, self.org_code),
            "categories": list(self.category_labels or []),
            "year_range": self.year_range or "",
            "digital_objects": list(self.digital_object_paths or []),
        }

        # Use dc_creators and dc_contributors (formatted as "Name (Role)" or "Name")
        all_contributors = list(self.dc_creators or []) + list(self.dc_contributors or [])
        for idx, entry in enumerate(all_contributors[:4]):
            if not entry:
                continue
            # Parse "Name (Role)" format - extract name and role separately
            if " (" in entry and entry.endswith(")"):
                name, role = entry.rsplit(" (", 1)
                role = role[:-1]  # Remove trailing ")"
            else:
                name = entry
                role = ""
            card[f"contributor{idx + 1}_name"] = name
            card[f"contributor{idx + 1}_role"] = role

        if len(all_contributors) > 4:
            card["additional_contributors"] = f"{len(all_contributors) - 4} weitere"

        if self.category_labels and len(self.category_labels) > 4:
            card["additional_categories"] = f"{len(self.category_labels) - 4} weitere"

        for idx, category in enumerate((self.category_labels or [])[:4]):
            card[f"category{idx + 1}"] = category

        return card

    # --- RDF properties ---

    @property
    def has_canonical_rdf(self) -> bool:
        return bool(self.canonical_rdf_xml)

    @property
    def has_institutional_rdf(self) -> bool:
        return bool(self.institutional_rdf_xml)

    # --- Record methods ---

    def to_record(self) -> Optional["ProjectRecord"]:
        """Materialize the stored JSON into a ProjectRecord."""
        try:
            from arkumu.projects import ProjectRecord

            return ProjectRecord.from_dict(self.record_jsonb)
        except Exception:
            return None

    # --- Detail view methods ---

    def to_view_context(self) -> dict:
        """Build the context dict for project detail view templates."""
        normalized_events = []
        for event in self.events or []:
            # Skip junction entities without proper event data (e.g., HMT kreuz-projekt-ereignis)
            name = event.get("name")
            if not name or (isinstance(name, str) and name.isdigit()):
                continue
            actors = event.get("actors", [])
            start = event.get("start")
            end = event.get("end")
            if start and end:
                display_date = start if start == end else f"{start} – {end}"
            else:
                display_date = start or end or None
            normalized_event = {
                **event,
                "display_date": display_date,
                "primary_actor": actors[0].get("name", "") if len(actors) > 0 else "",
                "secondary_actor": actors[1].get("name", "") if len(actors) > 1 else "",
            }
            normalized_events.append(normalized_event)

        return {
            "uri": self.uri,
            "title": self.title or "Untitled Project",
            "subtitle": self.subtitle or "",
            "alternative_title": (
                self.alternative_titles[0].get("value", "") if self.alternative_titles else ""
            ),
            "descriptions": [self.description] if self.description else [],
            "image": self._resolve_images(),
            "institution": self.ORG_CODE_TO_NAME.get(self.org_code, self.org_code),
            "projektart": self.project_type_label or "",
            "year_range": self.year_range or "",
            "categories": self.categories or [],
            "actors": self.actors or [],
            "catchphrases": self.catchphrases or [],
            "digital_objects": [
                obj.get("path") for obj in (self.digital_objects or []) if obj.get("path")
            ],
            "events": normalized_events,
        }

    def _resolve_images(self) -> List[str]:
        """Extract image paths with preview availability."""
        from arkumu.catalog.models import PreviewImages

        def normalize(p: str) -> str:
            return p.replace("\\", "/").replace(" ", "_")

        candidates = []
        seen = set()
        if self.image:
            norm = normalize(self.image)
            if norm not in seen:
                seen.add(norm)
                candidates.append(norm)
        for obj in self.digital_objects or []:
            path = obj.get("path")
            if path:
                norm = normalize(path)
                if norm not in seen:
                    seen.add(norm)
                    candidates.append(norm)

        preview_paths = []
        for candidate in candidates:
            if PreviewImages.objects.filter(path=candidate).exists():
                preview_paths.append(candidate)

        return preview_paths or candidates


# Backwards compatibility aliases
ProjectRecordIndex = ProjectIndex
ProjectDetailIndex = ProjectIndex
