"""
Management command to process canonical URI mappings from CSV files.
Maps organization-specific resource names to Arkumu canonical URIs.
"""

import sys
from pathlib import Path
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

try:
    import polars as pl
except ImportError:
    pl = None

from arkumu.metadata.services.integration import CanonicalUriMappingService


class Command(BaseCommand):
    help = 'Process canonical URI mappings from CSV file'
    
    def add_arguments(self, parser):
        parser.add_argument(
            'csv_file',
            type=str,
            help='Path to CSV file containing canonical URI mappings'
        )
        parser.add_argument(
            '--organization',
            '-o',
            type=str,
            required=True,
            help='Organization code (e.g., hmt, rsh)'
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Preview changes without applying them'
        )
        parser.add_argument(
            '--validate-only',
            action='store_true',
            help='Only validate the CSV format without processing'
        )
        parser.add_argument(
            '--show-unmapped',
            action='store_true',
            help='Show unmapped resources for the organization before processing'
        )
        parser.add_argument(
            '--limit',
            type=int,
            default=50,
            help='Limit for unmapped resources display (default: 50)'
        )
    
    def handle(self, *args, **options):
        # Check if Polars is installed
        if pl is None:
            self.stdout.write(self.style.ERROR(
                "Polars is required for robust CSV handling.\n"
                "Install it with: pip install polars"
            ))
            return
        
        csv_file = options['csv_file']
        organization_code = options['organization']
        dry_run = options['dry_run']
        validate_only = options['validate_only']
        show_unmapped = options['show_unmapped']
        limit = options['limit']
        
        # Check if CSV file exists
        if not Path(csv_file).exists():
            raise CommandError(f"CSV file not found: {csv_file}")
        
        try:
            # Initialize service
            service = CanonicalUriMappingService(organization_code)
            self.stdout.write(f"Organization: {service.organization.name} ({organization_code})")
            self.stdout.write("-" * 50)
            
            # Show unmapped resources if requested
            if show_unmapped:
                self._show_unmapped_resources(service, limit)
                if not validate_only and not dry_run:
                    response = input("\nDo you want to continue with processing? (y/n): ")
                    if response.lower() != 'y':
                        self.stdout.write(self.style.WARNING("Processing cancelled"))
                        return
            
            # Validate CSV
            if validate_only:
                self._validate_csv(service, csv_file)
                return
            
            # Process mappings
            self._process_mappings(service, csv_file, dry_run)
            
        except ValueError as e:
            raise CommandError(str(e))
        except Exception as e:
            raise CommandError(f"Error processing mappings: {e}")
    
    def _show_unmapped_resources(self, service, limit):
        """Display unmapped resources for the organization."""
        self.stdout.write(self.style.SUCCESS("\n=== Unmapped Resources ==="))
        
        from arkumu.metadata.models import Resource, ResourceType
        
        # Get unmapped classes
        unmapped_classes = service.get_unmapped_resources(
            resource_type=ResourceType.CLASS,
            limit=limit
        )
        
        if unmapped_classes:
            self.stdout.write(f"\nClasses without canonical URIs (showing {min(len(unmapped_classes), limit)}):")
            for resource in unmapped_classes[:limit]:
                self.stdout.write(f"  - {resource.name} ({resource.uri})")
        
        # Get unmapped properties
        unmapped_properties = service.get_unmapped_resources(
            resource_type=ResourceType.PROPERTY,
            limit=limit
        )
        
        if unmapped_properties:
            self.stdout.write(f"\nProperties without canonical URIs (showing {min(len(unmapped_properties), limit)}):")
            for resource in unmapped_properties[:limit]:
                self.stdout.write(f"  - {resource.name} ({resource.uri})")
        
        total_unmapped = len(unmapped_classes) + len(unmapped_properties)
        self.stdout.write(f"\nTotal unmapped resources: {total_unmapped}")
    
    def _validate_csv(self, service, csv_file):
        """Validate CSV format using Polars and display sample rows with splitting info."""
        self.stdout.write(self.style.SUCCESS("\n=== Validating CSV ==="))
        
        # Read CSV with Polars
        try:
            df = pl.read_csv(csv_file)
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Error reading CSV: {e}"))
            return
        
        # Check required columns
        required_cols = ['Type', 'Target', 'Label', 'Name']
        missing_cols = [col for col in required_cols if col not in df.columns]
        
        if missing_cols:
            self.stdout.write(self.style.ERROR(f"Missing required columns: {', '.join(missing_cols)}"))
            return
        
        # Analyze with Polars
        csv_stats = {
            'total_rows': len(df),
            'rows_with_names': 0,
            'total_names': 0,
            'split_count': 0,
            'single_count': 0
        }
        
        # Process and display sample rows
        self.stdout.write("\nSample rows from CSV (showing how names will be split):")
        self.stdout.write("-" * 80)
        
        sample_rows = []
        for row in df.filter(pl.col('Name').is_not_null() & (pl.col('Name') != '')).head(5).iter_rows(named=True):
            names_str = row['Name'] or ''
            if names_str:
                csv_stats['rows_with_names'] += 1
                names = [n.strip() for n in names_str.split(',') if n.strip()]
                sample_rows.append((row, names))
        
        # Calculate full stats
        for row in df.iter_rows(named=True):
            names_str = (row.get('Name') or '').strip()
            if names_str:
                names = [n.strip() for n in names_str.split(',') if n.strip()]
                csv_stats['total_names'] += len(names)
                if len(names) > 1:
                    csv_stats['split_count'] += 1
                else:
                    csv_stats['single_count'] += 1
        
        # Display sample rows
        for i, (row, names) in enumerate(sample_rows, 1):
            self.stdout.write(f"Row {i}:")
            self.stdout.write(f"  Type: {row.get('Type', 'N/A')}")
            self.stdout.write(f"  Target: {row.get('Target', 'N/A')[:50]}...")
            self.stdout.write(f"  Label: {row.get('Label', 'N/A')}")
            self.stdout.write(f"  Names raw: {row.get('Name', 'N/A')}")
            if len(names) > 1:
                self.stdout.write(f"  → Will split into {len(names)} names:")
                for j, name in enumerate(names, 1):
                    self.stdout.write(f"      {j}. {name}")
            else:
                self.stdout.write(f"  → Single name: {names[0] if names else 'N/A'}")
            self.stdout.write("")
        
        # Recount rows with names properly
        csv_stats['rows_with_names'] = len(df.filter(pl.col('Name').is_not_null() & (pl.col('Name') != '')))
        
        # Show statistics
        self.stdout.write(self.style.SUCCESS("\n📊 CSV Statistics:"))
        self.stdout.write(f"  • Total rows: {csv_stats['total_rows']}")
        self.stdout.write(f"  • Rows with mappable names: {csv_stats['rows_with_names']}")
        self.stdout.write(f"  • Total names to process: {csv_stats['total_names']}")
        self.stdout.write(f"    - Rows with single name: {csv_stats['single_count']}")
        self.stdout.write(f"    - Rows with multiple names: {csv_stats['split_count']}")
        
        # Validation passed if we got here
        self.stdout.write(self.style.SUCCESS("\n✓ CSV format is valid"))
        
        # Show resource matching preview
        self._show_resource_matching_preview(df, service)
    
    def _show_resource_matching_preview(self, df, service):
        """Show stats and examples of resource matching by type."""
        self.stdout.write(self.style.SUCCESS("\n🔍 Resource Matching Preview:"))
        self.stdout.write("-" * 60)
        
        from arkumu.metadata.models import Resource
        
        # Get stats by type
        type_stats = {}
        examples_per_type = {}
        
        valid_rows = df.filter(pl.col('Name').is_not_null() & (pl.col('Name') != ''))
        
        # Limit to reasonable sample size for validation (first 20 rows)  
        sample_rows = valid_rows.head(20)
        total_sample = len(sample_rows)
        
        self.stdout.write(f"Analyzing first {total_sample} rows for matching preview...")
        
        processed = 0
        for row in sample_rows.iter_rows(named=True):
            processed += 1
            if processed % 5 == 0:
                self.stdout.write(f"  Processing row {processed}/{total_sample}...")
                self.stdout.flush()
            names_str = row['Name'] or ''
            if not names_str:
                continue
                
            names = [n.strip() for n in names_str.split(',') if n.strip()]
            row_type = row.get('Type', '')
            target = row.get('Target', 'N/A')
            label = row.get('Label', 'N/A')
            
            # Parse resource type like the service does
            resource_type = service._parse_resource_type(row_type)
            if not resource_type:
                continue
            
            # Initialize stats for this type
            if row_type not in type_stats:
                type_stats[row_type] = {'total': 0, 'matched': 0, 'not_found': 0}
                examples_per_type[row_type] = []
            
            type_stats[row_type]['total'] += 1
            
            # Check if we have matches for this row
            has_matches = False
            for name in names:
                resources = Resource.objects.filter(
                    organization=service.organization,
                    resource_type=resource_type,
                    name=name,
                    is_placeholder=False
                )
                if resources.exists():
                    has_matches = True
                    break
            
            if has_matches:
                type_stats[row_type]['matched'] += 1
            else:
                type_stats[row_type]['not_found'] += 1
            
            # Store examples (max 2 per type)
            if len(examples_per_type[row_type]) < 2:
                examples_per_type[row_type].append({
                    'label': label,
                    'target': target,
                    'names': names,
                    'row_type': row_type,
                    'resource_type': resource_type
                })
        
        # Show stats per type
        self.stdout.write(f"\n📊 Matching Statistics by Type:")
        for row_type, stats in type_stats.items():
            total = stats['total']
            matched = stats['matched']
            not_found = stats['not_found']
            match_rate = (matched / total * 100) if total > 0 else 0
            
            self.stdout.write(f"\n  {row_type}:")
            self.stdout.write(f"    Total entries: {total}")
            self.stdout.write(f"    ✅ Will match: {matched}")
            self.stdout.write(f"    ❌ Won't match: {not_found}")
            self.stdout.write(f"    📈 Match rate: {match_rate:.1f}%")
        
        # Show examples
        self.stdout.write(f"\n🔍 Examples (up to 2 per type):")
        for row_type, examples in examples_per_type.items():
            if not examples:
                continue
                
            self.stdout.write(f"\n  {row_type} Examples:")
            for example in examples:
                self.stdout.write(f"\n    Row: {example['label']}")
                self.stdout.write(f"      Target: {example['target'][:60]}...")
                self.stdout.write(f"      Names to match ({len(example['names'])}):")
                
                for i, name in enumerate(example['names'], 1):
                    resources = Resource.objects.filter(
                        organization=service.organization,
                        resource_type=example['resource_type'],
                        name=name,
                        is_placeholder=False
                    )
                    
                    if resources.exists():
                        resource = resources.first()
                        current_canonical = resource.canonical_uri or "(none)"
                        self.stdout.write(f"        {i}. '{name}' → ✅ MATCH")
                        self.stdout.write(f"           Resource: {resource.name} ({resource.uri})")
                        self.stdout.write(f"           Type: {resource.resource_type}")
                        self.stdout.write(f"           Current canonical: {current_canonical}")
                    else:
                        self.stdout.write(f"        {i}. '{name}' → ❌ NOT FOUND")
                        self.stdout.write(f"           (No resource found with this name)")
        
        # Overall summary
        total_entries = sum(stats['total'] for stats in type_stats.values())
        total_matched = sum(stats['matched'] for stats in type_stats.values())
        total_not_found = sum(stats['not_found'] for stats in type_stats.values())
        overall_match_rate = (total_matched / total_entries * 100) if total_entries > 0 else 0
        
        # Get full CSV stats for context
        total_csv_rows = len(df)
        mappable_rows = len(valid_rows)
        
        # Analyze conflicts across ALL rows (not just sample)
        self.stdout.write(f"\n🔍 Analyzing conflicts across all {mappable_rows} mappable rows...")
        conflicts = self._analyze_conflicts(valid_rows, service)
        
        self.stdout.write(f"\n📈 Sample Summary (from first 20 rows with names):")
        self.stdout.write(f"  Sample entries analyzed: {total_entries}")
        self.stdout.write(f"  ✅ Will match: {total_matched}")
        self.stdout.write(f"  ❌ Won't match: {total_not_found}")
        self.stdout.write(f"  📈 Sample match rate: {overall_match_rate:.1f}%")
        self.stdout.write(f"\n📊 Full CSV Context:")
        self.stdout.write(f"  Total CSV rows: {total_csv_rows}")
        self.stdout.write(f"  Rows with names to map: {mappable_rows}")
        self.stdout.write(f"  Rows without names: {total_csv_rows - mappable_rows} (target URI definitions only)")
        
        # Show conflict warnings
        if conflicts['overwrites'] or conflicts['duplicates'] or conflicts['multiple_targets'] or conflicts['invalid_id_sharing']:
            self.stdout.write(f"\n⚠️  VALIDATION RESULTS:")
            
            if conflicts['overwrites']:
                self.stdout.write(f"\n  📝 Resources with existing canonical URIs that will be OVERWRITTEN:")
                for resource_name, old_uri, new_uri in conflicts['overwrites'][:10]:  # Show first 10
                    self.stdout.write(f"    • {resource_name}: {old_uri} → {new_uri}")
                if len(conflicts['overwrites']) > 10:
                    self.stdout.write(f"    ... and {len(conflicts['overwrites']) - 10} more")
            
            if conflicts['duplicates']:
                self.stdout.write(f"\n  🔄 Multiple resources will get the SAME canonical URI:")
                for target_uri, resource_names in list(conflicts['duplicates'].items())[:5]:  # Show first 5
                    self.stdout.write(f"    • {target_uri}")
                    for name in resource_names[:3]:  # Show first 3 names per URI
                        self.stdout.write(f"      - {name}")
                    if len(resource_names) > 3:
                        self.stdout.write(f"      - ... and {len(resource_names) - 3} more")
                if len(conflicts['duplicates']) > 5:
                    self.stdout.write(f"    ... and {len(conflicts['duplicates']) - 5} more target URIs")
            
            if conflicts['multiple_targets']:
                self.stdout.write(f"\n  ⚡ Same CSV name appears with DIFFERENT target URIs:")
                for name, targets in conflicts['multiple_targets'].items():
                    self.stdout.write(f"    • '{name}' maps to:")
                    for target in targets:
                        self.stdout.write(f"      - {target}")
            
            if conflicts['invalid_id_sharing']:
                self.stdout.write(f"\n  🚫 PROBLEM: Multiple database fields mapped to same ID")
                self.stdout.write(f"\n    📋 EXPLANATION FOR CSV EDITOR:")
                self.stdout.write(f"    When your CSV maps multiple database fields to the same Arkumu ID,")
                self.stdout.write(f"    you're saying they are the exact same identifier - which is impossible.")
                self.stdout.write(f"    Each database field that contains IDs needs its own unique Arkumu identifier.")
                self.stdout.write(f"\n    ✅ RULE: One database field = One Arkumu identifier")
                self.stdout.write(f"    ❌ Don't do this: UUID, Projekt_ID, Equipment_ID all → same Arkumu ID")
                self.stdout.write(f"    ✅ Instead: Edit CSV Target column to give each ID field a different URI")
                self.stdout.write(f"    Example: Split UUID,Projekt_ID into separate CSV rows with different Target URIs")
                self.stdout.write(f"\n    💡 NOTE: This rule only applies to ID/identifier fields.")
                self.stdout.write(f"    For descriptions, titles, names - multiple fields can share the same Arkumu URI.")
                self.stdout.write(f"\n    🔧 CONFLICTING MAPPINGS FOUND:")
                for target_uri, resource_names in conflicts['invalid_id_sharing'][:3]:
                    self.stdout.write(f"    • {target_uri}")
                    self.stdout.write(f"      Database fields: {', '.join(resource_names[:5])}")
                    if len(resource_names) > 5:
                        self.stdout.write(f"      ... and {len(resource_names) - 5} more")
                if len(conflicts['invalid_id_sharing']) > 3:
                    self.stdout.write(f"    ... and {len(conflicts['invalid_id_sharing']) - 3} more ID conflicts")
                self.stdout.write(f"\n    🛠️  FIX: Edit your CSV to give each ID field a unique Target URI")
        else:
            self.stdout.write(f"\n✅ No conflicts detected - safe to proceed")
    
    def _analyze_conflicts(self, valid_rows, service):
        """Analyze potential conflicts in the mapping data."""
        from arkumu.metadata.models import Resource
        from collections import defaultdict
        
        conflicts = {
            'overwrites': [],  # Resources that will lose existing canonical URIs
            'duplicates': defaultdict(list),  # Multiple resources mapping to same canonical URI
            'multiple_targets': defaultdict(set),  # Same name mapping to different targets
            'invalid_id_sharing': []  # Multiple resources mapping to same ID-type canonical URI
        }
        
        # Track all name -> target mappings
        name_target_map = {}
        target_names_map = defaultdict(list)
        
        for row in valid_rows.iter_rows(named=True):
            names_str = row['Name'] or ''
            if not names_str:
                continue
                
            names = [n.strip() for n in names_str.split(',') if n.strip()]
            target = row.get('Target', '')
            row_type = row.get('Type', '')
            
            # Parse resource type like the service does
            resource_type = service._parse_resource_type(row_type)
            if not resource_type or not target:
                continue
            
            for name in names:
                # Check for multiple targets for same name
                if name in name_target_map and name_target_map[name] != target:
                    conflicts['multiple_targets'][name].add(name_target_map[name])
                    conflicts['multiple_targets'][name].add(target)
                else:
                    name_target_map[name] = target
                
                # Track for duplicate detection
                target_names_map[target].append(name)
                
                # Check for existing canonical URIs that will be overwritten
                resources = Resource.objects.filter(
                    organization=service.organization,
                    resource_type=resource_type,
                    name=name,
                    is_placeholder=False
                )
                
                for resource in resources:
                    if resource.canonical_uri and resource.canonical_uri != target:
                        conflicts['overwrites'].append((name, resource.canonical_uri, target))
        
        # Find duplicates (multiple names mapping to same target)
        for target, names in target_names_map.items():
            if len(names) > 1:
                conflicts['duplicates'][target] = names
                
                # Check if this is an invalid ID sharing scenario
                if self._is_id_type_uri(target):
                    conflicts['invalid_id_sharing'].append((target, names))
        
        return conflicts
    
    def _is_id_type_uri(self, uri):
        """Check if a URI represents an ID/identifier type that should be unique."""
        uri_lower = uri.lower()
        id_indicators = [
            '-id', '_id', '/id', 'identifier', 'uuid', 'guid', 
            'primary-key', 'pk', 'key', 'nummer', 'number'
        ]
        return any(indicator in uri_lower for indicator in id_indicators)
    
    def _process_mappings(self, service, csv_file, dry_run):
        """Process the CSV mappings using Polars with enhanced statistics."""
        mode = "DRY RUN" if dry_run else "LIVE"
        self.stdout.write(self.style.SUCCESS(f"\n=== Processing Mappings ({mode}) ==="))
        
        # Read and analyze with Polars
        df = pl.read_csv(csv_file)
        
        csv_stats = {
            'total_rows': len(df),
            'rows_with_names': 0,
            'total_names': 0,
            'split_names': 0,
            'single_names': 0,
            'unique_targets': set()
        }
        
        # Analyze with Polars
        for row in df.iter_rows(named=True):
            names_str = (row.get('Name') or '').strip()
            target = (row.get('Target') or '').strip()
            
            if target:
                csv_stats['unique_targets'].add(target)
            
            if names_str:
                csv_stats['rows_with_names'] += 1
                names = [n.strip() for n in names_str.split(',') if n.strip()]
                csv_stats['total_names'] += len(names)
                if len(names) > 1:
                    csv_stats['split_names'] += len(names)
                else:
                    csv_stats['single_names'] += 1
        
        # Display CSV analysis
        self.stdout.write("\n📊 CSV Analysis:")
        self.stdout.write(f"  • Total rows: {csv_stats['total_rows']}")
        self.stdout.write(f"  • Rows with names: {csv_stats['rows_with_names']}")
        self.stdout.write(f"  • Total names to process: {csv_stats['total_names']}")
        self.stdout.write(f"    - Single names: {csv_stats['single_names']}")
        self.stdout.write(f"    - Names from splits: {csv_stats['split_names']}")
        self.stdout.write(f"  • Unique target URIs: {len(csv_stats['unique_targets'])}")
        self.stdout.write("")
        
        # Process the mappings
        stats = service.process_canonical_mappings(csv_file, dry_run=dry_run)
        
        # Calculate match rate
        match_rate = 0
        if csv_stats['total_names'] > 0:
            match_rate = (stats['updated'] / csv_stats['total_names']) * 100
        
        # Display results
        self.stdout.write("\n📈 Processing Results:")
        self.stdout.write(f"  ✓ Matched & Updated: {stats['updated']}/{csv_stats['total_names']} ({match_rate:.1f}%)")
        self.stdout.write(f"  ⚠ Not found: {len(stats['not_found'])} names")
        self.stdout.write(f"  ⊘ Skipped rows: {stats['skipped']}")
        self.stdout.write(f"  ✗ Error rows: {stats['errors']}")
        
        if stats['not_found'] and len(stats['not_found']) <= 20:
            self.stdout.write(f"\n  Names not found:")
            for name in stats['not_found']:
                self.stdout.write(f"    • {name}")
        elif stats['not_found']:
            self.stdout.write(f"\n  Names not found (showing first 20 of {len(stats['not_found'])}):")
            for name in stats['not_found'][:20]:
                self.stdout.write(f"    • {name}")
        
        # Summary
        self.stdout.write("\n" + "=" * 50)
        if dry_run:
            self.stdout.write(self.style.WARNING(
                f"DRY RUN COMPLETE - No changes made\n"
                f"Would update {stats['updated']} resources ({match_rate:.1f}% match rate)\n"
                f"Run without --dry-run to apply changes"
            ))
        else:
            if stats['updated'] > 0:
                self.stdout.write(self.style.SUCCESS(
                    f"✅ Successfully updated {stats['updated']} resources\n"
                    f"   Match rate: {match_rate:.1f}%"
                ))
            else:
                self.stdout.write(self.style.WARNING(
                    "No resources were updated"
                ))