from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("metadata", "0014_merge_20251107_1639"),
        ("oaipmh", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="OAIProjectPublication",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("is_approved", models.BooleanField(default=False, help_text="Whether this project is approved for OAI harvesting.")),
                ("approved_at", models.DateTimeField(blank=True, help_text="When OAI publication was last approved.", null=True)),
                ("notes", models.TextField(blank=True, help_text="Optional notes explaining the OAI publication decision.")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "approved_by",
                    models.ForeignKey(
                        blank=True,
                        help_text="User who last approved OAI publication for this project.",
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="oai_project_publications",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "project",
                    models.OneToOneField(
                        help_text="Project resource this OAI publication state applies to.",
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="oai_publication",
                        to="metadata.resource",
                    ),
                ),
            ],
            options={
                "verbose_name": "OAI Project Publication",
                "verbose_name_plural": "OAI Project Publications",
            },
        ),
        migrations.AddIndex(
            model_name="oaiprojectpublication",
            index=models.Index(fields=["project"], name="oai_project_pub_project_idx"),
        ),
        migrations.AddIndex(
            model_name="oaiprojectpublication",
            index=models.Index(fields=["is_approved"], name="oai_project_pub_approved_idx"),
        ),
    ]

