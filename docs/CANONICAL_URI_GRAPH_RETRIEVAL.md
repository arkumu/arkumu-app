# Canonical URI–Aware Graph Retrieval (FUK Focus)

## Goal
Design an efficient, reusable query approach to retrieve the “main FUK graph” for projects while also including any resources that align via the same `canonical_uri`. This leverages the current Resource/Triple model and the FUK mapping/schema already in the database.

## What "Canonical" Means Here
- `Resource.canonical_uri` acts as a cross‑archive unifier:
  - Properties: set to canonical (institution‑agnostic) URIs for Arkumu‑compliant orgs (`rsh`, `det`, `fuk`).
  - Classes (types): same as properties — class resources get canonical URIs.
  - Literals: canonical literal URIs minted from the literal value + datatype (no org attached), so the same literal is shared across archives.
  - Entities (IRI instances): intentionally NOT canonicalized — remain institution-specific to preserve data provenance and source authority. Cross-archive discovery happens through shared canonical properties and literals.

## Where canonical_uri Is Filled
- In importer processing (mapping-aware):
  - Properties: `_generate_canonical_property_uri` drops `/{institution}/` in the property URI and stores it in `Resource.canonical_uri` when creating property resources.
  - Classes (entity types): `_generate_canonical_type_uri` does the same for class resources.
  - Control flag: Arkumu‑compliant orgs hardcoded as `{'rsh', 'det', 'fuk'}`.
- In resource management (values):
  - Literals minted via `ResourceManager.create_canonical_literal_uri(value, datatype)` so the literal `Resource.uri` itself is canonical and `organization` is `None`.

This means predicate/class unification works out of the box; value unification works as well. Entity instances remain institution-specific by design, enabling cross-archive discovery through shared canonical properties and values.

## FUK Mapping Facts That Matter
- FUK mapping `Mapping_20250828_170402` has dataset “Projekt” with anchor `fuk::Projekt::Projekt-ID`.
- During schema‑first processing, Arkumu creates:
  - A class (type) resource for Projekt with canonical URI (e.g., `http://arkumu.org/types/projekt`).
  - Property resources for each Projekt column with canonical URIs (e.g., `http://arkumu.org/properties/beschreibung`, etc.).
  - RDF triples of the shape: `entity —rdf:type→ projekt_type`, and property triples for each column mapped.
- FK relationships connect Projekt to Digitales_Objekt, Ereignis, AkteurIn, etc. These relations can be traversed to bring in the “whole project graph”.

## Canonical‑Aware Query Recipes
Below are efficient query patterns that leverage existing indexes.

Assumptions
- Tables: `metadata_resource` (Resource), `metadata_triple` (Triple).
- Indexes already present: on `metadata_triple(subject, predicate)`, `(object)`, `(object, predicate)`, `(predicate)`, `(source)` and on `metadata_resource(canonical_uri)`.
- `rdf:type` predicate URI: `http://www.w3.org/1999/02/22-rdf-syntax-ns#type`.

1) Find all FUK Project entities (subjects)
- Via canonical class match on the object side of rdf:type:

```
SELECT s.id AS subject_id
FROM metadata_triple t
JOIN metadata_resource p ON p.id = t.predicate_id
JOIN metadata_resource o ON o.id = t.object_id
JOIN metadata_resource s ON s.id = t.subject_id
WHERE p.uri = 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type'
  AND (o.canonical_uri = 'http://arkumu.org/types/projekt'
       OR o.uri = 'http://arkumu.org/types/projekt')
  AND s.organization_id = (SELECT id FROM users_organization WHERE code = 'fuk');
```

- Notes:
  - Uses `(object, predicate)` index to accelerate class lookup.
  - Restricts subjects to FUK via `s.organization_id` (keeps the result as “main FUK projects”).

2) Pull a project’s 1‑hop graph (all properties/relations)
- For a set of subject IDs (from step 1), fetch all triples:

```
SELECT t.id, t.subject_id, pred.uri AS pred_uri, pred.canonical_uri AS pred_canon,
       obj.id AS object_id, obj.uri AS obj_uri, obj.value AS obj_value,
       obj.canonical_uri AS obj_canon, obj.resource_type AS obj_type
FROM metadata_triple t
JOIN metadata_resource pred ON pred.id = t.predicate_id
JOIN metadata_resource obj  ON obj.id  = t.object_id
WHERE t.subject_id = ANY(%s);
```

- Canonical effect:
  - Predicates carry `canonical_uri`, so downstream consumers can group/merge by `pred_canon` across archives.
  - Literal objects are already canonical (shared URIs and `organization IS NULL`).

3) Canonical predicate filter (optional)
- If you want only “core” properties (e.g., DC‑relevant), filter by a known set of canonical property URIs (from schema blueprints or your DC crosswalk):

```
AND pred.canonical_uri = ANY(%s)  -- array of canonical property URIs
```

4) FK/Junction expansion (selective graph growth)
- Use schema blueprints (`SchemaService`) to identify FK properties for the Projekt dataset, then selectively expand one hop to related entities (Digitales_Objekt, Ereignis, etc.). Those expansions reuse patterns from (2) using the related entity IDs as new subjects.

