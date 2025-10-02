"""Export FK relationships that lack canonical property mappings."""

import csv
from pathlib import Path
from typing import Dict, Iterable, Optional

from django.core.management.base import BaseCommand

from arkumu.metadata.models.mappings import Mapping


class Command(BaseCommand):
    """Generate a CSV report of FK bindings without canonical URIs."""

    help = "Export FK relationships that are missing canonical properties"

    def add_arguments(self, parser) -> None:  # pragma: no cover - argument parser
        parser.add_argument(
            "--organization",
            "-o",
            action="append",
            dest="organizations",
            help="Organization code(s) to inspect (default: all organizations)",
        )
        parser.add_argument(
            "--output",
            "-f",
            type=Path,
            help="Optional path to write the CSV file (default: stdout)",
        )
        parser.add_argument(
            "--labels",
            action="store_true",
            help="Output helper rows in Type/Target/Label/Name format for CSV label files",
        )
        parser.add_argument(
            "--all-versions",
            action="store_true",
            help="Include all mapping records instead of only the latest per organization",
        )

    def handle(self, *args, **options):
        organizations = options.get("organizations")
        output_path: Optional[Path] = options.get("output")
        include_all_versions: bool = options.get("all_versions")

        headers = [
            "organization",
            "dataset",
            "column",
            "local_property_uri",
            "canonical_uri",
            "suggested_canonical_uri",
            "related_dataset",
            "related_column",
            "relationship_type",
        ]
        row_iter = list(
            self._collect_missing_fk_rows(
                organizations=organizations,
                include_all_versions=include_all_versions,
            )
        )

        labels_mode = options.get("labels")

        rows = sorted(
            row_iter,
            key=lambda r: (
                r[4] or r[5],  # canonical uri if present, otherwise suggestion
                r[1],
                r[2],
            ),
        )

        if output_path:
            if output_path.is_dir():
                self._write_per_org_files(output_path, rows, headers, labels_mode)
                return

            self._write_single_file(output_path, rows, headers, labels_mode)
            return

        if not rows:
            self.stdout.write(self.style.SUCCESS("No FK entries missing canonical URIs found."))
            return

        if labels_mode:
            writer = csv.writer(self.stdout)
            writer.writerow(["Type", "Target", "Name", "Dataset", "Local Property URI"])
            for label_row in self._to_label_rows(rows):
                writer.writerow(label_row)
        else:
            writer = csv.writer(self.stdout)
            writer.writerow(headers)
            writer.writerows(rows)

    def _collect_missing_fk_rows(
        self,
        *,
        organizations: Optional[Iterable[str]] = None,
        include_all_versions: bool = False,
    ) -> Iterable[list[str]]:
        mapping_qs = Mapping.objects.all().order_by("organization_id", "-created_at")

        if organizations:
            mapping_qs = mapping_qs.filter(organization_id__in=organizations)

        seen_orgs: set[str] = set()

        for mapping in mapping_qs.iterator():
            org_code = mapping.organization_id

            if not include_all_versions and org_code in seen_orgs:
                continue
            seen_orgs.add(org_code)

            config = mapping.mapping_config or {}
            manifest: Dict[str, Dict] = config.get("schema_manifest", {}) or {}

            for dataset_name, dataset_manifest in manifest.items():
                fk_entries = dataset_manifest.get("fk_relationships", []) or []
                for fk_entry in fk_entries:
                    source_canonical = fk_entry.get("source_canonical_property")
                    target_canonical = fk_entry.get("target_canonical_property")

                    if not source_canonical:
                        source_column = fk_entry.get("source_column", "")
                        yield [
                            org_code,
                            dataset_name,
                            source_column,
                            fk_entry.get("source_property_uri", ""),
                            "",
                            self._suggest_canonical_uri(source_column, dataset_name),
                            fk_entry.get("target_dataset", ""),
                            fk_entry.get("target_column", ""),
                            fk_entry.get("relationship_type", ""),
                        ]

    def _write_per_org_files(self, directory: Path, rows: Iterable[list[str]], headers: list[str], labels_mode: bool) -> None:
        per_org: Dict[str, list[list[str]]] = {}
        for row in rows:
            per_org.setdefault(row[0], []).append(row)

        if not per_org:
            self.stdout.write(self.style.SUCCESS("No FK entries missing canonical URIs found."))
            return

        for org_code, org_rows in per_org.items():
            filename = f"missing_fk_{org_code}.csv"
            path = directory / filename
            with path.open("w", encoding="utf-8", newline="") as fh:
                writer = csv.writer(fh)
                if labels_mode:
                    writer.writerow(["Type", "Target", "Name", "Dataset", "Local Property URI"])
                    writer.writerows(self._to_label_rows(org_rows))
                else:
                    writer.writerow(headers)
                    writer.writerows(org_rows)
            self.stdout.write(
                self.style.SUCCESS(
                    f"Exported {len(org_rows)} FK entries without canonical URIs to {path}"
                )
            )

    def _write_single_file(self, path: Path, rows: Iterable[list[str]], headers: list[str], labels_mode: bool) -> None:
        rows = list(rows)
        if not rows:
            self.stdout.write(self.style.SUCCESS("No FK entries missing canonical URIs found."))
            return

        with path.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.writer(fh)
            if labels_mode:
                writer.writerow(["Type", "Target", "Name", "Dataset", "Local Property URI"])
                writer.writerows(self._to_label_rows(rows))
            else:
                writer.writerow(headers)
                writer.writerows(rows)

        self.stdout.write(
            self.style.SUCCESS(
                f"Exported {len(rows)} FK entries without canonical URIs to {path}"
            )
        )

    def _to_label_rows(self, rows: Iterable[list[str]]) -> Iterable[list[str]]:
        for org, dataset, column, local_uri, _, suggestion, *_ in rows:
            yield [
                "Property",
                suggestion or "",
                column,
                dataset,
                local_uri,
            ]

    def _suggest_canonical_uri(self, column_name: str, dataset_name: str) -> str:
        column_lower = column_name.lower()
        dataset_lower = dataset_name.lower()

        def contains(text: str, *tokens: str) -> bool:
            return any(token in text for token in tokens)

        if contains(column_lower, "event", "ereignis"):
            return "http://arkumu.org/data/properties/ereignis"

        if contains(column_lower, "proj", "projekt"):
            return "http://arkumu.org/data/properties/projekt"

        if contains(column_lower, "akteur", "akteurin"):
            return "http://arkumu.org/data/properties/akteurin"

        if contains(column_lower, "keyword", "schlagwort"):
            return "http://arkumu.org/data/properties/schlagwort"

        if contains(column_lower, "dat_id", "digital"):
            return "http://arkumu.org/data/properties/digitales-objekt"

        if "equipment" in column_lower:
            return "http://arkumu.org/data/properties/equipment-und-software"

        if contains(column_lower, "vorschaubild", "preview"):
            return "http://arkumu.org/data/properties/vorschaubild"

        if "organisationseinheit" in column_lower:
            return "http://arkumu.org/data/properties/organisationseinheit"

        if "physmedien" in column_lower:
            return "http://arkumu.org/data/properties/digitales-objekt"

        if "ereignis" in dataset_lower:
            return "http://arkumu.org/data/properties/ereignis"
        if "projekt" in dataset_lower:
            return "http://arkumu.org/data/properties/projekt"

        return ""
