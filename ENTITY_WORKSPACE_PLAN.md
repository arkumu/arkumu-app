# Entity Workspace Improvement Plan

## Context & Problem Statement

### Current Architecture
The system uses **triple-based RDF storage** (Resource → Property → Value) instead of traditional relational database tables. Data is imported from legacy SQL databases via mappings that define:
- Entity types (Classes)
- Properties
- FK relationships
- Junction tables

**Key Models:**
- `Resource` (arkumu/metadata/models/resource.py) - All entities, properties, and literals
- `Triple` (arkumu/metadata/models/triples.py) - Subject → Predicate → Object relationships
- `Mapping` - Defines schema from legacy SQL exports

### The Problem
1. **Relational baggage in RDF**: Current mapping creates triples with SQL implementation details:
   - FK column names appear as properties (`Ereignis_Nr_fk` instead of semantic `has_event`)
   - Junction tables become intermediate entities instead of direct relationships
   - Multi-value columns handled via comma separation

2. **Cluttered workspace**: Shows ALL datasets including:
   - Main entities (Project, Event, Actor)
   - Junction tables (Kreuz_Ereignis_Akteure)
   - Technical implementation details

3. **No hierarchy**: Users can't easily create Project → Event → Actor flows

### Desired Semantic Model
From `arkumu/projects/models.py` - this is the clean structure we want:

```python
Project
  ├─ events: List[ProjectEvent]           # Direct relationship!
  │   └─ actors: List[ProjectEventActor]  # With roles
  ├─ actors: List[ProjectActor]           # Project-level actors
  ├─ digital_objects: List[DigitalObject]
  ├─ categories: List[ProjectCategory]
  └─ institution: ProjectInstitution
```

**NOT** the relational mess:
```
Projekt table
├─ Kreuz_Projekt_Ereignis (junction!)
│   └─ Ereignis table
│       └─ Kreuz_Ereignis_Akteure (junction!)
│           └─ Rolle column
│           └─ Akteurin table
```

## Solution Architecture

### Two-Tier Entity System

#### 1. Main Entities (All Users)
From type classes (ignore `-kreuztabelle` suffixes):
- **Projekt** (Project) - Central entity
- **Ereignis** (Event) - Linked to projects
- **Akteurin** (Actor/Person/Organization)
- **Digitales Objekt** (Digital Object)
- **Informationsträger** (Information Carrier/Physical Media)

#### 2. Controlled Vocabularies (Admin/Curator Only)
Reference data for dropdowns and validation:
- **Ereignistyp** (Event Type)
- **Rolle** (Role)
- **Projektkategorie** (Project Category)
- **Projektart** (Project Type)
- **Informationsträgertyp** (Media Type)
- **Schlagwort** (Keyword)
- **Sprache** (Language)
- **Ort** (Place)
- **Organisationseinheit** (Organizational Unit)

### Workspace Layout

```
┌─ Sidebar ─────────────────────┐   ┌─ Main Panel ─────────────────┐
│ [Mapping Selector]            │   │                              │
│                               │   │  [Dataset Form]              │
│ === Main Entities ===         │   │                              │
│  • Projekt              [42]  │   │  Field Name *                │
│  • Ereignis            [128]  │   │  [input]                     │
│  • Akteurin             [89]  │   │                              │
│  • Digitales Objekt     [56]  │   │  Multi-value Field           │
│  • Informationsträger   [34]  │   │  [input] [×]                 │
│                               │   │  [input] [×]                 │
│ === Controlled Vocab ===      │   │  [+ Add another]             │
│  🔒 Ereignistyp        [12]   │   │                              │
│  🔒 Rolle               [8]   │   │  FK Field                    │
│  🔒 Projektkategorie    [5]   │   │  [Searchable select]         │
│  🔒 ...                       │   │                              │
└───────────────────────────────┘   └──────────────────────────────┘
```

## Implementation Tasks

### Phase 1: Filter & Organize Datasets ✓ Current Branch

**File:** `arkumu/metadata/schema_workspace/services.py`

