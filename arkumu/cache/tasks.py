"""Cache Tasks

Huey background tasks for cache management and warming.
"""

import logging
from typing import Optional

from django.conf import settings
from django.core.cache import cache
from huey import crontab
from huey.contrib.djhuey import db_task, periodic_task

# Periodic tasks are always available in djhuey
HUEY_PERIODIC_AVAILABLE = True

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


_PROJECT_WARM_LOCK_KEY = "arkumu:cache:projects:warming"
_PROJECT_WARM_TIMEOUT = 60 * 5  # 5 minutes safety window


def _warm_projects_cache(*, force_refresh: bool) -> str:
    from arkumu.projects.services import ProjectSnapshotService

    if not cache.add(_PROJECT_WARM_LOCK_KEY, 1, timeout=_PROJECT_WARM_TIMEOUT):
        logger.info("Cross-institutional projects cache warm-up skipped (already in progress)")
        return "Skipped: already warming"

    try:
        logger.info(
            "Starting cross-institutional projects cache warming%s...",
            " (forced refresh)" if force_refresh else "",
        )
        snapshot_service = ProjectSnapshotService()
        snapshot = snapshot_service.get_cross_institutional_snapshot(force_refresh=force_refresh)
        project_count = len(snapshot.projects)
        logger.info("Cross-institutional projects cache warmed: %d projects", project_count)
        return f"Success: {project_count} projects cached"
    except Exception as exc:
        logger.error("Failed to warm cross-institutional projects cache: %s", exc)
        raise
    finally:
        cache.delete(_PROJECT_WARM_LOCK_KEY)


@db_task()
def warm_cross_institutional_projects_cache(force_refresh: bool = False):
    """Warm the cross-institutional projects cache for fast catalog searches."""
    return _warm_projects_cache(force_refresh=force_refresh)


@db_task()
def warm_card_schema_cache(organization_code: Optional[str] = None):
    """Warm the built card schema cache for catalog views."""
    from arkumu.catalog.services.schema_manifest_service import SchemaManifestService
    from arkumu.metadata.models import Mapping

    target_orgs = [organization_code] if organization_code else _DEFAULT_CARD_SCHEMA_ORGS
    if not target_orgs:
        logger.info("Card schema cache warm-up skipped: no target organizations configured")
        return "No schemas warmed"

    existing_orgs = set(
        Mapping.objects
        .filter(organization_id__in=target_orgs)
        .values_list('organization_id', flat=True)
    )

    service = SchemaManifestService()
    warmed = 0

    for org in target_orgs:
        if org not in existing_orgs:
            logger.info(
                "Card schema warm-up skipped for org '%s': no mapping configuration found",
                org,
            )
            continue
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
    @periodic_task(crontab(minute='*/30'))  # Run every 30 minutes
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

    @periodic_task(crontab(minute='*/20'))  # Run every 20 minutes to stay ahead of the 60m TTL
    def refresh_projects_cache_periodic():
        """Periodically refresh the cross-institutional projects cache."""
        try:
            logger.info("Running periodic projects cache refresh...")
            _warm_projects_cache(force_refresh=True)
        except Exception as e:
            logger.error(f"Periodic projects cache refresh failed: {e}")
            # Don't re-raise to avoid task retry loops

    @periodic_task(crontab(minute='*/10'))  # Run every 10 minutes to align with card schema TTL
    def refresh_card_schema_cache_periodic():
        """Periodically refresh built card schema caches."""
        try:
            logger.info("Running periodic card schema cache refresh...")
            warm_card_schema_cache()
        except Exception as e:
            logger.error(f"Periodic card schema cache refresh failed: {e}")
