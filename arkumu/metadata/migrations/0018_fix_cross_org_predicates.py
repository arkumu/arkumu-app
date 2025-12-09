# Data migration to fix cross-organization predicate contamination
# KHM and HMT entities incorrectly use predicates from FUK/DET/RSH/KHM
# Total affected: 305,469 triples

from django.db import migrations


def fix_cross_org_predicates(apps, schema_editor):
    """Fix triples that use predicates from wrong organizations."""
    from django.db import connection

    Resource = apps.get_model('metadata', 'Resource')
    Triple = apps.get_model('metadata', 'Triple')
    Organization = apps.get_model('users', 'Organization')

    # Get organization IDs
    orgs = {o.code: o.id for o in Organization.objects.all()}

    # Step 1: Fix KHM projektkategorie canonical_uri (wrong: synonyme, correct: projektkategorie)
    khm_projektkategorie = Resource.objects.filter(
        uri='http://arkumu.org/data/khm/properties/projekte-export-projektkategorien-arkumu'
    ).first()
    if khm_projektkategorie and khm_projektkategorie.canonical_uri != 'http://arkumu.org/data/properties/projektkategorie':
        khm_projektkategorie.canonical_uri = 'http://arkumu.org/data/properties/projektkategorie'
        khm_projektkategorie.save(update_fields=['canonical_uri'])
        print(f"  Fixed KHM projektkategorie canonical_uri")

    # Step 2: Build predicate mapping (wrong_uri -> correct_uri for each org)
    # Format: (subject_org, wrong_predicate_uri, correct_predicate_uri)
    migrations_map = [
        # KHM migrations (289,882 triples)
        ('khm', 'http://arkumu.org/data/det/properties/digitales-objekt', 'http://arkumu.org/data/khm/properties/dat-id'),
        ('khm', 'http://arkumu.org/data/fuk/properties/digitales-objekt', 'http://arkumu.org/data/khm/properties/dat-id'),
        ('khm', 'http://arkumu.org/data/fuk/properties/ereignis', 'http://arkumu.org/data/khm/properties/kr-event-id'),
        ('khm', 'http://arkumu.org/data/det/properties/akteurin-im-ereignis', 'http://arkumu.org/data/khm/properties/pe-id-fk'),
        ('khm', 'http://arkumu.org/data/det/properties/projektkategorie', 'http://arkumu.org/data/khm/properties/projekte-export-projektkategorien-arkumu'),
        ('khm', 'http://arkumu.org/data/fuk/properties/informationstraeger', 'http://arkumu.org/data/khm/properties/physmedien-id-fk'),
        ('khm', 'http://arkumu.org/data/fuk/properties/schlagwort', 'http://arkumu.org/data/khm/properties/keyword-id-fk'),
        ('khm', 'http://arkumu.org/data/rsh/properties/equipment-und-software', 'http://arkumu.org/data/khm/properties/equipment-id-fk'),
        # HMT migrations (15,587 triples)
        ('hmt', 'http://arkumu.org/data/det/properties/akteurin-im-ereignis', 'http://arkumu.org/data/hmt/properties/hfmt-akteur-id-fk'),
        ('hmt', 'http://arkumu.org/data/det/properties/digitales-objekt', 'http://arkumu.org/data/hmt/properties/digitalesobjekt-id-fk'),
        ('hmt', 'http://arkumu.org/data/fuk/properties/ereignis', 'http://arkumu.org/data/hmt/properties/ereignisnr'),
        ('hmt', 'http://arkumu.org/data/khm/properties/proj-id-fk', 'http://arkumu.org/data/hmt/properties/hfmt-werk-id-fk'),
        ('hmt', 'http://arkumu.org/data/det/properties/projektkategorie', 'http://arkumu.org/data/hmt/properties/projektkategorie'),
        ('hmt', 'http://arkumu.org/data/fuk/properties/digitales-objekt', 'http://arkumu.org/data/hmt/properties/digitalesobjekt-id-fk'),
    ]

    # Cache predicate lookups
    predicate_cache = {}

    def get_predicate_id(uri):
        if uri not in predicate_cache:
            pred = Resource.objects.filter(uri=uri, resource_type='PROPERTY').first()
            predicate_cache[uri] = pred.id if pred else None
        return predicate_cache[uri]

    # Step 3: Execute migrations using raw SQL to handle duplicates
    total_updated = 0
    total_deleted = 0

    for subject_org, wrong_uri, correct_uri in migrations_map:
        wrong_pred_id = get_predicate_id(wrong_uri)
        correct_pred_id = get_predicate_id(correct_uri)

        if not wrong_pred_id:
            print(f"  WARNING: Wrong predicate not found: {wrong_uri}")
            continue
        if not correct_pred_id:
            print(f"  WARNING: Correct predicate not found: {correct_uri}")
            continue

        org_id = orgs.get(subject_org)
        if not org_id:
            print(f"  WARNING: Organization not found: {subject_org}")
            continue

        # First, delete triples that would become duplicates after update
        # (where the same subject-object pair already exists with correct predicate)
        with connection.cursor() as cursor:
            cursor.execute("""
                DELETE FROM metadata_triple t1
                WHERE t1.predicate_id = %s
                AND t1.subject_id IN (
                    SELECT r.id FROM metadata_resource r WHERE r.organization_id = %s
                )
                AND EXISTS (
                    SELECT 1 FROM metadata_triple t2
                    WHERE t2.subject_id = t1.subject_id
                    AND t2.object_id = t1.object_id
                    AND t2.predicate_id = %s
                )
            """, [str(wrong_pred_id), str(org_id), str(correct_pred_id)])
            deleted = cursor.rowcount

        if deleted > 0:
            print(f"  {subject_org}: {deleted:,} duplicate triples removed")
            total_deleted += deleted

        # Now update the remaining triples
        updated = Triple.objects.filter(
            subject__organization_id=org_id,
            predicate_id=wrong_pred_id
        ).update(predicate_id=correct_pred_id)

        if updated > 0:
            print(f"  {subject_org}: {updated:,} triples updated ({wrong_uri.split('/')[-1]} -> {correct_uri.split('/')[-1]})")
            total_updated += updated

    print(f"  TOTAL: {total_updated:,} triples fixed, {total_deleted:,} duplicates removed")


