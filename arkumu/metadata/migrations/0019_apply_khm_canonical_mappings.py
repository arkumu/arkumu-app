"""
Apply canonical URI mappings from khm_labels.csv to KHM predicate Resources.

This migration reads the CSV mapping file and updates Resource.canonical_uri
for KHM predicates that are missing their canonical mappings.
"""

import csv
from pathlib import Path

from django.db import migrations


def load_mappings_from_csv(csv_path: Path) -> dict:
    """Load property name -> canonical URI mappings from CSV."""
    mappings = {}

    with csv_path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            row_type = (row.get("Type") or "").strip().lower()
            if row_type != "property":
                continue

            target_uri = (row.get("Target") or "").strip()
            names_str = (row.get("Name") or "").strip()

            if not target_uri or not names_str:
                continue

            for name in names_str.split(","):
                name = name.strip()
                if name:
                    # Normalize to lowercase for matching
                    mappings[name.lower()] = target_uri

    return mappings


def apply_canonical_mappings(apps, schema_editor):
    """Apply canonical URIs to KHM predicate Resources."""
    Resource = apps.get_model("metadata", "Resource")

    # Find CSV file - try multiple locations for different environments
    possible_paths = [
        Path("/app/data/mappings/khm_labels.csv"),  # Docker container
        Path(__file__).parent.parent.parent.parent.parent / "data" / "mappings" / "khm_labels.csv",  # Local dev
    ]

    csv_path = None
    for p in possible_paths:
        if p.exists():
            csv_path = p
            break

    if not csv_path:
        print(f"Warning: CSV file not found, skipping migration")
        return

    # Load mappings
    name_to_canonical = load_mappings_from_csv(csv_path)
    print(f"Loaded {len(name_to_canonical)} property mappings from CSV")

    # Find KHM predicate resources without canonical_uri
    khm_predicates = Resource.objects.filter(
        uri__icontains="/khm/properties/",
        resource_type="PROPERTY",
    )

    updated = 0
    for resource in khm_predicates:
        # Extract property name from URI (last segment)
        prop_name = resource.uri.rsplit("/", 1)[-1] if "/" in resource.uri else ""
        if not prop_name:
            continue

        # Try to find canonical mapping
        # Match by normalized property name (replace - with various formats)
        variants = [
            prop_name.lower(),
            prop_name.lower().replace("-", "_"),
            prop_name.lower().replace("-", ""),
        ]

        canonical_uri = None
        for variant in variants:
            if variant in name_to_canonical:
                canonical_uri = name_to_canonical[variant]
                break

        if canonical_uri and resource.canonical_uri != canonical_uri:
            old_uri = resource.canonical_uri
            resource.canonical_uri = canonical_uri
            resource.save(update_fields=["canonical_uri"])
            updated += 1
            if updated <= 20:  # Limit output
                print(f"  {prop_name}: {old_uri} -> {canonical_uri}")

    print(f"Updated {updated} KHM predicate resources with canonical URIs")


def reverse_migration(apps, schema_editor):
    """Reverse is a no-op - we don't want to remove canonical mappings."""
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("metadata", "0018_fix_cross_org_predicates"),
    ]

    operations = [
        migrations.RunPython(apply_canonical_mappings, reverse_migration),
    ]
