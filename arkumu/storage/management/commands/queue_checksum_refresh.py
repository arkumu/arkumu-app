"""Schedule checksum recalculation Huey tasks."""

from __future__ import annotations

from django.core.management.base import BaseCommand

from arkumu.storage.tasks import recalculate_s3_checksums


class Command(BaseCommand):
    help = "Queue SHA256 checksum recalculation for S3 files via Huey."

    def add_arguments(self, parser) -> None:  # type: ignore[override]
        parser.add_argument(
            "--bucket",
            dest="organization",
            help="Limit recalculation to a specific organization/bucket code.",
        )
        parser.add_argument(
            "--all",
            action="store_true",
            dest="all_files",
            help="Recalculate even when a checksum already exists.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            help="Maximum number of files to queue (processed in updated_at order).",
        )

    def handle(self, *args, **options) -> None:  # type: ignore[override]
        organization: str | None = options.get("organization")
        missing_only = not options.get("all_files", False)
        limit: int | None = options.get("limit")

        recalculate_s3_checksums.schedule(
            args=(organization,),
            kwargs={"missing_only": missing_only, "limit": limit},
            delay=0,
        )

        scope = organization or "all buckets"
        mode = "missing-only" if missing_only else "all files"
        if limit:
            mode += f", limit {limit}"

        self.stdout.write(
            self.style.SUCCESS(
                f"Queued checksum recalculation for {scope} ({mode}).",
            )
        )

