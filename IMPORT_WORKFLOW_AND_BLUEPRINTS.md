# Arkumu Import Workflow and Blueprint System

## Overview

The Arkumu import system uses a **schema-first approach** where complete blueprints are generated *before* any CSV data processing begins. This ensures data integrity, consistency, and enables users to preview exactly how their data will be transformed into RDF triples.

## Key Components

### 1. Main Import Task (`import_metadata.py`)
- **Entry point**: `run_mapping_aware_import_workflow()`
- **Purpose**: Orchestrates the complete CSV import process using mapping configurations
- **Key feature**: Uses pre-built schema blueprints for enhanced processing

### 2. Schema Service (`schema_service.py`)
- **Purpose**: Creates and caches complete schema blueprints
- **Key method**: `get_schema_visualization_data()` - used by blueprint visualizer
- **Caching**: Blueprints are cached by mapping_id for efficiency

### 3. Mapping-Aware Processor (`mapping_aware_processor.py`)
- **Purpose**: Processes CSV data using schema blueprints
- **Key feature**: Handles all column types (anchor, FK, multi-value, external ontology)
- **Blueprint integration**: Uses pre-created blueprints to guide processing

### 4. Resource Manager (`resource_manager.py`)
- **Purpose**: Generates URIs and creates RDF triples
- **Key feature**: Bulk creation operations for efficiency
- **URI patterns**: Standardized URI generation for all resource types

## Complete Import Workflow

### Phase 1: Initialization and Configuration
```
1. Load mapping configuration by mapping_id
2. Translate mapping config to ExecutionConfig using MappingAdapter
3. Validate configuration and file requirements
4. Initialize progress tracking and logging
```

### Phase 2: Schema Blueprint Creation (Schema-First Approach)
```
Key Process: _create_complete_schema_blueprints()

1. Generate cache key: "complete_schema_blueprints_mapping_{mapping_id}"
2. Check cache for existing blueprints
   - HIT: Load cached blueprints → Skip to Phase 3
   - MISS: Create blueprints from scratch

3. Blueprint Creation Steps:
   a. Create dataset resources for all datasets
   b. Create entity type definitions  
   c. Create property definitions for all columns
   d. Map FK relationships between datasets
   e. Create junction table schemas
   f. Map external ontology connections
   g. Define anchor columns and constraints
   
4. Cache blueprints for future use
5. Log blueprint statistics (datasets, properties, relationships)
```

### Phase 3: Data Preparation
```
1. Download CSV file from S3 using BucketService
2. Parse CSV into list of dictionaries
3. Validate CSV structure against blueprint requirements
```

### Phase 4: Entity and Triple Generation
```
Key Process: MappingAwareProcessor.process_with_execution_config()

For each dataset:
1. Process entities using blueprint schema
2. Generate URIs for all entities
3. Create entity resources
4. Process different column types:
   - Regular columns → simple property triples
   - Anchor columns → primary key properties
   - Multi-value columns → multiple value triples
   - External ontology columns → external URI links
   - FK columns → relationship triples
5. Create all triples in bulk for efficiency
```

### Phase 5: Relationship Processing
```
1. Process FK relationships between datasets
2. Create junction entities for many-to-many relationships
3. Process relationship contexts (junction table attributes)
4. Generate relationship triples connecting entities
```

### Phase 6: Finalization
```
1. Aggregate processing statistics
2. Update IngestSession status
3. Log final results and performance metrics
4. Return execution results
```

## Blueprint Structure and Content

### What Blueprints Contain

Each blueprint is a comprehensive schema definition containing:

```python
{
    'dataset_name': str,
    'dataset_resource': Resource,           # Dataset URI resource
    'entity_type_resource': Resource,       # Entity type URI
    'property_resources': {                 # Column name → Property URI mapping
        'column_name': Resource
    },
    'fk_relationships': [                   # Foreign key definitions
        {
            'source_column': str,
            'target_dataset': str,
            'target_column': str,
            'relationship_type': str
        }
    ],
    'column_metadata': {                    # Detailed column information
        'column_name': {
            'arkumu_type': str,
            'is_anchor': bool,
            'is_multi_value': bool,
            'is_external_ontology': bool,
            'external_ontologies': []
        }
    },
    'junction_schema': {                    # For junction tables
        'primary_dataset': str,
        'secondary_dataset': str,
        'primary_fk': str,
        'secondary_fk': str
    },
    'anchor_columns': [                     # Primary key definitions
        {
            'column_name': str,
            'uri_pattern': str
        }
    ],
    'multi_value_schemas': {},              # Multi-value column schemas
    'external_ontology_schemas': {}         # External ontology mappings
}
```

## URI Generation Patterns

