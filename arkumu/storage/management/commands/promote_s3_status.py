from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from arkumu.storage.models import S3FileObject


VALID_STATUSES = {"pending", "uploading", "completed", "failed", "verified"}


class Command(BaseCommand):
    help = (
        "Bulk promote S3FileObject rows into a target status. "
        "Defaults to moving pending/uploading/completed items into 'verified'."
    )

    def add_arguments(self, parser) -> None:  # type: ignore[override]
        parser.add_argument(
            "--organization",
            dest="organizations",
            action="append",
            help="Only update rows matching this organization code (repeatable).",
        )
        parser.add_argument(
            "--include-status",
            dest="include_statuses",
            action="append",
            help="Source status to include (repeatable). Defaults to pending, uploading, completed.",
        )
        parser.add_argument(
            "--target-status",
            dest="target_status",
            default="verified",
            help="Status to assign after promotion (default: verified).",
        )
        parser.add_argument(
            "--limit",
            type=int,
            help="Maximum number of rows to update (ordered by created_at).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would change without updating the database.",
        )

    def handle(self, *args, **options) -> None:  # type: ignore[override]
        organizations: list[str] | None = options.get("organizations")
        include_statuses: list[str] | None = options.get("include_statuses")
        target_status: str = (options.get("target_status") or "verified").strip().lower()
        limit: int | None = options.get("limit")
        dry_run: bool = options.get("dry_run", False)

        if target_status not in VALID_STATUSES:
            raise CommandError(f"Invalid target status '{target_status}'. Valid options: {sorted(VALID_STATUSES)}")

        if include_statuses:
            source_statuses = {status.strip().lower() for status in include_statuses if status}
        else:
            source_statuses = {"pending", "uploading", "completed"}

        invalid_sources = source_statuses - VALID_STATUSES
        if invalid_sources:
            raise CommandError(f"Invalid include-status value(s): {sorted(invalid_sources)}")

        queryset = S3FileObject.objects.filter(status__in=source_statuses).order_by("created_at")

        if organizations:
            normalized_orgs = [org.strip().lower() for org in organizations if org]
            queryset = queryset.filter(organization__in=normalized_orgs)

        if limit is not None:
            queryset = queryset[:limit]

        count = queryset.count()
        if count == 0:
            self.stdout.write(self.style.SUCCESS("No S3FileObject rows matched the criteria."))
            return

        action = "Dry-run: would promote" if dry_run else "Promoting"
        self.stdout.write(f"{action} {count} row(s) to '{target_status}'...")

        updated = 0
        for obj in queryset:
            if dry_run:
                self.stdout.write(f"[dry-run] {obj.id} status {obj.status} -> {target_status}")
                updated += 1
                continue

            with transaction.atomic():
                obj.status = target_status
                obj.save(update_fields=["status", "updated_at"])
                updated += 1

        suffix = " (dry-run)" if dry_run else ""
        self.stdout.write(self.style.SUCCESS(f"Updated {updated} row(s) to '{target_status}'{suffix}."))
