from __future__ import annotations

from typing import Iterable, List, Optional

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from arkumu.metadata.models.mappings import Mapping


class Command(BaseCommand):
    help = (
        "Remove the stored schema_manifest from mapping configurations. "
        "Useful when the manifest needs to be regenerated from the current workspace columns."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--organization",
            action="append",
            dest="organizations",
            help="Organization code whose mappings should be cleaned. "
                 "Can be provided multiple times.",
        )
        parser.add_argument(
            "--mapping-id",
            action="append",
            dest="mapping_ids",
            help="Specific mapping UUID to clean. Can be provided multiple times.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Preview the mappings that would be cleaned without persisting changes.",
        )

    def handle(self, *args, **options):
        organizations: Optional[List[str]] = options["organizations"]
        mapping_ids: Optional[List[str]] = options["mapping_ids"]
        dry_run: bool = options["dry_run"]

        if not organizations and not mapping_ids:
            raise CommandError("Provide at least --organization or --mapping-id.")

        queryset = Mapping.objects.all()

        if organizations:
            queryset = queryset.filter(organization_id__in=organizations)

        if mapping_ids:
            queryset = queryset.filter(id__in=mapping_ids)

        mappings: List[Mapping] = list(queryset)

        if not mappings:
            self.stdout.write(self.style.WARNING("No mappings matched the provided filters."))
            return

        self.stdout.write(f"Located {len(mappings)} mapping(s). Inspecting for schema_manifest entries...")

        affected: List[Mapping] = [
            mapping for mapping in mappings if "schema_manifest" in mapping.mapping_config
        ]

        if not affected:
            self.stdout.write(self.style.SUCCESS("No schema_manifest entries found. Nothing to clean."))
            return

        self.stdout.write(
            f"Schema manifest present on {len(affected)} mapping(s): "
            f"{', '.join(mapping.name for mapping in affected)}"
        )

        if dry_run:
            self.stdout.write(self.style.WARNING("Dry-run enabled – no changes were written."))
            return

        with transaction.atomic():
            for mapping in affected:
                config = dict(mapping.mapping_config)
                config.pop("schema_manifest", None)
                mapping.mapping_config = config
                mapping.save(update_fields=["mapping_config", "updated_at"])

        self.stdout.write(self.style.SUCCESS(f"Removed schema_manifest from {len(affected)} mapping(s)."))
