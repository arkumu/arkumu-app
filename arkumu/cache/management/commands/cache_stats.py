"""
Django management command to show cache statistics.
"""

from django.core.management.base import BaseCommand
from arkumu.cache.services import CacheManager
import json


class Command(BaseCommand):
    help = 'Display cache statistics for all services'

    def add_arguments(self, parser):
        parser.add_argument(
            '--service',
            choices=['oai', 'graph', 'catalog', 'all'],
            default='all',
            help='Show statistics for specific service or all services'
        )
        parser.add_argument(
            '--format',
            choices=['table', 'json'],
            default='table',
            help='Output format'
        )

    def handle(self, *args, **options):
        cache_manager = CacheManager()

        if options['service'] == 'all':
            stats = cache_manager.get_all_statistics()
        else:
            service_map = {
                'oai': cache_manager.oai,
                'graph': cache_manager.graph,
                'catalog': cache_manager.catalog
            }
            service = service_map[options['service']]
            stats = {options['service']: service.get_cache_statistics()}

        if options['format'] == 'json':
            self.stdout.write(json.dumps(stats, indent=2))
        else:
            self._print_table_format(stats)

    def _print_table_format(self, stats):
        """Print statistics in table format."""
        self.stdout.write(self.style.SUCCESS('=== Cache Statistics ==='))

        for service_name, service_stats in stats.items():
            self.stdout.write(f'\n{service_name.upper()} Cache Service:')
            self.stdout.write(f'  Service Type: {service_stats.get("service_type", "N/A")}')
            self.stdout.write(f'  Backend: {service_stats.get("backend", "N/A")}')
            self.stdout.write(f'  Prefix: {service_stats.get("prefix", "N/A")}')

            if 'ttl_config' in service_stats:
                self.stdout.write('  TTL Configuration:')
                for cache_type, ttl in service_stats['ttl_config'].items():
                    hours = ttl / 3600
                    self.stdout.write(f'    {cache_type}: {hours}h ({ttl}s)')

            if 'supported_operations' in service_stats:
                self.stdout.write('  Supported Operations:')
                for op in service_stats['supported_operations']:
                    self.stdout.write(f'    - {op}')

            if 'cache_types' in service_stats:
                self.stdout.write(f'  Cache Types: {", ".join(service_stats["cache_types"])}')

            if 'supported_formats' in service_stats:
                self.stdout.write(f'  Supported Formats: {", ".join(service_stats["supported_formats"])}')

            self.stdout.write(f'  Timestamp: {service_stats.get("timestamp", "N/A")}')