"""Prune derived project→digital object triples for selected organizations.

This is a safety valve for over-eager runs of ``derive_project_relationships``
that produced too many derived project↔digital object links (e.g. for KHM).

Usage (compose dev):

    docker compose -f docker-compose.dev.yml run --rm django \\
      python manage.py prune_derived_project_digital_links --organization khm

Use ``--dry-run`` first to inspect counts without deleting anything.
"""

from __future__ import annotations

from typing import Iterable, Optional

from django.core.management.base import BaseCommand

from arkumu.metadata.models import Triple


class Command(BaseCommand):
    help = "Delete derived project→digital object triples for the given organization(s)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--organization",
            "-o",
            action="append",
            dest="organizations",
            help="Organization code(s) to prune (e.g. khm). Can be passed multiple times.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show how many triples would be deleted without modifying the database.",
        )

    def handle(self, *args, **options):
        orgs: Optional[Iterable[str]] = options.get("organizations") or ()
        dry_run: bool = bool(options.get("dry_run", False))

        org_codes = {code.strip().lower() for code in orgs if code and code.strip()}
        if not org_codes:
            self.stdout.write(
                self.style.ERROR(
                    "No organizations specified. Use --organization khm (and repeat as needed)."
                )
            )
            return

        total_deleted = 0

        for org_code in sorted(org_codes):
            qs = Triple.objects.filter(
                predicate__canonical_uri="http://arkumu.org/data/properties/digitales-objekt",
                subject__organization__code__iexact=org_code,
                subject__uri__contains="/entities/projekt/",
                is_derived=True,
            )

            total = qs.count()
            if dry_run:
                self.stdout.write(
                    self.style.HTTP_INFO(
                        f"[DRY RUN] Organization={org_code}: derived project→digital triples={total}"
                    )
                )
                continue

            deleted, _ = qs.delete()
            total_deleted += deleted
            self.stdout.write(
                self.style.SUCCESS(
                    f"Organization={org_code}: deleted {deleted} derived project→digital triples"
                )
            )

        if not dry_run:
            self.stdout.write(
                self.style.MIGRATE_HEADING(
                    f"Prune complete. Total deleted derived project→digital triples: {total_deleted}"
                )
            )
