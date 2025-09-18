import logging
from django.apps import AppConfig
from django.conf import settings

logger = logging.getLogger(__name__)


class CacheConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'arkumu.cache'
    verbose_name = 'Centralized Cache Service'

    def ready(self):
        """Warm critical caches on application startup."""
        # Only warm cache in production or when explicitly enabled
        if getattr(settings, 'WARM_CACHE_ON_STARTUP', False) or not settings.DEBUG:
            try:
                # Import here to avoid circular imports during app loading
                from arkumu.cache.services import SchemaMapCacheService
                from arkumu.cache.tasks import warm_cross_institutional_projects_cache

                logger.info("Warming schema map cache on startup...")
                schema_cache = SchemaMapCacheService()

                # Warm only the global cache for fast startup
                schema_map = schema_cache.get_complete_schema_map()
                logger.info(
                    f"Schema cache warmed: {schema_map['meta']['total_classes']} classes, "
                    f"{schema_map['meta']['total_properties']} properties"
                )

                # Schedule cross-institutional projects cache warming
                logger.info("Scheduling cross-institutional projects cache warming...")
                warm_cross_institutional_projects_cache()

            except Exception as e:
                # Don't fail startup if cache warming fails
                logger.warning(f"Failed to warm schema cache on startup: {e}")
        else:
            logger.debug("Cache warming disabled in DEBUG mode")
