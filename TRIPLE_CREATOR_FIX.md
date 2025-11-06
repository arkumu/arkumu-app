# Triple Creator Widget Fix - WIP

## Issue
Triple creator widget was showing as teal placeholders instead of interactive HTMX widgets in the simplified workspace.

## Root Cause
The promoted manifest in the database was incomplete - property URIs and widget metadata were `None`.

## Fix Applied (2025-11-06)

### 1. Regenerated Promoted Manifest
```bash
docker compose -f docker-compose.local.yml run --rm django \
  python manage.py create_promoted_schema_manifest --organization=fuk
```

This correctly populated:
- `widget: "TripleCreatorWidget"`
- `predicate_uri: http://arkumu.org/data/fuk/properties/projekt-hat-teil`
- `source_property_uri` in FK relationships
- `source_canonical_property` in FK relationships

### 2. Cleared Schema Cache
```bash
docker compose -f docker-compose.local.yml run --rm django \
  python manage.py shell -c "from django.core.cache import cache; cache.delete_pattern('complete_schema_blueprints_*')"
```

### 3. Verified Configuration
- ✅ `METADATA_SCHEMA_MANIFEST_KEY = "promoted_manifest"` (correct)
- ✅ Property resources exist in database
- ✅ Promoted manifest now has complete metadata

## Current Status
✅ Widget now displays correctly (interactive instead of teal placeholders)
❌ **Cannot save** - validation or submission issue

## Data Flow Verified

1. **Promoted Manifest Creation** (`create_promoted_schema_manifest.py`)
   - ✅ Generates complete FK relationships with URIs

2. **Schema Loading** (`mapping_adapter.py:99-104`)
   - ✅ Loads `promoted_manifest` from `mapping_config`
   - ✅ Replaces sections: `workspace_columns`, `schema_manifest`, `fk_relationships`

3. **Metadata Processing** (`services.py:630-670`)
   - ✅ Builds FK lookup from relationships
   - ✅ Copies complete FK relationship data to field metadata

4. **Widget Selection** (`simplified_workspace_views.py:571-589`)
   - ✅ Checks `property_uri`, `source_property_uri`, `source_canonical_property`
   - ✅ Matches against `PROJECT_TRIPLE_PREDICATE_SLUGS`
   - ✅ Assigns `TripleCreatorWidget`

## Next Steps
- [ ] Debug save functionality
- [ ] Check HTMX endpoints are receiving POST data correctly
- [ ] Verify triple relationship persistence logic
- [ ] Test end-to-end: add triple → save → reload → verify triple exists

## Affected Predicates (FUK)
- projekt-hat-teil
- projekt-ist-teil-von
- projekt-hat-bezug-zu
- projekt-basiert-auf
- projekt-ist-vorbereitend-fuer
- ereignis-hat-akteurin
- akteurin-im-ereignis
- akteurin-hat-rolle-im-ereignis
