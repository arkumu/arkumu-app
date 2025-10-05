"""Mark linked S3FileObjects as failed when the object is gone in S3."""

from __future__ import annotations

from django.core.management.base import BaseCommand

from arkumu.storage.models import S3FileObject


class Command(BaseCommand):
    help = (
        "Check linked S3FileObject rows against the S3 bucket and update their"
        " status to 'failed' when the object is missing."
    )

    def add_arguments(self, parser) -> None:  # type: ignore[override]
        parser.add_argument(
            "--bucket",
            dest="bucket",
            help="Restrict the check to a specific organization/bucket code.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            help="Maximum number of files to scan (ordered by -created_at).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report missing objects without updating the database.",
        )

    def handle(self, *args, **options) -> None:  # type: ignore[override]
        bucket = options["bucket"]
        limit = options["limit"]
        dry_run = options["dry_run"]

        queryset = S3FileObject.objects.filter(
            related_resource__isnull=False,
        ).exclude(status="failed")

        if bucket:
            queryset = queryset.filter(organization=bucket)

        queryset = queryset.order_by("-created_at")

        if limit:
            queryset = queryset[:limit]

        total = queryset.count()
        if not total:
            self.stdout.write(self.style.SUCCESS("No eligible S3 files found."))
            return

        self.stdout.write(
            f"Checking {total} linked file(s){' in ' + bucket if bucket else ''}"
            + (" [dry-run]" if dry_run else ""),
        )

        missing = 0

        for obj in queryset.iterator():
            exists = obj.exists_in_s3()
            if exists:
                continue

            missing += 1
            self.stdout.write(
                f"Missing: {obj.s3_key} (resource={obj.related_resource_id})",
            )

            if dry_run:
                continue

            obj.status = "failed"
            obj.error_message = "File missing in S3"
            obj.save(update_fields=["status", "error_message", "updated_at"])

        if missing == 0:
            self.stdout.write(self.style.SUCCESS("All checked files exist in S3."))
        else:
            suffix = " (dry-run)" if dry_run else ""
            self.stdout.write(
                self.style.WARNING(f"Marked {missing} file(s) as missing in S3{suffix}"),
            )

