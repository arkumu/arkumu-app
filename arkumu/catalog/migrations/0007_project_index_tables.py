from django.db import migrations, models
import django.contrib.postgres.fields
import django.contrib.postgres.indexes
import django.utils.timezone
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("metadata", "0016_add_s3fileobject_related_name"),
        ("catalog", "0006_alter_previewimages_bucket_and_more"),
    ]

    operations = [
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
                ("title", models.TextField(blank=True, default="")),
                ("subtitle", models.TextField(blank=True, default="")),
                ("image", models.TextField(blank=True, default="")),
                ("institution_label", models.TextField(blank=True, default="")),
                (
                    "categories",
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
                    "digital_object_paths",
                    django.contrib.postgres.fields.ArrayField(
                        base_field=models.TextField(), blank=True, default=list, size=None
                    ),
                ),
                ("year_range", models.CharField(blank=True, default="", max_length=64)),
                ("source_updated_at", models.DateTimeField(blank=True, null=True)),
                ("built_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("source_version", models.CharField(blank=True, default="", max_length=128)),
            ],
            options={
                "db_table": "projects_index",
                "ordering": ["org_code", "title"],
            },
        ),
        migrations.CreateModel(
            name="ProjectRecordIndex",
            fields=[
                (
                    "project_resource",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        primary_key=True,
                        related_name="project_record_index",
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
                ("title", models.TextField(blank=True, default="")),
                ("subtitle", models.TextField(blank=True, default="")),
                ("description", models.TextField(blank=True, default="")),
                ("institution_label", models.TextField(blank=True, default="")),
                (
                    "institution_codes",
                    django.contrib.postgres.fields.ArrayField(
                        base_field=models.TextField(), blank=True, default=list, size=None
                    ),
                ),
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
                ("project_type_label", models.TextField(blank=True, default="")),
                (
                    "catchphrase_labels",
                    django.contrib.postgres.fields.ArrayField(
                        base_field=models.TextField(), blank=True, default=list, size=None
                    ),
                ),
                ("image", models.TextField(blank=True, default="")),
                (
                    "digital_object_paths",
                    django.contrib.postgres.fields.ArrayField(
                        base_field=models.TextField(), blank=True, default=list, size=None
                    ),
                ),
                ("reference_only", models.BooleanField(default=False)),
                ("harvestable", models.BooleanField(default=True)),
                ("ownership_filtered", models.BooleanField(default=False)),
                ("record_jsonb", models.JSONField()),
                ("source_updated_at", models.DateTimeField(blank=True, null=True)),
                ("built_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("source_version", models.CharField(blank=True, default="", max_length=128)),
            ],
            options={
                "db_table": "project_records",
                "ordering": ["org_code", "title"],
            },
        ),
        migrations.AddIndex(
            model_name="projectindex",
            index=models.Index(
                fields=["org_code", "public_access_level", "is_public_approved"],
                name="projects_index_visibility_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="projectindex",
            index=django.contrib.postgres.indexes.GinIndex(
                fields=["title"],
                name="projects_index_title_trgm",
                opclasses=["gin_trgm_ops"],
            ),
        ),
        migrations.AddIndex(
            model_name="projectindex",
            index=django.contrib.postgres.indexes.GinIndex(
                fields=["subtitle"],
                name="projects_index_subtitle_trgm",
                opclasses=["gin_trgm_ops"],
            ),
        ),
        migrations.AddIndex(
            model_name="projectindex",
            index=django.contrib.postgres.indexes.GinIndex(
                fields=["categories"],
                name="projects_index_categories_gin",
            ),
        ),
        migrations.AddIndex(
            model_name="projectindex",
            index=django.contrib.postgres.indexes.GinIndex(
                fields=["actor_names"],
                name="projects_index_actor_names_gin",
            ),
        ),
        migrations.AddIndex(
            model_name="projectrecordindex",
            index=models.Index(
                fields=["org_code", "public_access_level", "is_public_approved"],
                name="project_records_visibility_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="projectrecordindex",
            index=django.contrib.postgres.indexes.GinIndex(
                fields=["title"],
                name="project_records_title_trgm",
                opclasses=["gin_trgm_ops"],
            ),
        ),
        migrations.AddIndex(
            model_name="projectrecordindex",
            index=django.contrib.postgres.indexes.GinIndex(
                fields=["subtitle"],
                name="project_records_subtitle_trgm",
                opclasses=["gin_trgm_ops"],
            ),
        ),
        migrations.AddIndex(
            model_name="projectrecordindex",
            index=django.contrib.postgres.indexes.GinIndex(
                fields=["category_labels"],
                name="prj_rec_cat_labels_gin",
            ),
        ),
        migrations.AddIndex(
            model_name="projectrecordindex",
            index=django.contrib.postgres.indexes.GinIndex(
                fields=["category_slugs"],
                name="prj_rec_cat_slugs_gin",
            ),
        ),
        migrations.AddIndex(
            model_name="projectrecordindex",
            index=django.contrib.postgres.indexes.GinIndex(
                fields=["actor_names"],
                name="prj_rec_actr_names_gin",
            ),
        ),
        migrations.AddIndex(
            model_name="projectrecordindex",
            index=django.contrib.postgres.indexes.GinIndex(
                fields=["institution_codes"],
                name="prj_rec_inst_codes_gin",
            ),
        ),
        migrations.AddIndex(
            model_name="projectrecordindex",
            index=django.contrib.postgres.indexes.GinIndex(
                fields=["year_values"],
                name="prj_rec_year_vals_gin",
            ),
        ),
    ]
