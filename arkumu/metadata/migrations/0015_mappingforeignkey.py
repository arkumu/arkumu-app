from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("metadata", "0014_merge_20251107_1639"),
    ]

    operations = [
        migrations.CreateModel(
            name="MappingForeignKey",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("organization_code", models.CharField(db_index=True, max_length=64)),
                ("source_dataset", models.CharField(max_length=255)),
                ("source_column", models.CharField(max_length=255)),
                ("target_dataset", models.CharField(max_length=255)),
                ("target_column", models.CharField(max_length=255)),
                ("relationship_type", models.CharField(blank=True, max_length=64)),
                ("direction", models.CharField(blank=True, max_length=32)),
                ("display_column", models.CharField(blank=True, max_length=255)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "Mapping Foreign Key",
                "verbose_name_plural": "Mapping Foreign Keys",
                "unique_together": {
                    (
                        "organization_code",
                        "source_dataset",
                        "source_column",
                        "target_dataset",
                        "target_column",
                    )
                },
            },
        ),
        migrations.AddIndex(
            model_name="mappingforeignkey",
            index=models.Index(
                fields=["organization_code", "source_dataset"],
                name="metadata_fk_source_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="mappingforeignkey",
            index=models.Index(
                fields=["organization_code", "target_dataset"],
                name="metadata_fk_target_idx",
            ),
        ),
    ]
