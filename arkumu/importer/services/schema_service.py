"""
Schema Service for Post-Import CRUD Operations

This service provides access to complete schema information for creating,
updating, and validating entities after the initial import process.
"""

import logging
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime

from django.core.cache import cache
from django.db import transaction
import time
import random

from arkumu.metadata.models.resource import Resource, ResourceType
from arkumu.metadata.models.mappings import Mapping
from arkumu.users.models import Organization
from arkumu.importer.services.mapping_consumer import MappingAdapter
from arkumu.importer.services.execution.complete_schema_processor import CompleteSchemaProcessor
from arkumu.importer.services.execution.statistics import ExecutionStatistics

logger = logging.getLogger(__name__)


class SchemaService:
    """
    Service for accessing and using complete schema information
    for post-import CRUD operations.
    """
    
    def __init__(self, mapping_id: str, institution: str = "ARKUMU", 
                 base_uri: str = "http://arkumu.org/data"):
        """
        Initialize schema service for a specific mapping.
        
        Args:
            mapping_id: The mapping ID to load schema for
            institution: Institution name for URI generation
            base_uri: Base URI for resource creation
        """
        self.mapping_id = mapping_id
        self.institution = institution
        self.base_uri = base_uri
        self._processor = None
        self._schema_loaded = False
    
    def _ensure_schema_loaded(self):
        """Ensure schema is loaded from cache or created if needed."""
        if self._schema_loaded:
            return
        
        # Get organization object for the mapping
        try:
            mapping = Mapping.objects.get(id=self.mapping_id)
            organization = Organization.objects.get(code=mapping.organization_id)
        except (Mapping.DoesNotExist, Organization.DoesNotExist) as e:
            logger.error(f"Failed to load mapping or organization: {e}")
            raise ValueError(f"Cannot load schema - mapping or organization not found: {e}")
        
        # Check cache first
        cache_key = f"complete_schema_blueprints_mapping_{self.mapping_id}"
        cached_blueprints = cache.get(cache_key)
        
        if cached_blueprints:
            logger.info(f"📋 Loading cached schema for mapping {self.mapping_id}")
            
            # Validate cached blueprints - check if Resource objects still exist
            try:
                self._validate_cached_resources(cached_blueprints)
                
                # Create processor with cached blueprints
                self._processor = CompleteSchemaProcessor(
                    organization=organization,
                    base_uri=self.base_uri,
                    statistics=ExecutionStatistics()
                )
                self._processor.dataset_blueprints = cached_blueprints
                self._schema_loaded = True
                return
                
            except ValueError as e:
                logger.warning(f"Cached blueprints invalid: {e}. Regenerating schema...")
                # Cache will be cleared by validation function, continue to regeneration
        
        # Schema not in cache - need to create it with distributed locking
        self._create_schema_with_locking(organization)
    
    def _create_schema_with_locking(self, organization):
        """Create schema with distributed locking to prevent concurrent creation."""
        lock_key = f"schema_creation_lock_mapping_{self.mapping_id}"
        cache_key = f"complete_schema_blueprints_mapping_{self.mapping_id}"
        
        # Try to acquire distributed lock
        lock_timeout = 300  # 5 minutes max for schema creation
        lock_acquired = False
        
        try:
            # Use cache-based distributed lock with timeout
            lock_acquired = cache.add(lock_key, "locked", timeout=lock_timeout)
            
            if lock_acquired:
                logger.info(f"🔒 Acquired schema creation lock for mapping {self.mapping_id}")
                
                # Double-check cache after acquiring lock (another process may have completed)
                cached_blueprints = cache.get(cache_key)
                if cached_blueprints:
                    try:
                        self._validate_cached_resources(cached_blueprints)
                        logger.info(f"📋 Found valid cached schema after acquiring lock for mapping {self.mapping_id}")
                        
                        # Use the cached version
                        self._processor = CompleteSchemaProcessor(
                            organization=organization,
                            base_uri=self.base_uri,
                            statistics=ExecutionStatistics()
                        )
                        self._processor.dataset_blueprints = cached_blueprints
                        self._schema_loaded = True
                        return
                    except ValueError:
                        logger.info(f"Cached schema invalid even after lock, recreating...")
                
                # Create the schema (we have the lock)
                logger.info(f"🏗️  Creating schema for mapping {self.mapping_id} (with lock)")
                
                # Load mapping configuration
                adapter = MappingAdapter()
                execution_config = adapter.translate_to_execution_config(self.mapping_id)
                
                # Create processor and generate complete schema
                self._processor = CompleteSchemaProcessor(
                    organization=organization,
                    base_uri=self.base_uri,
                    statistics=ExecutionStatistics()
                )
                
                # This will create and cache the complete schema
                self._processor._create_complete_schema_blueprints(execution_config)
                self._schema_loaded = True
                
                logger.info(f"✅ Schema creation completed for mapping {self.mapping_id}")
                
            else:
                # Lock not acquired - another process is creating schema
                logger.info(f"⏳ Waiting for concurrent schema creation for mapping {self.mapping_id}")
                
                # Wait for the other process to complete (with exponential backoff)
                max_wait_time = 300  # 5 minutes max wait
                wait_time = 1
                total_waited = 0
                
                while total_waited < max_wait_time:
                    time.sleep(wait_time + random.uniform(0, 0.5))  # Add jitter
                    total_waited += wait_time
                    
                    # Check if schema is now available in cache
                    cached_blueprints = cache.get(cache_key)
                    if cached_blueprints:
                        try:
                            self._validate_cached_resources(cached_blueprints)
                            logger.info(f"📋 Schema became available after waiting {total_waited}s for mapping {self.mapping_id}")
                            
                            # Use the cached version
                            self._processor = CompleteSchemaProcessor(
                                organization=organization,
                                base_uri=self.base_uri,
                                statistics=ExecutionStatistics()
                            )
                            self._processor.dataset_blueprints = cached_blueprints
                            self._schema_loaded = True
                            return
                        except ValueError:
                            logger.warning(f"Cached schema invalid, continuing to wait...")
                    
                    # Check if lock is still held (other process still working)
                    if not cache.get(lock_key):
                        logger.warning(f"Schema creation lock released but no valid cache found, breaking wait loop...")
                        # Lock released but no cache - break out and try to create ourselves
                        break
                    
                    # Exponential backoff with max
                    wait_time = min(wait_time * 1.5, 10)
                
                raise RuntimeError(f"Timeout waiting for schema creation for mapping {self.mapping_id}")
                
        finally:
            # Release lock if we acquired it
            if lock_acquired:
                try:
                    cache.delete(lock_key)
                    logger.debug(f"🔓 Released schema creation lock for mapping {self.mapping_id}")
                except:
                    pass  # Lock might have expired, that's ok
    
    def _validate_cached_resources(self, blueprints: Dict[str, Any]):
        """
        Validate that all Resource objects in cached blueprints still exist in database.
        Raises ValueError if stale references found (e.g., after DB deletion).
        """
        missing_resources = []
        
        for dataset_name, blueprint in blueprints.items():
            # Check entity_type_resource
            if 'entity_type_resource' in blueprint:
                resource = blueprint['entity_type_resource']
                if hasattr(resource, 'id') and not Resource.objects.filter(id=resource.id).exists():
                    missing_resources.append(f"entity_type_resource for {dataset_name} (ID: {resource.id})")
            
            # Check property_resources
            if 'property_resources' in blueprint:
                for prop_name, prop_resource in blueprint['property_resources'].items():
                    if hasattr(prop_resource, 'id') and not Resource.objects.filter(id=prop_resource.id).exists():
                        missing_resources.append(f"property_resource {prop_name} for {dataset_name} (ID: {prop_resource.id})")
        
        if missing_resources:
            # Clear all related caches to force regeneration
            cache_keys = [
                f"schema_blueprints_mapping_{self.mapping_id}",
                f"complete_schema_blueprints_mapping_{self.mapping_id}"
            ]
            for key in cache_keys:
                cache.delete(key)
            
            raise ValueError(
                f"Stale blueprint resources detected (likely after database reset). "
                f"Cache cleared. Missing: {missing_resources[:3]}{'...' if len(missing_resources) > 3 else ''}"
            )
    
    def get_dataset_schema(self, dataset_name: str) -> Optional[Dict[str, Any]]:
        """
        Get complete schema for a dataset.
        
        Returns:
            Complete schema including properties, relationships, and metadata
        """
        self._ensure_schema_loaded()
        return self._processor.get_schema_for_entity_creation(dataset_name)
    
    def list_datasets(self) -> List[str]:
        """Get list of all datasets in the schema."""
        self._ensure_schema_loaded()
        return list(self._processor.dataset_blueprints.keys())
    
    def get_dataset_properties(self, dataset_name: str) -> Dict[str, Dict[str, Any]]:
        """
        Get all properties for a dataset with their metadata.
        
        Returns:
            Dictionary mapping column names to their metadata
        """
        schema = self.get_dataset_schema(dataset_name)
        if not schema:
            return {}
        
        return schema.get('column_metadata', {})
    
    def get_relationship_info(self, dataset_name: str) -> Dict[str, Any]:
        """
        Get all relationship information for a dataset.
        
        Returns:
            Dictionary with FK relationships, junction info, etc.
        """
        schema = self.get_dataset_schema(dataset_name)
        if not schema:
            return {}
        
        return {
            'fk_relationships': schema.get('fk_relationships', []),
            'junction_schema': schema.get('junction_schema', None),
            'multi_value_columns': list(schema.get('multi_value_schemas', {}).keys()),
            'external_ontologies': list(schema.get('external_ontology_schemas', {}).keys())
        }
    
    @transaction.atomic
    def create_entity(self, dataset_name: str, entity_data: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
        """
        Create a new entity using the schema.
        
        Args:
            dataset_name: Name of the dataset
            entity_data: Dictionary of column_name -> value
            
        Returns:
            Tuple of (success, result_dict)
        """
        self._ensure_schema_loaded()
        
        try:
            # Validate against schema
            validation_result = self.validate_entity_data(dataset_name, entity_data)
            if not validation_result['valid']:
                return False, {
                    'error': 'Validation failed',
                    'validation_errors': validation_result['errors']
                }
            
            # Create entity
            entity_resource = self._processor.create_entity_from_schema(dataset_name, entity_data)
            
            if entity_resource:
                return True, {
                    'entity_uri': entity_resource.uri,
                    'entity_id': entity_resource.id,
                    'message': f'Entity created successfully in {dataset_name}'
                }
            else:
                return False, {
                    'error': 'Failed to create entity'
                }
                
        except Exception as e:
            logger.error(f"Error creating entity: {e}")
            return False, {
                'error': f'Exception during entity creation: {str(e)}'
            }
    
    def validate_entity_data(self, dataset_name: str, entity_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate entity data against schema.
        
        Returns:
            Dictionary with 'valid' boolean and 'errors' list
        """
        schema = self.get_dataset_schema(dataset_name)
        if not schema:
            return {
                'valid': False,
                'errors': [f'No schema found for dataset: {dataset_name}']
            }
        
        errors = []
        
        # Check required anchor columns
        for anchor_col in schema.get('anchor_columns', []):
            col_name = anchor_col['column_name']
            if col_name not in entity_data or not entity_data[col_name]:
                errors.append(f'Required anchor column missing: {col_name}')
        
        # Check column types and constraints
        column_metadata = schema.get('column_metadata', {})
        for col_name, value in entity_data.items():
            if col_name not in column_metadata:
                errors.append(f'Unknown column: {col_name}')
                continue
            
            col_meta = column_metadata[col_name]
            
            # Check required fields
            if col_meta.get('is_required', False) and not value:
                errors.append(f'Required field missing: {col_name}')
            
            # Validate multi-value format
            if col_meta.get('is_multi_value', False) and value:
                if not isinstance(value, (str, list)):
                    errors.append(f'Multi-value column {col_name} must be string or list')
        
        # Check FK constraints exist
        for fk_rel in schema.get('fk_relationships', []):
            if fk_rel['source_column'] in entity_data:
                # Could add FK validation here
                pass
        
        return {
            'valid': len(errors) == 0,
            'errors': errors
        }
    
    @transaction.atomic
    def create_relationship(self, source_dataset: str, source_id: str,
                          target_dataset: str, target_id: str,
                          relationship_type: str, properties: Optional[Dict[str, Any]] = None) -> Tuple[bool, Dict[str, Any]]:
        """
        Create a relationship between two entities.
        
        This is especially useful for creating junction table entries.
        
        Args:
            source_dataset: Source dataset name
            source_id: Source entity identifier (anchor value)
            target_dataset: Target dataset name  
            target_id: Target entity identifier (anchor value)
            relationship_type: Type of relationship
            properties: Additional properties for junction table
            
        Returns:
            Tuple of (success, result_dict)
        """
        self._ensure_schema_loaded()
        
        try:
            # Find source and target entities
            source_uri = self._processor._generate_entity_uri(source_dataset, [source_id])
            target_uri = self._processor._generate_entity_uri(target_dataset, [target_id])
            
            source_resource = Resource.objects.filter(uri=source_uri).first()
            target_resource = Resource.objects.filter(uri=target_uri).first()
            
            if not source_resource:
                return False, {'error': f'Source entity not found: {source_dataset}/{source_id}'}
            
            if not target_resource:
                return False, {'error': f'Target entity not found: {target_dataset}/{target_id}'}
            
            # Check if this should be a junction table entry
            junction_dataset = None
            for dataset_name, blueprint in self._processor.dataset_blueprints.items():
                if 'junction_schema' in blueprint:
                    junction = blueprint['junction_schema']
                    if (junction['primary_dataset'] == source_dataset and 
                        junction['secondary_dataset'] == target_dataset):
                        junction_dataset = dataset_name
                        break
            
            if junction_dataset and properties:
                # Create junction entity
                junction_data = {
                    junction['primary_fk']: source_id,
                    junction['secondary_fk']: target_id,
                    **properties
                }
                
                return self.create_entity(junction_dataset, junction_data)
            else:
                # Create simple relationship
                relationship_uri = self._processor._generate_property_uri(relationship_type)
                triple = self._processor.resource_manager.create_relationship_triple(
                    source_resource,
                    relationship_uri,
                    target_resource
                )
                
                return True, {
                    'triple_id': triple.id,
                    'message': f'Relationship created: {source_dataset}/{source_id} -> {target_dataset}/{target_id}'
                }
                
        except Exception as e:
            logger.error(f"Error creating relationship: {e}")
            return False, {
                'error': f'Exception during relationship creation: {str(e)}'
            }
    
    def get_schema_visualization_data(self) -> Dict[str, Any]:
        """
        Get data structure suitable for visualizing the complete schema.
        
        Returns:
            Dictionary with nodes (datasets/entities) and edges (relationships)
        """
        self._ensure_schema_loaded()
        
        nodes = []
        edges = []
        
        # Create nodes for each dataset
        for dataset_name, blueprint in self._processor.dataset_blueprints.items():
            node = {
                'id': dataset_name,
                'label': dataset_name,
                'type': 'dataset',
                'entity_type': blueprint['entity_type_resource'].name,
                'properties': list(blueprint['property_resources'].keys()),
                'is_junction': 'junction_schema' in blueprint,
                'anchor_columns': [a['column_name'] for a in blueprint.get('anchor_columns', [])],
                'multi_value_columns': list(blueprint.get('multi_value_schemas', {}).keys()),
                'external_ontologies': list(blueprint.get('external_ontology_schemas', {}).keys())
            }
            nodes.append(node)
            
            # Create edges for FK relationships
            for fk_rel in blueprint.get('fk_relationships', []):
                edge = {
                    'source': dataset_name,
                    'target': fk_rel['target_dataset'],
                    'relationship_type': fk_rel['relationship_type'],
                    'source_column': fk_rel['source_column'],
                    'target_column': fk_rel['target_column'],
                    'type': 'foreign_key'
                }
                edges.append(edge)
            
            # Create edges for junction relationships
            if 'junction_schema' in blueprint:
                junction = blueprint['junction_schema']
                
                # Edge from junction to primary
                edges.append({
                    'source': dataset_name,
                    'target': junction['primary_dataset'],
                    'relationship_type': 'junction_primary',
                    'source_column': junction['primary_fk'],
                    'type': 'junction'
                })
                
                # Edge from junction to secondary
                edges.append({
                    'source': dataset_name,
                    'target': junction['secondary_dataset'],
                    'relationship_type': 'junction_secondary',
                    'source_column': junction['secondary_fk'],
                    'type': 'junction'
                })
        
        return {
            'nodes': nodes,
            'edges': edges,
            'metadata': {
                'total_datasets': len(nodes),
                'total_relationships': len(edges),
                'junction_tables': sum(1 for n in nodes if n['is_junction']),
                'mapping_id': self.mapping_id,
                'generated_at': datetime.now().isoformat()
            }
        }
    
    def export_schema_definition(self) -> Dict[str, Any]:
        """
        Export the complete schema definition for documentation or migration.
        
        Returns:
            Complete schema definition as dictionary
        """
        self._ensure_schema_loaded()
        
        schema_export = {
            'mapping_id': self.mapping_id,
            'institution': self.institution,
            'base_uri': self.base_uri,
            'exported_at': datetime.now().isoformat(),
            'datasets': {}
        }
        
        for dataset_name, blueprint in self._processor.dataset_blueprints.items():
            dataset_export = {
                'entity_type': blueprint['entity_type_resource'].name,
                'properties': {
                    col_name: {
                        'uri': prop_res.uri,
                        'name': prop_res.name,
                        'metadata': blueprint.get('column_metadata', {}).get(col_name, {})
                    }
                    for col_name, prop_res in blueprint['property_resources'].items()
                },
                'fk_relationships': blueprint.get('fk_relationships', []),
                'anchor_columns': blueprint.get('anchor_columns', []),
                'multi_value_schemas': blueprint.get('multi_value_schemas', {}),
                'external_ontology_schemas': blueprint.get('external_ontology_schemas', {}),
                'junction_schema': blueprint.get('junction_schema', None)
            }
            
            schema_export['datasets'][dataset_name] = dataset_export
        
        return schema_export