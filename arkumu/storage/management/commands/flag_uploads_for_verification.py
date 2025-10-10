"""Promote finished async upload sessions into manual verification state."""

from __future__ import annotations

from typing import Iterable

from django.core.management.base import BaseCommand
from django.db import transaction

from arkumu.storage.models.upload_tracking import AsyncUploadSession
from arkumu.storage.tasks import trigger_ui_refresh


TERMINAL_STATES = {"uploaded", "completed", "failed"}


class Command(BaseCommand):
    help = (
        "Mark async upload sessions that finished uploading as awaiting verification"
        " so staff can trigger the verification task manually."
    )

    def add_arguments(self, parser) -> None:  # type: ignore[override]
        parser.add_argument(
            "--session",
            dest="session_ids",
            action="append",
            help="Limit to one or more specific session UUIDs.",
        )
        parser.add_argument(
            "--dry-run",
            dest="dry_run",
            action="store_true",
            help="Show what would change without persisting any updates.",
        )

    def handle(self, *args, **options) -> None:  # type: ignore[override]
        session_ids: Iterable[str] | None = options.get("session_ids")
        dry_run: bool = options.get("dry_run", False)

        sessions_qs = AsyncUploadSession.objects.filter(status="uploading")
        if session_ids:
            sessions_qs = sessions_qs.filter(id__in=session_ids)

        candidates = list(sessions_qs.select_related("user").prefetch_related("files"))

        if not candidates:
            self.stdout.write(self.style.NOTICE("No upload sessions require promotion."))
            return

        promoted = 0

        for session in candidates:
            pending_exists = session.files.exclude(status__in=TERMINAL_STATES).exists()

            if pending_exists:
                continue

            completed_count = session.files.filter(status="completed").count()
            failed_count = session.files.filter(status="failed").count()

            promoted += 1

            self.stdout.write(
                f"Promoting session {session.id} (user={session.user.username}) to awaiting_verification"
            )

            if dry_run:
                continue

            with transaction.atomic():
                session.status = "awaiting_verification"
                session.completed_files = completed_count
                session.failed_files = failed_count
                session.save(update_fields=[
                    "status",
                    "completed_files",
                    "failed_files",
                    "updated_at",
                ])

            trigger_ui_refresh.schedule(args=(str(session.id), session.organization), delay=0)

        if promoted == 0:
            self.stdout.write(self.style.NOTICE("All checked sessions still have pending files."))
        else:
            message = f"Promoted {promoted} session{'s' if promoted != 1 else ''}."
            if dry_run:
                message += " (dry-run)"
            self.stdout.write(self.style.SUCCESS(message))

