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
            "--org",
            dest="org_code",
            help="Limit rebuild to specific organization code (e.g., 'fuk', 'khm').",
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
            default="graph",
            help="Data source: 'graph' (default, uses graph_service) or 'snapshot'.",
        )

    def handle(self, *args, **options):
        backend = options.get("backend", "graph")
        project_uris = options.get("project_uris") or None
        org_code = options.get("org_code")

        service = ProjectIndexDbService()
        start = time.perf_counter()

        if backend == "graph":
            if org_code:
                self.stdout.write(f"Rebuilding from graph_service for org={org_code}...")
                result = service._rebuild_streaming(
                    org_codes=[org_code],
                    prune_missing=False,  # Don't delete other orgs' indices
                )
            else:
                self.stdout.write("Rebuilding from graph_service...")
                result = service.rebuild(
                    project_uris=project_uris,
                    use_graph_service=True,
                )
        else:
            self.stdout.write("Rebuilding from snapshot...")
            result = service.rebuild(
                project_uris=project_uris,
                use_graph_service=False,
                force_snapshot=bool(options.get("force_snapshot")),
            )

        elapsed = time.perf_counter() - start

        # Invalidate and re-warm the in-memory cards cache
        from arkumu.catalog.services.project_index_service import invalidate_cards_cache, warm_cards_cache
        invalidate_cards_cache()
        warm_cards_cache()

        self.stdout.write(
            self.style.SUCCESS(
                f"Rebuilt project index ({backend}): index={result.get('project_index', 0)} in {elapsed:.2f}s",
            )
        )
