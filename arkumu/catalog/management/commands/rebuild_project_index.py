import time

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
            help="Force snapshot rebuild before projection (snapshot backend only).",
        )
        parser.add_argument(
            "--backend",
            choices=["snapshot", "graph"],
            default="snapshot",
            help="Data source: 'snapshot' (default) or 'graph' (canonical graph, faster).",
        )

    def handle(self, *args, **options):
        backend = options.get("backend", "snapshot")
        project_uris = options.get("project_uris") or None

        service = ProjectIndexDbService()
        start = time.perf_counter()

        if backend == "graph":
            self.stdout.write("Rebuilding from canonical graph...")
            result = service.rebuild_from_graph(project_uris=project_uris)
        else:
            self.stdout.write("Rebuilding from snapshot...")
            result = service.rebuild(
                project_uris=project_uris,
                force_snapshot=bool(options.get("force_snapshot")),
            )

        elapsed = time.perf_counter() - start

        self.stdout.write(
            self.style.SUCCESS(
                f"Rebuilt project index ({backend}): index={result.get('project_index', 0)} in {elapsed:.2f}s",
            )
        )
