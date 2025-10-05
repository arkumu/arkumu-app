"""Queue upload verification Huey tasks manually."""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from arkumu.storage.models.upload_tracking import AsyncUploadSession
from arkumu.storage.tasks import verify_upload_session


class Command(BaseCommand):
    help = (
        "Schedule the async upload verification Huey task for one or more sessions."
    )

    def add_arguments(self, parser) -> None:  # type: ignore[override]
        parser.add_argument(
            "session_ids",
            metavar="SESSION_ID",
            nargs="+",
            help="UUID(s) of AsyncUploadSession records to verify",
        )

    def handle(self, *args, **options) -> None:  # type: ignore[override]
        for session_id in options["session_ids"]:
            try:
                session = AsyncUploadSession.objects.get(id=session_id)
            except AsyncUploadSession.DoesNotExist as exc:
                raise CommandError(f"Session {session_id} does not exist") from exc

            if session.status == "processing":
                self.stdout.write(
                    self.style.WARNING(f"Session {session_id} is already processing; skipping."),
                )
                continue

            session.mark_processing()
            verify_upload_session.schedule(args=(session_id,), delay=0)
            self.stdout.write(self.style.SUCCESS(f"Queued verification for {session_id}."))

