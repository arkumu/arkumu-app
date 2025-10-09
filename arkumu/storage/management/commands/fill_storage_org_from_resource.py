from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Q

from arkumu.storage.models import S3FileObject


class Command(BaseCommand):
    help = (
        "Copy the organization code from the linked Resource to S3FileObject rows "
        "that are missing their storage organization."
    )

    def add_arguments(self, parser) -> None:  # type: ignore[override]
        parser.add_argument(
            "--organization",
            dest="filter_org",
            help="Restrict updates to rows whose resource organization matches this code.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            help="Limit the number of rows updated (ordered by created_at).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would change without writing to the database.",
        )

    def handle(self, *args, **options) -> None:  # type: ignore[override]
        filter_org: str | None = options.get("filter_org")
        limit: int | None = options.get("limit")
        dry_run: bool = options.get("dry_run", False)

        queryset = (
            S3FileObject.objects.filter(
                Q(organization__isnull=True) | Q(organization=""),
            )
            .filter(related_resource__organization__isnull=False)
            .select_related("related_resource__organization")
            .order_by("created_at")
        )

        if filter_org:
            queryset = queryset.filter(
                related_resource__organization__code__iexact=filter_org.strip(),
            )

        if limit is not None:
            queryset = queryset[:limit]

        total = queryset.count()
        if total == 0:
            self.stdout.write(self.style.SUCCESS("No storage rows require updates."))
            return

        updated = 0
        skipped = 0

        action = "Dry-run: would update" if dry_run else "Updating"
        self.stdout.write(f"{action} {total} row(s)...")

        for obj in queryset:
            org = obj.related_resource.organization
            if not org or not org.code:
                skipped += 1
                continue

            code = org.code.strip().lower()
            if not code:
                skipped += 1
                continue

            if dry_run:
                self.stdout.write(f"[dry-run] {obj.id} -> {code}")
                updated += 1
                continue

            with transaction.atomic():
                obj.organization = code
                obj.save(update_fields=["organization", "updated_at"])
                updated += 1

        summary = f"Updated {updated} row(s)"
        if skipped:
            summary += f"; skipped {skipped} row(s) without a resource organization"
        if dry_run:
            summary += " (dry-run)"
        self.stdout.write(self.style.SUCCESS(summary))
