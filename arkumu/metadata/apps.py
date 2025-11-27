from django.apps import AppConfig
import logging

logger = logging.getLogger(__name__)


class MetadataConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'arkumu.metadata'

    def ready(self):
        """Import signals and perform startup tasks when the app is ready"""
        import arkumu.metadata.signals

        # Only run cleanup on server startup, not during migrations or commands
        if self._is_server_startup():
            self._cleanup_orphaned_literals()

    def _is_server_startup(self):
        """Check if this is a server startup (not migration, test, or management command)"""
        import sys

        # Skip during migrations
        if 'migrate' in sys.argv:
            return False

        # Skip during management commands (except runserver)
        if 'manage.py' in sys.argv[0]:
            if len(sys.argv) > 1 and sys.argv[1] not in ['runserver', 'runserver_plus']:
                return False

        # Skip during tests
        if 'test' in sys.argv or 'pytest' in sys.modules:
            return False

        return True

    def _cleanup_orphaned_literals(self):
        """Clean up orphaned literals on startup"""
        try:
            from django.db import connection
            from asgiref.sync import sync_to_async
            import asyncio

            # Check if we're in an async context (ASGI server like uvicorn)
            try:
                # Try to get the current event loop
                asyncio.get_running_loop()
                # We're in async context, skip cleanup to avoid the async context error
                logger.debug("Startup cleanup: Skipped in async context (ASGI server)")
                return
            except RuntimeError:
                # No running event loop, we're in sync context - proceed with cleanup
                pass

            from arkumu.metadata.models import Resource, ResourceType

            # Find orphaned literals
            orphaned_literals = Resource.objects.filter(
                resource_type=ResourceType.LITERAL,
                object_triples__isnull=True
            )

            count = orphaned_literals.count()
            if count > 0:
                deleted, _ = orphaned_literals.delete()
                logger.info(f"Startup cleanup: Deleted {deleted} orphaned literals")
            else:
                logger.debug("Startup cleanup: No orphaned literals found")

        except Exception as e:
            # Don't fail startup if cleanup fails
            logger.warning(f"Startup literal cleanup failed: {e}")
