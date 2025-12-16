# Data migration to fix KHM beschreibung-verkettet canonical_uri
# The predicate was incorrectly mapped to ereignisbeschreibung instead of beschreibung
# See: https://gitlab.git.nrw/arkumu/arkumu-app/-/issues/128

from django.db import migrations


def fix_beschreibung_canonical_uri(apps, schema_editor):
    """Fix KHM beschreibung-verkettet predicate canonical_uri mapping."""
    Resource = apps.get_model('metadata', 'Resource')

    # Fix beschreibung-verkettet canonical_uri (wrong: ereignisbeschreibung, correct: beschreibung)
    pred = Resource.objects.filter(
        uri='http://arkumu.org/data/khm/properties/beschreibung-verkettet'
    ).first()

    if pred:
        old_canonical = pred.canonical_uri
        if old_canonical != 'http://arkumu.org/data/properties/beschreibung':
            pred.canonical_uri = 'http://arkumu.org/data/properties/beschreibung'
            pred.save(update_fields=['canonical_uri'])
            print(f"  Fixed KHM beschreibung-verkettet canonical_uri: {old_canonical} -> {pred.canonical_uri}")
        else:
            print(f"  KHM beschreibung-verkettet canonical_uri already correct")
    else:
        print("  WARNING: Predicate http://arkumu.org/data/khm/properties/beschreibung-verkettet not found")


def reverse_migration(apps, schema_editor):
    """Reverse the canonical_uri fix (for rollback)."""
    Resource = apps.get_model('metadata', 'Resource')

    pred = Resource.objects.filter(
        uri='http://arkumu.org/data/khm/properties/beschreibung-verkettet'
    ).first()

    if pred:
        pred.canonical_uri = 'http://arkumu.org/data/properties/ereignisbeschreibung'
        pred.save(update_fields=['canonical_uri'])
        print(f"  Reverted KHM beschreibung-verkettet canonical_uri to ereignisbeschreibung")


class Migration(migrations.Migration):

    dependencies = [
        ('metadata', '0022_fix_hmt_informationstraeger_fk'),
    ]

    operations = [
        migrations.RunPython(fix_beschreibung_canonical_uri, reverse_migration),
    ]
