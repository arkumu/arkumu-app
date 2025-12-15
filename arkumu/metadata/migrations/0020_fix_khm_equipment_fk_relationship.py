"""
Add missing FK relationship from 19_Equipment_und_Software to 20_Equipmentart in KHM schema.

This fixes the issue where Equipmentart_fk values are stored as literals instead of
being resolved to entity URIs during ingestion.
"""

from django.db import migrations


def add_equipment_fk_relationship(apps, schema_editor):
    """Add FK relationship to KHM schema manifest."""
    Mapping = apps.get_model("metadata", "Mapping")

    # Get KHM mappings
    khm_mappings = Mapping.objects.filter(organization_id__iexact="khm")

    updated = 0
    for mapping in khm_mappings:
        config = mapping.mapping_config or {}
        schema = config.get("schema_manifest", {})

        # Find 19_Equipment_und_Software dataset
        equipment_key = None
        for key in schema.keys():
            if "19" in key and "equipment" in key.lower() and "kreuz" not in key.lower():
                equipment_key = key
                break

        if not equipment_key:
            print(f"  Mapping {mapping.id}: No 19_Equipment dataset found, skipping")
            continue

        equipment_config = schema[equipment_key]
        fk_relationships = equipment_config.get("fk_relationships", [])

        # Check if FK to equipmentart already exists
        has_equipmentart_fk = any(
            "equipmentart" in (fk.get("target_dataset", "") or "").lower()
            for fk in fk_relationships
        )

        if has_equipmentart_fk:
            print(f"  Mapping {mapping.id}: FK to equipmentart already exists, skipping")
            continue

        # Add the FK relationship
        new_fk = {
            "source_property": "Equipmentart_fk",
            "source_property_uri": "http://arkumu.org/data/khm/properties/equipmentart-fk",
            "target_dataset": "20_Equipmentart",
            "target_key": "Equipmentart_ID",
        }

        fk_relationships.append(new_fk)
        equipment_config["fk_relationships"] = fk_relationships
        schema[equipment_key] = equipment_config
        config["schema_manifest"] = schema
        mapping.mapping_config = config
        mapping.save(update_fields=["mapping_config", "updated_at"])

        updated += 1
        print(f"  Mapping {mapping.id}: Added FK relationship Equipmentart_fk -> 20_Equipmentart")

    print(f"Updated {updated} KHM mapping(s) with equipment FK relationship")


def reverse_migration(apps, schema_editor):
    """Remove the FK relationship (reverse)."""
    Mapping = apps.get_model("metadata", "Mapping")

    khm_mappings = Mapping.objects.filter(organization_id__iexact="khm")

    for mapping in khm_mappings:
        config = mapping.mapping_config or {}
        schema = config.get("schema_manifest", {})

        for key in schema.keys():
            if "19" in key and "equipment" in key.lower() and "kreuz" not in key.lower():
                equipment_config = schema[key]
                fk_relationships = equipment_config.get("fk_relationships", [])

                # Remove equipmentart FK
                fk_relationships = [
                    fk for fk in fk_relationships
                    if "equipmentart" not in (fk.get("target_dataset", "") or "").lower()
                ]

                equipment_config["fk_relationships"] = fk_relationships
                schema[key] = equipment_config
                config["schema_manifest"] = schema
                mapping.mapping_config = config
                mapping.save(update_fields=["mapping_config", "updated_at"])
                break


class Migration(migrations.Migration):

    dependencies = [
        ("metadata", "0019_apply_khm_canonical_mappings"),
    ]

    operations = [
        migrations.RunPython(add_equipment_fk_relationship, reverse_migration),
    ]
