"""Management command to populate the Wikidata entity cache."""

from __future__ import annotations

import pathlib
from typing import Iterable, List, Set

from django.core.management.base import BaseCommand, CommandError

from arkumu.metadata.services import WikidataEntityCacheService


class Command(BaseCommand):
    help = "Fetch Wikidata metadata for the supplied identifiers and cache them locally."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--ids",
            nargs="*",
            help="Wikidata identifiers (e.g. Q42 Q64). Comma separated lists are also accepted.",
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
        parser.add_argument(
            "--language",
            action="append",
            dest="languages",
            help="Additional language codes to request (default: de, en). Can be specified multiple times.",
        )

    def handle(self, *args, **options):
        wikidata_ids = self._collect_ids(options.get("ids"), options.get("file"))
        if not wikidata_ids:
            raise CommandError("No Wikidata identifiers supplied.")

        languages = options.get("languages") or None
        service = WikidataEntityCacheService(languages=languages)

        self.stdout.write(
            f"Caching {len(wikidata_ids)} Wikidata entities (force={options['force']})...",
        )
        updated = service.ensure_cached(
            wikidata_ids,
            force_refresh=options["force"],
        )

        if updated:
            self.stdout.write(self.style.SUCCESS(f"Updated {len(updated)} entities."))
        else:
            self.stdout.write("No entities required updating.")

    def _collect_ids(self, ids: Iterable[str] | None, file_path: str | None) -> List[str]:
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
