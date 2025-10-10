from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q

from arkumu.storage.models import S3FileObject


class Command(BaseCommand):
    help = (
        "Set the organization code on S3FileObject rows based on their bucket/prefix. "
        "Useful for legacy uploads that were created without organization metadata."
    )

    def add_arguments(self, parser) -> None:  # type: ignore[override]
        parser.add_argument(
            "--organization",
            required=True,
            help="Organization code to assign (e.g. 'det').",
        )
        parser.add_argument(
            "--prefix",
            default="",
            help="Only update rows whose s3_key starts with this prefix.",
        )
        parser.add_argument(
            "--include-existing",
            action="store_true",
            help="Update rows even if an organization is already set.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would change without updating the database.",
        )

    def handle(self, *args, **options) -> None:  # type: ignore[override]
        organization: str = options["organization"].strip()
        prefix: str = options["prefix"].strip()
        include_existing: bool = options["include_existing"]
        dry_run: bool = options["dry_run"]

        if not organization:
            raise CommandError("Organization code cannot be empty.")

        queryset = S3FileObject.objects.all()
        if prefix:
            queryset = queryset.filter(s3_key__startswith=prefix)

        if not include_existing:
            queryset = queryset.filter(Q(organization="") | Q(organization__isnull=True))

        total = queryset.count()
        if total == 0:
            self.stdout.write(self.style.SUCCESS("No S3FileObject rows matched the criteria."))
            return

        action = "Dry-run: would update" if dry_run else "Updating"
        self.stdout.write(f"{action} {total} S3FileObject row(s) to organization '{organization.lower()}'.")

        if dry_run:
            return

        with transaction.atomic():
            updated = queryset.update(organization=organization.lower())

        self.stdout.write(self.style.SUCCESS(f"Updated {updated} row(s)."))
