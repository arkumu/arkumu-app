# Enhanced Canonical URI Mapping Validation

## Issue Title
**Add comprehensive validation warnings for canonical URI mapping conflicts**

## Brief Description
The `map_canonical_uris` command needs better validation to prevent data modeling errors, especially when multiple ID fields are incorrectly mapped to the same canonical URI.

## Problem Statement
Currently, users can create invalid mappings where:
1. Multiple different ID fields map to the same canonical URI (logically impossible)
2. Existing canonical URIs get overwritten without warning
3. CSV inconsistencies (same field name → different target URIs) go undetected

## Expected Behavior
The validation should clearly distinguish between:
- ✅ **Valid harmonization**: Multiple descriptive fields → same canonical URI
- ❌ **Invalid ID sharing**: Multiple ID fields → same canonical URI  
- ⚠️ **Data loss warnings**: Existing canonical URIs being overwritten

## User Impact
Non-technical users need clear, actionable guidance to fix their CSV files before importing, preventing data corruption and logical inconsistencies in the canonical mapping system.

## Success Criteria
- [ ] Clear problem categorization (Info vs Warning vs Error)
- [ ] Non-technical explanations for CSV editors
- [ ] Specific examples using actual field names from the CSV
- [ ] Actionable fix instructions
- [ ] Prevention of invalid ID field mappings

## Technical Notes
- Affects `arkumu/metadata/management/commands/map_canonical_uris.py`
- Should integrate with existing `--validate-only` flag
- Must handle large CSV files efficiently (100+ mappable rows)