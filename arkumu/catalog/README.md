# Catalog Explorer

## Overview

The Catalog app provides a graph-based exploration interface for browsing RDF data through a hierarchical navigation system: **Classes → Properties → Literal Values**.

## Architecture

### Service Layer

**GraphSearchService** (`services/graph_search_service.py`)
- Core service for navigating the RDF graph structure
- Provides efficient queries for exploring entities, properties, and values
- Caches frequently accessed data for performance

### Views

The explorer uses three HTMX-powered views for dynamic, interactive browsing:

1. **CatalogExplorerView** - Main interface with class selector
2. **CatalogExplorerPropertiesView** - HTMX endpoint for loading properties of selected class
3. **CatalogExplorerLiteralsView** - HTMX endpoint for browsing literal values with pagination

## How It Works

### Navigation Flow

```
1. Select Class (Entity Type)
   ↓
2. View Available Properties for that Class
   ↓
3. Browse Literal Values for Selected Property
   ↓
4. Paginate Through Results (20 per page)
```

### Key Features

- **Graph-Based Browsing**: Navigate RDF data through its natural graph structure
- **Dynamic Loading**: Uses HTMX for seamless updates without page refreshes
- **Efficient Caching**: 5-minute cache on class and property queries
- **Paginated Results**: Database-level pagination for large datasets
- **Access Control**: Respects user permissions and organization scoping

### Example Usage

1. **Select a Class**: Choose "Person" to see all person entities
2. **Pick a Property**: Select "name" to view name values
3. **Browse Values**: See all unique name values with usage counts
4. **Search Within**: Filter values with search terms
5. **Navigate Pages**: Move through paginated results

## API Methods

### GraphSearchService

```python
# Get available entity types with counts
get_classes_with_counts(limit=50)

# Get properties for a specific class
get_properties_for_class(class_uri, limit=30)

# Browse literal values for a property
browse_property_values(property_uri, class_uri, search_term, offset, limit)

# Get available types for dropdown
get_available_types()

# Get searchable properties
get_available_properties(class_uri)
```

## Templates

- `catalog/explorer_sidebar.html` - Main explorer interface
- `catalog/partials/properties_list.html` - Property dropdown
- `catalog/partials/literals_list.html` - Literal values display
- `catalog/partials/literals_results_section.html` - Results grid

## URL Endpoints

- `/catalog/` - Main explorer interface
- `/catalog/explorer/` - Alternate explorer URL
- `/catalog/explorer/properties/` - HTMX properties loader
- `/catalog/explorer/literals/` - HTMX literals browser

## Technical Details

### Caching Strategy
- Classes cached for 5 minutes
- Properties cached per class for 5 minutes
- Literal values not cached (real-time data)

### Performance Optimizations
- Database-level pagination
- Efficient COUNT queries with filters
- Prefetch related data where possible
- Index usage on URI and type fields

### Data Model
Works with RDF triple store structure:
- **Resources**: Entities, Classes, Properties, Literals
- **Triples**: Subject-Predicate-Object relationships
- **Canonical URIs**: Harmonized identifiers for cross-organization data

## Development Notes

This is a lightweight, experimental interface for exploring RDF graph data. It demonstrates:
- Efficient graph traversal patterns
- HTMX for dynamic UI updates
- Django view composition with mixins
- Cache-aware service architecture

---

# Project Index Table

The catalog module provides a unified, denormalized index table for fast project search and display. This table is derived from the canonical RDF triplestore and Resource models.

## Tables Overview

| Table | DB Name | Purpose |
|-------|---------|---------|
| `ProjectIndex` | `project_index` | Unified index for cards, search, and detail views |
| `PreviewImages` | `catalog_previewimages` | Cached S3 image binaries |

## ProjectIndex

A single unified table combining card display, search filtering, and detail view data.

### Field Categories

**Core Display Fields:**
- `title`, `subtitle`, `description`, `image` - Text content
- `year_range` - Formatted year range string
- `institution_label`, `institution_uri` - Institution info

**Flat Arrays (GIN indexed for search):**
- `category_labels` - Category names for filtering
- `category_slugs` - Category slugs
- `actor_names` - Actor names for filtering
- `year_values` - Integer array for year range queries
- `catchphrase_labels` - Catchphrase labels
- `digital_object_paths` - File paths

**Structured JSON (for detail views):**
- `categories` - `[{label, uri, slug}]`
- `actors` - `[{name, roles, uri}]`
- `events` - `[{id, name, start, end, location, actors}]`
- `digital_objects` - `[{path, uri}]`
- `properties`, `status`, `authority` - Metadata bundles

**Full Record:**
- `record_jsonb` - Complete `ProjectRecord` as JSON

### Indexes

