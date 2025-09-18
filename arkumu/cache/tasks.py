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


@db_task()
def warm_cross_institutional_projects_cache():
    """Warm the cross-institutional projects cache for fast catalog searches."""
    from arkumu.cache.services.graph_cache_service import GraphCacheService

    try:
        logger.info("Starting cross-institutional projects cache warming...")

        # Use the new atomic refresh method
        graph_cache = GraphCacheService()
        result = graph_cache.refresh_cross_institutional_projects_cache()

        if result and result.get('projects'):
            project_count = len(result['projects'])
            logger.info(f"Cross-institutional projects cache warmed: {project_count} projects")
            return f"Success: {project_count} projects cached"

        logger.error("Failed to warm projects cache - no project data returned")
        return "Failed: No data returned"

    except Exception as e:
        logger.error(f"Failed to warm cross-institutional projects cache: {e}")
        raise


if HUEY_PERIODIC_AVAILABLE:
    @db_periodic_task(crontab(minute='*/30'))  # Run every 30 minutes
    def refresh_schema_cache_periodic():
        """Periodically refresh the schema map cache."""
        try:
            logger.info("Running periodic schema cache refresh...")
            from arkumu.cache.services import SchemaMapCacheService

            schema_cache = SchemaMapCacheService()

            schema_map = schema_cache.refresh_cache()
            logger.info(
                f"Periodic cache refresh completed: {schema_map['meta']['total_classes']} classes, "
                f"{schema_map['meta']['total_properties']} properties"
            )

        except Exception as e:
            logger.error(f"Periodic schema cache refresh failed: {e}")
            # Don't re-raise to avoid task retry loops

    @db_periodic_task(crontab(minute='*/60'))  # Run every 60 minutes
    def refresh_projects_cache_periodic():
        """Periodically refresh the cross-institutional projects cache."""
        try:
            logger.info("Running periodic projects cache refresh...")
            from arkumu.cache.services.graph_cache_service import GraphCacheService

            graph_cache = GraphCacheService()
            result = graph_cache.refresh_cross_institutional_projects_cache()

            if result and result.get('projects'):
                project_count = len(result['projects'])
                edge_count = (
                    result.get('counts', {}).get('edges')
                    if isinstance(result.get('counts'), dict)
                    else 'unknown'
                )
                logger.info(
                    f"Periodic projects cache refresh completed: {project_count} projects, "
                    f"{edge_count} edges"
                )
            else:
                logger.warning("Periodic projects cache refresh returned no project data")

        except Exception as e:
            logger.error(f"Periodic projects cache refresh failed: {e}")
            # Don't re-raise to avoid task retry loops
