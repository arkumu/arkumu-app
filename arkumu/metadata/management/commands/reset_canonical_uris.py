from django.core.management.base import BaseCommand
from django.db import transaction
from arkumu.metadata.models import Resource
from arkumu.users.models import Organization


class Command(BaseCommand):
    help = 'Reset canonical URIs to null for all resources in an organization'

    def add_arguments(self, parser):
        parser.add_argument(
            '-o', '--organization',
            type=str,
            required=True,
            help='Organization code (e.g., khm)'
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be reset without making changes'
        )
        parser.add_argument(
            '--resource-type',
            type=str,
            choices=['CLASS', 'PROPERTY', 'IRI'],
            help='Only reset specific resource type'
        )

    def handle(self, *args, **options):
        org_code = options['organization']
        dry_run = options['dry_run']
        resource_type_filter = options.get('resource_type')
        
        try:
            organization = Organization.objects.get(code=org_code)
        except Organization.DoesNotExist:
            self.stdout.write(
                self.style.ERROR(f'Organization with code "{org_code}" not found')
            )
            return
        
        self.stdout.write(f"Organization: {organization.name} ({org_code})")
        self.stdout.write("-" * 50)
        
        # Build query
        query = Resource.objects.filter(
            organization=organization,
            canonical_uri__isnull=False,
            is_placeholder=False
        )
        
        if resource_type_filter:
            from arkumu.metadata.models import ResourceType
            resource_type = getattr(ResourceType, resource_type_filter)
            query = query.filter(resource_type=resource_type)
        
        # Get resources with canonical URIs
        resources_with_canonical = query.select_related('organization')
        total_count = resources_with_canonical.count()
        
        if total_count == 0:
            self.stdout.write(self.style.SUCCESS("No resources with canonical URIs found"))
            return
        
        # Show summary
        self.stdout.write(f"\n📊 Resources with canonical URIs:")
        if resource_type_filter:
            self.stdout.write(f"  Resource type: {resource_type_filter}")
        else:
            # Show breakdown by type
            from collections import Counter
            type_counts = Counter(resources_with_canonical.values_list('resource_type', flat=True))
            for resource_type, count in type_counts.items():
                self.stdout.write(f"  {resource_type}: {count}")
        
        self.stdout.write(f"  Total to reset: {total_count}")
        
        if dry_run:
            self.stdout.write(f"\n🔍 DRY RUN - Showing first 10 resources that would be reset:")
            for resource in resources_with_canonical[:10]:
                self.stdout.write(f"  • {resource.name} ({resource.resource_type})")
                self.stdout.write(f"    Current canonical: {resource.canonical_uri}")
            
            if total_count > 10:
                self.stdout.write(f"    ... and {total_count - 10} more")
            
            self.stdout.write(f"\nTo actually reset, run without --dry-run")
            return
        
        # Confirm before proceeding
        confirm = input(f"\n⚠️  This will reset {total_count} canonical URIs to null. Continue? (y/N): ")
        if confirm.lower() != 'y':
            self.stdout.write("Operation cancelled")
            return
        
        # Perform the reset
        self.stdout.write(f"\n🔄 Resetting canonical URIs...")
        
        with transaction.atomic():
            updated_count = resources_with_canonical.update(canonical_uri=None)
        
        self.stdout.write(
            self.style.SUCCESS(f"\n✅ Successfully reset {updated_count} canonical URIs to null")
        )