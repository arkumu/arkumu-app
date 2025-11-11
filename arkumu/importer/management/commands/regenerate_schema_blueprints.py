"""
Regenerate cached schema blueprints for specific mappings.
"""

from __future__ import annotations

from django.conf import settings
from django.core.cache import cache
from django.core.management.base import BaseCommand, CommandError

from arkumu.importer.services.schema_service import SchemaService
from arkumu.metadata.models.mappings import Mapping
from arkumu.users.models import Organization


DEFAULT_BASE_URI = getattr(settings, "ARKUMU_BASE_URI", "http://arkumu.org/data")


class Command(BaseCommand):
    """
    Clear the cached schema blueprints for one or more mappings and regenerate them
    using SchemaService. This ensures downstream tooling (entity creation flow,
    schema workspace) reads the latest field metadata after a mapping change.
    """

    help = "Regenerate cached schema blueprints for the given mapping(s)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--mapping-id",
            action="append",
            dest="mapping_ids",
            help="Process a specific mapping UUID (can be provided multiple times).",
        )
        parser.add_argument(
            "--organization",
            dest="organization_code",
            help="Process the most recent mapping for the given organization code.",
        )
        parser.add_argument(
            "--base-uri",
            dest="base_uri",
            default=DEFAULT_BASE_URI,
            help="Base URI to use when minting resources (default: %(default)s).",
        )

    def handle(self, *args, **options):
        mapping_ids = options.get("mapping_ids") or []
        org_code = options.get("organization_code")
        base_uri = options.get("base_uri") or DEFAULT_BASE_URI

        mappings = self._resolve_mappings(mapping_ids, org_code)
        if not mappings:
            raise CommandError("No mappings resolved – provide --mapping-id and/or --organization.")

        processed = 0
        skipped = 0

        for mapping in mappings:
            organization = None
            if mapping.organization_id:
                organization = Organization.objects.filter(code=mapping.organization_id).first()
            if organization is None:
                self.stdout.write(
                    self.style.WARNING(
                        f"Skipping {mapping.id} – organization '{mapping.organization_id}' not found."
                    )
                )
                skipped += 1
                continue

            cache_keys = [
                f"schema_blueprints_mapping_{mapping.id}",
                f"complete_schema_blueprints_mapping_{mapping.id}",
            ]
            for key in cache_keys:
                cache.delete(key)

            try:
                service = SchemaService(
                    mapping_id=str(mapping.id),
                    institution=organization.code,
                    base_uri=base_uri,
                )
                service.list_datasets()  # Force schema load/rebuild
            except Exception as exc:
                self.stdout.write(
                    self.style.ERROR(
                        f"Failed to regenerate schema for mapping {mapping.id}: {exc}"
                    )
                )
                skipped += 1
                continue

            processed += 1
            self.stdout.write(self.style.SUCCESS(f"Schema blueprints regenerated for mapping {mapping.id}"))

        summary = f"Processed {processed} mapping(s); Skipped {skipped}."
        self.stdout.write(self.style.SUCCESS(summary) if processed else summary)

    def _resolve_mappings(self, mapping_ids, org_code):
        queryset = Mapping.objects.none()

        if mapping_ids:
            queryset = queryset | Mapping.objects.filter(id__in=mapping_ids)

        if org_code:
            latest = Mapping.get_active_for_organization(org_code)
            if latest:
                queryset = queryset | Mapping.objects.filter(id=latest.id)
            else:
                self.stdout.write(
                    self.style.WARNING(
                        f"No mappings found for organization '{org_code}'."
                    )
                )

        return queryset.distinct()