5) Canonical class filter on neighbors (cross‑archive merge by type)
- When pulling related entities, use rdf:type + canonical class checks to include entities from any org that share the same type canon (e.g., all “digitales_objekt” regardless of org):

```
AND (neighbor_class.canonical_uri = %s OR neighbor_class.uri = %s)
```

## Performance Notes
- Current indexes support the key access paths:
  - `(object, predicate)` for rdf:type lookups.
  - `(subject, predicate)` for subject‑centric browsing.
  - `resource.canonical_uri` for canonical expansion.
- Optional improvements if needed:
  - Add an index on `metadata_triple(predicate, object)` specifically for rdf:type to accelerate class scans further.
  - Add a composite index on `metadata_resource(canonical_uri, resource_type)` to speed class/property filtering.

## Why Entity Canonicalization is NOT Needed

### Current Architecture is Correct
- Entity instances (rows) are intentionally institution‑scoped and should remain so:
  - Each institution's record is a distinct data point with its own provenance
  - FUK's "Projekt #123" and RSH's "Projekt #456" are separate records that may or may not represent the same real-world object
  - Institution-specific URIs preserve data source authority and lineage

### Cross-Archive Unification Already Works
The system achieves cross-archive discovery through the existing canonical layers:

1. **Canonical Properties**: All institutions use the same property URIs
   - `beschreibung` from FUK, RSH, and DET all map to `http://arkumu.org/properties/beschreibung`

2. **Canonical Literals**: Values are shared across all archives
   - The literal "Project Alpha" exists once as `http://arkumu.org/literals/[hash]`
   - Any entity referencing this value points to the SAME literal resource

3. **Graph Traversal Pattern**:
   ```
   Entity (institution-specific) → Property (canonical) → Literal (canonical)
   ```

   Example triple:
   - Subject: `http://arkumu.org/fuk/projekt/123` (FUK-specific)
   - Predicate: `http://arkumu.org/properties/title` (canonical)
   - Object: `http://arkumu.org/literals/project-alpha` (canonical)

### Why Entity Canonicalization Would Be Harmful
1. **No reliable matching mechanism**: How would the system know FUK row #123 equals RSH row #456?
2. **Different ID systems**: Each archive uses its own identification scheme
3. **Data integrity loss**: Merging entities would lose institution-specific variations and context
4. **Provenance destruction**: Would obscure which institution provided which data

### The Correct Query Pattern
To find related data across archives, query through the canonical layers:
```sql
-- Find all entities (from any archive) with a specific property-value pair
SELECT DISTINCT s.*
FROM metadata_triple t
JOIN metadata_resource s ON s.id = t.subject_id
JOIN metadata_resource p ON p.id = t.predicate_id
JOIN metadata_resource o ON o.id = t.object_id
WHERE p.canonical_uri = 'http://arkumu.org/properties/title'
  AND o.uri = 'http://arkumu.org/literals/project-alpha';
```

This returns all institution-specific entities that share the same canonical property-value combination, maintaining data provenance while enabling cross-archive discovery.

## Implementation Recommendations
- Materialized views: If full project graphs are retrieved frequently for OAI or UI, consider a per‑org materialized view keyed by (project_subject_id) pre‑aggregating core properties (title, creators, dates, identifiers) with canonical folding.

## Recommended “Common Query” Shape (Reusable Function)
Inputs
- `org_code`: e.g., `fuk` (scope of “main graph”)
- `type_canonical_uri`: e.g., `http://arkumu.org/types/projekt`
- `predicate_canon_whitelist` (optional): list of canonical property URIs to focus on
- `expand_neighbors`: bool or list of canonical relationship types to expand

Steps
1) Resolve subjects for the org and canonical class (Recipe 1).
2) Fetch subject‑centric triples (Recipe 2), optionally filtered by canonical predicate whitelist (Recipe 3).
3) If `expand_neighbors`, identify FK/junction properties for Projekt from `SchemaService` and fetch 1‑hop neighbor triples (Recipe 4), optionally constrained by neighbor canonical classes.
4) Return a structured graph: nodes (Resources) + edges (Triples), with predicates normalized via `canonical_uri` so clients can group/merge across archives.

## Why This Meets the Requirement
- “Efficient”: Uses existing btree/GiST/GIN indexes and minimal joins. The heavy filters are on indexed columns (predicate, object, canonical_uri, organization).
- “Main FUK graph”: Subjects are constrained to FUK organization; properties and neighbors match the FUK mapping/schema.
- "Any resource with the same canonical_uri": Predicates and classes already normalize via `canonical_uri`; literals are canonical by URI, enabling cross-archive discovery through shared property-value pairs.

## Next Steps
- Implement the reusable query service with the inputs above (Django ORM or raw SQL), leveraging the existing canonical properties and literals for cross-archive discovery.
- Build a small cache for canonical predicate whitelists per dataset to optimize common queries.
- Optionally add the suggested indexes after measuring on staging data.
- Consider materialized views for frequently accessed project graphs, aggregating by canonical properties while preserving institution-specific entity URIs.