def reverse_migration(apps, schema_editor):
    """Reverse the predicate fixes (for rollback)."""
    Resource = apps.get_model('metadata', 'Resource')
    Triple = apps.get_model('metadata', 'Triple')
    Organization = apps.get_model('users', 'Organization')

    orgs = {o.code: o.id for o in Organization.objects.all()}

    # Reverse mapping (correct -> wrong)
    reverse_map = [
        # KHM reversals
        ('khm', 'http://arkumu.org/data/khm/properties/dat-id', 'http://arkumu.org/data/det/properties/digitales-objekt'),
        ('khm', 'http://arkumu.org/data/khm/properties/kr-event-id', 'http://arkumu.org/data/fuk/properties/ereignis'),
        ('khm', 'http://arkumu.org/data/khm/properties/pe-id-fk', 'http://arkumu.org/data/det/properties/akteurin-im-ereignis'),
        ('khm', 'http://arkumu.org/data/khm/properties/projekte-export-projektkategorien-arkumu', 'http://arkumu.org/data/det/properties/projektkategorie'),
        ('khm', 'http://arkumu.org/data/khm/properties/physmedien-id-fk', 'http://arkumu.org/data/fuk/properties/informationstraeger'),
        ('khm', 'http://arkumu.org/data/khm/properties/keyword-id-fk', 'http://arkumu.org/data/fuk/properties/schlagwort'),
        ('khm', 'http://arkumu.org/data/khm/properties/equipment-id-fk', 'http://arkumu.org/data/rsh/properties/equipment-und-software'),
        # HMT reversals
        ('hmt', 'http://arkumu.org/data/hmt/properties/hfmt-akteur-id-fk', 'http://arkumu.org/data/det/properties/akteurin-im-ereignis'),
        ('hmt', 'http://arkumu.org/data/hmt/properties/digitalesobjekt-id-fk', 'http://arkumu.org/data/det/properties/digitales-objekt'),
        ('hmt', 'http://arkumu.org/data/hmt/properties/ereignisnr', 'http://arkumu.org/data/fuk/properties/ereignis'),
        ('hmt', 'http://arkumu.org/data/hmt/properties/hfmt-werk-id-fk', 'http://arkumu.org/data/khm/properties/proj-id-fk'),
        ('hmt', 'http://arkumu.org/data/hmt/properties/projektkategorie', 'http://arkumu.org/data/det/properties/projektkategorie'),
    ]

    predicate_cache = {}

    def get_predicate_id(uri):
        if uri not in predicate_cache:
            pred = Resource.objects.filter(uri=uri, resource_type='PROPERTY').first()
            predicate_cache[uri] = pred.id if pred else None
        return predicate_cache[uri]

    # Note: This reversal is approximate - it won't perfectly restore the original state
    # because some triples may have come from different wrong sources (det vs fuk)
    print("  WARNING: Reversal is approximate and may not perfectly restore original state")

    for subject_org, correct_uri, wrong_uri in reverse_map:
        correct_pred_id = get_predicate_id(correct_uri)
        wrong_pred_id = get_predicate_id(wrong_uri)

        if not correct_pred_id or not wrong_pred_id:
            continue

        org_id = orgs.get(subject_org)
        if not org_id:
            continue

        updated = Triple.objects.filter(
            subject__organization_id=org_id,
            predicate_id=correct_pred_id
        ).update(predicate_id=wrong_pred_id)

        if updated > 0:
            print(f"  {subject_org}: {updated:,} triples reverted")

    # Revert KHM projektkategorie canonical_uri
    khm_projektkategorie = Resource.objects.filter(
        uri='http://arkumu.org/data/khm/properties/projekte-export-projektkategorien-arkumu'
    ).first()
    if khm_projektkategorie:
        khm_projektkategorie.canonical_uri = 'http://arkumu.org/data/properties/synonyme'
        khm_projektkategorie.save(update_fields=['canonical_uri'])


class Migration(migrations.Migration):

    dependencies = [
        ('metadata', '0017_add_resource_org_type_index'),
        ('users', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(fix_cross_org_predicates, reverse_migration),
    ]
