from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path
from typing import Dict, Iterable, List, Sequence, Tuple

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from arkumu.storage.models import S3FileObject

try:
    import boto3  # type: ignore
    from botocore.exceptions import ClientError  # type: ignore
except Exception:  # noqa: BLE001
    boto3 = None  # type: ignore[assignment]
    ClientError = Exception  # type: ignore


class Command(BaseCommand):
    help = (
        "Collect an S3 inventory (bucket/key pairs) once, optionally dump it to disk, "
        "and use it to reconcile S3FileObject rows. Keys found in exactly one bucket "
        "are marked verified and assigned that bucket. Keys missing from all buckets "
        "are marked failed. Keys found in multiple buckets are reported for manual review."
    )

    def add_arguments(self, parser) -> None:  # type: ignore[override]
        parser.add_argument(
            "--bucket",
            dest="buckets",
            action="append",
            help="Bucket to include in the inventory (repeatable). "
            "If omitted, distinct session.s3_bucket values are used.",
        )
        parser.add_argument(
            "--prefix",
            dest="prefixes",
            action="append",
            help="Optional key prefix filter (repeatable). Only objects starting with these prefixes are considered.",
        )
        parser.add_argument(
            "--output",
            help="Optional path to write the gathered inventory (json or csv, see --format).",
        )
        parser.add_argument(
            "--format",
            choices=("json", "csv"),
            default="json",
            help="When --output is provided, choose json or csv (default: json).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Collect the inventory and show the reconciliation summary without writing database changes.",
        )
        parser.add_argument(
            "--sample",
            type=int,
            default=20,
            help="Number of sample rows to display per discrepancy category (default: 20).",
        )

    def handle(self, *args, **options) -> None:  # type: ignore[override]
        buckets: List[str] | None = options.get("buckets")
        prefixes: List[str] | None = options.get("prefixes")
        output_path = options.get("output")
        output_format = options.get("format", "json")
        dry_run: bool = options.get("dry_run", False)
        sample_size: int = options.get("sample", 20)

        bucket_list = list(buckets or self._infer_buckets())
        if not bucket_list:
            raise CommandError("No buckets specified or inferred.")

        inventory = self._collect_inventory(bucket_list, prefixes or [])
        if not inventory:
            self.stdout.write(self.style.WARNING("Inventory is empty; nothing to reconcile."))
            return

        if output_path:
            path = Path(output_path)
            if output_format == "json":
                self._write_json(path, inventory)
            else:
                self._write_csv(path, inventory)
            self.stdout.write(
                self.style.SUCCESS(
                    f"Inventory written to {path} ({len(inventory)} object(s) across {len(bucket_list)} bucket(s))."
                )
            )

        summary = self._reconcile_with_database(inventory, prefixes or [], dry_run=dry_run)
        self._print_summary(summary, sample_size, dry_run=dry_run)

    # ---------------- Inventory helpers ---------------- #

    def _collect_inventory(
        self,
        buckets: Sequence[str],
        prefixes: Sequence[str],
    ) -> List[Tuple[str, str]]:
        if boto3 is None:
            raise CommandError("boto3 is required to collect inventory. Install boto3 and configure credentials.")

        client = boto3.client("s3")  # type: ignore[call-arg]
        entries: List[Tuple[str, str]] = []
        seen = set()

        prefix_list = prefixes or [None]

        for bucket in buckets:
            paginator = client.get_paginator("list_objects_v2")
            for prefix in prefix_list:
                try:
                    kwargs = {"Bucket": bucket}
                    if prefix:
                        kwargs["Prefix"] = prefix
                    for page in paginator.paginate(**kwargs):
                        for obj in page.get("Contents", []):
                            key = obj.get("Key")
                            if not key:
                                continue
                            identifier = (bucket, key)
                            if identifier in seen:
                                continue
                            seen.add(identifier)
                            entries.append(identifier)
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
        payload = {"items": [{"bucket": bucket, "key": key} for bucket, key in entries]}
        path.write_text(json.dumps(payload, indent=2))

    def _write_csv(self, path: Path, entries: Sequence[Tuple[str, str]]) -> None:
        with path.open("w", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["bucket", "key"])
            writer.writerows(entries)

    # ---------------- Reconciliation ---------------- #

    def _reconcile_with_database(
        self,
        inventory: Sequence[Tuple[str, str]],
        prefixes: Sequence[str],
        *,
        dry_run: bool,
    ) -> Dict[str, object]:
        key_to_buckets: Dict[str, List[str]] = defaultdict(list)
        for bucket, key in inventory:
            key_to_buckets[key].append(bucket)

        queryset = S3FileObject.objects.select_related("session").all()
        if prefixes:
            filtered = None
            for prefix in prefixes:
                filtered = (filtered | S3FileObject.objects.filter(s3_key__startswith=prefix)) if filtered else S3FileObject.objects.filter(s3_key__startswith=prefix)
            queryset = queryset.filter(pk__in=filtered.values("pk"))

        total = queryset.count()
        db_keys = set()
        verified = 0
        failed = 0
        skipped = 0
        ambiguous_entries: List[Tuple[str, str, List[str]]] = []
        missing_entries: List[Tuple[str, str]] = []

        for obj in queryset.iterator():
            key = (obj.s3_key or "").strip()
            if not key:
                continue
            db_keys.add(key)

            candidate_buckets = key_to_buckets.get(key, [])

            if not candidate_buckets:
                failed += 1
                missing_entries.append((str(obj.pk), key))
                if dry_run:
                    continue
                obj.status = "failed"
                obj.error_message = "File absent from S3 inventory"
                with transaction.atomic():
                    obj.save(update_fields=["status", "error_message", "updated_at"])
                continue

            unique_candidates = list(dict.fromkeys(candidate_buckets))
            if len(unique_candidates) > 1:
                skipped += 1
                ambiguous_entries.append((str(obj.pk), key, unique_candidates))
                continue

            bucket = unique_candidates[0]
            verified += 1
            if dry_run:
                continue

            obj.status = "verified"
            obj.organization = bucket
            if obj.error_message:
                obj.error_message = ""
            with transaction.atomic():
                obj.save(update_fields=["status", "organization", "error_message", "updated_at"])

        untracked_objects = [
            (bucket, key) for bucket, key in inventory if key not in db_keys
        ]

        return {
            "total": total,
            "verified": verified,
            "failed": failed,
            "skipped": skipped,
            "ambiguous": ambiguous_entries,
            "missing": missing_entries,
            "orphan_inventory": untracked_objects,
        }

    def _print_summary(
        self,
        summary: Dict[str, object],
        sample_size: int,
        *,
        dry_run: bool,
    ) -> None:
        total = summary["total"]
        verified = summary["verified"]
        failed = summary["failed"]
        skipped = summary["skipped"]
        ambiguous_entries = summary["ambiguous"]
        missing_entries = summary["missing"]
        untracked_objects = summary["orphan_inventory"]

        action = "Would mark" if dry_run else "Marked"

        self.stdout.write(self.style.SUCCESS(f"S3FileObject rows examined: {total}"))
        self.stdout.write(f"{action} {verified} row(s) as verified.")
        self.stdout.write(f"{action} {failed} row(s) as failed (missing).")
        self.stdout.write(f"Skipped {skipped} row(s) due to ambiguous buckets.")
        self.stdout.write(f"S3 objects without DB entries: {len(untracked_objects)}")

        if missing_entries:
            self.stdout.write("")
            self.stdout.write(
                self.style.WARNING(
                    f"Sample rows marked missing (up to {sample_size}):"
                )
            )
            for pk, key in missing_entries[:sample_size]:
                self.stdout.write(f"    {pk}: {key}")

        if ambiguous_entries:
            self.stdout.write("")
            self.stdout.write(
                self.style.WARNING(
                    f"Sample ambiguous rows (up to {sample_size}):"
                )
            )
            for pk, key, buckets in ambiguous_entries[:sample_size]:
                self.stdout.write(f"    {pk}: {key} -> buckets={', '.join(buckets)}")

        if untracked_objects:
            self.stdout.write("")
            self.stdout.write(
                self.style.WARNING(
                    f"Sample S3 objects without a database entry (up to {sample_size}):"
                )
            )
            for bucket, key in untracked_objects[:sample_size]:
                self.stdout.write(f"    {bucket}: {key}")
