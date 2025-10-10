from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from arkumu.metadata.services.metatdata_s3_mapping.map_resources_to_files import (
    FileResourceMatcherService,
    MatchingConfig,
)
from arkumu.storage.models import S3FileObject

VALID_STATUSES = {"pending", "uploading", "completed", "failed", "missing", "verified"}


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
        parser.add_argument(
            "--set-status",
            dest="set_status",
            help="Set status for existing S3FileObject rows after syncing (e.g. 'verified').",
        )
        parser.add_argument(
            "--from-status",
            dest="from_statuses",
            action="append",
            help="Only update rows currently in this status (repeatable).",
        )

    def handle(self, *args, **options) -> None:  # type: ignore[override]
        bucket: str = options["bucket"].strip()
        prefix: str = options["prefix"].strip()
        batch_size: int = options["batch_size"]
        dry_run: bool = options["dry_run"]
        set_status_opt: str | None = options.get("set_status")
        from_statuses_opt: list[str] | None = options.get("from_statuses")

        if not bucket:
            raise CommandError("Bucket code cannot be empty.")

        target_status: str | None = None
        if set_status_opt:
            normalized = set_status_opt.strip().lower()
            if normalized not in VALID_STATUSES:
                raise CommandError(
                    f"Invalid --set-status '{set_status_opt}'. "
                    f"Valid options: {sorted(VALID_STATUSES)}"
                )
            target_status = normalized

        from_statuses: list[str] | None = None
        if from_statuses_opt:
            from_statuses = []
            for value in from_statuses_opt:
                normalized = value.strip().lower()
                if normalized not in VALID_STATUSES:
                    raise CommandError(
                        f"Invalid --from-status '{value}'. "
                        f"Valid options: {sorted(VALID_STATUSES)}"
                    )
                from_statuses.append(normalized)

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

        updated = 0
        if target_status:
            queryset = S3FileObject.objects.all()
            queryset = queryset.filter(organization__iexact=bucket.lower())
            if prefix:
                queryset = queryset.filter(s3_key__startswith=prefix)
            if from_statuses:
                queryset = queryset.filter(status__in=from_statuses)
            if dry_run:
                updated = queryset.count()
            else:
                updated = queryset.update(status=target_status)

        summary = (
            f"{'Dry-run: would create' if dry_run else 'Created'} {created} S3FileObject(s); "
            f"{synced} existing; skipped {skipped}; errors {errors}."
        )
        style = self.style.WARNING if dry_run else self.style.SUCCESS
        self.stdout.write(style(summary))

        if target_status is not None:
            status_msg = (
                f"{'Dry-run: would update' if dry_run else 'Updated'} "
                f"{updated} S3FileObject row(s) to status '{target_status}'."
            )
            self.stdout.write(style(status_msg))
