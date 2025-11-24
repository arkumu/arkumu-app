from __future__ import annotations

from typing import Iterable, Sequence

from django.core.management.base import BaseCommand

from arkumu.metadata.models.mappings import Mapping, MappingForeignKey


class Command(BaseCommand):
    """Persist FK definitions from active mappings into MappingForeignKey."""

    help = "Cache foreign-key relationships defined in active schema mappings."

    def add_arguments(self, parser):
        parser.add_argument(
            "-o",
            "--organization",
            action="append",
            dest="org_codes",
            help="Organization code to refresh (can be passed multiple times). Defaults to all organizations with mappings.",
        )

    def handle(self, *args, **options):
        org_codes: Iterable[str] | None = options.get("org_codes")
        if org_codes:
            targets: Sequence[str] = [code.lower().strip() for code in org_codes if code]
        else:
            targets = (
                Mapping.objects.values_list("organization_id", flat=True)
                .distinct()
                .order_by()
            )

        if not targets:
            self.stdout.write(self.style.WARNING("No organizations with mappings found."))
            return

        for code in targets:
            if not code:
                continue
            mapping = Mapping.get_active_for_organization(code)
            if mapping is None:
                self.stdout.write(self.style.WARNING(f"No active mapping found for organization '{code}'."))
                continue

            MappingForeignKey.objects.filter(organization_code=code).delete()
            fk_map = mapping.mapping_config.get("fk_relationships", {}) or {}
            bulk: list[MappingForeignKey] = []
            for meta in fk_map.values():
                source_dataset = meta.get("source_dataset")
                source_column = meta.get("source_column")
                target_dataset = meta.get("target_dataset")
                target_column = meta.get("target_column")
                if not all([source_dataset, source_column, target_dataset, target_column]):
                    continue
                bulk.append(
                    MappingForeignKey(
                        organization_code=code,
                        source_dataset=source_dataset,
                        source_column=source_column,
                        target_dataset=target_dataset,
                        target_column=target_column,
                        relationship_type=meta.get("relationship_type", ""),
                        direction=meta.get("direction", ""),
                        display_column=meta.get("display_column", "") or "",
                    )
                )

            MappingForeignKey.objects.bulk_create(bulk, ignore_conflicts=True)
            self.stdout.write(
                self.style.SUCCESS(
                    f"Cached {len(bulk)} FK definitions for organization '{code}'."
                )
            )
