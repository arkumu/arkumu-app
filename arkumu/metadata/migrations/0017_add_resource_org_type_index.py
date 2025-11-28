from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("metadata", "0016_add_s3fileobject_related_name"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="resource",
            index=models.Index(
                fields=["organization", "resource_type"],
                name="metadata_re_org_type_idx",
            ),
        ),
    ]
