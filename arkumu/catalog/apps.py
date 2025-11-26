from django.apps import AppConfig
import logging
import threading


logger = logging.getLogger(__name__)


class CatalogConfig(AppConfig):
    name = "arkumu.catalog"

    def ready(self):
        """Warm caches on startup."""

        def _warm_wikidata_cache():
            try:
                from arkumu.catalog.services.wikidata_service import WikidataService
                WikidataService.warm_cache_from_db()
            except Exception:
                logger.exception("CatalogConfig: failed to warm Wikidata cache from DB")

        # Run in thread to avoid async context issues with ASGI
        threading.Thread(target=_warm_wikidata_cache, daemon=True).start()

        # Warm card cache asynchronously
        try:
            from arkumu.catalog.services.project_card_search_service import ProjectCardSearchService

            service = ProjectCardSearchService()
            service.preload_cache_async()
        except Exception:
            logger.exception("CatalogConfig: failed to schedule card cache preload")