```python
def list_datasets(self) -> List[DatasetSummary]:
    summaries = []
    for dataset_name in self._schema_service.list_datasets():
        schema = self._schema_service.get_dataset_schema(dataset_name)

        # Skip junction tables
        if schema.get('junction_schema'):
            continue

        # Categorize by type
        is_controlled_vocab = self._is_controlled_vocabulary(dataset_name, schema)

        summaries.append(DatasetSummary(
            dataset_name=dataset_name,
            display_label=...,
            is_controlled_vocab=is_controlled_vocab,
            requires_admin=is_controlled_vocab,
            ...
        ))

    return sorted(summaries, key=lambda x: (x.is_controlled_vocab, x.display_label))

def _is_controlled_vocabulary(self, dataset_name: str, schema: Dict) -> bool:
    """Detect controlled vocabularies by name patterns."""
    vocab_patterns = [
        'typ', 'art', 'kategorie', 'rolle', 'schlagwort',
        'sprache', 'ort', 'einheit', 'lizenz'
    ]
    return any(pattern in dataset_name.lower() for pattern in vocab_patterns)
```

### Phase 2: Permission-Based Filtering

**File:** `arkumu/metadata/views/schema_workspace_views.py`

```python
def get(self, request, mapping_id=None):
    # ... existing code ...

    dataset_summaries = workspace_service.list_datasets()

    # Filter controlled vocabularies for non-admin users
    if not request.user.is_staff and not request.user.has_role('curator'):
        dataset_summaries = [
            ds for ds in dataset_summaries
            if not ds.is_controlled_vocab
        ]

    context = {
        'dataset_summaries': dataset_summaries,
        'main_entities': [ds for ds in dataset_summaries if not ds.is_controlled_vocab],
        'controlled_vocabs': [ds for ds in dataset_summaries if ds.is_controlled_vocab],
        'user_can_edit_vocabs': request.user.is_staff or request.user.has_role('curator'),
    }
```

### Phase 3: UI Sections

**File:** `arkumu/metadata/templates/metadata/entity_creation/workspace.html`

```django
<aside class="xl:col-span-4 space-y-6">
  <!-- Mapping selector -->

  <div class="card bg-base-100 border border-base-300 shadow-sm">
    <div class="card-body space-y-4">
      <h2 class="text-sm font-semibold uppercase tracking-wide text-base-content/60">
        Hauptentitäten
      </h2>
      <div class="space-y-2 max-h-[20rem] overflow-y-auto pr-1">
        {% for dataset in main_entities %}
          <button type="button" class="btn btn-sm w-full justify-between..."
                  hx-get="{% url 'metadata:entity_workspace_dataset' mapping.id %}?dataset={{ dataset.dataset_name }}">
            <span>{{ dataset.display_label }}</span>
            <span class="badge badge-outline">{{ dataset.entity_count }}</span>
          </button>
        {% endfor %}
      </div>
    </div>
  </div>

  {% if user_can_edit_vocabs %}
  <div class="card bg-base-100 border border-base-300 shadow-sm">
    <div class="card-body space-y-4">
      <h2 class="text-sm font-semibold uppercase tracking-wide text-base-content/60">
        Kontrollierte Vokabulare
      </h2>
      <div class="space-y-2 max-h-[20rem] overflow-y-auto pr-1">
        {% for dataset in controlled_vocabs %}
          <button type="button" class="btn btn-sm btn-ghost w-full justify-between...">
            <span class="flex items-center gap-2">
              <svg class="w-3 h-3"><!-- lock icon --></svg>
              {{ dataset.display_label }}
            </span>
            <span class="badge badge-outline badge-sm">{{ dataset.entity_count }}</span>
          </button>
        {% endfor %}
      </div>
    </div>
  </div>
  {% endif %}
</aside>
```

### Phase 4: Hierarchical Creation Flow (Future)

**Concept:** Project → Event → Actor flow that creates clean semantic triples

```python
# When creating Event for Project:
# Creates: Project_123 → has_event → Event_456
# NOT: Junction table entity

# When adding Actor to Event with Role:
# Creates: Event_456 → has_participant → Participation_1
#          Participation_1 → actor → Actor_789
#          Participation_1 → role → Role_Director
# NOT: Junction table with FK columns
```

