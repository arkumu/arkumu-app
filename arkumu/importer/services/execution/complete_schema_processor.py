"""
Complete Schema Processor with Full Relationship Support

This module extends the blueprint creation to include ALL relationship types,
not just FK relationships. It captures the complete schema including:
- Junction tables (relationship_contexts)
- Multi-value columns
- External ontology mappings
- Anchor columns
- Column constraints and metadata
"""

import logging
from datetime import datetime
from typing import Dict, List, Any, Optional

from django.core.cache import cache

from arkumu.importer.services.mapping_consumer.config_translator import (
    ExecutionConfig, DatasetConfig, ColumnConfig, ColumnType
)
from arkumu.metadata.models.resource import Resource, ResourceType
from arkumu.metadata.models.triples import Triple
from .mapping_aware_processor import MappingAwareProcessor

logger = logging.getLogger(__name__)


class CompleteSchemaProcessor(MappingAwareProcessor):
    """
    Enhanced processor that creates COMPLETE schema blueprints including
    all relationship types for both import and post-import CRUD operations.
    """
    
    def _create_complete_schema_blueprints(self, execution_config: ExecutionConfig):
        """Create TRULY complete schema blueprints including all relationship types."""
        # Store execution config for access by helper methods
        self._current_execution_config = execution_config
        
        # Generate cache key based on mapping_id
        mapping_id = execution_config.mapping_id
        blueprint_cache_key = f"complete_schema_blueprints_mapping_{mapping_id}"
        
        # Try to load from cache first
        cached_blueprints = cache.get(blueprint_cache_key)
        
        logger.info(f"🔍 COMPLETE SCHEMA CACHE: Key mapping_{mapping_id} → {'HIT' if cached_blueprints else 'MISS'}")
        
        if cached_blueprints:
            logger.info(f"🚀 CACHE HIT: Loading complete schema blueprints for mapping {mapping_id}")
            self.dataset_blueprints = cached_blueprints
            self._log_complete_schema_statistics()
            return
        
        # Cache miss - create complete blueprints from scratch
        logger.info("🏗️  COMPLETE SCHEMA-FIRST: Creating full schema blueprints for all datasets")
        
        # Call parent's blueprint creation first
        super()._create_complete_schema_blueprints(execution_config)
        
        # Extend with additional schema information
        self._extend_blueprints_with_complete_schema(execution_config)
        
        # Cache the complete blueprints
        try:
            cache.set(blueprint_cache_key, self.dataset_blueprints, timeout=3600)
            logger.info(f"💾 COMPLETE SCHEMA CACHED: Full blueprints cached for mapping {mapping_id} (1h timeout)")
        except Exception as e:
            logger.warning(f"Failed to cache complete schema blueprints: {e}")
        
        self._log_complete_schema_statistics()
    
    def _extend_blueprints_with_complete_schema(self, execution_config: ExecutionConfig):
        """Extend blueprints with complete schema information."""
        logger.info("   🔧 Extending blueprints with complete schema information...")
        
        # Phase 1: Add column metadata to blueprints
        self._add_column_metadata_to_blueprints(execution_config.datasets)
        
        # Phase 2: Add junction table schemas
        self._add_junction_table_schemas(execution_config)
        
        # Phase 3: Add multi-value column schemas
        self._add_multi_value_schemas(execution_config.datasets)
        
        # Phase 4: Add external ontology schemas
        self._add_external_ontology_schemas(execution_config.datasets)
        
        # Phase 5: Add anchor column information
        self._add_anchor_column_schemas(execution_config.datasets)
        
        # Phase 6: Schema metadata triples removed - mapping already contains this info
    
    def _add_column_metadata_to_blueprints(self, datasets: List[DatasetConfig]):
        """Add detailed column metadata to blueprints."""
        logger.info("   📝 Adding column metadata to blueprints...")

        # Get schema_manifest from execution config (if available)
        schema_manifest = getattr(self._current_execution_config, 'schema_manifest', {})

        for dataset_config in datasets:
            blueprint = self.dataset_blueprints[dataset_config.dataset_name]

            # Initialize column metadata section
            blueprint['column_metadata'] = {}

            # Get promoted column metadata for this dataset (if exists)
            dataset_manifest = schema_manifest.get(dataset_config.dataset_name, {})
            promoted_column_metadata = dataset_manifest.get('column_metadata', {})

            for column in dataset_config.columns:
                column_metadata = {
                    'column_name': column.column_name,
                    'column_type': column.column_type.value,
                    'arkumu_type': column.arkumu_type,
                    'is_required': getattr(column, 'is_required', False),
                    'is_anchor': column.column_type == ColumnType.ANCHOR,
                    'is_multi_value': column.column_type == ColumnType.MULTI_VALUE,
                    'is_external_ontology': column.column_type == ColumnType.EXTERNAL_ONTOLOGY,
                    'has_fk': hasattr(column, 'fk_config') and column.fk_config is not None
                }

                # Add multi-value specific metadata
                if column.column_type == ColumnType.MULTI_VALUE:
                    column_metadata['multi_value_separator'] = getattr(column, 'separator', ',')

                # Add external ontology metadata
                if column.column_type == ColumnType.EXTERNAL_ONTOLOGY:
                    column_metadata['ontology_type'] = getattr(column, 'ontology_type', None)
                    column_metadata['uri_template'] = getattr(column, 'uri_template', None)

                # Merge promoted column metadata (widget, property_label, etc.)
                if column.column_name in promoted_column_metadata:
                    promoted_meta = promoted_column_metadata[column.column_name]
                    # Only merge specific fields we care about (widget, property_label)
                    if 'widget' in promoted_meta:
                        column_metadata['widget'] = promoted_meta['widget']
                    if 'property_label' in promoted_meta:
                        column_metadata['property_label'] = promoted_meta['property_label']

                blueprint['column_metadata'][column.column_name] = column_metadata

            logger.info(f"     📝 {dataset_config.dataset_name}: Added metadata for {len(blueprint['column_metadata'])} columns")
    
    def _add_junction_table_schemas(self, execution_config: ExecutionConfig):
        """Add junction table schemas to blueprints."""
        logger.info("   🔗 Adding junction table schemas...")
        
        # Look for relationship contexts in execution config
        if hasattr(execution_config, 'relationship_contexts'):
            for rel_context in execution_config.relationship_contexts:
                dataset_name = rel_context.dataset_name
                
                if dataset_name in self.dataset_blueprints:
                    blueprint = self.dataset_blueprints[dataset_name]
                    
                    # Create junction schema
                    # Get primary and secondary datasets dynamically for backwards compatibility
                    primary_dataset = getattr(rel_context, 'primary_dataset', '') or self._get_target_dataset_from_fk(rel_context.primary_fk)
                    secondary_dataset = getattr(rel_context, 'secondary_dataset', '') or self._get_target_dataset_from_fk(rel_context.secondary_fk)
                    
                    junction_schema = {
                        'context_type': rel_context.context_type,
                        'primary_fk': rel_context.primary_fk,
                        'secondary_fk': rel_context.secondary_fk,
                        'primary_dataset': primary_dataset,
                        'secondary_dataset': secondary_dataset,
                        'context_columns': rel_context.context_columns,
                        'entity_type_resource': self._create_junction_entity_type_resource(rel_context),
                        'context_property_resources': {}
                    }
                    
                    # Create property resources for context columns using bulk method
                    if rel_context.context_columns:
                        junction_property_uris = []
                        for context_col in rel_context.context_columns:
                            prop_uri = self._generate_property_uri(f"junction_{context_col}")
                            junction_property_uris.append(prop_uri)
                        
                        # Use resource manager's bulk method to avoid duplicates
                        junction_property_resources = self.resource_manager._create_property_resources_bulk(junction_property_uris)
                        
                        # Map back to context columns
                        for context_col in rel_context.context_columns:
                            prop_uri = self._generate_property_uri(f"junction_{context_col}")
                            junction_schema['context_property_resources'][context_col] = junction_property_resources[prop_uri]
                    
                    blueprint['junction_schema'] = junction_schema
                    logger.info(f"     🔗 {dataset_name}: Added junction table schema")
    
    def _create_junction_entity_type_resource(self, rel_context) -> Resource:
        """Create entity type resource for junction table."""
        # Get primary and secondary datasets dynamically for backwards compatibility
        primary_dataset = getattr(rel_context, 'primary_dataset', '') or self._get_target_dataset_from_fk(rel_context.primary_fk)
        secondary_dataset = getattr(rel_context, 'secondary_dataset', '') or self._get_target_dataset_from_fk(rel_context.secondary_fk)
        
        # Generate entity type for junction
        entity_type_name = f"{primary_dataset}_{secondary_dataset}_relationship"
        entity_type_uri = self._generate_type_uri(entity_type_name)
        
        # Use bulk method to avoid duplicate key violations
        existing_resources = self.resource_manager.get_existing_resources_bulk([entity_type_uri])
        
        if entity_type_uri in existing_resources:
            entity_type_resource = existing_resources[entity_type_uri]
        else:
            # Create new resource with atomic transaction
            from django.db import transaction
            try:
                with transaction.atomic():
                    entity_type_resource, _ = Resource.objects.get_or_create(
                        uri=entity_type_uri,
                        defaults={
                            "resource_type": ResourceType.CLASS,
                            "name": entity_type_name,
                            "is_placeholder": False,
                            "organization": self.organization
                        }
                    )
            except Exception as e:
                # If creation fails due to duplicate, fetch existing
                logger.debug(f"Junction type resource creation failed, fetching existing: {e}")
                entity_type_resource = Resource.objects.get(uri=entity_type_uri)
        
        return entity_type_resource
    
    def _add_multi_value_schemas(self, datasets: List[DatasetConfig]):
        """Add multi-value column schemas to blueprints."""
        logger.info("   🎯 Adding multi-value column schemas...")
        
        for dataset_config in datasets:
            blueprint = self.dataset_blueprints[dataset_config.dataset_name]
            blueprint['multi_value_schemas'] = {}
            
            for column in dataset_config.columns:
                if column.column_type == ColumnType.MULTI_VALUE:
                    multi_value_schema = {
                        'column_name': column.column_name,
                        'separator': getattr(column, 'separator', ','),
                        'property_resource': blueprint['property_resources'][column.column_name],
                        'creates_multiple_triples': True,
                        'trim_values': True
                    }
                    
                    blueprint['multi_value_schemas'][column.column_name] = multi_value_schema
            
            if blueprint['multi_value_schemas']:
                logger.info(f"     🎯 {dataset_config.dataset_name}: {len(blueprint['multi_value_schemas'])} multi-value columns")
    
    def _add_external_ontology_schemas(self, datasets: List[DatasetConfig]):
        """Add external ontology mapping schemas to blueprints."""
        logger.info("   🌐 Adding external ontology schemas...")
        
        for dataset_config in datasets:
            blueprint = self.dataset_blueprints[dataset_config.dataset_name]
            blueprint['external_ontology_schemas'] = {}
            
            for column in dataset_config.columns:
                if column.column_type == ColumnType.EXTERNAL_ONTOLOGY:
                    configs = getattr(column, "external_ontology_configs", None) or []
                    if not configs and getattr(column, "external_ontology_config", None):
                        configs = [column.external_ontology_config]

                    selected_config = next(
                        (cfg for cfg in configs if isinstance(cfg, dict) and cfg.get("uri_template")),
                        None,
                    )
                    if not selected_config:
                        logger.warning(
                            "External ontology column '%s.%s' has no valid configuration; treated as literal",
                            dataset_config.dataset_name,
                            column.column_name,
                        )
                        continue

                    external_schema = {
                        'column_name': column.column_name,
                        'ontology_type': selected_config.get('ontology_type', 'generic'),
                        'uri_template': selected_config.get('uri_template'),
                        'property_resource': blueprint['property_resources'][column.column_name],
                        'creates_external_reference': True
                    }

                    blueprint['external_ontology_schemas'][column.column_name] = external_schema
            
            if blueprint['external_ontology_schemas']:
                logger.info(f"     🌐 {dataset_config.dataset_name}: {len(blueprint['external_ontology_schemas'])} external ontology mappings")
    
    def _add_anchor_column_schemas(self, datasets: List[DatasetConfig]):
        """Add anchor column information to blueprints."""
        logger.info("   ⚓ Adding anchor column schemas...")
        
        for dataset_config in datasets:
            blueprint = self.dataset_blueprints[dataset_config.dataset_name]
            blueprint['anchor_columns'] = []
            
            for column in dataset_config.columns:
                if column.column_type == ColumnType.ANCHOR:
                    anchor_info = {
                        'column_name': column.column_name,
                        'arkumu_type': column.arkumu_type,
                        'is_primary_key': True,
                        'used_for_uri_generation': True
                    }
                    
                    blueprint['anchor_columns'].append(anchor_info)
            
            if blueprint['anchor_columns']:
                logger.info(f"     ⚓ {dataset_config.dataset_name}: {len(blueprint['anchor_columns'])} anchor columns")
    
    
    def _log_complete_schema_statistics(self):
        """Log comprehensive statistics about the complete schema."""
        total_datasets = len(self.dataset_blueprints)
        total_properties = sum(len(bp.get('property_resources', {})) for bp in self.dataset_blueprints.values())
        total_fk_relationships = sum(len(bp.get('fk_relationships', [])) for bp in self.dataset_blueprints.values())
        total_multi_value = sum(len(bp.get('multi_value_schemas', {})) for bp in self.dataset_blueprints.values())
        total_external_ontology = sum(len(bp.get('external_ontology_schemas', {})) for bp in self.dataset_blueprints.values())
        total_junction_tables = sum(1 for bp in self.dataset_blueprints.values() if 'junction_schema' in bp)
        
        logger.info(f"   ✅ Complete Schema Statistics:")
        logger.info(f"      📁 Datasets: {total_datasets}")
        logger.info(f"      🏷️  Properties: {total_properties}")
        logger.info(f"      🔗 FK Relationships: {total_fk_relationships}")
        logger.info(f"      🎯 Multi-value Columns: {total_multi_value}")
        logger.info(f"      🌐 External Ontologies: {total_external_ontology}")
        logger.info(f"      🔄 Junction Tables: {total_junction_tables}")
    
    def get_schema_for_entity_creation(self, dataset_name: str) -> Optional[Dict[str, Any]]:
        """
        Get complete schema for creating new entities post-import.
        
        This method provides everything needed to create new entities
        that conform to the schema defined during mapping.
        """
        if dataset_name not in self.dataset_blueprints:
            return None
        
        blueprint = self.dataset_blueprints[dataset_name]
        
        return {
            'dataset_name': dataset_name,
            'entity_type': blueprint['entity_type_resource'],
            'properties': blueprint['property_resources'],
            'column_metadata': blueprint.get('column_metadata', {}),
            'multi_value_schemas': blueprint.get('multi_value_schemas', {}),
            'external_ontology_schemas': blueprint.get('external_ontology_schemas', {}),
            'anchor_columns': blueprint.get('anchor_columns', []),
            'fk_relationships': blueprint.get('fk_relationships', []),
            'junction_schema': blueprint.get('junction_schema', None)
        }
    
    def create_entity_from_schema(self, dataset_name: str, entity_data: Dict[str, Any]) -> Optional[Resource]:
        """
        Create a new entity using the cached complete schema.
        
        This allows post-import creation of entities that conform
        to the same schema used during import.
        """
        schema = self.get_schema_for_entity_creation(dataset_name)
        if not schema:
            logger.error(f"No schema found for dataset: {dataset_name}")
            return None
        
        # Generate entity URI using anchor columns
        anchor_values = []
        for anchor_col in schema['anchor_columns']:
            col_name = anchor_col['column_name']
            if col_name in entity_data:
                anchor_values.append(str(entity_data[col_name]))
        
        if not anchor_values:
            logger.error(f"No anchor values provided for entity creation in {dataset_name}")
            return None
        
        entity_uri = self._generate_entity_uri(dataset_name, anchor_values)
        
        # Create entity resource
        entity_resource = self.resource_manager.create_entity_resource(entity_uri)
        
        # Add entity to dataset
        dataset_resource = self.dataset_blueprints[dataset_name]['dataset_resource']
        isPartOf_uri = self._generate_property_uri("isPartOf")
        self.resource_manager.create_relationship_triple(
            entity_resource,
            isPartOf_uri,
            dataset_resource
        )
        
        # Process each property according to schema
        for column_name, value in entity_data.items():
            if column_name not in schema['properties']:
                continue
            
            property_resource = schema['properties'][column_name]
            column_metadata = schema['column_metadata'].get(column_name, {})
            
            # Handle multi-value columns
            if column_name in schema['multi_value_schemas']:
                mv_schema = schema['multi_value_schemas'][column_name]
                if isinstance(value, str):
                    values = [v.strip() for v in value.split(mv_schema['separator'])]
                else:
                    values = [value]
                
                for single_value in values:
                    if single_value:
                        self.resource_manager.create_property_triple(
                            entity_resource,
                            property_resource.uri,
                            single_value,
                            "http://www.w3.org/2001/XMLSchema#string"
                        )
            
            # Handle external ontology columns
            elif column_name in schema['external_ontology_schemas']:
                ext_schema = schema['external_ontology_schemas'][column_name]
                if value:
                    external_uri = ext_schema['uri_template'].format(value=value)
                    external_resource = self.resource_manager.create_entity_resource(external_uri)
                    self.resource_manager.create_relationship_triple(
                        entity_resource,
                        property_resource.uri,
                        external_resource
                    )
            
            # Handle regular properties
            else:
                if value is not None:
                    self.resource_manager.create_property_triple(
                        entity_resource,
                        property_resource.uri,
                        str(value),
                        "http://www.w3.org/2001/XMLSchema#string"
                    )
        
        return entity_resource
    
    def _get_target_dataset_from_fk(self, fk_column: str) -> str:
        """Get target dataset for FK column from configuration"""
        # Access the execution config from the current processing context
        if hasattr(self, '_current_execution_config'):
            for fk_rel in self._current_execution_config.fk_relationships:
                if fk_rel.source_column == fk_column:
                    return fk_rel.target_dataset
        
        return f"unknown_target_for_{fk_column}"
