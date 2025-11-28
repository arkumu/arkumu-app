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

# Project Index Tables

The catalog module also provides denormalized, indexed tables for fast project search and display. These tables are derived from the canonical RDF triplestore and Resource models.

## Tables Overview

| Table | DB Name | Purpose | Data Source |
|-------|---------|---------|-------------|
| `ProjectIndex` | `projects_index` | Card display & text search | Snapshot/Graph |
| `ProjectRecordIndex` | `project_records` | Full record cache with JSON | Snapshot/Graph |
| `ProjectDetailIndex` | `project_detail_index` | Structured detail view data | Graph only |
| `PreviewImages` | `catalog_previewimages` | Cached S3 image binaries | S3 |

## Table Details

### ProjectIndex

Lightweight projection for catalog card listings and search results.

**Key fields:**
- `title`, `subtitle`, `image` - Display fields
- `categories` - ArrayField of category labels
- `actor_names` - ArrayField of actor names
- `institution_label` - Denormalized institution name
- `year_range` - Formatted year range string

**Indexes:**
- GIN trigram indexes on `title`, `subtitle` for fuzzy search
- GIN indexes on `categories`, `actor_names` for array containment
- Composite index on `org_code`, `public_access_level`, `is_public_approved`

**Usage:** Powers the catalog card grid and advanced search filtering.

### ProjectRecordIndex

Full project record cache with searchable helper columns.

**Key fields:**
- All fields from `ProjectIndex` plus:
- `description` - Project description
- `category_labels`, `category_slugs` - Separate arrays for display/filtering
- `year_values` - Integer array for year range queries
- `record_jsonb` - Complete `ProjectRecord` as JSON

**Usage:** Advanced search with complex filters, full record materialization via `to_record()`.

### ProjectDetailIndex

Structured data for project detail views with typed JSON columns.

**Key fields:**
- `categories` - JSON array: `[{label, uri, slug}]`
- `actors` - JSON array: `[{name, roles, uri}]`
- `events` - JSON array: `[{id, name, start, end, location, actors}]`
- `digital_objects` - JSON array: `[{path, access_url}]`
- `properties` - JSON dict: dauer, tonarten, etc.
- `authority` - JSON dict: wikidata_ids, gnd_ids

**Usage:** Project detail page rendering via `to_view_context()`.

### PreviewImages

Local cache of preview images from S3.

**Key fields:**
- `bucket`, `path` - S3 location (unique together)
- `img` - Binary image data
- `content_type`, `content_length` - HTTP response headers

**Usage:** Serve preview images without S3 round-trips.

## Syncing Data

### Rebuild Project Index Tables

The primary command to sync all index tables:

```bash
# Default: rebuild from snapshot (ProjectIndex + ProjectRecordIndex)
docker compose -f docker-compose.local.yml run --rm django \
    python manage.py rebuild_project_index

# Rebuild from graph (all three tables, faster)
docker compose -f docker-compose.local.yml run --rm django \
    python manage.py rebuild_project_index --backend graph

# Rebuild specific project(s) only
docker compose -f docker-compose.local.yml run --rm django \
    python manage.py rebuild_project_index --project-uri "http://example.org/project/123"

# Force snapshot refresh before rebuild
docker compose -f docker-compose.local.yml run --rm django \
    python manage.py rebuild_project_index --force-snapshot
```

**Options:**

| Flag | Description |
|------|-------------|
| `--backend snapshot` | Use ProjectSnapshot (default) |
| `--backend graph` | Use canonical graph directly (faster, includes ProjectDetailIndex) |
| `--project-uri URI` | Rebuild specific project(s), repeatable |
| `--force-snapshot` | Force snapshot refresh first (snapshot backend only) |

### Clear Caches After Rebuild

The advanced search caches dropdown options for 1 hour. Clear after rebuilding:

```bash
# Clear dropdown cache
docker compose -f docker-compose.local.yml run --rm django \
    python manage.py shell -c "from django.core.cache import cache; cache.delete('arkumu:advanced_search:dropdown_options')"

# Or clear all cache
docker compose -f docker-compose.local.yml run --rm django \
    python manage.py shell -c "from django.core.cache import cache; cache.clear()"
```

### Download Preview Images

Sync preview images from S3:

```bash
docker compose -f docker-compose.local.yml run --rm django \
    python manage.py download_preview_imgs
```

## Data Flow

```
Triplestore (RDF)
       |
       v
  Resource Model  ──────────────────────────────┐
       |                                        |
       v                                        v
ProjectSnapshot ─────────> rebuild_project_index
       |                          |
       v                          v
 ProjectRecord          ┌─────────┴─────────┐
                        |                   |
                        v                   v
              ProjectIndex          ProjectRecordIndex
              (cards/search)        (full records + JSON)
                                            |
                                            v
                                   ProjectDetailIndex
                                   (detail view data)
```

## When to Rebuild

Rebuild the index tables when:

1. **New projects ingested** - After importing new RDF data
2. **Project metadata updated** - After modifying triples
3. **Resource visibility changed** - After `public_access_level` or `is_public_approved` changes
4. **Schema changes** - After modifying index table fields
5. **Fresh deployment** - To ensure indexes match current data

## Index Services

| Service | Purpose |
|---------|---------|
| `ProjectIndexDbService` | Builds/updates all three index tables |
| `ProjectIndexService` | Query interface for cards with filtering |
| `ProjectDetailIndexService` | Query interface for detail views |

## Admin

All tables are registered in Django admin at `/admin/catalog/`:

- **Project Index** - View/search card projections
- **Project Record Index** - View full records with JSON preview
- **Project Detail Index** - View structured detail data
- **Preview Images** - View cached images with thumbnails

## Troubleshooting

### Actors not appearing in advanced search

1. Rebuild index: `python manage.py rebuild_project_index --backend graph`
2. Clear cache: `cache.delete('arkumu:advanced_search:dropdown_options')`

### Stale data in catalog

1. Check `built_at` timestamp in admin
2. Rebuild with `--force-snapshot` or `--backend graph`

### Missing preview images

1. Run `python manage.py download_preview_imgs`
2. Check S3 credentials in settings

### Index out of sync with Resources

The index tables link to `Resource` via `project_resource` FK. If a Resource is deleted, the index row cascades. If Resource visibility changes, rebuild to update the index.