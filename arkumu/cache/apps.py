import logging
import sys
from django.apps import AppConfig
from django.conf import settings

logger = logging.getLogger(__name__)


class CacheConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'arkumu.cache'
    verbose_name = 'Centralized Cache Service'

    def ready(self):
        """Clear all caches and warm critical caches on application startup."""
        # Clear caches only in development for fresh FK logic
        if settings.DEBUG and getattr(settings, 'CLEAR_CACHE_ON_STARTUP', False):
            try:
                from arkumu.cache.services import CacheManager
                logger.info("Clearing all caches on startup (development mode)...")
                cache_manager = CacheManager()

                # Clear all cache services
                cache_manager.graph.clear_cache()
                cache_manager.catalog.clear_cache()
                cache_manager.oai.clear_cache()

                logger.info("All caches cleared successfully on startup")
            except Exception as e:
                logger.warning(f"Failed to clear caches on startup: {e}")

        # Only warm cache in production or when explicitly enabled
        warm_schema = getattr(settings, 'WARM_CACHE_ON_STARTUP', False) or not settings.DEBUG
        warm_projects = getattr(settings, 'WARM_CROSS_INSTITUTIONAL_CACHE_ON_STARTUP', True)  # Enable by default

        if warm_schema:
            try:
                # Import here to avoid circular imports during app loading
                from arkumu.cache.services import SchemaMapCacheService

                logger.info("Warming schema map cache on startup...")
                schema_cache = SchemaMapCacheService()

                # Warm only the global cache for fast startup
                schema_map = schema_cache.get_complete_schema_map(include_properties=True)
                logger.info(
                    f"Schema cache warmed: {schema_map['meta']['total_classes']} classes, "
                    f"{schema_map['meta']['total_properties']} properties"
                )

            except Exception as e:
                # Don't fail startup if cache warming fails
                logger.warning(f"Failed to warm schema cache on startup: {e}")
        else:
            logger.debug("Cache warming disabled in DEBUG mode")

        if warm_projects and 'run_huey' not in sys.argv:
            try:
                from arkumu.cache.tasks import warm_cross_institutional_projects_cache

                logger.info("Scheduling cross-institutional projects cache warming...")
                warm_cross_institutional_projects_cache.schedule()
            except Exception as e:
                logger.warning(f"Failed to schedule projects cache warm-up: {e}")
