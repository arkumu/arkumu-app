from django.apps import AppConfig


class CatalogConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'arkumu.catalog'

    def ready(self):
        from arkumu.catalog.tasks import download_previews_task
        # Only run cleanup on server startup, not during migrations or commands
        if self._is_server_startup():
            download_previews_task.schedule(delay=0)

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
