"""
Fix HMT Informationsträger mapping configuration and FK references.

Problem: The 09_hfm_Informationstraeger dataset has no primary_key set, causing:
1. Entity URIs created from numeric ID_pk column (e.g., /09-hfm-informationstraeger/1)
2. FK references resolved using signature column, creating shell entities (e.g., /09-hfm-informationstraeger/a-1-69)
3. The FK is also multi-value (compound signatures like "A 11/69 [TA 11/69]") but marked as single-value

Solution:
1. Fix the mapping config: set primary_key to signature column, mark FK as multi-value
2. Fix existing data: remap FK triples from shell entities to real entities where possible
3. Clean up orphan shell entities

After this migration, future imports will use the signature as the primary key.
"""

import re

from django.db import migrations


def normalize_signature(sig: str) -> str:
    """Normalize signature to match URI creation: lowercase, special char handling, collapse dashes."""
    if not sig:
        return ""
    import re
    normalized = sig.lower()
    # Replace + with 'plus' (as done in URI creation)
    normalized = normalized.replace("+", "plus")
    # Remove commas and semicolons (as done in URI creation)
    normalized = normalized.replace(",", "").replace(";", "")
    # Replace / and spaces with dashes
    normalized = normalized.replace("/", "-").replace(" ", "-")
    # Remove brackets
    normalized = normalized.replace("[", "").replace("]", "")
    # Collapse multiple dashes into one
    return re.sub(r"-+", "-", normalized)


def fix_hmt_mapping_and_data(apps, schema_editor):
    """Fix HMT mapping configuration and existing FK data."""
    Mapping = apps.get_model("metadata", "Mapping")
    Resource = apps.get_model("metadata", "Resource")
    Triple = apps.get_model("metadata", "Triple")

    # ========================================
    # PART 1: Fix mapping configuration
    # ========================================
    print("  Part 1: Fixing HMT mapping configuration...")

    hmt_mappings = Mapping.objects.filter(organization_id__iexact="hmt")
    mappings_updated = 0

    for mapping in hmt_mappings:
        config = mapping.mapping_config or {}
        schema = config.get("schema_manifest", {})
        modified = False

        # Fix 09_hfm_Informationstraeger: set primary_key
        info_key = "09_hfm_Informationstraeger"
        if info_key in schema:
            info_config = schema[info_key]
            if not info_config.get("primary_key"):
                info_config["primary_key"] = "Informationsträger_Externe InventarSignaturnummer"
                schema[info_key] = info_config
                modified = True
                print(f"    Set primary_key on {info_key}")

        # Fix 02_hfm_Ereignis: mark FK as multi-value
        ereignis_key = "02_hfm_Ereignis"
        if ereignis_key in schema:
            ereignis_config = schema[ereignis_key]
            fk_relationships = ereignis_config.get("fk_relationships", [])

            for fk in fk_relationships:
                if fk.get("target_dataset") == info_key:
                    if not fk.get("is_multi_value"):
                        fk["is_multi_value"] = True
                        modified = True
                        print(f"    Set is_multi_value=True on FK to {info_key}")

            ereignis_config["fk_relationships"] = fk_relationships
            schema[ereignis_key] = ereignis_config

        if modified:
            config["schema_manifest"] = schema
            mapping.mapping_config = config
            mapping.save(update_fields=["mapping_config", "updated_at"])
            mappings_updated += 1

    print(f"  Updated {mappings_updated} HMT mapping(s)")

    # ========================================
    # PART 2: Fix existing FK data
    # ========================================
    print("  Part 2: Fixing existing FK data...")

    # Find the signature property predicate
    sig_pred = Resource.objects.filter(
        uri="http://arkumu.org/data/hmt/properties/informationstraeger-externe-inventarsignaturnummer"
    ).first()

    if not sig_pred:
        print("    Signature predicate not found, skipping data fix")
        return

    # Build mapping from normalized signature -> real entity (with numeric ID)
    sig_to_entity = {}
    sig_triples = Triple.objects.filter(predicate=sig_pred).select_related("subject", "object")

    for t in sig_triples:
        if t.object and t.object.value and t.subject:
            sig_norm = normalize_signature(t.object.value)
            if sig_norm:
                sig_to_entity[sig_norm] = t.subject

    print(f"    Built {len(sig_to_entity)} signature -> entity mappings")

    # Find the FK predicate
    fk_pred = Resource.objects.filter(
        uri="http://arkumu.org/data/hmt/properties/informationstraeger-externe-inventarsignaturnummer-fk"
    ).first()

    if not fk_pred:
        print("    FK predicate not found, skipping data fix")
        return

    # Find and update FK triples pointing to shell entities
    fk_triples = Triple.objects.filter(predicate=fk_pred).select_related("subject", "object")

    updated = 0
    already_correct = 0
    compound_refs = 0
    shell_entity_ids = set()

    for t in fk_triples:
        if not t.object or not t.object.uri:
            continue

        ref_uri = t.object.uri
        if "/09-hfm-informationstraeger/" not in ref_uri:
            continue

        uri_suffix = ref_uri.split("/")[-1]

        # Skip if already pointing to a numeric-ID entity
        if re.match(r"^\d+$", uri_suffix):
            already_correct += 1
            continue

        # Try to find matching real entity
        real_entity = sig_to_entity.get(uri_suffix)

        if real_entity and real_entity.uri != ref_uri:
            shell_entity_ids.add(t.object_id)
            t.object = real_entity
            t.save(update_fields=["object"])
            updated += 1
        else:
            # This is likely a compound reference (multi-value)
            compound_refs += 1

    print(f"    Already correct (numeric IDs): {already_correct}")
    print(f"    Updated to real entities: {updated}")
    print(f"    Compound references (kept as-is): {compound_refs}")

    # Clean up orphan shell entities
    if shell_entity_ids:
        still_referenced = set()
        for shell_id in shell_entity_ids:
            if Triple.objects.filter(object_id=shell_id).exists():
                still_referenced.add(shell_id)

        orphan_ids = shell_entity_ids - still_referenced

        if orphan_ids:
            deleted_triples = Triple.objects.filter(subject_id__in=orphan_ids).delete()[0]
            print(f"    Deleted {deleted_triples} triples from orphan shells")

            deleted_resources = Resource.objects.filter(id__in=orphan_ids).delete()[0]
            print(f"    Deleted {deleted_resources} orphan shell entities")


def reverse_migration(apps, schema_editor):
    """Reverse is complex - would need to recreate shell entities. Skip."""
    print("  Reverse migration not implemented - manual intervention required")


class Migration(migrations.Migration):

    dependencies = [
        ("metadata", "0021_resolve_khm_equipmentart_fk_triples"),
    ]

    operations = [
        migrations.RunPython(fix_hmt_mapping_and_data, reverse_migration),
    ]
