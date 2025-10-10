from __future__ import annotations

from typing import Tuple

from botocore.exceptions import ClientError
from django.core.management.base import BaseCommand

from arkumu.storage.models import S3FileObject
from arkumu.storage.services.base_storage_service import BaseStorageService


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

        service = BaseStorageService()
        verified = 0
        newly_verified = 0
        missing = 0
        newly_missing = 0
        skipped = 0

        try:
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

                try:
                    head = service.s3_client.head_object(Bucket=bucket, Key=key)
                except ClientError as exc:
                    missing += 1
                    self.stderr.write(self.style.WARNING(f"{bucket}/{key} missing: {exc}"))
                    if obj.status != "missing":
                        newly_missing += 1
                    if dry_run:
                        continue
                    obj.status = "missing"
                    obj.error_message = "File missing in S3"
                    obj.save(update_fields=["status", "error_message", "updated_at"])
                    continue
                except Exception as exc:  # noqa: BLE001
                    missing += 1
                    self.stderr.write(self.style.WARNING(f"{bucket}/{key} unable to verify: {exc}"))
                    if obj.status != "missing":
                        newly_missing += 1
                    if dry_run:
                        continue
                    obj.status = "missing"
                    obj.error_message = f"S3 verification error: {exc}"
                    obj.save(update_fields=["status", "error_message", "updated_at"])
                    continue

                verified += 1
                status_was_verified = obj.status == "verified"
                if dry_run:
                    if not status_was_verified:
                        newly_verified += 1
                    continue

                updates: list[str] = []
                if not status_was_verified:
                    obj.status = "verified"
                    updates.append("status")
                    newly_verified += 1

                etag = head.get("ETag") or ""
                if etag and etag != obj.etag:
                    obj.etag = etag
                    updates.append("etag")

                if obj.organization != bucket:
                    obj.organization = bucket
                    updates.append("organization")

                if updates:
                    updates.append("updated_at")
                    obj.save(update_fields=updates)
        finally:
            if hasattr(service, "close"):
                try:
                    service.close()  # type: ignore[attr-defined]
                except Exception:  # noqa: BLE001
                    pass

        summary = (
            f"{'Would verify' if dry_run else 'Verified'} {verified} object(s); "
            f"{'Would newly verify' if dry_run else 'Newly verified'} {newly_verified}; "
            f"{'Would mark as missing' if dry_run else 'Newly missing'} {newly_missing}; "
            f"{missing} missing; {skipped} skipped."
        )
        self.stdout.write(self.style.SUCCESS(summary))
