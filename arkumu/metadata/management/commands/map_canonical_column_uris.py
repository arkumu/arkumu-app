"""
Populate Mapping.mapping_config.canonical_column_mappings from CSV label files.

This command is intentionally lightweight and scoped to mapping configurations:
it does not modify Resource records or schema manifests. The goal is to let the
CSV mapping editor show canonical property URIs/labels for workspace columns
based on organization-specific label CSVs (e.g. KHM/HMT label files).
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Dict, List, Set, Tuple

from django.core.management.base import BaseCommand, CommandError

from arkumu.metadata.models.mappings import Mapping
from arkumu.users.models import Organization


class Command(BaseCommand):
    help = (
        "Populate canonical_column_mappings for CSV mappings using a label CSV.\n"
        "The CSV must follow the Type/Target/Label/Name format used by khm_labels.csv."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "csv_file",
            type=str,
            help="Path to CSV file containing canonical property labels/mappings",
        )
        parser.add_argument(
            "--organization",
            "-o",
            type=str,
            required=True,
            help="Organization code to update (e.g., khm, hmt)",
        )
        parser.add_argument(
            "--mapping-id",
            type=str,
            help="Optional mapping UUID to restrict updates to a single mapping",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Preview changes without persisting them",
        )

    def handle(self, *args, **options):
        csv_path = Path(options["csv_file"])
        org_code = (options["organization"] or "").strip().lower()
        mapping_id = options.get("mapping_id")
        dry_run: bool = options["dry_run"]

        if not csv_path.exists():
            raise CommandError(f"CSV file not found: {csv_path}")

        if not org_code:
            raise CommandError("Organization code is required")

        try:
            organization = Organization.objects.get(code=org_code)
        except Organization.DoesNotExist as exc:
            raise CommandError(f"Organization '{org_code}' not found") from exc

        name_map, ambiguous_names = self._load_property_name_map(csv_path)
        if not name_map:
            self.stdout.write(
                self.style.WARNING(
                    "No property name mappings were found in CSV "
                    "(expected Type='Property' rows with non-empty Name)."
                )
            )
            return

        if ambiguous_names:
            self.stdout.write(
                self.style.WARNING(
                    f"Ambiguous Names: {len(ambiguous_names)} name(s) map to multiple canonical URIs. "
                    "These will be skipped."
                )
            )

        if mapping_id:
            mappings_qs = Mapping.objects.filter(
                id=mapping_id,
                organization_id=organization.code,
            )
            if not mappings_qs.exists():
                raise CommandError(
                    f"Mapping '{mapping_id}' does not belong to organization '{org_code}'"
                )
        else:
            mappings_qs = Mapping.objects.filter(organization_id=organization.code)

        total_mappings = mappings_qs.count()
        if not total_mappings:
            self.stdout.write(
                self.style.WARNING(
                    f"No mappings found for organization '{organization.code}'."
                )
            )
            return

        self.stdout.write(
            self.style.SUCCESS(
                f"Organization: {organization.name} ({organization.code})\n"
                f"CSV: {csv_path}\n"
                f"Mappings to inspect: {total_mappings}"
            )
        )

        source_tag = csv_path.stem
        updated_mappings = 0
        updated_columns_total = 0

        for mapping in mappings_qs:
            updated_columns = self._apply_to_mapping(
                mapping,
                name_map,
                ambiguous_names,
                source_tag,
                dry_run=dry_run,
            )
            if updated_columns:
                updated_mappings += 1
                updated_columns_total += updated_columns

        if dry_run:
            self.stdout.write(
                self.style.WARNING(
                    f"DRY RUN: would update {updated_columns_total} column(s) "
                    f"across {updated_mappings} mapping(s)."
                )
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Updated {updated_columns_total} column(s) "
                    f"across {updated_mappings} mapping(s)."
                )
            )

    # ------------------------------------------------------------------
    # CSV parsing helpers
    # ------------------------------------------------------------------

    def _load_property_name_map(
        self, csv_path: Path
    ) -> Tuple[Dict[str, Tuple[str, str]], Set[str]]:
        """
        Build a mapping from normalized column names to canonical URIs/labels.

        Returns:
            (name_to_property, ambiguous_names)

            name_to_property: {normalized_name: (canonical_uri, label)}
            ambiguous_names: set of names that map to more than one canonical URI
        """

        def norm_key(value: str) -> str:
            return (value or "").strip().casefold()

        name_to_properties: Dict[str, Set[Tuple[str, str]]] = {}

        with csv_path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            required_cols = {"Type", "Target", "Label", "Name"}
            missing = required_cols - set(reader.fieldnames or [])
            if missing:
                raise CommandError(
                    f"CSV file is missing required columns: {', '.join(sorted(missing))}"
                )

            for row in reader:
                row_type = (row.get("Type") or "").strip().lower()
                if row_type != "property":
                    continue

                target = (row.get("Target") or "").strip()
                names_str = (row.get("Name") or "").strip()
                if not target or not names_str:
                    continue

                label = (row.get("Label") or "").strip() or target.rsplit("/", 1)[-1]

                for raw_name in names_str.split(","):
                    raw_name = raw_name.strip()
                    if not raw_name:
                        continue
                    key = norm_key(raw_name)
                    name_to_properties.setdefault(key, set()).add((target, label))

        name_to_property: Dict[str, Tuple[str, str]] = {}
        ambiguous_names: Set[str] = set()

        for key, values in name_to_properties.items():
            if len(values) == 1:
                name_to_property[key] = next(iter(values))
            else:
                ambiguous_names.add(key)

        return name_to_property, ambiguous_names

    # ------------------------------------------------------------------
    # Mapping update helpers
    # ------------------------------------------------------------------

    def _apply_to_mapping(
        self,
        mapping: Mapping,
        name_map: Dict[str, Tuple[str, str]],
        ambiguous_names: Set[str],
        source_tag: str,
        *,
        dry_run: bool,
    ) -> int:
        """
        Apply canonical mappings to a single Mapping instance.

        Returns:
            int: number of columns updated on this mapping
        """

        def norm_key(value: str) -> str:
            return (value or "").strip().casefold()

        config = mapping.mapping_config or {}
        workspace_columns = config.get("workspace_columns") or {}
        if not isinstance(workspace_columns, dict):
            self.stdout.write(
                self.style.WARNING(
                    f"- Mapping '{mapping.name}' ({mapping.id}) has unexpected "
                    "'workspace_columns' format; skipping."
                )
            )
            return 0

        canonical_column_mappings = dict(
            config.get("canonical_column_mappings") or {}
        )

        updated_columns = 0

        for column_id, col in workspace_columns.items():
            if not isinstance(col, dict):
                continue
            column_name = col.get("name")
            if not column_name:
                continue

            key = norm_key(column_name)
            if key in ambiguous_names:
                continue

            mapping_entry = name_map.get(key)
            if not mapping_entry:
                continue

            canonical_uri, label = mapping_entry
            existing_entry = canonical_column_mappings.get(column_id)
            if (
                existing_entry
                and existing_entry.get("canonical_property_uri") == canonical_uri
            ):
                # Already mapped to the same URI; keep existing entry
                continue

            canonical_column_mappings[column_id] = {
                "canonical_property_uri": canonical_uri,
                "canonical_property_label": label,
                # Class information is not available from the CSV; leave as-is if present.
                "canonical_class_uri": (
                    existing_entry.get("canonical_class_uri")
                    if existing_entry
                    else None
                ),
                "canonical_class_label": (
                    existing_entry.get("canonical_class_label")
                    if existing_entry
                    else None
                ),
                "source": source_tag,
            }
            updated_columns += 1

        if not updated_columns:
            return 0

        self.stdout.write(
            f"- Mapping '{mapping.name}' ({mapping.id}): "
            f"{updated_columns} column(s) updated."
        )

        if not dry_run:
            new_config = dict(config)
            new_config["canonical_column_mappings"] = canonical_column_mappings
            mapping.mapping_config = new_config
            mapping.save(update_fields=["mapping_config", "updated_at"])

        return updated_columns

