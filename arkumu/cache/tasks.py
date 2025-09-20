"""Cache Tasks

Huey background tasks for cache management and warming.
"""

import logging
from typing import Optional

from django.conf import settings
from huey.contrib.djhuey import db_task

try:
    from huey.contrib.djhuey import db_periodic_task, crontab
    HUEY_PERIODIC_AVAILABLE = True
except ImportError:
    HUEY_PERIODIC_AVAILABLE = False

logger = logging.getLogger(__name__)


_DEFAULT_CARD_SCHEMA_ORGS = getattr(settings, 'CACHE_CARD_SCHEMA_ORGS', ['fuk'])


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
    from arkumu.projects.services import ProjectSnapshotService

    try:
        logger.info("Starting cross-institutional projects cache warming...")
        snapshot_service = ProjectSnapshotService()
        snapshot = snapshot_service.get_cross_institutional_snapshot(force_refresh=True)
        project_count = len(snapshot.projects)
        logger.info("Cross-institutional projects cache warmed: %d projects", project_count)
        return f"Success: {project_count} projects cached"

    except Exception as e:
        logger.error(f"Failed to warm cross-institutional projects cache: {e}")
        raise


@db_task()
def warm_card_schema_cache(organization_code: Optional[str] = None):
    """Warm the built card schema cache for catalog views."""
    from arkumu.catalog.services.schema_manifest_service import SchemaManifestService

    target_orgs = [organization_code] if organization_code else _DEFAULT_CARD_SCHEMA_ORGS

    service = SchemaManifestService()
    warmed = 0

    for org in target_orgs:
        try:
            logger.info("Starting card schema cache warm-up for org '%s'", org)
            schema = service.get_card_schema(org)
            available_sections = [section for section in schema.sections.values() if section.available] if schema else []
            logger.info(
                "Card schema warm-up complete for org '%s': %d total sections, %d available",
                org,
                len(schema.sections) if schema else 0,
                len(available_sections),
            )
            warmed += 1
        except Exception as exc:
            logger.error("Card schema warm-up failed for org '%s': %s", org, exc)

    return f"Warmed {warmed} schema(s)" if warmed else "No schemas warmed"


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

    @db_periodic_task(crontab(minute='*/20'))  # Run every 20 minutes to stay ahead of the 60m TTL
    def refresh_projects_cache_periodic():
        """Periodically refresh the cross-institutional projects cache."""
        try:
            logger.info("Running periodic projects cache refresh...")
            from arkumu.projects.services import ProjectSnapshotService

            snapshot_service = ProjectSnapshotService()
            snapshot = snapshot_service.get_cross_institutional_snapshot(force_refresh=True)
            project_count = len(snapshot.projects)
            edge_count = snapshot.counts.get('edges')
            logger.info(
                "Periodic projects cache refresh completed: %d projects, %s edges",
                project_count,
                edge_count,
            )

        except Exception as e:
            logger.error(f"Periodic projects cache refresh failed: {e}")
            # Don't re-raise to avoid task retry loops

    @db_periodic_task(crontab(minute='*/10'))  # Run every 10 minutes to align with card schema TTL
    def refresh_card_schema_cache_periodic():
        """Periodically refresh built card schema caches."""
        try:
            logger.info("Running periodic card schema cache refresh...")
            warm_card_schema_cache()
        except Exception as e:
            logger.error(f"Periodic card schema cache refresh failed: {e}")
