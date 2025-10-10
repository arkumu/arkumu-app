from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from arkumu.storage.tasks import recalculate_s3_checksums


class Command(BaseCommand):
    help = "Recalculate S3 file checksums immediately without queuing Huey tasks."

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
            help="Recalculate even when a checksum already exists (default: missing only).",
        )
        parser.add_argument(
            "--limit",
            type=int,
            help="Maximum number of files to process (ordered by updated_at).",
        )

    def handle(self, *args, **options) -> None:  # type: ignore[override]
        organization: str | None = options.get("organization")
        missing_only = not options.get("all_files", False)
        limit: int | None = options.get("limit")

        try:
            recalculate_s3_checksums(
                organization=organization,
                missing_only=missing_only,
                limit=limit,
            )
        except Exception as exc:  # noqa: BLE001
            raise CommandError(f"Checksum recalculation failed: {exc}") from exc

        scope = organization or "all buckets"
        mode = "missing-only" if missing_only else "all files"
        if limit is not None:
            mode += f", limit {limit}"

        self.stdout.write(
            self.style.SUCCESS(
                f"Checksum recalculation complete for {scope} ({mode}).",
            )
        )
