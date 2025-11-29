# Controlled Vocabulary Migration Proposal

## Problem

Currently, each organization maintains copies of controlled vocabulary (CV) entities instead of referencing the shared CV directly.

**Current state (duplicated):**
```
Project → fuk/entities/projektkategorie/98 → (copy of CV data)
Project → khm/entities/projektkategorie/128 → (copy of CV data)
```

**Desired state (single source of truth):**
```
Project → types/projektkategorie/project-category-98 → (CV directly)
```

## Analysis

### Controlled Vocabularies

| CV Type | CV Entities | Description |
|---------|-------------|-------------|
| projektkategorie | 291 | Project categories |
| rolle | 404 | Actor roles |
| organisationseinheit | 228 | Organizational units |
| informationstraegertyp | 135 | Information storage media types |
| ereignistyp | 64 | Event types |
| equipmentart | 58 | Equipment types |
| projektart | 13 | Project types |

### Org-Specific Copies

| CV Type | Org | Org Entities | References | CV Pattern |
|---------|-----|--------------|------------|------------|
| **projektkategorie** | fuk | 286 | 833 | `project-category-{id}` |
| | hmt | 18 | 1,013 | |
| | khm | 59 | 6,815 | |
| **rolle** | fuk | 381 | 18,379 | `role-{id}` |
| **organisationseinheit** | fuk | 229 | 737 | `organisational-unit-{id}` |
| **projektart** | fuk | 14 | 715 | `autonomous-project`, `bachelor-thesis`, etc. |
| **ereignistyp** | fuk | 54 | 1,124 | `event-type-{id}` |
| **equipmentart** | fuk | 57 | 27 | `equipment-type-{id}` |
| **informationstraegertyp** | fuk | 135 | 0 | `information-storage-medium-type-{id}` |

**Total references to migrate: ~29,643**

## CV URI Patterns

| CV Type | Pattern |
|---------|---------|
| projektkategorie | `types/projektkategorie/project-category-{id}` |
| rolle | `types/rolle/role-{id}` |
| organisationseinheit | `types/organisationseinheit/organisational-unit-{id}` |
| projektart | `types/projektart/{slug}` (not numeric) |
| ereignistyp | `types/ereignistyp/event-type-{id}` |
| equipmentart | `types/equipmentart/equipment-type-{id}` |
| informationstraegertyp | `types/informationstraegertyp/information-storage-medium-type-{id}` |

## Migration Commands

### Already Created

1. **`link_to_cv`** - Links org entities to CV (copies data from CV to org entities)
2. **`migrate_to_cv`** - Redirects references from org entities to CV entities
3. **`set_self_canonical`** - Sets canonical_uri for shared predicates

### Migration Steps

For each CV type:

```bash
# 1. Dry run to see impact
python manage.py migrate_to_cv --all-orgs --entity-type <type> --cv <cv-type> --dry-run

# 2. Migrate references
python manage.py migrate_to_cv --all-orgs --entity-type <type> --cv <cv-type>

# 3. Cleanup orphaned org entities
python manage.py migrate_to_cv --all-orgs --entity-type <type> --cv <cv-type> --cleanup

# 4. Rebuild index
python manage.py rebuild_project_index
```

## Migration Order (Recommended)

1. **projektkategorie** - Already analyzed, 8,661 refs
2. **ereignistyp** - 1,124 refs
3. **projektart** - 715 refs (NOTE: slug-based, needs custom mapping)
4. **organisationseinheit** - 737 refs
5. **rolle** - 18,379 refs (largest, do last)
6. **equipmentart** - 27 refs
7. **informationstraegertyp** - 0 refs (no migration needed)

## Special Cases

### projektart
Uses slugs instead of numeric IDs:
- `types/projektart/autonomous-project`
- `types/projektart/bachelor-thesis`

Org entities may use different ID patterns. Requires custom mapping logic.

### rolle
Largest migration (18,379 references). Consider:
- Running during low-traffic period
- Breaking into smaller batches per org

## Command Enhancements Needed

The `migrate_to_cv` command currently assumes:
- CV pattern: `types/{cv}/project-category-{id}` (hardcoded for projektkategorie)

To support all CV types, add:
- `--cv-pattern` parameter for custom URI patterns
- Or auto-detect pattern from CV type

## Benefits After Migration

1. **Single source of truth** - CV changes apply everywhere
2. **Reduced duplication** - No org-specific copies
3. **Simpler queries** - Direct CV references
4. **Consistent labels** - All orgs see same labels

## Risks

1. **Data loss** - If org entity has custom data not in CV
2. **Missing CV entries** - Some org IDs may not exist in CV
3. **Performance** - Large migrations (rolle) may be slow

## Pre-Migration Checklist

- [ ] Backup database
- [ ] Verify all CV entries exist for org entity IDs
- [ ] Check for custom data on org entities not in CV
- [ ] Test migration on staging environment
- [ ] Plan rollback procedure
