# Generated manually - consolidate three project index tables into one

import django.contrib.postgres.fields
import django.contrib.postgres.indexes
import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("catalog", "0008_add_project_detail_index"),
        ("metadata", "0016_add_s3fileobject_related_name"),
    ]

    operations = [
        # Drop the three old tables
        migrations.DeleteModel(name="ProjectDetailIndex"),
        migrations.DeleteModel(name="ProjectRecordIndex"),
        migrations.DeleteModel(name="ProjectIndex"),
        # Create the new unified table
        migrations.CreateModel(
            name="ProjectIndex",
            fields=[
                (
                    "project_resource",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        primary_key=True,
                        related_name="project_index",
                        serialize=False,
                        to="metadata.resource",
                    ),
                ),
                ("uri", models.URLField(max_length=512, unique=True)),
                ("org_code", models.CharField(blank=True, db_index=True, max_length=50)),
                (
                    "public_access_level",
                    models.CharField(
                        choices=[
                            ("private", "Private - Organization only"),
                            ("restricted", "Restricted - Authenticated users only"),
                            ("public", "Public - Catalog display allowed"),
                        ],
                        default="restricted",
                        max_length=20,
                    ),
                ),
                ("is_public_approved", models.BooleanField(default=False)),
                ("is_derived", models.BooleanField(default=False)),
                # Core display fields
                ("title", models.TextField(blank=True, default="")),
                ("subtitle", models.TextField(blank=True, default="")),
                ("description", models.TextField(blank=True, default="")),
                ("image", models.TextField(blank=True, default="")),
                ("year_range", models.CharField(blank=True, default="", max_length=64)),
                # Relationships (denormalized)
                ("institution_label", models.TextField(blank=True, default="")),
                ("institution_uri", models.URLField(blank=True, default="", max_length=512)),
                (
                    "institution_codes",
                    django.contrib.postgres.fields.ArrayField(
                        base_field=models.TextField(), blank=True, default=list, size=None
                    ),
                ),
                ("project_type_label", models.TextField(blank=True, default="")),
                # Flat arrays for search/filtering (GIN indexed)
                (
                    "category_labels",
                    django.contrib.postgres.fields.ArrayField(
                        base_field=models.TextField(), blank=True, default=list, size=None
                    ),
                ),
                (
                    "category_slugs",
                    django.contrib.postgres.fields.ArrayField(
                        base_field=models.TextField(), blank=True, default=list, size=None
                    ),
                ),
                (
                    "actor_names",
                    django.contrib.postgres.fields.ArrayField(
                        base_field=models.TextField(), blank=True, default=list, size=None
                    ),
                ),
                (
                    "year_values",
                    django.contrib.postgres.fields.ArrayField(
                        base_field=models.IntegerField(), blank=True, default=list, size=None
                    ),
                ),
                (
                    "catchphrase_labels",
                    django.contrib.postgres.fields.ArrayField(
                        base_field=models.TextField(), blank=True, default=list, size=None
                    ),
                ),
                (
                    "digital_object_paths",
                    django.contrib.postgres.fields.ArrayField(
                        base_field=models.TextField(), blank=True, default=list, size=None
                    ),
                ),
                # Structured JSON for detail views
                ("categories", models.JSONField(default=list)),
                ("actors", models.JSONField(default=list)),
                ("events", models.JSONField(default=list)),
                ("digital_objects", models.JSONField(default=list)),
                ("alternative_titles", models.JSONField(default=list)),
                ("catchphrases", models.JSONField(default=list)),
                # Metadata bundles (structured JSON)
                ("properties", models.JSONField(default=dict)),
                ("status", models.JSONField(default=dict)),
                ("authority", models.JSONField(default=dict)),
                ("submitter", models.JSONField(default=dict)),
                ("licenses", models.JSONField(default=dict)),
                ("rights_status", models.JSONField(default=dict)),
                # Full record JSON blob
                ("record_jsonb", models.JSONField(default=dict)),
                # Flags
                ("reference_only", models.BooleanField(default=False)),
                ("harvestable", models.BooleanField(default=True)),
                ("ownership_filtered", models.BooleanField(default=False)),
                # Index metadata
                ("source_updated_at", models.DateTimeField(blank=True, null=True)),
                ("built_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("source_version", models.CharField(blank=True, default="", max_length=128)),
            ],
            options={
                "db_table": "project_index",
                "ordering": ["org_code", "title"],
            },
        ),
        # Add indexes
        migrations.AddIndex(
            model_name="projectindex",
            index=models.Index(
                fields=["org_code", "public_access_level", "is_public_approved"],
                name="project_index_visibility_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="projectindex",
            index=django.contrib.postgres.indexes.GinIndex(
                fields=["title"],
                name="project_index_title_trgm",
                opclasses=["gin_trgm_ops"],
            ),
        ),
        migrations.AddIndex(
            model_name="projectindex",
            index=django.contrib.postgres.indexes.GinIndex(
                fields=["subtitle"],
                name="project_index_subtitle_trgm",
                opclasses=["gin_trgm_ops"],
            ),
        ),
        migrations.AddIndex(
            model_name="projectindex",
            index=django.contrib.postgres.indexes.GinIndex(
                fields=["category_labels"],
                name="project_index_cat_labels_gin",
            ),
        ),
        migrations.AddIndex(
            model_name="projectindex",
            index=django.contrib.postgres.indexes.GinIndex(
                fields=["category_slugs"],
                name="project_index_cat_slugs_gin",
            ),
        ),
        migrations.AddIndex(
            model_name="projectindex",
            index=django.contrib.postgres.indexes.GinIndex(
                fields=["actor_names"],
                name="project_index_actor_names_gin",
            ),
        ),
        migrations.AddIndex(
            model_name="projectindex",
            index=django.contrib.postgres.indexes.GinIndex(
                fields=["institution_codes"],
                name="project_index_inst_codes_gin",
            ),
        ),
        migrations.AddIndex(
            model_name="projectindex",
            index=django.contrib.postgres.indexes.GinIndex(
                fields=["year_values"],
                name="project_index_year_vals_gin",
            ),
        ),
    ]
