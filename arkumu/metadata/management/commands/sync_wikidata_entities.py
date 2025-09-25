"""Management command to populate the ExternalSources entity cache."""

from __future__ import annotations

import pathlib
from typing import Iterable, List, Set

from django.core.management.base import BaseCommand, CommandError

from arkumu.metadata.services import ExternalSourcesEntityCacheService


class Command(BaseCommand):
    help = "Fetch metadata from External Sources for the supplied identifiers and cache them locally."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--ids",
            nargs="*",
            help="Identifiers (e.g. Q42 Q64). Comma separated lists are also accepted.",
        )
        parser.add_argument(
            "--properties",
            nargs="*",
            help="Properties (e.g. P42 P64). Comma separated lists are also accepted.",
        )
        parser.add_argument(
            "--file",
            help="Path to a text file containing one Wikidata identifier per line.",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Force refresh even if the entity is already cached.",
        )

    def handle(self, *args, **options):
        data_ids = self._collect_ids(options.get("ids"), options.get("file"))
        property_ids = self._collect_ids(options.get("properties"))
        if not data_ids:
            raise CommandError("No identifiers supplied.")
        if not property_ids:
            raise CommandError("No properties supplied")

        service = ExternalSourcesEntityCacheService()

        self.stdout.write(
            f"Caching {len(data_ids)} Wikidata entities (force={options['force']})...",
        )
        updated = service.ensure_cached(
            data_ids,
            property_ids,
            ExternalSourcesEntityCacheService.Source.WD,
            force_refresh=options["force"],
        )

        if updated:
            self.stdout.write(self.style.SUCCESS(f"Updated {len(updated)} entities."))
        else:
            self.stdout.write("No entities required updating.")

    def _collect_ids(self, ids: Iterable[str] | None, file_path: str | None = None) -> List[str]:
        unique_ids: Set[str] = set()

        def _ingest(token: str) -> None:
            token = (token or "").strip()
            if not token:
                return
            for part in token.split(','):
                part = part.strip()
                if part:
                    unique_ids.add(part)

        if ids:
            for token in ids:
                _ingest(token)

        if file_path:
            path = pathlib.Path(file_path)
            if not path.exists():
                raise CommandError(f"File not found: {file_path}")
            with path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    _ingest(line)

        return sorted(unique_ids)