### Entity URIs
```
Pattern: <base_uri>/<institution>/entities/<dataset_name>/<entity_id>
Example: http://data.arkumu.org/fuk/entities/Person/john_doe_123
```

### Property URIs
```
Pattern: <base_uri>/<institution>/properties/<property_name>
Example: http://data.arkumu.org/fuk/properties/firstName
```

### Dataset URIs
```
Pattern: <base_uri>/<institution>/datasets/<dataset_name>
Example: http://data.arkumu.org/fuk/datasets/Person
```

### Junction Entity URIs
```
Pattern: <base_uri>/<institution>/junctions/<dataset_name>/<primary_value>_<secondary_value>
Example: http://data.arkumu.org/fuk/junctions/PersonOrganization/john_doe_123_acme_corp
```

## Triple Generation Process

### 1. Structural Triples (Schema Level)
```turtle
# Dataset definition
<dataset_uri> rdf:type arkumu:Dataset .
<dataset_uri> dcterms:title "Dataset Name" .

# Property definitions
<property_uri> rdf:type rdf:Property .
<property_uri> rdfs:domain <entity_type_uri> .
```

### 2. Entity Triples (Data Level)
```turtle
# Entity definition
<entity_uri> rdf:type <entity_type_uri> .
<entity_uri> arkumu:sourceDataset <dataset_uri> .

# Property values
<entity_uri> <property_uri> "value" .
<entity_uri> <property_uri> <related_entity_uri> .
```

### 3. Relationship Triples
```turtle
# Foreign key relationships
<source_entity> <relationship_property> <target_entity> .

# Junction table relationships
<junction_entity> arkumu:relates <primary_entity> .
<junction_entity> arkumu:relates <secondary_entity> .
<junction_entity> <context_property> "context_value" .
```

## Kreuz Derivation Step

- After canonical URIs are mapped for an organization, run `python manage.py derive_project_relationships --organization <code>` to materialize reusable relationships from Kreuz (cross-table) datasets. The command is idempotent and supports `--dry-run` for import rehearsals.
- Derivation patterns and dataset inventories live in `arkumu/metadata/derivations/kreuz_config.py`; update this configuration when new Kreuz tables appear or canonical predicates change.
- The engine emits direct triples for project↔event, event↔digital object, project↔digital object, keywords, equipment, and actor junctions (all marked `is_derived=True`).
- These derived triples are required for catalog queries, schema manifests, and OAI exports to expose event-level digital objects and contributor metadata without rehydrating junction nodes at read time.

## Blueprint Integration Points

### 1. Schema Validation
- Blueprints define expected structure before data processing
- CSV columns are validated against blueprint property definitions
- Missing required properties trigger warnings

### 2. URI Generation Guidance
- Blueprints contain pre-generated property and entity type URIs
- Consistent URI patterns across all import sessions
- Anchor column definitions guide entity URI generation

### 3. Relationship Processing
- FK relationships are pre-defined in blueprints
- Junction table schemas guide many-to-many processing
- External ontology mappings are pre-resolved

### 4. Type Safety and Constraints
- Column types are validated against blueprint metadata
- Multi-value columns are processed according to blueprint schemas
- External ontology constraints are enforced

## Performance Optimizations

### 1. Blueprint Caching
- Blueprints are cached by mapping_id
- Subsequent imports reuse cached blueprints
- Cache invalidation on mapping configuration changes

### 2. Bulk Operations
- Resources created in bulk using Django ORM bulk_create()
- Triples created in bulk for efficiency
- Batch processing of CSV chunks

### 3. Streaming Processing
- Large CSV files processed in chunks
- Memory-efficient streaming approach
- Progress tracking for long-running imports

## Error Handling and Validation

### 1. Pre-Processing Validation
- CSV structure validated against blueprints
- Required columns checked before processing
- Data type validation using blueprint metadata

### 2. Runtime Error Recovery
- FK resolution failures logged but don't stop import
- Invalid external ontology URLs handled gracefully
- Partial import results preserved on failures

### 3. Post-Processing Verification
- Triple count validation against expected results
- Relationship integrity checking
- Import statistics and quality metrics

## What Users Need to Understand

For an RDF Preview visualizer, users need to see:

1. **URI Patterns**: How their data will be converted to URIs
2. **Property Mappings**: Which columns become which RDF properties
3. **Relationship Structure**: How FK relationships become RDF triples
4. **Entity Hierarchy**: How datasets relate to entity types
5. **Junction Processing**: How many-to-many relationships are modeled
6. **External Ontology Integration**: How external URIs are incorporated
7. **Sample Triple Output**: Example RDF triples for their specific data

This understanding helps users validate their mapping configuration before running expensive import operations and ensures the resulting knowledge graph matches their expectations.
