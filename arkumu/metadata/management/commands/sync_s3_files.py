from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from arkumu.metadata.services.metatdata_s3_mapping.map_resources_to_files import (
    FileResourceMatcherService,
    MatchingConfig,
)


class Command(BaseCommand):
    help = (
        "Scan an S3 bucket/prefix and create S3FileObject rows for any missing keys. "
        "This is useful when files were uploaded outside the async pipeline."
    )

    def add_arguments(self, parser) -> None:  # type: ignore[override]
        parser.add_argument(
            "--bucket",
            required=True,
            help="Organization/bucket code to synchronize (required).",
        )
        parser.add_argument(
            "--prefix",
            default="",
            help="Optional S3 prefix to limit scanning (default: entire bucket).",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=1000,
            help="Bulk-create batch size (default: 1000).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be created without writing to the database.",
        )

    def handle(self, *args, **options) -> None:  # type: ignore[override]
        bucket: str = options["bucket"].strip()
        prefix: str = options["prefix"].strip()
        batch_size: int = options["batch_size"]
        dry_run: bool = options["dry_run"]

        if not bucket:
            raise CommandError("Bucket code cannot be empty.")

        logger_messages: list[str] = []

        def _logger(msg: str, level: str = "info") -> None:
            if dry_run:
                logger_messages.append(f"[dry-run] {msg}")
            else:
                logger_messages.append(msg)

        config = MatchingConfig(batch_size=batch_size)
        service = FileResourceMatcherService(logger_func=_logger, config=config)

        self.stdout.write(
            f"{'Dry-run: would sync' if dry_run else 'Synchronizing'} bucket '{bucket}'"
            + (f" with prefix '{prefix}'" if prefix else "")
        )

        try:
            if dry_run:
                with transaction.atomic():
                    synced, created, skipped, errors = service.discover_and_sync_s3_files(
                        bucket_name=bucket,
                        prefix=prefix,
                    )
                    transaction.set_rollback(True)
            else:
                synced, created, skipped, errors = service.discover_and_sync_s3_files(
                    bucket_name=bucket,
                    prefix=prefix,
                )
        except Exception as exc:  # noqa: BLE001
            raise CommandError(f"S3 discovery failed: {exc}") from exc

        for message in logger_messages:
            self.stdout.write(message)

        summary = (
            f"{'Dry-run: would create' if dry_run else 'Created'} {created} S3FileObject(s); "
            f"{synced} existing; skipped {skipped}; errors {errors}."
        )
        style = self.style.WARNING if dry_run else self.style.SUCCESS
        self.stdout.write(style(summary))
