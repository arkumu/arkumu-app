import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("catalog", "0013_add_oai_precomputed_fields"),
    ]

    operations = [
        migrations.AlterField(
            model_name="previewimages",
            name="last_download",
            field=models.DateTimeField(
                default=django.utils.timezone.now,
                help_text="Last Downloaded",
            ),
        ),
    ]
