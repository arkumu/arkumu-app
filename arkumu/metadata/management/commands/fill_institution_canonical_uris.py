"""Backfill canonical URIs for institution-specific resources."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from django.core.management.base import BaseCommand
from django.db import transaction

from arkumu.metadata.models.resource import Resource


@dataclass
class UpdateStats:
    institution: str
    attempted: int = 0
    updated: int = 0


class Command(BaseCommand):
    """Fill missing canonical URIs for institution-scoped resources.

    Many importer mappings emit resources under org-specific namespaces
    such as ``http://arkumu.org/data/fuk/...``.  When the mapping does
    not specify the canonical property/class, ``Resource.canonical_uri``
    remains empty and the canonical graph service subsequently ignores
    those triples.  This command normalises those URIs by replacing the
    institution segment with the shared ``/data/`` namespace.
    """

    help = "Backfill canonical URIs for FUK/RSH/DET (or other) resources"

    DEFAULT_INSTITUTIONS = ("fuk", "rsh", "det")

    def add_arguments(self, parser):
        parser.add_argument(
            "--institutions",
            nargs="+",
            dest="institutions",
            default=self.DEFAULT_INSTITUTIONS,
            help="Institution codes whose resources should be normalised (default: fuk rsh det)",
        )
        parser.add_argument(
            "--dry-run",
            dest="dry_run",
            action="store_true",
            help="Report the planned changes without writing to the database",
        )

    def handle(self, *args, **options):
        institutions: Iterable[str] = options["institutions"] or self.DEFAULT_INSTITUTIONS
        dry_run: bool = options["dry_run"]

        stats: list[UpdateStats] = []

        for code in institutions:
            normalized = (code or "").strip().lower()
            if not normalized:
                self.stdout.write(self.style.WARNING("Skipping blank institution code"))
                continue

            stats.append(self._process_institution(normalized, dry_run=dry_run))

        for entry in stats:
            message = f"{entry.institution}: attempted {entry.attempted}, updated {entry.updated}"
            style = self.style.SUCCESS if entry.updated else self.style.WARNING
            self.stdout.write(style(message))

        total_updates = sum(entry.updated for entry in stats)
        if dry_run:
            self.stdout.write(self.style.WARNING(f"Dry-run complete. {total_updates} resources would be updated."))
        else:
            self.stdout.write(self.style.SUCCESS(f"Canonical URI backfill complete. Updated {total_updates} resources."))

    def _process_institution(self, institution: str, *, dry_run: bool) -> UpdateStats:
        stats = UpdateStats(institution=institution)

        segment = f"/data/{institution}/"

        queryset = Resource.objects.filter(
            canonical_uri__isnull=True,
            uri__icontains=segment,
        ).exclude(uri__isnull=True)

        with transaction.atomic():
            for resource in queryset.iterator(chunk_size=500):
                stats.attempted += 1
                canonical = resource.uri.replace(segment, "/data/", 1)
                if canonical == resource.uri:
                    # Nothing to normalise
                    continue

                stats.updated += 1
                resource.canonical_uri = canonical
                if not dry_run:
                    resource.save(update_fields=["canonical_uri", "updated_at"])

            if dry_run:
                transaction.set_rollback(True)

        return stats
