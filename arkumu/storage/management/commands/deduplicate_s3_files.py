"""Remove duplicate S3FileObject rows per S3 key."""

from __future__ import annotations

from collections import defaultdict

from django.core.management.base import BaseCommand
from django.db import models, transaction

from arkumu.storage.models import S3FileObject


class Command(BaseCommand):
    help = (
        "Keep only the most recent S3FileObject row for each s3_key and remove"
        " older duplicates."
    )

    def add_arguments(self, parser) -> None:  # type: ignore[override]
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show the duplicates that would be removed without deleting them.",
        )
        parser.add_argument(
            "--organization",
            dest="organization",
            help="Limit deduplication to a specific organization/bucket code.",
        )

    def handle(self, *args, **options) -> None:  # type: ignore[override]
        dry_run = options["dry_run"]
        organization = options.get("organization")

        queryset = S3FileObject.objects.filter(status="completed")
        if organization:
            queryset = queryset.filter(organization=organization)

        duplicate_keys = (
            queryset.values("s3_key")
            .annotate(key_count=models.Count("id"))
            .filter(key_count__gt=1)
            .order_by("s3_key")
        )

        if not duplicate_keys.exists():
            self.stdout.write(self.style.SUCCESS("No duplicate S3 keys found."))
            return

        self.stdout.write(
            f"Found {duplicate_keys.count()} duplicate S3 key(s)"
            + (f" in '{organization}'" if organization else "")
            + (" [dry-run]" if dry_run else ""),
        )

        total_removed = 0

        for entry in duplicate_keys.iterator():
            key = entry["s3_key"]
            records = list(
                queryset
                .filter(s3_key=key)
                .order_by("-created_at", "-updated_at", "-id")
            )

            keep = records[0]
            to_remove = records[1:]

            if dry_run:
                self.stdout.write(
                    f"[dry-run] Keep {keep.id}; remove {[obj.id for obj in to_remove]} for key {key}"
                )
                total_removed += len(to_remove)
                continue

            with transaction.atomic():
                ids = [obj.id for obj in to_remove]
                S3FileObject.objects.filter(id__in=ids).delete()
                self.stdout.write(
                    self.style.SUCCESS(
                        f"Removed {len(ids)} duplicate(s) for {key}; kept {keep.id}",
                    )
                )
                total_removed += len(ids)

        self.stdout.write(
            self.style.SUCCESS(
                f"Removed {total_removed} duplicate record(s)."
                + (" (dry-run)" if dry_run else "")
            )
        )

