"""
Django management command to clear cache entries.
"""

from django.core.management.base import BaseCommand, CommandError
from django.core.cache import cache
from arkumu.cache.services import CacheManager


class Command(BaseCommand):
    help = 'Clear cache entries'

    def add_arguments(self, parser):
        parser.add_argument(
            '--service',
            choices=['oai', 'graph', 'catalog', 'all'],
            default='all',
            help='Clear cache for specific service or all services'
        )
        parser.add_argument(
            '--resource-uri',
            help='Clear cache for specific resource URI'
        )
        parser.add_argument(
            '--confirm',
            action='store_true',
            help='Confirm cache clearing operation'
        )

    def handle(self, *args, **options):
        if not options['confirm']:
            self.stdout.write(
                self.style.WARNING(
                    'This operation will clear cache entries. Use --confirm to proceed.'
                )
            )
            return

        cache_manager = CacheManager()

        if options['resource_uri']:
            self._clear_resource_cache(cache_manager, options)
        else:
            self._clear_service_cache(options)

    def _clear_resource_cache(self, cache_manager, options):
        """Clear cache for a specific resource."""
        resource_uri = options['resource_uri']
        service = options['service']

        self.stdout.write(f'Clearing cache for resource: {resource_uri}')

        try:
            if service in ['all']:
                cache_manager.invalidate_resource_globally(resource_uri)
                self.stdout.write(self.style.SUCCESS('✓ All service caches cleared for resource'))
            else:
                if service == 'oai':
                    cache_manager.oai.invalidate_resource(resource_uri)
                    self.stdout.write(self.style.SUCCESS('✓ OAI cache cleared for resource'))
                elif service == 'graph':
                    cache_manager.graph.invalidate_resource(resource_uri)
                    self.stdout.write(self.style.SUCCESS('✓ Graph cache cleared for resource'))
                elif service == 'catalog':
                    cache_manager.catalog.invalidate_catalog_data(resource_uri)
                    self.stdout.write(self.style.SUCCESS('✓ Catalog cache cleared for resource'))

        except Exception as e:
            raise CommandError(f'Error clearing resource cache: {str(e)}')

    def _clear_service_cache(self, options):
        """Clear cache for entire service(s)."""
        service = options['service']

        if service == 'all':
            self.stdout.write('Clearing all cache entries...')
            try:
                cache.clear()
                self.stdout.write(self.style.SUCCESS('✓ All cache entries cleared'))
            except Exception as e:
                raise CommandError(f'Error clearing all cache: {str(e)}')
        else:
            self.stdout.write(f'Clearing {service} cache entries...')

            # Note: This is a simplified implementation
            # In production, we'd need pattern-based clearing or cache tagging
            self.stdout.write(
                self.style.WARNING(
                    f'Partial cache clearing for {service} not fully implemented. '
                    'Use --service=all to clear entire cache.'
                )
            )