from __future__ import annotations

from typing import Iterable, Sequence

from django.conf import settings
from django.core.management.base import BaseCommand

from arkumu.metadata.models.mappings import Mapping


class Command(BaseCommand):
    """Export a minimal arkumu_base project↔digital-object mapping per org.

    This command inspects the active Mapping.mapping_config for each
    organization and prints a lightweight summary that answers exactly:

        “For this org, which dataset is Project, which is DigitalObject,
        and which join(s) link them?”

    It does *not* modify any data – it is a read-only diagnostic tool that
    can be used as a blueprint for seeding logic or ontology annotations.
    """

    help = "Summarize arkumu_base-style Project↔DigitalObject mappings for each organization."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "-o",
            "--organization",
            action="append",
            dest="org_codes",
            help="Organization code to inspect (may be passed multiple times). Defaults to all orgs with mappings.",
        )

    def handle(self, *args, **options) -> None:
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

        project_type_uris = set(getattr(settings, "OAI_PROJECT_TYPE_URIS", ()))

        for code in targets:
            if not code:
                continue
            mapping = Mapping.get_active_for_organization(code)
            if mapping is None:
                self.stdout.write(self.style.WARNING(f"[{code}] No active mapping found."))
                continue

            self.stdout.write(f"## Organization `{code}` – mapping `{mapping.name}`\n")

            manifest = mapping.mapping_config.get("schema_manifest", {}) or {}

            # ------------------------------------------------------------------
            # Discover project and digital-object datasets.
            # ------------------------------------------------------------------
            project_datasets: list[tuple[str, str]] = []
            digital_datasets: list[tuple[str, str]] = []

            for dataset, cfg in manifest.items():
                et = cfg.get("entity_type") or {}
                canonical_uri = (et.get("canonical_uri") or "").strip()
                if canonical_uri in project_type_uris:
                    project_datasets.append((dataset, canonical_uri))

                canonical_lower = canonical_uri.lower()
                if "digitales-objekt" in canonical_lower:
                    digital_datasets.append((dataset, canonical_uri))

            if not project_datasets:
                self.stdout.write(self.style.WARNING(f"- No Project datasets found for `{code}`.\n"))
            else:
                self.stdout.write("- Project datasets:\n")
                for ds, uri in project_datasets:
                    self.stdout.write(f"  - `{ds}` (type: `{uri}`)\n")

            if not digital_datasets:
                self.stdout.write(self.style.WARNING(f"- No DigitalObject datasets found for `{code}`.\n"))
            else:
                self.stdout.write("- DigitalObject datasets:\n")
                for ds, uri in digital_datasets:
                    self.stdout.write(f"  - `{ds}` (type: `{uri}`)\n")

            project_ds_names = {ds for ds, _ in project_datasets}
            digital_ds_names = {ds for ds, _ in digital_datasets}

            # ------------------------------------------------------------------
            # Discover FKs that directly join Project ↔ DigitalObject.
            # ------------------------------------------------------------------
            direct_joins: list[dict] = []
            join_datasets: dict[str, dict[str, list[dict]]] = {}

            for dataset, cfg in manifest.items():
                fk_list = cfg.get("fk_relationships", []) or []
                if not fk_list:
                    continue
                for meta in fk_list:
                    src_ds = meta.get("source_dataset") or dataset
                    tgt_ds = meta.get("target_dataset")
                    src_col = meta.get("source_column")
                    tgt_col = meta.get("target_column")
                    if not (src_ds and tgt_ds and src_col and tgt_col):
                        continue

                    if src_ds in project_ds_names and tgt_ds in digital_ds_names:
                        direct_joins.append(meta)

                # Track potential join datasets that touch both project and digital
                targets_project: list[dict] = []
                targets_digital: list[dict] = []
                for meta in fk_list:
                    tgt_ds = meta.get("target_dataset")
                    if tgt_ds in project_ds_names:
                        targets_project.append(meta)
                    if tgt_ds in digital_ds_names:
                        targets_digital.append(meta)
                if targets_project and targets_digital:
                    join_datasets[dataset] = {
                        "to_project": targets_project,
                        "to_digital": targets_digital,
                    }

            if direct_joins:
                self.stdout.write("- Direct Project↔DigitalObject joins:\n")
                for meta in direct_joins:
                    src_ds = meta.get("source_dataset")
                    src_col = meta.get("source_column")
                    tgt_ds = meta.get("target_dataset")
                    tgt_col = meta.get("target_column")
                    self.stdout.write(
                        f"  - `{src_ds}.{src_col}` → `{tgt_ds}.{tgt_col}`\n"
                    )
            else:
                self.stdout.write("- Direct Project↔DigitalObject joins: *(none detected)*\n")

            if join_datasets:
                self.stdout.write("- Join datasets connecting Project ↔ DigitalObject:\n")
                for ds, parts in join_datasets.items():
                    self.stdout.write(f"  - `{ds}`:\n")
                    for meta in parts.get("to_project", []):
                        self.stdout.write(
                            f"    • to Project via `{meta.get('source_column')}` → "
                            f"`{meta.get('target_dataset')}.{meta.get('target_column')}`\n"
                        )
                    for meta in parts.get("to_digital", []):
                        self.stdout.write(
                            f"    • to DigitalObject via `{meta.get('source_column')}` → "
                            f"`{meta.get('target_dataset')}.{meta.get('target_column')}`\n"
                        )
            else:
                self.stdout.write("- Join datasets: *(none that touch both Project and DigitalObject)*\n")

            self.stdout.write("")  # blank line separator
