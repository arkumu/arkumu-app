"""
Resolve existing Equipmentart_fk literal values to entity URI references.

This migration converts triples like:
  equipment -> equipmentart-fk -> "33" (literal)
To:
  equipment -> equipmentart-fk -> http://arkumu.org/data/khm/entities/20-equipmentart/33 (entity)
"""

from django.db import migrations


def resolve_equipmentart_fk_triples(apps, schema_editor):
    """Convert literal FK values to entity references."""
    Resource = apps.get_model("metadata", "Resource")
    Triple = apps.get_model("metadata", "Triple")

    # Find the equipmentart-fk predicate
    predicate = Resource.objects.filter(
        uri="http://arkumu.org/data/khm/properties/equipmentart-fk"
    ).first()

    if not predicate:
        print("  equipmentart-fk predicate not found, skipping")
        return

    # Find all triples with this predicate that have literal values
    fk_triples = Triple.objects.filter(
        predicate=predicate,
        object__value__isnull=False,  # Has a literal value
    ).select_related("object")

    print(f"  Found {fk_triples.count()} equipmentart-fk triples with literal values")

    # Build cache of equipmentart entities by ID
    equipmentart_entities = Resource.objects.filter(
        uri__startswith="http://arkumu.org/data/khm/entities/20-equipmentart/"
    )

    # Map ID -> entity
    id_to_entity = {}
    for entity in equipmentart_entities:
        # Extract ID from URI like .../20-equipmentart/33
        entity_id = entity.uri.rsplit("/", 1)[-1]
        id_to_entity[entity_id] = entity

    print(f"  Found {len(id_to_entity)} equipmentart entities")

    # Update triples
    updated = 0
    not_found = set()

    for triple in fk_triples:
        fk_value = triple.object.value
        if not fk_value:
            continue

        # Look up the entity
        entity = id_to_entity.get(str(fk_value).strip())
        if not entity:
            not_found.add(fk_value)
            continue

        # Update the triple to point to the entity instead of the literal
        triple.object = entity
        triple.save(update_fields=["object"])
        updated += 1

    print(f"  Updated {updated} triples to reference equipmentart entities")
    if not_found:
        print(f"  Could not find entities for FK values: {sorted(not_found)[:10]}")


def reverse_migration(apps, schema_editor):
    """Reverse is complex - would need to recreate literals. Skip for now."""
    print("  Reverse migration not implemented - would need to recreate literal resources")


class Migration(migrations.Migration):

    dependencies = [
        ("metadata", "0020_fix_khm_equipment_fk_relationship"),
    ]

    operations = [
        migrations.RunPython(resolve_equipmentart_fk_triples, reverse_migration),
    ]
