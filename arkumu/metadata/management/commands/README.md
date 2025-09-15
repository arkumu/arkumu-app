# Metadata Management Commands

## map_canonical_uris

Map organization-specific resource names to canonical URIs using the CanonicalUriMappingService.

### Purpose

This command uses the proper service layer to map resource names within an organization to standardized canonical URIs, enabling data harmonization across different archives and collections. It uses the `CanonicalUriMappingService` for organization-scoped mapping with comprehensive validation.

### CSV Format

The CSV file must contain these columns:

| Column | Description | Example |
|--------|-------------|---------|
| Type | Resource type (`Class` or `Property`) | `Class` |
| Target | Canonical URI to assign | `http://arkumu.org/canonical/person/john-smith` |
| Label | Human-readable label (informational) | `John Smith` |
| Name | Comma-separated resource names to find | `John Smith, J. Smith, Smith John` |

### Usage

```bash
# Basic mapping with organization scope
docker compose -f docker-compose.local.yml run --rm django \
  python manage.py map_canonical_uris /path/to/mappings.csv --organization hmt

# Dry run (preview changes without applying)
docker compose -f docker-compose.local.yml run --rm django \
  python manage.py map_canonical_uris /path/to/mappings.csv --organization hmt --dry-run

# Validate CSV format only
docker compose -f docker-compose.local.yml run --rm django \
  python manage.py map_canonical_uris /path/to/mappings.csv --organization hmt --validate-only

# Show unmapped resources before processing
docker compose -f docker-compose.local.yml run --rm django \
  python manage.py map_canonical_uris /path/to/mappings.csv --organization hmt --show-unmapped
```

### Example CSV File

```csv
Type,Target,Label,Name
Class,http://arkumu.org/canonical/person/john-smith,John Smith,"John Smith, J. Smith, Smith John"
Class,http://arkumu.org/canonical/org/state-university,State University,"State University, University"
Property,http://arkumu.org/canonical/prop/birth-date,Birth Date,"birth date, birthDate, date of birth"
Class,http://arkumu.org/canonical/doc/correspondence-1850,Letter Collection,"Letters, Correspondence, Personal Letters"
```

### Output

The command provides detailed feedback:

```
Row 1: Updated John Smith → http://arkumu.org/canonical/person/john-smith
Row 1: Updated J. Smith → http://arkumu.org/canonical/person/john-smith
Row 2: Resource not found - Type: Class, Name: 'Missing Person'
Row 3: Would update State University → http://arkumu.org/canonical/org/state-university (DRY RUN)

Processing complete:
Updated: 2 resources
Not found: ['Class: Missing Person']
Skipped: 0 rows
Errors: 0
```

### Workflow

1. **Prepare CSV mapping file** with resource names and target canonical URIs
2. **Validate CSV format** using `--validate-only` flag
3. **Check unmapped resources** using `--show-unmapped` to see what needs mapping
4. **Run dry run** to preview changes and validate data
5. **Execute mapping** to apply canonical URI assignments
6. **Verify results** using the statistics output

### Service Architecture

This command uses the **CanonicalUriMappingService** from `arkumu.metadata.services.integration`:

- **Organization-scoped**: Resources are found within specific organization
- **Name-based matching**: Finds resources by exact name match (not URI)
- **Multiple names**: Supports comma-separated names for the same canonical URI
- **Type validation**: Validates resource types (Class/Property)
- **Transaction safety**: All changes in single atomic transaction

### Best Practices

- **Always specify organization** using `--organization` flag
- **Use exact resource names** as they appear in the database
- **Run validation first** to check CSV format
- **Check unmapped resources** before processing to understand scope
- **Always run dry run** to preview changes
- **Use multiple name variants** for flexible matching (e.g., "John Smith, J. Smith")

### Error Handling

- **Missing Type/Target**: Rows with empty required fields are skipped
- **Invalid resource type**: Non-Class/Property types are skipped
- **Resource not found**: Names not found in organization are logged
- **Database errors**: Individual row errors reported, transaction rolled back
- **Dry run rollback**: Dry runs automatically roll back all changes

### Advanced Options

```bash
# Validate CSV format without processing
--validate-only

# Show unmapped resources for organization
--show-unmapped

# Preview changes without applying
--dry-run

# Specify organization code (required)
--organization hmt
```

### Related Commands

- `reset_canonical_uris.py` - Resets/clears canonical URI assignments for an organization

### Technical Notes

- Uses **CanonicalUriMappingService** for proper service layer architecture
- **Organization-scoped queries** for resource isolation
- **Exact name matching** without slugification
- **Non-placeholder resources only** - skips placeholder/temporary resources
- **Atomic transactions** with rollback support for dry runs
- **UTF-8 CSV support** with proper encoding handling