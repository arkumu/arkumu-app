"""Backfill organization/base-folder metadata on S3FileObject records."""

from __future__ import annotations

from collections import Counter

from django.core.management.base import BaseCommand
from django.db import models, transaction

from arkumu.storage.models import S3FileObject
from arkumu.storage.models.upload_tracking import AsyncUploadFile


class Command(BaseCommand):
    help = (
        "Populate S3FileObject.base_folder and organization using linked async upload"
        " sessions or by inferring from the S3 key."
    )

    def add_arguments(self, parser) -> None:  # type: ignore[override]
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would change without writing to the database.",
        )
        parser.add_argument(
            "--all",
            action="store_true",
            help="Process all rows, not just those missing metadata.",
        )

    def handle(self, *args, **options) -> None:  # type: ignore[override]
        dry_run: bool = options["dry_run"]
        process_all: bool = options["all"]

        qs = S3FileObject.objects.all().order_by("created_at")
        if not process_all:
            qs = qs.filter(
                (models.Q(base_folder="") | models.Q(base_folder__isnull=True))
                | (models.Q(organization="") | models.Q(organization__isnull=True))
            )

        total = qs.count()
        if not total:
            self.stdout.write(self.style.SUCCESS("No S3FileObject records require backfilling."))
            return

        self.stdout.write(f"Processing {total} S3FileObject record(s)...")

        stats = Counter()

        # Prefetch related async upload files to avoid N+1 queries
        async_map = {
            item["s3_file_object"]: (item["session__base_folder"], item["session__organization"])
            for item in AsyncUploadFile.objects.filter(
                s3_file_object__in=qs
            ).values(
                "s3_file_object",
                "session__base_folder",
                "session__organization",
            )
        }

        for obj in qs.iterator():
            base_folder, organization = self._resolve_metadata(obj, async_map.get(obj.id))

            if not base_folder and not organization:
                stats["skipped"] += 1
                continue

            if (
                obj.base_folder == base_folder
                and obj.organization == organization
            ):
                stats["unchanged"] += 1
                continue

            stats["updated"] += 1

            if dry_run:
                self.stdout.write(
                    f"DRY-RUN: would update {obj.id} to base_folder='{base_folder}', organization='{organization}'"
                )
                continue

            with transaction.atomic():
                obj.base_folder = base_folder or obj.base_folder
                obj.organization = organization or obj.organization
                obj.save(update_fields=["base_folder", "organization", "updated_at"])

        self.stdout.write(
            self.style.SUCCESS(
                f"Updated {stats['updated']} record(s); skipped {stats['skipped']} with no data; unchanged {stats['unchanged']}.",
            ),
        )

        if dry_run:
            self.stdout.write(self.style.WARNING("No changes written because --dry-run was used."))

    def _resolve_metadata(
        self,
        obj: S3FileObject,
        async_values: tuple[str | None, str | None] | None,
    ) -> tuple[str | None, str | None]:
        base_folder = None
        organization = None

        if async_values:
            base_folder, organization = async_values
            return base_folder or None, organization or None

        # Fall back to S3 key heuristics
        if obj.s3_key:
            parts = [part for part in obj.s3_key.split('/') if part]
            if len(parts) >= 1:
                base_folder = parts[0]
            if len(parts) >= 2:
                organization = parts[1]

        return base_folder, organization
