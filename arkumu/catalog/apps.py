from django.apps import AppConfig
import logging


logger = logging.getLogger(__name__)


class CatalogConfig(AppConfig):
    name = "arkumu.catalog"

    def ready(self):
        """Warm card cache asynchronously on startup."""
        try:
            from arkumu.catalog.services.project_card_search_service import ProjectCardSearchService

            service = ProjectCardSearchService()
            service.preload_cache_async()
        except Exception:
            logger.exception("CatalogConfig: failed to schedule card cache preload")
