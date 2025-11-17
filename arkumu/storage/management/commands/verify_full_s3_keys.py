from __future__ import annotations

from typing import Tuple

from django.core.management.base import BaseCommand

from arkumu.storage.models import S3FileObject
from arkumu.storage.services.verification_service import verify_single_object


def _split_s3_location(
    s3_key: str,
) -> Tuple[str | None, str | None]:
    """
    Return bucket and key components from a stored S3 key.

    We prefer values that explicitly include the bucket, e.g. ``s3://bucket/path``.
    """
    if not s3_key:
        return None, None

    s3_key = s3_key.lstrip("/")

    if s3_key.startswith("s3://"):
        remainder = s3_key[5:]
        bucket, _, key = remainder.partition("/")
        return bucket or None, key or ""

    return None, s3_key


class Command(BaseCommand):
    help = (
        "Verify each S3FileObject by performing a head_object request using the stored S3 key. "
        "If the file exists, mark it as verified, store the ETag, and capture the bucket as organization."
    )

    def add_arguments(self, parser) -> None:  # type: ignore[override]
        parser.add_argument(
            "--limit",
            type=int,
            help="Process at most this many S3FileObject rows (ordered by pk).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print what would change without updating the database.",
        )

    def handle(self, *args, **options) -> None:  # type: ignore[override]
        limit: int | None = options.get("limit")
        dry_run: bool = options.get("dry_run", False)

        queryset = S3FileObject.objects.select_related("session").all().order_by("pk")
        if limit is not None:
            queryset = queryset[:limit]

        total = queryset.count()
        if total == 0:
            self.stdout.write(self.style.SUCCESS("No S3FileObject rows to process."))
            return

        verified = 0
        newly_verified = 0
        missing = 0
        newly_missing = 0
        skipped = 0

        for obj in queryset.iterator():
            bucket, key = _split_s3_location(obj.s3_key or "")
            if not bucket and obj.session_id:
                session_bucket = (getattr(obj.session, "s3_bucket", "") or "").strip()
                if session_bucket:
                    bucket = session_bucket
            if not bucket or not key:
                skipped += 1
                self.stderr.write(
                    self.style.WARNING(
                        f"Skipping {obj.pk}: unable to determine bucket for key '{obj.s3_key}'."
                    )
                )
                continue

            status_was_verified = obj.status == "verified"
            previously_missing = obj.status == "missing"

            result = verify_single_object(
                bucket,
                key,
                bucket,
                dry_run=dry_run,
            )

            if result.missing:
                missing += 1
                self.stderr.write(self.style.WARNING(f"{bucket}/{key} missing during verification"))
                if not previously_missing:
                    newly_missing += 1
                if dry_run:
                    continue
                if obj.status != "missing" or obj.error_message != "File missing in S3":
                    obj.status = "missing"
                    obj.error_message = "File missing in S3"
                    obj.save(update_fields=["status", "error_message", "updated_at"])
                continue

            if result.error:
                missing += 1
                self.stderr.write(self.style.WARNING(f"{bucket}/{key} unable to verify: {result.error}"))
                if not previously_missing:
                    newly_missing += 1
                if dry_run:
                    continue
                desired_error = f"S3 verification error: {result.error or 'Unknown error'}"
                if obj.status != "missing" or obj.error_message != desired_error:
                    obj.status = "missing"
                    obj.error_message = desired_error
                    obj.save(update_fields=["status", "error_message", "updated_at"])
                continue

            verified += 1
            if dry_run:
                if not status_was_verified:
                    newly_verified += 1
                continue

            if not status_was_verified:
                newly_verified += 1

        summary = (
            f"{'Would verify' if dry_run else 'Verified'} {verified} object(s); "
            f"{'Would newly verify' if dry_run else 'Newly verified'} {newly_verified}; "
            f"{'Would mark as missing' if dry_run else 'Newly missing'} {newly_missing}; "
            f"{missing} missing; {skipped} skipped."
        )
        self.stdout.write(self.style.SUCCESS(summary))
