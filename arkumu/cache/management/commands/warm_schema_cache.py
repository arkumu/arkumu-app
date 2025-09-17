"""
Management command to warm the schema map cache.

This pre-populates the comprehensive schema cache for faster catalog explorer performance.
"""

import logging
from django.core.management.base import BaseCommand
from arkumu.cache.services import SchemaMapCacheService
from arkumu.users.models import Organization

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Warm the schema map cache for catalog explorer performance'

    def add_arguments(self, parser):
        parser.add_argument(
            '--organizations',
            nargs='*',
            help='Specific organization codes to warm (default: all active organizations)'
        )
        parser.add_argument(
            '--global-only',
            action='store_true',
            help='Only warm the global schema cache (all organizations combined)'
        )

    def handle(self, *args, **options):
        schema_cache = SchemaMapCacheService()

        # Warm global cache (all organizations)
        self.stdout.write("Warming global schema cache...")
        global_map = schema_cache.get_complete_schema_map()
        self.stdout.write(
            self.style.SUCCESS(
                f"✓ Global cache warmed: {global_map['meta']['total_classes']} classes, "
                f"{global_map['meta']['total_properties']} properties"
            )
        )

        if not options['global_only']:
            # Get organization codes to warm
            if options['organizations']:
                org_codes = options['organizations']
                self.stdout.write(f"Warming cache for specific organizations: {', '.join(org_codes)}")
            else:
                # Get all active organizations
                orgs = Organization.objects.filter(is_active=True)
                org_codes = [org.code for org in orgs]
                self.stdout.write(f"Warming cache for all active organizations: {', '.join(org_codes)}")

            # Warm each organization's cache
            for org_code in org_codes:
                self.stdout.write(f"Warming cache for organization: {org_code}")
                try:
                    org_map = schema_cache.get_complete_schema_map(org_code)
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"✓ {org_code}: {org_map['meta']['total_classes']} classes, "
                            f"{org_map['meta']['total_properties']} properties"
                        )
                    )
                except Exception as e:
                    self.stdout.write(
                        self.style.ERROR(f"✗ Failed to warm cache for {org_code}: {e}")
                    )

        self.stdout.write(
            self.style.SUCCESS("Schema cache warming completed!")
        )