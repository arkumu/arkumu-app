from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("metadata", "0024_remove_guardian_tables"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="triple",
            index=models.Index(
                fields=["predicate", "object", "subject"],
                name="metadata_tr_pred_obj_subj_idx",
            ),
        ),
    ]
