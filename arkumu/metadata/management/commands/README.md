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
| Target | Canonical URI to assign | `http://arkumu.org/types/akteurin` |
| Label | Human-readable label (informational) | `John Smith` |
| Name | Comma-separated resource names to map to the same canonical URI | `Person, Actor, Individual` |

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
Class,http://arkumu.org/types/akteurin,Akteurin,"Person, Actor, Individual"
Class,http://arkumu.org/types/organisationseinheit,Organisationseinheit,"Organization, Institution, Agency"
Property,http://arkumu.org/properties/alternativer-titel,Alternativer Titel,"alternative_title, alt_title, alternative_name"
Class,http://arkumu.org/types/sammlung,Sammlung,"Collection, Archive, Series"
```

### Output

The command provides detailed feedback:

```
Row 1: Updated Person → http://arkumu.org/types/akteurin
Row 1: Updated Actor → http://arkumu.org/types/akteurin
Row 2: Resource not found - Type: Class, Name: 'Missing Class'
Row 3: Would update Organization → http://arkumu.org/types/organisationseinheit (DRY RUN)

Processing complete:
Updated: 2 resources
Not found: ['Class: Missing Class']
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
- **Multiple names**: Each row can map multiple comma-separated resource names to the same canonical URI
- **Type validation**: Validates resource types (Class/Property)
- **Transaction safety**: All changes in single atomic transaction

### Best Practices

- **Always specify organization** using `--organization` flag
- **Use exact resource names** as they appear in the database
- **Run validation first** to check CSV format
- **Check unmapped resources** before processing to understand scope
- **Always run dry run** to preview changes
- **Use multiple name variants** in a single row for flexible matching - all variants will get the same canonical URI (e.g., "John Smith, J. Smith, Smith John")

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