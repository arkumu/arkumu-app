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