"""
Cache Tasks

Huey background tasks for cache management and warming.
"""

import logging
from huey.contrib.djhuey import db_task

try:
    from huey.contrib.djhuey import db_periodic_task, crontab
    HUEY_PERIODIC_AVAILABLE = True
except ImportError:
    HUEY_PERIODIC_AVAILABLE = False

logger = logging.getLogger(__name__)


@db_task()
def warm_schema_cache():
    """Warm the schema map cache manually."""
    from arkumu.cache.services import SchemaMapCacheService

    try:
        logger.info("Starting schema cache warming task...")
        schema_cache = SchemaMapCacheService()

        # Warm the global cache
        schema_map = schema_cache.get_complete_schema_map()
        logger.info(
            f"Schema cache warmed: {schema_map['meta']['total_classes']} classes, "
            f"{schema_map['meta']['total_properties']} properties"
        )
        return f"Success: {schema_map['meta']['total_classes']} classes cached"

    except Exception as e:
        logger.error(f"Failed to warm schema cache: {e}")
        raise


if HUEY_PERIODIC_AVAILABLE:
    @db_periodic_task(crontab(minute='*/30'))  # Run every 30 minutes
    def refresh_schema_cache_periodic():
        """Periodically refresh the schema map cache."""
        try:
            logger.info("Running periodic schema cache refresh...")
            from arkumu.cache.services import SchemaMapCacheService

            schema_cache = SchemaMapCacheService()

            # Invalidate existing cache to force fresh build
            schema_cache.invalidate_schema_cache()

            # Rebuild cache
            schema_map = schema_cache.get_complete_schema_map()
            logger.info(
                f"Periodic cache refresh completed: {schema_map['meta']['total_classes']} classes, "
                f"{schema_map['meta']['total_properties']} properties"
            )

        except Exception as e:
            logger.error(f"Periodic schema cache refresh failed: {e}")
            # Don't re-raise to avoid task retry loops