from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Iterable, List, Sequence, Tuple

from django.core.management.base import BaseCommand, CommandError

from arkumu.storage.models import S3FileObject

try:
    import boto3  # type: ignore
    from botocore.exceptions import ClientError  # type: ignore
except Exception:  # noqa: BLE001
    boto3 = None  # type: ignore[assignment]
    ClientError = Exception  # type: ignore


class Command(BaseCommand):
    help = (
        "Dump a catalogue of S3 objects (bucket/key pairs) to a file for later processing. "
        "Provide explicit buckets with --bucket, or let the command infer them from upload sessions."
    )

    def add_arguments(self, parser) -> None:  # type: ignore[override]
        parser.add_argument(
            "--bucket",
            dest="buckets",
            action="append",
            help="Bucket to include in the dump (repeatable). If omitted, session.s3_bucket values are used.",
        )
        parser.add_argument(
            "--output",
            required=True,
            help="Destination file path for the dump.",
        )
        parser.add_argument(
            "--format",
            choices=("json", "csv"),
            default="json",
            help="Output format (json or csv). Default: json.",
        )

    def handle(self, *args, **options) -> None:  # type: ignore[override]
        output_path = Path(options["output"])
        output_format = options["format"]
        buckets: List[str] | None = options.get("buckets")

        bucket_list = list(buckets or self._infer_buckets())
        if not bucket_list:
            raise CommandError("No buckets specified or inferred.")

        entries = self._collect_inventory(bucket_list)
        if not entries:
            raise CommandError("No objects found in the selected buckets.")

        if output_format == "json":
            self._write_json(output_path, entries)
        else:
            self._write_csv(output_path, entries)

        self.stdout.write(
            self.style.SUCCESS(
                f"Wrote {len(entries)} object(s) from {len(bucket_list)} bucket(s) to {output_path}"
            )
        )

    def _collect_inventory(self, buckets: Sequence[str]) -> List[Tuple[str, str]]:
        if boto3 is None:
            raise CommandError("boto3 is required for this command. Install boto3 or supply a manual catalogue.")

        client = boto3.client("s3")  # type: ignore[call-arg]
        entries: List[Tuple[str, str]] = []

        for bucket in buckets:
            paginator = client.get_paginator("list_objects_v2")
            try:
                for page in paginator.paginate(Bucket=bucket):
                    for obj in page.get("Contents", []):
                        key = obj.get("Key")
                        if not key:
                            continue
                        entries.append((bucket, key))
            except ClientError as exc:  # type: ignore
                raise CommandError(f"Failed to list objects for bucket '{bucket}': {exc}") from exc

        return entries

    def _infer_buckets(self) -> Iterable[str]:
        queryset = (
            S3FileObject.objects.exclude(session__s3_bucket__isnull=True)
            .exclude(session__s3_bucket__exact="")
            .values_list("session__s3_bucket", flat=True)
            .distinct()
        )
        buckets = [value.strip() for value in queryset if value and value.strip()]
        return sorted(set(buckets))

    def _write_json(self, path: Path, entries: Sequence[Tuple[str, str]]) -> None:
        data = {"items": [{"bucket": bucket, "key": key} for bucket, key in entries]}
        path.write_text(json.dumps(data, indent=2))

    def _write_csv(self, path: Path, entries: Sequence[Tuple[str, str]]) -> None:
        with path.open("w", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["bucket", "key"])
            writer.writerows(entries)

