from __future__ import annotations

import csv
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence

from django.core.management.base import BaseCommand, CommandError

from arkumu.metadata.controlled_vocabularies.registry import (
    VocabularyConfig,
    column_to_field_name,
    get_vocabulary_config,
    list_vocabulary_keys,
)
from arkumu.metadata.controlled_vocabularies.service import ControlledVocabularyService
from arkumu.metadata.models.resource import Resource


def _strip_value(value: Optional[str]) -> str:
    return (value or "").strip()


class Command(BaseCommand):
    help = "Import canonical controlled vocabularies into the metadata resource graph."

    def add_arguments(self, parser):
        parser.add_argument(
            "--directory",
            type=str,
            default=None,
            help=(
                "Directory containing *_canonical.csv files. "
                "Defaults to ../arkumu-metadata/controlled_vocabularies relative to the project root."
            ),
        )
        parser.add_argument(
            "--vocabulary",
            action="append",
            dest="vocabularies",
            default=None,
            help="Restrict import to specific vocabularies (use registry keys, e.g. 'event_types').",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Load files and report planned changes without committing them.",
        )

    def handle(self, *args, **options):
        directory = self._resolve_directory(options["directory"])
        available_keys = set(list_vocabulary_keys())
        requested_keys = options["vocabularies"] or list(available_keys)

        missing = [key for key in requested_keys if key not in available_keys]
        if missing:
            raise CommandError(f"Unknown vocabulary keys: {', '.join(sorted(missing))}")

        overall_stats = {"concepts_created": 0, "concepts_updated": 0, "triples_created": 0, "triples_deleted": 0}

        for key in requested_keys:
            config = get_vocabulary_config(key)
            csv_path = directory / config.filename
            if not csv_path.exists():
                raise CommandError(f"CSV file not found for {key}: {csv_path}")

            stats = self._import_vocabulary(csv_path, config, key)
            for field, value in stats.items():
                overall_stats[field] += value

            self.stdout.write(
                self.style.SUCCESS(
                    f"{key}: imported {stats['concepts_created']} new concepts,"
                    f" updated {stats['concepts_updated']},"
                    f" created {stats['triples_created']} triples,"
                    f" removed {stats['triples_deleted']} triples."
                )
            )

        summary = (
            f"Total concepts created: {overall_stats['concepts_created']}; "
            f"updated: {overall_stats['concepts_updated']}; "
            f"triples created: {overall_stats['triples_created']}; "
            f"triples removed: {overall_stats['triples_deleted']}."
        )
        self.stdout.write(summary)

    def _resolve_directory(self, custom_dir: Optional[str]) -> Path:
        if custom_dir:
            return Path(custom_dir).expanduser().resolve()
        project_root = Path(__file__).resolve().parents[4]
        return (project_root.parent / "arkumu-metadata" / "controlled_vocabularies").resolve()

    def _import_vocabulary(self, csv_path: Path, config: VocabularyConfig, vocab_key: str) -> Dict[str, int]:
        fieldnames, rows = self._load_rows(csv_path)
        if not rows:
            self.stdout.write(self.style.WARNING(f"No rows found in {csv_path.name}; skipping."))
            return {key: 0 for key in ("concepts_created", "concepts_updated", "triples_created", "triples_deleted")}

        self._warn_unmapped_columns(csv_path.name, fieldnames, config)

        service = ControlledVocabularyService(vocab_key)
        id_to_resource: Dict[str, Resource] = {}

        stats = {"concepts_created": 0, "concepts_updated": 0, "triples_created": 0, "triples_deleted": 0}

        for row in rows:
            concept_id = _strip_value(row.get("ID"))
            canonical_uri = _strip_value(row.get("Canonical URI"))
            if not concept_id or not canonical_uri:
                self.stdout.write(
                    self.style.WARNING(
                        f"Skipping row without ID or Canonical URI in {csv_path.name}: {row}"
                    )
                )
                continue

            existing_resource = Resource.objects.filter(uri=canonical_uri).first()
            form_data = self._build_form_data(row, config, service, id_to_resource)
            save_result = service.save(form_data, resource=existing_resource, with_stats=True)
            saved_resource = save_result.resource
            id_to_resource[concept_id] = saved_resource

            if existing_resource is None:
                stats["concepts_created"] += 1
            else:
                stats["concepts_updated"] += 1

            stats["triples_created"] += save_result.stats.triples_created
            stats["triples_deleted"] += save_result.stats.triples_deleted

        return stats

    def _build_form_data(
        self,
        row: Dict[str, str],
        config: VocabularyConfig,
        service: ControlledVocabularyService,
        id_lookup: Dict[str, Resource],
    ) -> Dict[str, object]:
        canonical_uri = _strip_value(row.get("Canonical URI"))
        form_data: Dict[str, object] = {
            "slug": service.extract_slug(canonical_uri),
        }

        for column, column_config in config.columns.items():
            raw_value = _strip_value(row.get(column))
            field_name = column_to_field_name(column)

            if column_config.value_type == "boolean":
                form_data[field_name] = raw_value.lower() in {"1", "true", "yes", "ja"}
            elif column_config.value_type == "reference":
                if raw_value:
                    ref = id_lookup.get(raw_value)
                    if not ref:
                        self.stdout.write(
                            self.style.WARNING(
                                f"Missing referenced concept '{raw_value}' for {column}."
                            )
                        )
                        form_data[field_name] = ""
                    else:
                        form_data[field_name] = str(ref.id)
                else:
                    form_data[field_name] = ""
            else:
                form_data[field_name] = raw_value

        return form_data

    def _load_rows(self, csv_path: Path) -> (List[str], List[Dict[str, str]]):
        with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle, delimiter=";")
            raw_fieldnames = reader.fieldnames or []
            normalized_fieldnames = [name.strip() if name else name for name in raw_fieldnames]

            rows: List[Dict[str, str]] = []
            for raw_row in reader:
                normalized_row: Dict[str, str] = {}
                for raw_key, value in raw_row.items():
                    if raw_key is None:
                        continue
                    normalized_key = raw_key.strip()
                    if normalized_key:
                        normalized_row[normalized_key] = value
                rows.append(normalized_row)

            return normalized_fieldnames, rows

    def _warn_unmapped_columns(self, filename: str, fieldnames: Iterable[str], config: VocabularyConfig) -> None:
        standard_columns = {"ID", "URI", "Canonical URI"}
        known_columns = set(config.columns.keys()) | standard_columns
        unmapped = [column for column in fieldnames if column and column not in known_columns]
        if unmapped:
            self.stdout.write(
                self.style.WARNING(f"{filename}: ignoring unmapped columns {', '.join(unmapped)}")
            )
