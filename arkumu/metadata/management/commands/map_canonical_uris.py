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
        )
        
        if unmapped_classes:
            self.stdout.write(f"\nClasses without canonical URIs (showing {min(len(unmapped_classes), limit)}):")
            for resource in unmapped_classes[:limit]:
                self.stdout.write(f"  - {resource.name} ({resource.uri})")
        
        # Get unmapped properties
        unmapped_properties = service.get_unmapped_resources(
            resource_type=ResourceType.PROPERTY,
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
            df = pl.read_csv(csv_file).with_row_count("csv_row", offset=2)
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
        valid_rows = df.filter(pl.col('Name').is_not_null() & (pl.col('Name') != ''))

        csv_stats = {
            'total_rows': len(df),
            'rows_with_names': len(valid_rows),
            'total_names': 0,
            'split_count': 0,
            'single_count': 0
        }

        for row in df.iter_rows(named=True):
            names_str = (row.get('Name') or '').strip()
            if not names_str:
                continue
            names = [n.strip() for n in names_str.split(',') if n.strip()]
            csv_stats['total_names'] += len(names)
            if len(names) > 1:
                csv_stats['split_count'] += 1
            else:
                csv_stats['single_count'] += 1
        
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
        
        sample_rows = valid_rows
        total_sample = len(sample_rows)
        
        self.stdout.write(f"Analyzing {total_sample} rows for matching preview...")
        
        processed = 0
        for row in sample_rows.iter_rows(named=True):
            processed += 1
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
        
        total_entries = sum(stats['total'] for stats in type_stats.values())
        total_matched = sum(stats['matched'] for stats in type_stats.values())
        total_not_found = sum(stats['not_found'] for stats in type_stats.values())
        overall_match_rate = (total_matched / total_entries * 100) if total_entries > 0 else 0
        total_csv_rows = len(df)
        mappable_rows = len(valid_rows)

        self.stdout.write(f"\n📊 Matching Summary:")
        self.stdout.write(f"  Entries analyzed: {total_entries}")
        self.stdout.write(f"  ✅ Will match: {total_matched}")
        self.stdout.write(f"  ❌ Won't match: {total_not_found}")
        self.stdout.write(f"  📈 Match rate: {overall_match_rate:.1f}%")
        self.stdout.write(f"  Total CSV rows: {total_csv_rows}")
        self.stdout.write(f"  Rows with names to map: {mappable_rows}")
        self.stdout.write(f"  Rows without names: {total_csv_rows - mappable_rows} (target URI definitions only)")

        conflicts = self._analyze_conflicts(valid_rows, service)
        
        # Show conflict warnings
        if conflicts['overwrites'] or conflicts['duplicates'] or conflicts['multiple_targets'] or conflicts['invalid_id_sharing']:
            self.stdout.write(f"\n⚠️  VALIDATION RESULTS:")
            
            if conflicts['overwrites']:
                self.stdout.write(f"\n  📝 Resources with existing canonical URIs that will be OVERWRITTEN:")
                overwrite_rows = [
                    (name, old_uri, new_uri, csv_row if csv_row is not None else "-")
                    for name, old_uri, new_uri, csv_row in conflicts['overwrites']
                ]
                self._print_table(
                    rows=overwrite_rows,
                    headers=("Name", "Existing Canonical", "New Canonical", "CSV Row"),
                    indent="    "
                )
            
            if conflicts['duplicates']:
                self.stdout.write(f"\n  🔄 Multiple resources will get the SAME canonical URI:")
                duplicate_rows = []
                for target_uri, data in sorted(conflicts['duplicates'].items()):
                    for name in sorted(data['names']):
                        rows = ", ".join(str(r) for r in sorted(data['rows'][name])) or "-"
                        duplicate_rows.append((target_uri, name, rows))
                self._print_table(
                    rows=duplicate_rows,
                    headers=("Canonical URI", "CSV Name", "CSV Rows"),
                    indent="    "
                )
            
            if conflicts['multiple_targets']:
                self.stdout.write(f"\n  ⚡ Same CSV name appears with DIFFERENT target URIs:")
                multi_target_rows = []
                for name, data in sorted(conflicts['multiple_targets'].items()):
                    for target in sorted(data['targets']):
                        rows = ", ".join(str(r) for r in sorted(data['rows'][target])) or "-"
                        multi_target_rows.append((name, target, rows))
                self._print_table(
                    rows=multi_target_rows,
                    headers=("CSV Name", "Target URI", "CSV Rows"),
                    indent="    "
                )
            
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
                id_rows = []
                for target_uri, data in conflicts['invalid_id_sharing']:
                    for name in sorted(data['names']):
                        rows = ", ".join(str(r) for r in sorted(data['rows'][name])) or "-"
                        id_rows.append((target_uri, name, rows))
                self._print_table(
                    rows=id_rows,
                    headers=("Canonical ID URI", "CSV Field", "CSV Rows"),
                    indent="    "
                )
                self.stdout.write(f"\n    🛠️  FIX: Edit your CSV to give each ID field a unique Target URI")
        else:
            self.stdout.write(f"\n✅ No conflicts detected - safe to proceed")
    
    def _analyze_conflicts(self, valid_rows, service):
        """Analyze potential conflicts in the mapping data."""
        from arkumu.metadata.models import Resource
        from collections import defaultdict

        conflicts = {
            'overwrites': [],
            'duplicates': defaultdict(lambda: {'names': set(), 'rows': defaultdict(list)}),
            'multiple_targets': defaultdict(lambda: {'targets': set(), 'rows': defaultdict(list)}),
            'invalid_id_sharing': []
        }

        name_target_data = defaultdict(lambda: {'targets': set(), 'rows': defaultdict(list)})

        for row in valid_rows.iter_rows(named=True):
            names_str = row['Name'] or ''
            if not names_str:
                continue

            names = [n.strip() for n in names_str.split(',') if n.strip()]
            target = row.get('Target', '')
            row_type = row.get('Type', '')
            csv_row = row.get('csv_row')

            resource_type = service._parse_resource_type(row_type)
            if not resource_type or not target:
                continue

            for name in names:
                name_data = name_target_data[name]
                name_data['targets'].add(target)
                name_data['rows'][target].append(csv_row)
                if len(name_data['targets']) > 1:
                    conflicts['multiple_targets'][name] = name_data

                dup_data = conflicts['duplicates'][target]
                dup_data['names'].add(name)
                dup_data['rows'][name].append(csv_row)

                resources = Resource.objects.filter(
                    organization=service.organization,
                    resource_type=resource_type,
                    name=name,
                    is_placeholder=False
                )

                for resource in resources:
                    if resource.canonical_uri and resource.canonical_uri != target:
                        conflicts['overwrites'].append((name, resource.canonical_uri, target, csv_row))

        # Filter duplicates to only those with more than one unique name
        duplicates_filtered = defaultdict(lambda: {'names': set(), 'rows': defaultdict(list)})
        invalid_id = []
        for target, data in conflicts['duplicates'].items():
            if len(data['names']) > 1:
                duplicates_filtered[target] = data
                if self._is_id_type_uri(target):
                    invalid_id.append((target, data))

        conflicts['duplicates'] = duplicates_filtered
        conflicts['invalid_id_sharing'] = invalid_id

        return conflicts

    def _print_table(self, rows, headers, indent=""):
        """Render a simple ASCII table for CLI output."""
        if not rows:
            self.stdout.write(f"{indent}(none)")
            return

        headers = list(headers)
        data = [[str(value) for value in row] for row in rows]
        widths = [len(header) for header in headers]

        for row in data:
            for idx, value in enumerate(row):
                widths[idx] = max(widths[idx], len(value))

        header_line = indent + "  ".join(header.ljust(widths[idx]) for idx, header in enumerate(headers))
        separator = indent + "  ".join("-" * widths[idx] for idx in range(len(headers)))

        self.stdout.write(header_line)
        self.stdout.write(separator)

        for row in data:
            line = indent + "  ".join(value.ljust(widths[idx]) for idx, value in enumerate(row))
            self.stdout.write(line)
    
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
