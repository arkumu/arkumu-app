"""Drop django-guardian object permission tables.

The ObjectPermissionBackend was never added to AUTHENTICATION_BACKENDS,
so these tables were write-only (never queried for permission checks).
The project uses role-based permissions via the User model instead.
"""

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("metadata", "0023_fix_khm_beschreibung_canonical_uri"),
    ]

    operations = [
        migrations.RunSQL(
            sql="DROP TABLE IF EXISTS guardian_userobjectpermission CASCADE;",
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.RunSQL(
            sql="DROP TABLE IF EXISTS guardian_groupobjectpermission CASCADE;",
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.AlterModelOptions(
            name="resource",
            options={
                "permissions": [
                    ("can_approve_public_access", "Can approve resources for public access"),
                ],
            },
        ),
    ]