- GIN trigram indexes on `title`, `subtitle` for fuzzy search
- GIN indexes on `category_labels`, `actor_names`, `year_values` for array filtering
- Composite index on `org_code`, `public_access_level`, `is_public_approved`

### Methods

- `to_card_dict()` - Build card payload for catalog grid
- `to_record()` - Materialize full ProjectRecord from JSON
- `to_view_context()` - Build context for detail view templates

## PreviewImages

Local cache of preview images from S3.

**Key fields:**
- `bucket`, `path` - S3 location (unique together)
- `img` - Binary image data
- `content_type`, `content_length` - HTTP response headers

## Syncing Data

### Rebuild Project Index

```bash
# Rebuild from snapshot (default)
docker compose -f docker-compose.local.yml run --rm django \
    python manage.py rebuild_project_index

# Rebuild from graph (faster, recommended)
docker compose -f docker-compose.local.yml run --rm django \
    python manage.py rebuild_project_index --backend graph

# Rebuild specific project(s) only
docker compose -f docker-compose.local.yml run --rm django \
    python manage.py rebuild_project_index --project-uri "http://example.org/project/123"
```

**Options:**

| Flag | Description |
|------|-------------|
| `--backend snapshot` | Use ProjectSnapshot (default) |
| `--backend graph` | Use canonical graph directly (faster) |
| `--project-uri URI` | Rebuild specific project(s), repeatable |
| `--force-snapshot` | Force snapshot refresh first |

### Clear Caches After Rebuild

```bash
# Clear dropdown cache
docker compose -f docker-compose.local.yml run --rm django \
    python manage.py shell -c "from django.core.cache import cache; cache.delete('arkumu:advanced_search:dropdown_options')"

# Or clear all cache
docker compose -f docker-compose.local.yml run --rm django \
    python manage.py shell -c "from django.core.cache import cache; cache.clear()"
```

### Download Preview Images

```bash
docker compose -f docker-compose.local.yml run --rm django \
    python manage.py download_preview_imgs
```

## Data Flow

```
Triplestore (RDF)
       |
       v
  Resource Model
       |
       v
ProjectSnapshot ─────> rebuild_project_index ─────> ProjectIndex
       |                                              (unified)
       v
 ProjectRecord
```

### Graph Backend Architecture (Optimized)

The `--backend graph` option uses a batch pre-compute architecture for fast rebuilds (~25-45 seconds for 4700+ projects):

```
CanonicalGraphService.get_project_graph()
       |
       v
  edges_by_subject (dict)     ← O(1) edge lookups
       |
       v
 _expand_event_junctions()    ← Batch fetch junction entities
       |
       v
 _junctions_by_event          ← Reverse index: event → junctions
 _junctions_by_project        ← Reverse index: project → junctions
       |
       v
 _batch_precompute_all_fields()  ← Extract ALL fields in ONE pass
       |                            - Pass 1: Direct project edges
       |                            - Pass 2: Related entity names
       |                            - Pass 3: Actors via junctions
       |                            - Pass 4: Finalize (sets → lists)
       v
 _project_cache (dict)        ← project_id → {all fields}
       |
       v
 _write_indexes_from_graph()  ← O(1) dict lookups per project
       |
       v
  bulk_create()               ← Single DB write
```

**Key optimizations:**
- Single pass through graph data extracts all fields
- Pre-built reverse indexes for O(1) junction lookups
- No per-project DB queries during projection loop
- Bulk write with upsert (insert or update)

## When to Rebuild

1. **New projects ingested** - After importing new RDF data
2. **Project metadata updated** - After modifying triples
3. **Resource visibility changed** - After `public_access_level` or `is_public_approved` changes
4. **Schema changes** - After modifying index table fields
5. **Fresh deployment** - To ensure index matches current data

## Services

| Service | Purpose |
|---------|---------|
| `ProjectIndexDbService` | Builds/updates the index table |
| `ProjectIndexService` | Query interface for cards with filtering |
| `ProjectDetailIndexService` | Builds records from graph (bypasses index) |

## Admin

Registered in Django admin at `/admin/catalog/`:

- **Project Index** - View all project data with search, JSON previews
- **Preview Images** - View cached images with thumbnails

## Troubleshooting

### Actors not appearing in advanced search

1. Rebuild index: `python manage.py rebuild_project_index --backend graph`
2. Clear cache: `cache.delete('arkumu:advanced_search:dropdown_options')`

### Stale data in catalog

1. Check `built_at` timestamp in admin
2. Rebuild with `--backend graph`

### Missing preview images

1. Run `python manage.py download_preview_imgs`
2. Check S3 credentials in settings

### Index out of sync with Resources

The index links to `Resource` via `project_resource` FK. If a Resource is deleted, the index row cascades. If visibility changes, rebuild to update.