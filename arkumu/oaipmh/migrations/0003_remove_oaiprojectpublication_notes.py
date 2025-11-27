from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("oaipmh", "0002_oaiprojectpublication"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="oaiprojectpublication",
            name="notes",
        ),
    ]

