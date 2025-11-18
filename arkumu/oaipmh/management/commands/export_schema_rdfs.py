from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Export canonical and institutional Arkumu schema snapshots as RDF."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--output-dir",
            dest="output_dir",
            help="Directory for the generated schema files (default: schemas/<timestamp>).",
        )
        parser.add_argument(
            "--format",
            dest="formats",
            action="append",
            help="RDF serialization(s) to emit. Can be passed multiple times (default: ttl + xml).",
        )
        parser.add_argument(
            "--mark-latest",
            action="store_true",
            help="Update schemas/latest to point at the generated snapshot.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        module = self._load_export_module()
        if not hasattr(module, "export_schemas"):
            raise CommandError("scripts/export_schema_rdfs.py does not expose export_schemas().")

        output_dir_arg = options.get("output_dir")
        formats = options.get("formats")
        mark_latest = bool(options.get("mark_latest"))

        try:
            exported_dir = module.export_schemas(
                output_dir=Path(output_dir_arg) if output_dir_arg else None,
                formats=formats,
                mark_latest=mark_latest,
                emitter=self.stdout.write,
            )
        except Exception as exc:  # pragma: no cover - defensive
            raise CommandError(f"Schema export failed: {exc}") from exc

        self.stdout.write(self.style.SUCCESS(f"Schema export completed in {exported_dir}"))

    def _load_export_module(self):
        script_path = Path(settings.BASE_DIR) / "scripts" / "export_schema_rdfs.py"
        if not script_path.exists():
            raise CommandError(f"Schema export script not found at {script_path}")

        spec = importlib.util.spec_from_file_location("arkumu_schema_export_script", script_path)
        if spec is None or spec.loader is None:
            raise CommandError("Unable to load schema export script module.")

        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)  # type: ignore[union-attr]
        return module
