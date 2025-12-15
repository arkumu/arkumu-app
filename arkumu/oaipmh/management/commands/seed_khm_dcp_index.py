from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, Set

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from arkumu.oaipmh import path_mapping
from arkumu.oaipmh.models import OAIDcpPathIndex

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Seed the OAIDcpPathIndex table for KHM from dateipfad-dcp-ordner triples and path mapping."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Clear existing KHM DCP index entries before seeding.",
        )

    def handle(self, *args, **options) -> None:
        org_code = "khm"
        org = org_code.lower().strip()

        rosetta_root = getattr(settings, "OAI_EXTERNAL_ROSETTA_ROOTS", {}).get(org)
        if not rosetta_root:
            raise CommandError("OAI_EXTERNAL_ROSETTA_ROOTS['khm'] is not configured; cannot seed DCP index.")

        rosetta_root = str(rosetta_root).rstrip("/")
        index = path_mapping._load_index(org)  # type: ignore[attr-defined]
        if not index.full_paths:
            raise CommandError("No KHM external path index is loaded; check OAI_EXTERNAL_PATH_FILES['khm'].")

        if options.get("reset"):
            deleted, _ = OAIDcpPathIndex.objects.filter(org_code=org).delete()
            self.stdout.write(self.style.WARNING(f"Cleared {deleted} existing OAIDcpPathIndex rows for org={org}."))

        # Get all DCP folder names from dateipfad-dcp-ordner triples
        dcp_folder_names = self._get_dcp_folder_names_from_triples()
        self.stdout.write(f"Found {len(dcp_folder_names)} DCP folders from triples")

        # Build a map of folder_name -> list of file paths
        folder_files: Dict[str, list] = {fn: [] for fn in dcp_folder_names}

        for abs_path in index.full_paths:
            normalized = abs_path.replace("\\", "/")
            if not normalized.startswith(rosetta_root + "/"):
                continue

            rel_path = normalized[len(rosetta_root) + 1:]
            if not rel_path:
                continue

            # Check if this path contains any known DCP folder
            for folder_name in dcp_folder_names:
                if f"/{folder_name}/" in f"/{rel_path}":
                    folder_files[folder_name].append(rel_path)
                    break

        created = 0
        updated = 0

        for folder_name, file_paths in folder_files.items():
            if not file_paths:
                continue

            for rel_path in file_paths:
                parts = [segment for segment in rel_path.split("/") if segment]
                if not parts:
                    continue

                # Find the folder_name in the path to build bundle_key
                try:
                    idx = parts.index(folder_name)
                    bundle_key = "/".join(parts[: idx + 1])
                except ValueError:
                    bundle_key = folder_name

                file_name = Path(rel_path).name
                if not file_name:
                    continue

                obj, created_flag = OAIDcpPathIndex.objects.update_or_create(
                    org_code=org,
                    relative_file_path=rel_path,
                    defaults={
                        "bundle_key": bundle_key,
                        "folder_name": folder_name,
                        "file_name": file_name,
                    },
                )
                if created_flag:
                    created += 1
                else:
                    updated += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded OAIDcpPathIndex for org={org}: created={created}, updated={updated}."
            )
        )

    def _get_dcp_folder_names_from_triples(self) -> Set[str]:
        """Get all DCP folder names from dateipfad-dcp-ordner triples."""
        from arkumu.metadata.models import Triple

        DCP_PREDICATE = "http://arkumu.org/data/khm/properties/dateipfad-dcp-ordner"
        triples = Triple.objects.filter(
            predicate__uri=DCP_PREDICATE,
        ).select_related("object")

        folder_names: Set[str] = set()
        for t in triples:
            value = getattr(t.object, "value", None)
            if value:
                path = str(value).strip().replace("\\", "/")
                # Extract folder name (last segment)
                folder_name = path.rstrip("/").split("/")[-1] if "/" in path else path
                if folder_name:
                    folder_names.add(folder_name)

        return folder_names
