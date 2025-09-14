# Catalog Query Patterns: ORM vs SQL

This document explains the query patterns used in the catalog system, showing both Django ORM and equivalent SQL.

## 1. Getting Available Resource Types

### ORM Query
```python
type_counts = Triple.objects.filter(
    predicate__uri='http://www.w3.org/1999/02/22-rdf-syntax-ns#type',
    object__resource_type=ResourceType.CLASS
).values(
    'object__uri',
    'object__name'
).annotate(
    count=Count('subject', distinct=True)
).order_by('-count')[:20]
```

### Equivalent SQL
```sql
SELECT
    o.uri AS object__uri,
    o.name AS object__name,
    COUNT(DISTINCT t.subject_id) AS count
FROM metadata_triple t
JOIN metadata_resource p ON t.predicate_id = p.id
JOIN metadata_resource o ON t.object_id = o.id
WHERE
    p.uri = 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type'
    AND o.resource_type = 'CLASS'
GROUP BY o.uri, o.name
ORDER BY count DESC
LIMIT 20;
```

**Purpose**: Find all types (classes) in the system and count how many resources have each type.

## 2. Finding Projects by Canonical Type (CanonicalGraphService)

### ORM Query
```python
Triple.objects.filter(
    Q(predicate__uri=RDF_TYPE_URI) &
    (Q(object__canonical_uri=canonical_type_uri) | Q(object__uri=canonical_type_uri)) &
    Q(subject__organization=organization)
).values_list('subject_id', flat=True).distinct()
```

### Equivalent SQL
```sql
SELECT DISTINCT t.subject_id
FROM metadata_triple t
JOIN metadata_resource p ON p.id = t.predicate_id
JOIN metadata_resource o ON o.id = t.object_id
JOIN metadata_resource s ON s.id = t.subject_id
WHERE
    p.uri = 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type'
    AND (o.canonical_uri = 'http://arkumu.org/types/projekt'
         OR o.uri = 'http://arkumu.org/types/projekt')
    AND s.organization_id = (SELECT id FROM users_organization WHERE code = 'fuk');
```

**Purpose**: Find all entities of a specific type within an organization, using canonical URIs for cross-archive compatibility.

## 3. Fetching Subject-Centric Triples

### ORM Query
```python
Triple.objects.filter(
    subject_id__in=subject_ids
).select_related('predicate', 'object').only(
    'id', 'subject_id',
    'predicate__uri', 'predicate__canonical_uri',
    'object__id', 'object__uri', 'object__canonical_uri',
    'object__resource_type', 'object__value'
)
```

### Equivalent SQL
```sql
SELECT
    t.id, t.subject_id,
    pred.uri AS pred_uri, pred.canonical_uri AS pred_canon,
    obj.id AS object_id, obj.uri AS obj_uri,
    obj.value AS obj_value, obj.canonical_uri AS obj_canon,
    obj.resource_type AS obj_type
FROM metadata_triple t
JOIN metadata_resource pred ON pred.id = t.predicate_id
JOIN metadata_resource obj ON obj.id = t.object_id
WHERE t.subject_id = ANY(ARRAY['uuid1', 'uuid2', ...]);
```

**Purpose**: Get all properties and relationships for a set of subjects (1-hop graph expansion).

## 4. Faceted Search with Literal Values

### ORM Query
```python
Triple.objects.filter(
    subject_id__in=harmonized_resource_ids,
    object__resource_type=ResourceType.LITERAL,
    object__value__icontains=query
).select_related('subject').values_list('subject_id', flat=True).distinct()
```

### Equivalent SQL
```sql
SELECT DISTINCT t.subject_id
FROM metadata_triple t
JOIN metadata_resource o ON t.object_id = o.id
WHERE
    t.subject_id = ANY(ARRAY['uuid1', 'uuid2', ...])
    AND o.resource_type = 'LITERAL'
    AND LOWER(o.value) LIKE LOWER('%search_term%');
```

**Purpose**: Find resources that have literal values containing the search query.

## 5. Cross-Archive Discovery via Shared Literals

### ORM Query
```python
Triple.objects.filter(
    predicate=title_property,
    object=shared_literal
).select_related('subject')
```

### Equivalent SQL
```sql
SELECT t.*, s.*
FROM metadata_triple t
JOIN metadata_resource s ON t.subject_id = s.id
WHERE
    t.predicate_id = 'title_property_uuid'
    AND t.object_id = 'shared_literal_uuid';
```

**Purpose**: Find all entities across different archives that share the same property-value combination.

## 6. Getting Facet Values for Properties

### ORM Query
```python
Triple.objects.filter(
    subject_id__in=resource_ids,
    predicate__uri=property_uri,
    object__resource_type=ResourceType.LITERAL
).values('object__value').annotate(
    count=Count('subject', distinct=True)
).order_by('-count')[:100]
```

### Equivalent SQL
```sql
SELECT
    o.value AS object__value,
    COUNT(DISTINCT t.subject_id) AS count
FROM metadata_triple t
JOIN metadata_resource p ON t.predicate_id = p.id
JOIN metadata_resource o ON t.object_id = o.id
WHERE
    t.subject_id = ANY(ARRAY['uuid1', 'uuid2', ...])
    AND p.uri = 'http://arkumu.org/properties/title'
    AND o.resource_type = 'LITERAL'
GROUP BY o.value
ORDER BY count DESC
LIMIT 100;
```

**Purpose**: Get the top values for a specific property to use as facets in search filtering.

## Key Performance Considerations

### Indexes Used
- `metadata_triple(subject_id, predicate_id)` - Subject-centric browsing
- `metadata_triple(object_id, predicate_id)` - Type lookups
- `metadata_triple(predicate_id)` - Property filtering
- `metadata_resource(canonical_uri)` - Canonical URI matching
- `metadata_resource(uri)` - URI lookups
- `metadata_resource(organization_id)` - Organization filtering

### Query Optimization Strategies

1. **Use select_related() for joins**: Reduces N+1 queries
   ```python
   Triple.objects.filter(...).select_related('predicate', 'object')
   ```

2. **Use only() to limit fields**: Reduces data transfer
   ```python
   .only('id', 'subject_id', 'predicate__uri', 'object__value')
   ```

3. **Use values() for aggregations**: More efficient than loading full objects
   ```python
   .values('object__uri').annotate(count=Count('subject'))
   ```

4. **Chunk large result sets**: Use iterator() for memory efficiency
   ```python
   for triple in triples.iterator(chunk_size=2000):
       process(triple)
   ```

## Common Query Patterns

### Pattern 1: Entity → Properties → Values
Used to get all information about specific entities.
```
Subject (entity) → Predicate (property) → Object (value/reference)
```

### Pattern 2: Type → Entities → Properties
Used to browse entities by type and their properties.
```
Type (class) ← rdf:type ← Entity → Properties → Values
```

### Pattern 3: Value → Properties → Entities
Used for reverse lookups (find entities with specific values).
```
Literal (value) ← Property ← Entity
```

### Pattern 4: Canonical Property Grouping
Used for cross-archive aggregation.
```
Entity → Canonical Property → Shared Literal
```

## Query Monitoring in Development

The CatalogExplorerView captures and displays:
- Total query time
- Number of SQL queries executed
- Individual query SQL and execution time
- Query patterns for optimization

Enable Django debug toolbar or use `connection.queries` to monitor:
```python
from django.db import connection
queries_before = len(connection.queries)
# ... perform operations ...
new_queries = connection.queries[queries_before:]
```