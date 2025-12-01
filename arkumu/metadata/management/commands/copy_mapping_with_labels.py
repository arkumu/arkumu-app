"""
Management command to copy a mapping and populate canonical_mapping from a labels CSV.

This is a test/migration helper to verify the apply_mapping_canonicals flow works.
"""

import csv
import logging
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from arkumu.metadata.models.mappings import Mapping

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = (
        "Copy a mapping and populate workspace_columns.canonical_mapping from a labels CSV. "
        "Used to test/verify the apply_mapping_canonicals workflow."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--source-mapping-id",
            type=str,
            required=True,
            help="UUID of the mapping to copy",
        )
        parser.add_argument(
            "--labels-csv",
            type=str,
            required=True,
            help="Path to the labels CSV file",
        )
        parser.add_argument(
            "--new-name",
            type=str,
            default=None,
            help="Name for the new mapping (default: source name + '_with_labels')",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Preview changes without creating the mapping",
        )

    def handle(self, *args, **options):
        source_id = options["source_mapping_id"]
        labels_csv = options["labels_csv"]
        new_name = options.get("new_name")
        dry_run = options["dry_run"]

        # Validate CSV exists
        if not Path(labels_csv).exists():
            raise CommandError(f"Labels CSV not found: {labels_csv}")

        # Get source mapping
        try:
            source_mapping = Mapping.objects.get(id=source_id)
        except Mapping.DoesNotExist:
            raise CommandError(f"Mapping not found: {source_id}")

        self.stdout.write(f"Source mapping: {source_mapping.name}")
        self.stdout.write(f"Organization: {source_mapping.organization_id}")
        self.stdout.write(f"Labels CSV: {labels_csv}")
        self.stdout.write("-" * 60)

        # Parse the labels CSV
        labels = self._parse_labels_csv(labels_csv)
        self.stdout.write(f"Parsed {len(labels)} label mappings from CSV")

        # Get workspace_columns
        config = dict(source_mapping.mapping_config or {})
        workspace_columns = config.get("workspace_columns", {})

        if not workspace_columns:
            raise CommandError("Source mapping has no workspace_columns")

        # Apply labels to workspace_columns
        stats = self._apply_labels_to_columns(workspace_columns, labels, dry_run)

        self.stdout.write(f"\n=== Results ===")
        self.stdout.write(f"Total columns: {stats['total_columns']}")
        self.stdout.write(f"Columns matched: {stats['matched']}")
        self.stdout.write(f"Labels applied: {stats['applied']}")
        self.stdout.write(f"Already had mapping: {stats['already_mapped']}")
        self.stdout.write(f"No match in CSV: {stats['no_match']}")

        if dry_run:
            self.stdout.write(
                self.style.WARNING("\nDRY RUN - No changes made")
            )
            return

        # Create the new mapping
        new_name = new_name or f"{source_mapping.name}_with_labels"

        with transaction.atomic():
            new_mapping = Mapping.objects.create(
                name=new_name,
                description=f"Copy of {source_mapping.name} with labels from CSV",
                organization_id=source_mapping.organization_id,
                source_datasets=source_mapping.source_datasets,
                mapping_config=config,
                validation_status="draft",
            )

        self.stdout.write(
            self.style.SUCCESS(f"\nCreated new mapping: {new_mapping.name} (ID: {new_mapping.id})")
        )
        self.stdout.write(
            f"\nTo test: python manage.py apply_mapping_canonicals "
            f"--organization {source_mapping.organization_id} --mapping-id {new_mapping.id} --dry-run"
        )

    def _parse_labels_csv(self, csv_path: str) -> dict:
        """Parse the labels CSV into a lookup dict."""
        labels = {}

        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                type_ = row.get("Type", "").strip().lower()
                target = row.get("Target", "").strip()
                label = row.get("Label", "").strip()
                names_str = row.get("Name", "").strip()

                if not target or not names_str:
                    continue

                # Split names by comma
                names = [n.strip() for n in names_str.split(",") if n.strip()]

                for name in names:
                    labels[name] = {
                        "type": type_,
                        "target": target,
                        "label": label,
                    }

        return labels

    def _apply_labels_to_columns(
        self, workspace_columns: dict, labels: dict, dry_run: bool
    ) -> dict:
        """Apply label mappings to workspace_columns."""
        stats = {
            "total_columns": len(workspace_columns),
            "matched": 0,
            "applied": 0,
            "already_mapped": 0,
            "no_match": 0,
        }

        for col_id, col_data in workspace_columns.items():
            col_name = col_data.get("name")
            dataset = col_data.get("dataset") or col_data.get("source")

            if not col_name:
                continue

            # Try to find a match in labels
            label_info = labels.get(col_name)

            if not label_info:
                stats["no_match"] += 1
                continue

            stats["matched"] += 1

            # Check if already has canonical_mapping
            existing = col_data.get("canonical_mapping", {})
            if existing.get("canonical_property_uri") or existing.get("canonical_class_uri"):
                stats["already_mapped"] += 1
                if dry_run:
                    self.stdout.write(
                        f"  Already mapped: {col_name} -> {existing.get('canonical_property_uri') or existing.get('canonical_class_uri')}"
                    )
                continue

            # Apply the label
            if label_info["type"] == "property":
                canonical_mapping = {
                    "source": "labels_csv",
                    "canonical_class_uri": None,
                    "canonical_class_label": None,
                    "canonical_property_uri": label_info["target"],
                    "canonical_property_label": label_info["label"],
                }
            else:  # class
                canonical_mapping = {
                    "source": "labels_csv",
                    "canonical_class_uri": label_info["target"],
                    "canonical_class_label": label_info["label"],
                    "canonical_property_uri": None,
                    "canonical_property_label": None,
                }

            col_data["canonical_mapping"] = canonical_mapping
            stats["applied"] += 1

            if dry_run:
                self.stdout.write(
                    f"  Would apply: {col_name} -> {label_info['target']}"
                )

        return stats
