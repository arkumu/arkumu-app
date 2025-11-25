from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from arkumu.oaipmh import path_mapping
from arkumu.oaipmh.models import OAIDcpPathIndex

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Seed the OAIDcpPathIndex table for KHM from the configured _khm_paths.txt mapping."

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

        created = 0
        updated = 0

        for abs_path in index.full_paths:
            normalized = abs_path.replace("\\", "/")
            if not normalized.startswith(rosetta_root + "/"):
                logger.warning(
                    "Skipping KHM path outside Rosetta root: %s (root=%s)", normalized, rosetta_root
                )
                continue

            rel_path = normalized[len(rosetta_root) + 1 :]
            if not rel_path:
                continue

            parts = [segment for segment in rel_path.split("/") if segment]
            if not parts:
                continue

            bundle_parts = []
            folder_name: Optional[str] = None
            for segment in parts:
                bundle_parts.append(segment)
                if segment.lower().endswith(".dcp"):
                    folder_name = segment
                    break

            if not folder_name or not bundle_parts:
                # Not a DCP bundle path; skip
                continue

            bundle_key = "/".join(bundle_parts)
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

