import csv
from django.core.management.base import BaseCommand
from django.db import transaction
from arkumu.metadata.models import Resource, ResourceType


class Command(BaseCommand):
    help = 'Import simple harmonization mappings from CSV - updates Resource.canonical_uri'
    
    def add_arguments(self, parser):
        parser.add_argument(
            'csv_file',
            type=str,
            help='Path to CSV file with mappings (Type,Source,Target,Label columns)'
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be updated without making changes'
        )
    
    @transaction.atomic
    def handle(self, *args, **options):
        csv_file = options['csv_file']
        dry_run = options['dry_run']
        
        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN MODE - No changes will be made"))
        
        updated_count = 0
        not_found_count = 0
        
        with open(csv_file, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            
            for row_num, row in enumerate(reader, 1):
                source_uri = row.get('Source', '').strip()
                target_uri = row.get('Target', '').strip()
                resource_type = row.get('Type', '').strip()
                label = row.get('Label', '').strip()
                
                if not source_uri or not target_uri:
                    self.stdout.write(
                        self.style.ERROR(f"Row {row_num}: Missing Source or Target URI")
                    )
                    continue
                
                # Find the resource to update
                try:
                    resource = Resource.objects.get(uri=source_uri)
                    
                    if dry_run:
                        self.stdout.write(
                            f"Would update: {source_uri} → {target_uri}"
                        )
                    else:
                        # Update canonical_uri
                        resource.canonical_uri = target_uri
                        resource.save(update_fields=['canonical_uri'])
                        
                        self.stdout.write(
                            f"Updated: {source_uri} → {target_uri}"
                        )
                    
                    updated_count += 1
                    
                except Resource.DoesNotExist:
                    self.stdout.write(
                        self.style.WARNING(
                            f"Row {row_num}: Resource not found: {source_uri}"
                        )
                    )
                    not_found_count += 1
                
                except Exception as e:
                    self.stdout.write(
                        self.style.ERROR(
                            f"Row {row_num}: Error updating {source_uri}: {e}"
                        )
                    )
        
        # Summary
        self.stdout.write("\n" + "="*50)
        if dry_run:
            self.stdout.write(
                self.style.SUCCESS(f"DRY RUN COMPLETE:")
            )
            self.stdout.write(f"Would update: {updated_count} resources")
        else:
            self.stdout.write(
                self.style.SUCCESS(f"IMPORT COMPLETE:")
            )
            self.stdout.write(f"Updated: {updated_count} resources")
        
        self.stdout.write(f"Not found: {not_found_count} resources")
        
        # Show some examples of harmonized resources
        if not dry_run and updated_count > 0:
            self.stdout.write("\nSample harmonized resources:")
            examples = Resource.objects.filter(
                canonical_uri__isnull=False
            ).values('uri', 'canonical_uri', 'resource_type')[:5]
            
            for example in examples:
                self.stdout.write(
                    f"  {example['resource_type']}: {example['uri']} → {example['canonical_uri']}"
                )