from __future__ import annotations

import hashlib

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q

from arkumu.storage.models import S3FileObject
from arkumu.storage.services.base_storage_service import BaseStorageService

VALID_STATUSES = {"pending", "uploading", "completed", "failed", "verified"}


class Command(BaseCommand):
    help = (
        "Verify that S3FileObject rows still exist in the bucket. "
        "If the object is missing, mark the row as failed; otherwise refresh the checksum."
    )

    def add_arguments(self, parser) -> None:  # type: ignore[override]
        parser.add_argument(
            "--bucket",
            dest="bucket",
            help="Limit verification to a specific organization/bucket code.",
        )
        parser.add_argument(
            "--prefix",
            dest="prefix",
            default="",
            help="Optional key prefix filter (e.g. 'data/').",
        )
        parser.add_argument(
            "--status",
            dest="statuses",
            action="append",
            choices=sorted(VALID_STATUSES),
            help="Only process rows currently in this status (repeatable).",
        )
        parser.add_argument(
            "--limit",
            type=int,
            help="Maximum number of rows to process (ordered by -updated_at).",
        )
        parser.add_argument(
            "--missing-status",
            dest="missing_status",
            default="failed",
            choices=sorted(VALID_STATUSES),
            help="Status to assign when the S3 object is missing (default: failed).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would change without writing to the database.",
        )

    def handle(self, *args, **options) -> None:  # type: ignore[override]
        bucket: str | None = options.get("bucket")
        prefix: str = options.get("prefix", "").strip()
        statuses: list[str] | None = options.get("statuses")
        limit: int | None = options.get("limit")
        missing_status: str = options.get("missing_status", "failed")
        dry_run: bool = options.get("dry_run", False)

        queryset = S3FileObject.objects.all()

        if bucket:
            queryset = queryset.filter(
                Q(organization__iexact=bucket) | Q(session__s3_bucket__iexact=bucket)
            )

        if prefix:
            queryset = queryset.filter(s3_key__startswith=prefix)

        if statuses:
            queryset = queryset.filter(status__in=[status.lower() for status in statuses])

        queryset = queryset.order_by("-updated_at")

        if limit is not None:
            queryset = queryset[:limit]

        total = queryset.count()
        if total == 0:
            self.stdout.write(self.style.SUCCESS("No S3FileObject rows matched the criteria."))
            return

        self.stdout.write(
            f"{'Dry-run: would verify' if dry_run else 'Verifying'} {total} S3 file(s)."
        )

        service = BaseStorageService()
        missing = 0
        updated_checksums = 0
        failures: list[str] = []

        try:
            iterator = queryset.iterator()
            for obj in iterator:
                bucket_name = (
                    obj.organization
                    or getattr(obj.session, "organization", None)
                    or bucket
                    or "fuk"
                )
                key = obj.s3_key or ""

                try:
                    head = service.s3_client.head_object(Bucket=bucket_name, Key=key)
                except Exception:  # noqa: BLE001
                    missing += 1
                    failures.append(key)
                    if dry_run:
                        continue
                    obj.status = missing_status
                    obj.error_message = "File missing in S3"
                    obj.save(update_fields=["status", "error_message", "updated_at"])
                    continue

                etag = (head.get("ETag") or "").strip('"')
                if dry_run:
                    updated_checksums += 1
                    continue

                stored = False
                if etag and not obj.is_multipart_upload(etag):
                    obj._store_checksum("md5", etag)
                    stored = True
                else:
                    digest = _stream_hash(service.s3_client, bucket_name, key, "md5")
                    if digest:
                        obj._store_checksum("md5", digest)
                        stored = True
                if stored:
                    updated_checksums += 1
                    if obj.error_message:
                        obj.error_message = ""
                        obj.save(update_fields=["error_message", "updated_at"])
        except Exception as exc:  # noqa: BLE001
            raise CommandError(f"Verification failed: {exc}") from exc
        finally:
            if hasattr(service, "close"):
                try:
                    service.close()  # type: ignore[attr-defined]
                except Exception:  # noqa: BLE001
                    pass

        if missing == 0:
            self.stdout.write(self.style.SUCCESS("All verified S3 objects exist."))
        else:
            msg = f"{'Would mark' if dry_run else 'Marked'} {missing} file(s) as missing."
            self.stdout.write(self.style.WARNING(msg))
            if dry_run:
                for key in failures:
                    self.stdout.write(f"[dry-run] missing: {key}")

        summary = (
            f"{'Would update' if dry_run else 'Updated'} "
            f"{updated_checksums} checksum(s)."
        )
        self.stdout.write(self.style.SUCCESS(summary))


def _stream_hash(client, bucket: str, key: str, algorithm: str) -> str:
    """Download an object and return the hex digest for the requested algorithm."""
    try:
        response = client.get_object(Bucket=bucket, Key=key)
    except Exception:  # noqa: BLE001
        return ""

    body = response.get("Body")
    if body is None:
        return ""

    try:
        hasher = hashlib.new(algorithm)
    except ValueError:
        return ""

    while True:
        chunk = body.read(8192)
        if not chunk:
            break
        hasher.update(chunk)
    return hasher.hexdigest()
