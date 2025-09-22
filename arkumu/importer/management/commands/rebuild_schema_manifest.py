"""Rebuild schema manifests for existing mappings."""

from django.core.management.base import BaseCommand, CommandError
from django.conf import settings

from arkumu.metadata.models.mappings import Mapping
from arkumu.users.models import Organization
from arkumu.importer.services.mapping_consumer import ConfigTranslator
from arkumu.importer.services.execution.mapping_aware_processor import MappingAwareProcessor
from arkumu.importer.services.execution.statistics import ExecutionStatistics


DEFAULT_BASE_URI = getattr(settings, "ARKUMU_BASE_URI", "http://arkumu.org/data")


class Command(BaseCommand):
    """Management command to rebuild stored schema manifests."""

    help = "Generate and persist schema_manifest for mappings using the importer blueprints."

    def add_arguments(self, parser):
        parser.add_argument(
            "--mapping-id",
            action="append",
            dest="mapping_ids",
            help="Specific mapping UUID to rebuild (can be given multiple times)."
        )
        parser.add_argument(
            "--base-uri",
            dest="base_uri",
            default=DEFAULT_BASE_URI,
            help="Base URI to use when minting schema resources (default: %(default)s)."
        )

    def handle(self, *args, **options):
        mapping_ids = options.get("mapping_ids")
        base_uri = options.get("base_uri") or DEFAULT_BASE_URI

        mappings = Mapping.objects.all()
        if mapping_ids:
            mappings = mappings.filter(id__in=mapping_ids)
            if not mappings.exists():
                raise CommandError("No mappings matched the provided --mapping-id value(s).")

        translator = ConfigTranslator()
        processed = 0
        skipped = 0

        for mapping in mappings:
            mapping_config = mapping.mapping_config or {}
            if not mapping_config:
                self.stdout.write(self.style.WARNING(f"Skipping {mapping.id} – empty mapping_config."))
                skipped += 1
                continue

            organization = None
            if mapping.organization_id:
                organization = Organization.objects.filter(code=mapping.organization_id).first()
                if not organization:
                    self.stdout.write(
                        self.style.WARNING(
                            f"Skipping {mapping.id} – organization with code '{mapping.organization_id}' not found."
                        )
                    )
                    skipped += 1
                    continue
            else:
                self.stdout.write(
                    self.style.WARNING(f"Skipping {mapping.id} – mapping has no organization_id set.")
                )
                skipped += 1
                continue

            try:
                execution_config = translator.translate_mapping_config(mapping_config)
            except Exception as exc:
                self.stdout.write(
                    self.style.ERROR(f"Failed to translate mapping_config for {mapping.id}: {exc}")
                )
                skipped += 1
                continue

            if not execution_config.datasets:
                self.stdout.write(
                    self.style.WARNING(f"Skipping {mapping.id} – translated config has no datasets.")
                )
                skipped += 1
                continue

            # Ensure blueprint cache keys align with real mapping identifier
            execution_config.mapping_id = mapping.id

            processor = MappingAwareProcessor(
                organization=organization,
                base_uri=base_uri,
                statistics=ExecutionStatistics()
            )

            try:
                processor._create_complete_schema_blueprints(execution_config)
            except Exception as exc:
                self.stdout.write(
                    self.style.ERROR(f"Failed to build schema manifest for {mapping.id}: {exc}")
                )
                skipped += 1
                continue

            processed += 1
            self.stdout.write(self.style.SUCCESS(f"Schema manifest rebuilt for mapping {mapping.id}"))

        summary = f"Processed {processed} mapping(s); Skipped {skipped}."
        self.stdout.write(self.style.SUCCESS(summary) if processed else summary)
