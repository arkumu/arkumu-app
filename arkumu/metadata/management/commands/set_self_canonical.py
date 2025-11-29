"""
Management command to set canonical_uri = uri for shared predicates.

Shared predicates in http://arkumu.org/data/properties/ should be self-canonical
so they pass through canonical URI filters in the graph service.

Usage:
    python manage.py set_self_canonical --dry-run
    python manage.py set_self_canonical
"""

from django.core.management.base import BaseCommand
from django.db.models import F

from arkumu.metadata.models import Resource, ResourceType


class Command(BaseCommand):
    help = "Set canonical_uri = uri for shared predicates without a canonical mapping"

    SHARED_PREFIXES = [
        "http://arkumu.org/data/properties/",
        "http://arkumu.org/data/types/",
    ]

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be done without making changes",
        )
        parser.add_argument(
            "--prefix",
            type=str,
            action="append",
            dest="prefixes",
            help="Additional URI prefixes to include (can be repeated)",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        prefixes = self.SHARED_PREFIXES + (options.get("prefixes") or [])

        self.stdout.write("Setting self-canonical URIs for shared resources")
        self.stdout.write("=" * 60)

        total_updated = 0

        for prefix in prefixes:
            # Find resources without canonical_uri
            qs = Resource.objects.filter(
                uri__startswith=prefix,
                canonical_uri__isnull=True,
            )

            count = qs.count()
            if count == 0:
                self.stdout.write(f"  {prefix}: 0 resources to update")
                continue

            if dry_run:
                self.stdout.write(
                    self.style.WARNING(f"  {prefix}: would update {count} resources")
                )
                # Show samples
                for r in qs[:5]:
                    self.stdout.write(f"    - {r.uri.split('/')[-1]}")
            else:
                updated = qs.update(canonical_uri=F("uri"))
                self.stdout.write(
                    self.style.SUCCESS(f"  {prefix}: updated {updated} resources")
                )
                total_updated += updated

        self.stdout.write("")
        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN: No changes made"))
        else:
            self.stdout.write(self.style.SUCCESS(f"Total updated: {total_updated}"))