## Technical Details

### Multi-Value Fields (Already Implemented ✓)

**UI:** Dynamic + button interface
```html
<input name="keywords[]" value="keyword1"> [×]
<input name="keywords[]" value="keyword2"> [×]
[+ Weiteren Wert hinzufügen]
```

**Backend:** `services.py:287-313`
- Parses JSON arrays from UI: `["value1", "value2"]`
- Falls back to CSV splitting for legacy imports: `"value1, value2"`
- Creates separate triple for each value

### FK Field Handling

**Current:** Shows technical column names
```
Ereignis_Nr_fk → Dropdown of Events
```

**Future:** Clean semantic names from mapping
```python
# In column metadata
{
    "column": "Ereignis_Nr_fk",
    "display_label": "Ereignis",  # Clean name
    "semantic_property": "has_event",  # For triple creation
    "fk_target": "02_hfm_Ereignis"
}
```

### Schema Service Integration

**File:** `arkumu/importer/services/schema_service.py`

The schema service already:
- ✓ Creates entity types from mapping
- ✓ Creates properties for all columns
- ✓ Maps FK relationships
- ✓ Identifies junction tables
- ✓ Caches blueprints (1h timeout)

**What's needed:**
- Add `is_controlled_vocab` flag to blueprints
- Add `semantic_property_name` to column metadata
- Filter junction tables from user-facing views

## Data Flow

### Import (Existing)
```
CSV Export (SQL dump)
  → Mapping Definition
  → Schema Service (creates blueprints)
  → Mapping Aware Processor
  → Triples (preserves SQL structure for compatibility)
```

### User Creation (New)
```
Workspace UI
  → Schema-driven form (from blueprints)
  → Clean entity data
  → SchemaWorkspaceService.save_entity()
  → Semantic triples (clean structure)
```

## Migration Strategy

### Backwards Compatibility
1. **Keep existing import pipeline** - No changes to mapping/import
2. **Dual triple creation** - Both old (FK columns) and new (semantic) properties
3. **Query layer handles both** - ProjectRecord builder works with either pattern
4. **Gradual transition** - Old data remains valid, new data uses clean model

### No Breaking Changes
- Existing triples remain untouched
- Existing queries still work
- ProjectRecord can read both patterns
- Controlled vocab editing doesn't affect main entities

## Next Steps

1. **Immediate (this session):**
   - ✓ Remove guided flow
   - ✓ Add multi-value + buttons
   - ✓ Remove technical badges
   - → Commit current state

2. **Next session:**
   - Implement dataset categorization
   - Add permission filtering
   - Update workspace UI with sections
   - Test with real mapping data

3. **Future:**
   - Hierarchical creation flows
   - Visual relationship builder
   - Property name mapping (technical → semantic)
   - RDF-star for qualified relationships

## Files to Modify

### Core Services
- `arkumu/metadata/schema_workspace/services.py` - Add categorization
- `arkumu/importer/services/schema_service.py` - Extend blueprints

### Views
- `arkumu/metadata/views/schema_workspace_views.py` - Permission filtering

### Templates
- `arkumu/metadata/templates/metadata/entity_creation/workspace.html` - UI sections
- `arkumu/metadata/templates/metadata/entity_creation/partials/_dataset_panel.html` - Already updated ✓

### Models (Reference Only)
- `arkumu/metadata/models/resource.py` - Triple storage
- `arkumu/metadata/models/triples.py` - Relationships
- `arkumu/projects/models.py` - Target semantic structure

## Testing Checklist

- [ ] Admin users see controlled vocabularies
- [ ] Regular users only see main entities
- [ ] Junction tables hidden from both
- [ ] Multi-value fields work with + button
- [ ] FK fields searchable/selectable
- [ ] Creating entity produces clean triples
- [ ] Existing import still works
- [ ] ProjectRecord queries work with new data

## Questions for Next Session

1. Should we add semantic property names to mapping definition or derive from column names?
2. How to handle cases where same FK appears in multiple contexts (reification vs simple links)?
3. Should controlled vocabs be read-only for most users or just require approval workflow?
4. Do we need versioning for controlled vocabulary changes?
