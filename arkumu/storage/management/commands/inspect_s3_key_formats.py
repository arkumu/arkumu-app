from __future__ import annotations

from collections import Counter

from django.core.management.base import BaseCommand
from django.db.models import Q

from arkumu.storage.models import S3FileObject


class Command(BaseCommand):
    help = (
        "Summarise S3FileObject key formats and highlight rows that are missing the expected "
        "'s3://bucket/key' prefix."
    )

    def add_arguments(self, parser) -> None:  # type: ignore[override]
        parser.add_argument(
            "--organization",
            dest="organization",
            help="Limit the inspection to a specific organization/bucket code.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            help="Inspect at most this many rows (ordered by -updated_at).",
        )
        parser.add_argument(
            "--samples",
            type=int,
            default=20,
            help="Number of sample rows without bucket prefixes to display (default: 20).",
        )

    def handle(self, *args, **options) -> None:  # type: ignore[override]
        organization: str | None = options.get("organization")
        limit: int | None = options.get("limit")
        sample_size: int = options.get("samples") or 20

        queryset = S3FileObject.objects.all().order_by("-updated_at")

        if organization:
            queryset = queryset.filter(
                Q(organization__iexact=organization)
                | Q(session__organization__iexact=organization)
                | Q(session__s3_bucket__iexact=organization)
            )

        total = queryset.count()
        if total == 0:
            self.stdout.write(self.style.WARNING("No S3FileObject rows matched the supplied filters."))
            return

        if limit is not None:
            queryset = queryset[:limit]

        examined = 0
        prefixed = 0
        missing_prefix = 0
        bucket_counts: Counter[str] = Counter()
        missing_samples: list[tuple[str, str, str]] = []

        for obj in queryset.iterator():
            examined += 1
            key = (obj.s3_key or "").strip()

            if key.startswith("s3://"):
                prefixed += 1
                bucket, _, _key = key[5:].partition("/")
                if bucket:
                    bucket_counts[bucket] += 1
                continue

            missing_prefix += 1
            if len(missing_samples) < sample_size:
                missing_samples.append(
                    (
                        str(obj.pk),
                        key or "<empty>",
                        obj.organization or getattr(obj.session, "organization", "") or "",
                    )
                )

        self.stdout.write(
            self.style.SUCCESS(
                f"Inspected {examined} S3 file(s) "
                f"({'limited result set' if limit is not None else 'complete query'})."
            )
        )
        self.stdout.write(f"  With full 's3://bucket/key' prefix: {prefixed}")
        self.stdout.write(f"  Without prefix: {missing_prefix}")

        if bucket_counts:
            top = ", ".join(
                f"{bucket} ({count})" for bucket, count in bucket_counts.most_common(10)
            )
            self.stdout.write(f"  Top buckets: {top}")

        if missing_samples:
            self.stdout.write("")
            self.stdout.write(
                self.style.WARNING(
                    f"Sample rows without bucket prefixes (showing up to {sample_size}):"
                )
            )
            for obj_id, key, org in missing_samples:
                org_display = org or "—"
                self.stdout.write(f"    {obj_id}: {key} (org={org_display})")

