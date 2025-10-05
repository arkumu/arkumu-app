"""Run async upload verification synchronously without Huey."""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from arkumu.storage.models.upload_tracking import AsyncUploadSession
from arkumu.storage.tasks import verify_upload_session


class Command(BaseCommand):
    help = (
        "Execute upload verification immediately for one or more async sessions "
        "without queuing Huey tasks."
    )

    def add_arguments(self, parser) -> None:  # type: ignore[override]
        parser.add_argument(
            "session_ids",
            metavar="SESSION_ID",
            nargs="+",
            help="AsyncUploadSession UUID(s) to verify",
        )

    def handle(self, *args, **options) -> None:  # type: ignore[override]
        session_ids = options["session_ids"]

        for session_id in session_ids:
            try:
                session = AsyncUploadSession.objects.get(id=session_id)
            except AsyncUploadSession.DoesNotExist as exc:  # pragma: no cover - guard clause
                raise CommandError(f"Session {session_id} does not exist") from exc

            self.stdout.write(f"Verifying session {session_id}…")

            try:
                session.mark_processing()
                verify_upload_session(str(session.id))
            except Exception as exc:  # noqa: BLE001
                session.mark_failed(str(exc))
                raise CommandError(f"Verification failed for {session_id}: {exc}") from exc

            self.stdout.write(self.style.SUCCESS(f"Session {session_id} verified."))

