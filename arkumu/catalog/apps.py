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

        # Run in thread to avoid async context issues with ASGI
        threading.Thread(target=_warm_wikidata_cache, daemon=True).start()

        # Rebuild index if empty (skip for management commands like migrate)
        if 'migrate' not in sys.argv and 'makemigrations' not in sys.argv:
            threading.Thread(target=_rebuild_index_if_empty, daemon=True).start()

        # Warm card cache asynchronously
        try:
            from arkumu.catalog.services.project_card_search_service import ProjectCardSearchService

            service = ProjectCardSearchService()
            service.preload_cache_async()
        except Exception:
            logger.exception("CatalogConfig: failed to schedule card cache preload")
