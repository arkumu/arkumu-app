from django.core.management.base import BaseCommand

from arkumu.catalog.services.project_index_db_service import ProjectIndexDbService


class Command(BaseCommand):
    help = "Rebuild derived project index tables for cards and full records."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--project-uri",
            action="append",
            dest="project_uris",
            help="Limit rebuild to specific project URI (repeatable).",
        )
        parser.add_argument(
            "--force-snapshot",
            action="store_true",
            dest="force_snapshot",
            help="Force snapshot rebuild before projection.",
        )

    def handle(self, *args, **options):
        service = ProjectIndexDbService()
        result = service.rebuild(
            project_uris=options.get("project_uris") or None,
            force_snapshot=bool(options.get("force_snapshot")),
        )

        self.stdout.write(
            self.style.SUCCESS(
                f"Rebuilt project index: cards={result.get('projects_index', 0)}, "
                f"records={result.get('project_records', 0)}",
            )
        )
