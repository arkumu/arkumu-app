# Controlled Vocabulary Management Commands

This document describes the management commands for working with controlled vocabularies (CVs) in Arkumu.

## Overview

Controlled vocabularies ensure consistent terminology across organizations. Each CV type (e.g., ereignistyp, projektkategorie) has canonical entries that all organizations reference.

**CV URI Pattern:** `http://arkumu.org/data/types/{cv_type}/{slug}`

Example: `http://arkumu.org/data/types/ereignistyp/event-type-5`

## Commands

### 1. `import_canonical_vocabularies`

Import CV definitions from canonical CSV files.

```bash
python manage.py import_canonical_vocabularies
python manage.py import_canonical_vocabularies --only event_types,roles
```

**When to use:** After updating CSV files in `data/canonical_vocabularies/`

---

### 2. `split_multivalue_literals`

Split comma-separated literal values into individual entity references.

```bash
python manage.py split_multivalue_literals --org hmt --predicate projektkategorie \
    --target-type projektkategorie --delete-literals --include-single-values
```

**Parameters:**
- `--org`: Organization code (khm, fuk, hmt)
- `--predicate`: Predicate containing multi-value literals
- `--target-type`: Entity type to create
- `--separator`: Value separator (default: `,`)
- `--delete-literals`: Remove original literal triples after splitting
- `--include-single-values`: Also process single values (not just multi-value)
- `--dry-run`: Preview changes without applying

**When to use:** When import stored comma-separated IDs as single literals (e.g., "135,124,126")

---

### 3. `link_to_cv`

Link organization entities to CV entries based on matching IDs.

```bash
python manage.py link_to_cv --org khm --entity-type projektkategorie --cv projektkategorie --dry-run
python manage.py link_to_cv --org khm --entity-type projektkategorie --cv projektkategorie
```

**Parameters:**
- `--org`: Organization code
- `--entity-type`: Type of org entities to link
- `--cv`: Target controlled vocabulary
- `--only-stubs`: Only link entities without outgoing triples
- `--rebuild-index`: Rebuild ProjectIndex after linking
- `--dry-run`: Preview changes

**When to use:** After `split_multivalue_literals` creates org entities that need CV linking

---

### 4. `migrate_to_cv`

Migrate entity references from org-specific URIs to canonical CV URIs.

```bash
python manage.py migrate_to_cv --org khm --entity-type projektkategorie --cv projektkategorie --dry-run
python manage.py migrate_to_cv --all-orgs --entity-type projektkategorie --cv projektkategorie --cleanup
```

**Parameters:**
- `--org` or `--all-orgs`: Organization(s) to process
- `--entity-type`: Entity type to migrate
- `--cv`: Target controlled vocabulary
- `--cleanup`: Delete orphaned org entities after migration
- `--rebuild-index`: Rebuild ProjectIndex after migration
- `--dry-run`: Preview changes

**URI Transformation:**
```
khm/entities/projektkategorie/128 -> types/projektkategorie/project-category-128
```

**When to use:** After `link_to_cv` when org entities should be replaced by CV references

---

### 5. `literal_to_cv`

Convert literal string values directly to CV entity references by matching labels.

```bash
python manage.py literal_to_cv --org khm --predicate ereignistyp --cv ereignistyp --dry-run
python manage.py literal_to_cv --org khm --predicate ereignistyp --cv ereignistyp
```

**Parameters:**
- `--org`: Organization code
- `--predicate`: Predicate name containing literal values
- `--cv`: Target controlled vocabulary
- `--verbose`: Show detailed matching information
- `--dry-run`: Preview changes

**How it works:**
1. Finds triples with literal objects for the given predicate
2. Matches literal text to CV entity German/English names (case-insensitive)
3. Updates triple to point to matched CV entity

**When to use:** When import stored CV values as text labels (e.g., "Filmfestival") instead of entity references

---

### 6. `cleanup_orphaned_literals`

Remove orphaned literal resources that are no longer referenced.

```bash
python manage.py cleanup_orphaned_literals --dry-run
python manage.py cleanup_orphaned_literals
```

**When to use:** After CV migrations to clean up unused literal resources

---

## Common Workflows

### Workflow A: Numeric ID Literals (HMT projektkategorie)

Data pattern: Project has literal "135,124,126" instead of entity references

```bash
# 1. Split comma-separated IDs into entity references
python manage.py split_multivalue_literals --org hmt --predicate projektkategorie \
    --target-type projektkategorie --delete-literals --include-single-values

# 2. Link org entities to CV
python manage.py link_to_cv --org hmt --entity-type projektkategorie --cv projektkategorie

# 3. Migrate org references to CV
python manage.py migrate_to_cv --org hmt --entity-type projektkategorie --cv projektkategorie

# 4. Rebuild index
python manage.py rebuild_project_index --backend graph
```

### Workflow B: Text Label Literals (KHM ereignistyp)

Data pattern: Event has literal "Filmfestival" instead of entity reference

```bash
# 1. Convert literals directly to CV by label matching
python manage.py literal_to_cv --org khm --predicate ereignistyp --cv ereignistyp

# 2. Rebuild index
python manage.py rebuild_project_index --backend graph
```

### Workflow C: Entity References Needing CV Migration

Data pattern: Triples point to org entities that should point to CV

```bash
# 1. Link org entities to CV (if not already linked)
python manage.py link_to_cv --org khm --entity-type rolle --cv rolle

# 2. Migrate references
python manage.py migrate_to_cv --org khm --entity-type rolle --cv rolle --cleanup

# 3. Rebuild index
python manage.py rebuild_project_index --backend graph
```

## Supported CV Types

| CV Type | Class URI | ID Format |
|---------|-----------|-----------|
| ereignistyp | types/ereignistyp | event-type-{id} |
| projektkategorie | types/projektkategorie | project-category-{id} |
| rolle | types/rolle | role-{id} |
| projektart | types/projektart | {slug} |
| organisationseinheit | types/organisationseinheit | organisational-unit-{id} |
| equipmentart | types/equipmentart | equipment-type-{id} |
| informationstraegertyp | types/informationstraegertyp | information-storage-medium-type-{id} |

## Debugging Tips

1. **Check current state:**
   ```python
   # In Django shell
   from arkumu.metadata.models import Triple, Resource, ResourceType

   # Find literal values for a predicate
   Triple.objects.filter(
       predicate__uri__contains='ereignistyp',
       object__resource_type=ResourceType.LITERAL
   ).values_list('object__value', flat=True).distinct()[:20]
   ```

2. **Verify CV entities exist:**
   ```python
   Resource.objects.filter(uri__startswith='http://arkumu.org/data/types/ereignistyp/').count()
   ```

3. **Always use `--dry-run` first** to preview changes before applying.
