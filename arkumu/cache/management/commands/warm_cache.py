"""
Django management command to warm cache for resources.
"""

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q
from arkumu.metadata.models.resource import Resource
from arkumu.cache.services import CacheManager
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Warm cache for resources'

    def add_arguments(self, parser):
        parser.add_argument(
            '--resource-uri',
            help='Warm cache for specific resource URI'
        )
        parser.add_argument(
            '--organization',
            help='Warm cache for all resources in organization'
        )
        parser.add_argument(
            '--limit',
            type=int,
            default=100,
            help='Limit number of resources to process (default: 100)'
        )
        parser.add_argument(
            '--popular',
            action='store_true',
            help='Warm cache for popular/recently updated resources'
        )
        parser.add_argument(
            '--service',
            choices=['oai', 'graph', 'catalog', 'all'],
            default='oai',
            help='Which cache service to warm'
        )

    def handle(self, *args, **options):
        cache_manager = CacheManager()

        if options['resource_uri']:
            self._warm_single_resource(cache_manager, options)
        elif options['organization']:
            self._warm_organization_resources(cache_manager, options)
        elif options['popular']:
            self._warm_popular_resources(cache_manager, options)
        else:
            raise CommandError('Must specify --resource-uri, --organization, or --popular')

    def _warm_single_resource(self, cache_manager, options):
        """Warm cache for a single resource."""
        resource_uri = options['resource_uri']
        service = options['service']

        try:
            resource = Resource.objects.get(uri=resource_uri)
            self.stdout.write(f'Warming cache for resource: {resource_uri}')

            if service in ['oai', 'all']:
                cache_manager.oai.warm_resource_with_graph_integration(resource)
                self.stdout.write(self.style.SUCCESS('✓ OAI cache warmed'))

            if service in ['graph', 'all']:
                # Graph cache warming would be triggered by OAI warming
                self.stdout.write(self.style.SUCCESS('✓ Graph cache integrated'))

            if service in ['catalog', 'all']:
                # Catalog cache warming
                if resource.organization:
                    cache_manager.catalog.warm_popular_entities([resource_uri], resource.organization.code)
                    self.stdout.write(self.style.SUCCESS('✓ Catalog cache warmed'))

        except Resource.DoesNotExist:
            raise CommandError(f'Resource not found: {resource_uri}')
        except Exception as e:
            raise CommandError(f'Error warming cache: {str(e)}')

    def _warm_organization_resources(self, cache_manager, options):
        """Warm cache for all resources in an organization."""
        org_code = options['organization']
        limit = options['limit']
        service = options['service']

        try:
            resources = Resource.objects.filter(
                organization__code=org_code
            ).order_by('-updated_at')[:limit]

            if not resources:
                self.stdout.write(f'No resources found for organization: {org_code}')
                return

            self.stdout.write(f'Warming cache for {len(resources)} resources in {org_code}')

            warmed_count = 0
            error_count = 0

            for resource in resources:
                try:
                    if service in ['oai', 'all']:
                        cache_manager.oai.warm_resource_with_graph_integration(resource)

                    if service in ['catalog', 'all']:
                        cache_manager.catalog.warm_popular_entities([resource.uri], org_code)

                    warmed_count += 1
                    if warmed_count % 10 == 0:
                        self.stdout.write(f'Processed {warmed_count} resources...')

                except Exception as e:
                    error_count += 1
                    logger.error(f'Error warming cache for {resource.uri}: {str(e)}')

            self.stdout.write(
                self.style.SUCCESS(
                    f'✓ Cache warming complete: {warmed_count} successful, {error_count} errors'
                )
            )

        except Exception as e:
            raise CommandError(f'Error warming organization cache: {str(e)}')

    def _warm_popular_resources(self, cache_manager, options):
        """Warm cache for popular/recently updated resources."""
        limit = options['limit']
        service = options['service']

        try:
            # Get recently updated resources across all organizations
            popular_resources = Resource.objects.filter(
                Q(resource_type='entity') | Q(resource_type='project')
            ).order_by('-updated_at')[:limit]

            if not popular_resources:
                self.stdout.write('No popular resources found')
                return

            self.stdout.write(f'Warming cache for {len(popular_resources)} popular resources')

            # Group by organization for efficient warming
            org_resources = {}
            for resource in popular_resources:
                if resource.organization:
                    org_code = resource.organization.code
                    if org_code not in org_resources:
                        org_resources[org_code] = []
                    org_resources[org_code].append(resource)

            total_warmed = 0
            for org_code, resources in org_resources.items():
                try:
                    if service in ['oai', 'all']:
                        for resource in resources:
                            cache_manager.oai.warm_resource_with_graph_integration(resource)

                    if service in ['catalog', 'all']:
                        resource_uris = [r.uri for r in resources]
                        cache_manager.catalog.warm_popular_entities(resource_uris, org_code)

                    total_warmed += len(resources)
                    self.stdout.write(f'✓ Warmed {len(resources)} resources for {org_code}')

                except Exception as e:
                    logger.error(f'Error warming cache for organization {org_code}: {str(e)}')

            self.stdout.write(
                self.style.SUCCESS(f'✓ Popular cache warming complete: {total_warmed} resources')
            )

        except Exception as e:
            raise CommandError(f'Error warming popular cache: {str(e)}')