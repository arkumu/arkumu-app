"""
Test the flexible catalog service.
"""

from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model

from arkumu.metadata.services.flexible_catalog_service import FlexibleCatalogService

User = get_user_model()


class Command(BaseCommand):
    help = 'Test the flexible catalog service'

    def add_arguments(self, parser):
        parser.add_argument(
            '--username',
            type=str,
            default='fco',
            help='Username to test with (default: fco)'
        )

    def handle(self, *args, **options):
        username = options['username']
        
        self.stdout.write(
            self.style.SUCCESS(f'=== TESTING FLEXIBLE CATALOG SERVICE ===')
        )
        
        # Get user
        try:
            user = User.objects.get(username=username)
            self.stdout.write(f'User: {user}')
        except User.DoesNotExist:
            self.stdout.write(
                self.style.ERROR(f'User {username} not found')
            )
            return
        
        # Create service
        service = FlexibleCatalogService(user)
        
        # Get debug info
        self.test_debug_info(service)
        
        # Test resource counts
        self.test_resource_counts(service)
        
        # Test category queries
        self.test_category_queries(service)

    def test_debug_info(self, service):
        """Test debug information."""
        self.stdout.write('\n=== DEBUG INFO ===')
        
        debug_info = service.get_debug_info()
        self.stdout.write(f'Total harmonization rules: {debug_info["total_harmonization_rules"]}')
        self.stdout.write(f'Total type rules: {debug_info["total_type_rules"]}')
        
        self.stdout.write('\nDiscovered categories:')
        for category, info in debug_info['discovered_categories'].items():
            self.stdout.write(f'  {category}: {info["count"]} types')
            for type_uri in info['types']:
                self.stdout.write(f'    - {type_uri}')

    def test_resource_counts(self, service):
        """Test resource counts."""
        self.stdout.write('\n=== RESOURCE COUNTS ===')
        
        try:
            counts = service.get_resource_counts_by_type()
            self.stdout.write(f'Resource counts: {counts}')
            
            total = sum(counts.values())
            self.stdout.write(f'Total resources found: {total}')
            
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f'Error getting resource counts: {e}')
            )
            import traceback
            traceback.print_exc()

    def test_category_queries(self, service):
        """Test querying by category."""
        self.stdout.write('\n=== CATEGORY QUERIES ===')
        
        for category in ['projects', 'events', 'persons', 'organizations', 'documents']:
            try:
                resources = service.get_resources_by_category(category)
                count = resources.count()
                self.stdout.write(f'{category}: {count} resources')
                
                # Show first few examples
                for resource in resources[:3]:
                    self.stdout.write(f'  - {resource.uri} (Org: {resource.organization})')
                    
            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(f'Error querying {category}: {e}')
                )
                import traceback
                traceback.print_exc()