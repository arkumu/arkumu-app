from django.apps import AppConfig
import logging
import sys
import threading


logger = logging.getLogger(__name__)


class CatalogConfig(AppConfig):
    name = "arkumu.catalog"

    def ready(self):
        """Warm caches and rebuild index if empty on startup."""

        def _warm_wikidata_cache():
            try:
                from arkumu.catalog.services.wikidata_service import WikidataService
                WikidataService.warm_cache_from_db()
            except Exception:
                logger.exception("CatalogConfig: failed to warm Wikidata cache from DB")

        def _rebuild_index_if_empty():
            """Rebuild project index tables if they are empty."""
            try:
                import time
                time.sleep(2)  # Wait for DB to be ready
                from arkumu.catalog.models import ProjectIndex, ProjectDetailIndex
                from arkumu.catalog.services.project_index_db_service import ProjectIndexDbService

                index_count = ProjectIndex.objects.count()
                detail_count = ProjectDetailIndex.objects.count()

                if index_count == 0 or detail_count == 0:
                    logger.info(
                        "CatalogConfig: project index tables empty (index=%d, detail=%d), rebuilding...",
                        index_count, detail_count
                    )
                    service = ProjectIndexDbService()
                    result = service.rebuild_from_graph()
                    logger.info(
                        "CatalogConfig: rebuilt project index: cards=%d, records=%d",
                        result.get('projects_index', 0),
                        result.get('project_records', 0),
                    )
                else:
                    logger.info(
                        "CatalogConfig: project index tables populated (index=%d, detail=%d)",
                        index_count, detail_count
                    )
            except Exception:
                logger.exception("CatalogConfig: failed to rebuild project index")

        # Skip heavy initialization for management commands and Huey workers
        skip_commands = ('migrate', 'makemigrations', 'run_huey', 'collectstatic')
        is_management_cmd = any(cmd in sys.argv for cmd in skip_commands)

        # Warm Wikidata cache (skip for management commands when tables may not exist)
        if not is_management_cmd:
            threading.Thread(target=_warm_wikidata_cache, daemon=True).start()

        # Rebuild index if empty (skip for management commands and Huey)
        if not is_management_cmd:
            threading.Thread(target=_rebuild_index_if_empty, daemon=True).start()

        # Warm in-memory cards cache at startup (skip for management commands)
        if not is_management_cmd:
            def _warm_cards():
                try:
                    import time
                    time.sleep(3)  # Wait for DB and index to be ready
                    from arkumu.catalog.services.project_index_service import warm_cards_cache
                    warm_cards_cache()
                except Exception:
                    logger.exception("CatalogConfig: failed to warm cards cache")

            threading.Thread(target=_warm_cards, daemon=True).start()
