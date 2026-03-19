import asyncio
import logging
import sys
import threading
from django.apps import AppConfig
from django.conf import settings

from arkumu.common.startup import should_skip_startup_warmup

logger = logging.getLogger(__name__)


class CacheConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'arkumu.cache'
    verbose_name = 'Centralized Cache Service'

    def ready(self):
        """Clear all caches and warm critical caches on application startup."""

        def _call_threadsafe(func, *args, **kwargs):
            """Run sync functions safely whether or not an event loop is active."""
            try:
                asyncio.get_running_loop()
            except RuntimeError:
                return func(*args, **kwargs)

            result_holder = {}
            exception_holder = {}

            def runner():
                try:
                    result_holder['value'] = func(*args, **kwargs)
                except Exception as exc:  # pragma: no cover - defensive path
                    exception_holder['error'] = exc

            thread = threading.Thread(target=runner, daemon=True)
            thread.start()
            thread.join()

            if exception_holder:
                raise exception_holder['error']

            return result_holder.get('value')
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

        if should_skip_startup_warmup(sys.argv):
            logger.debug("Cache warming skipped for startup command: %s", " ".join(sys.argv))
            return

        # Only warm cache in production or when explicitly enabled
        warm_schema = getattr(settings, 'WARM_CACHE_ON_STARTUP', False) or not settings.DEBUG
        warm_projects = getattr(settings, 'WARM_CROSS_INSTITUTIONAL_CACHE_ON_STARTUP', True)  # Enable by default

        if getattr(settings, 'OAI_SKIP_CACHE_WARMUP', False):
            warm_schema = False
            warm_projects = False
            logger.debug("Cache warm-up skipped due to OAI_SKIP_CACHE_WARMUP flag")

        if warm_schema:
            def _warm_schema_async():
                try:
                    import time
                    time.sleep(2)  # Wait for DB to be ready
                    from arkumu.cache.services import SchemaMapCacheService
                    from arkumu.catalog.services.schema_manifest_service import SchemaManifestService

                    logger.info("Warming schema map cache on startup...")
                    schema_cache = SchemaMapCacheService()

                    schema_map = schema_cache.get_complete_schema_map(include_properties=True)
                    logger.info(
                        f"Schema cache warmed: {schema_map['meta']['total_classes']} classes, "
                        f"{schema_map['meta']['total_properties']} properties"
                    )

                    card_schema_orgs = getattr(settings, 'CACHE_CARD_SCHEMA_ORGS', ['fuk'])
                    schema_service = SchemaManifestService()

                    for org_code in card_schema_orgs:
                        try:
                            logger.info("Warming card schema cache for org '%s' on startup", org_code)
                            schema_service.get_card_schema(org_code)
                        except Exception as inner_exc:
                            logger.warning(
                                "Failed to warm card schema cache for org '%s': %s",
                                org_code,
                                inner_exc,
                            )
                except Exception as e:
                    logger.warning(f"Failed to warm schema cache on startup: {e}")

            threading.Thread(target=_warm_schema_async, daemon=True).start()
        else:
            logger.debug("Cache warming disabled in DEBUG mode")

        if warm_schema or warm_projects:
            try:
                from arkumu.cache.tasks import (
                    warm_card_schema_cache,
                    warm_cross_institutional_projects_cache,
                )

                if warm_projects:
                    logger.info("Scheduling cross-institutional projects cache warming...")
                    warm_cross_institutional_projects_cache.schedule(delay=5)

                if warm_schema:
                    logger.info("Scheduling card schema cache warming...")
                    warm_card_schema_cache.schedule(delay=3)
            except Exception as e:
                logger.warning(f"Failed to schedule cache warm-up tasks: {e}")
