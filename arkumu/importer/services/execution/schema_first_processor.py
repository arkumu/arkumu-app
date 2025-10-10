"""
Schema-First Blueprint Processor

Creates complete schema blueprints for all datasets, columns, IRIs, and relationships
BEFORE any CSV data processing begins. This ensures:
- Complete data model compatibility across institutions
- Resilient FK relationship handling
- Consistent schema structure regardless of data presence
"""

import logging
from typing import Dict, Any, List, Optional, Set, Tuple
from dataclasses import dataclass
from datetime import datetime

from arkumu.importer.services.mapping_consumer import ExecutionConfig, ColumnConfig, DatasetConfig
from .resource_manager import ResourceManager
from arkumu.metadata.models.resource import ResourceType, Resource
from .statistics import ExecutionStatistics

logger = logging.getLogger(__name__)


@dataclass
class SchemaBlueprint:
    """Complete schema blueprint for a dataset"""
    dataset_name: str
    dataset_resource: Resource
    entity_type_resource: Resource
    property_resources: Dict[str, Resource]  # column_name -> property_resource
    fk_relationships: List[Dict[str, Any]]   # FK relationship definitions
    created_at: datetime


class SchemaFirstProcessor:
    """
    Creates complete schema blueprints upfront before CSV processing.
    
    This ensures all datasets, entity types, properties, and FK relationships
    are defined in the metadata layer before any data import begins.
    """
    
    def __init__(self,
                 institution: str,
                 base_uri: str,
                 statistics: ExecutionStatistics):
        """
        Initialize schema-first processor.
        
        Args:
            institution: Institution identifier
            base_uri: Base URI for resource generation
            statistics: Statistics tracker
        """
        self.institution = institution
        self.base_uri = base_uri
        self.statistics = statistics
        
        self.resource_manager = ResourceManager(
            institution=institution,
            base_uri=base_uri,
            statistics=statistics
        )
        
        # Schema blueprints by dataset name
        self.blueprints: Dict[str, SchemaBlueprint] = {}
        
    def create_complete_schema_blueprint(self, execution_config: ExecutionConfig) -> Dict[str, SchemaBlueprint]:
        """
        Create complete schema blueprints for all datasets before CSV processing.
        
        This method:
        1. Creates dataset resources for all datasets
        2. Creates entity type definitions
        3. Creates property definitions for all columns
        4. Maps FK relationships between datasets
        5. Creates schema metadata triples
        
        Args:
            execution_config: Complete execution configuration
            
        Returns:
            Dictionary of dataset_name -> SchemaBlueprint
        """
        logger.info("🏗️  SCHEMA-FIRST: Creating complete schema blueprints for all datasets")
        
        # Phase 1: Create all dataset and entity type resources
        self._create_dataset_resources(execution_config.datasets)
        
        # Phase 2: Create property definitions for all columns
        self._create_property_definitions(execution_config.datasets)
        
        # Phase 3: Map FK relationships between datasets
        self._map_fk_relationships(execution_config.datasets)
        
        # Phase 4: Create schema metadata triples
        self._create_schema_metadata_triples()
        
        logger.info(f"   ✅ Created {len(self.blueprints)} complete schema blueprints")
        logger.info(f"   📊 Total properties: {sum(len(bp.property_resources) for bp in self.blueprints.values())}")
        logger.info(f"   🔗 Total FK relationships: {sum(len(bp.fk_relationships) for bp in self.blueprints.values())}")
        
        return self.blueprints
    
    def _create_dataset_resources(self, datasets: List[DatasetConfig]):
        """Create dataset and entity type resources for all datasets."""
        logger.info("   📁 Creating dataset and entity type resources...")
        
        for dataset_config in datasets:
            # Create dataset resource (metadata container)
            dataset_resource = self.resource_manager.create_dataset_resource(dataset_config.dataset_name)
            
            # Create entity type resource for this dataset
            entity_type_resource = self._create_entity_type_resource(dataset_config)
            
            # Initialize blueprint
            self.blueprints[dataset_config.dataset_name] = SchemaBlueprint(
                dataset_name=dataset_config.dataset_name,
                dataset_resource=dataset_resource,
                entity_type_resource=entity_type_resource,
                property_resources={},
                fk_relationships=[],
                created_at=datetime.now()
            )
            
            logger.info(f"     📁 {dataset_config.dataset_name}: dataset + entity type created")
    
    def _create_entity_type_resource(self, dataset_config: DatasetConfig) -> Resource:
        """Create entity type resource for a dataset."""
        # Find primary entity column (first entity column)
        entity_columns = [col for col in dataset_config.columns if col.column_type.value == 'entity']
        
        if entity_columns:
            primary_entity_column = entity_columns[0]
            entity_type_name = primary_entity_column.arkumu_type
        else:
            # Fallback: use dataset name as entity type
            entity_type_name = f"entity_type_{dataset_config.dataset_name}"
        
        # Create entity type URI
        entity_type_uri = self._generate_property_uri(entity_type_name)
        
        # Create or get entity type resource
        entity_type_resource, created = Resource.objects.get_or_create(
            uri=entity_type_uri,
            defaults={
                "resource_type": ResourceType.CLASS,
                "name": entity_type_name,
                "is_placeholder": False
            }
        )
        
        return entity_type_resource
    
    def _create_property_definitions(self, datasets: List[DatasetConfig]):
        """Create property definitions for all columns in all datasets."""
        logger.info("   🏷️  Creating property definitions for all columns...")
        
        for dataset_config in datasets:
            blueprint = self.blueprints[dataset_config.dataset_name]
            
            for column in dataset_config.columns:
                property_resource = self._create_property_resource(column, dataset_config.dataset_name)
                blueprint.property_resources[column.column_name] = property_resource
            
            logger.info(f"     🏷️  {dataset_config.dataset_name}: {len(blueprint.property_resources)} properties created")
    
    def _create_property_resource(self, column: ColumnConfig, dataset_name: str) -> Resource:
        """Create property resource for a column."""
        # Generate property URI based on arkumu_type
        property_uri = self._generate_property_uri(column.arkumu_type)
        
        # Determine resource type based on column type
        resource_type = self._get_resource_type_for_column(column)
        
        # Create or get property resource
        property_resource, created = Resource.objects.get_or_create(
            uri=property_uri,
            defaults={
                "resource_type": resource_type,
                "name": column.arkumu_type,
                "is_placeholder": False
            }
        )
        
        return property_resource
    
    def _get_resource_type_for_column(self, column: ColumnConfig) -> ResourceType:
        """Determine resource type based on column configuration."""
        # All columns define properties in the schema
        # The actual entities (rows) are created later as ResourceType.IRI
        return ResourceType.PROPERTY
    
    def _map_fk_relationships(self, datasets: List[DatasetConfig]):
        """Map FK relationships between all datasets."""
        logger.info("   🔗 Mapping FK relationships between datasets...")
        
        total_fk_relationships = 0
        
        for dataset_config in datasets:
            blueprint = self.blueprints[dataset_config.dataset_name]
            
            for column in dataset_config.columns:
                # Check if column has FK configuration (not all ColumnConfig implementations may have this)
                if hasattr(column, 'fk_config') and column.fk_config:
                    fk_relationship = self._create_fk_relationship_definition(
                        column, dataset_config.dataset_name, blueprint
                    )
                    blueprint.fk_relationships.append(fk_relationship)
                    total_fk_relationships += 1
            
            if blueprint.fk_relationships:
                logger.info(f"     🔗 {dataset_config.dataset_name}: {len(blueprint.fk_relationships)} FK relationships mapped")
        
        logger.info(f"   🔗 Total FK relationships mapped: {total_fk_relationships}")
    
    def _create_fk_relationship_definition(
        self,
        column: ColumnConfig,
        source_dataset: str,
        blueprint: SchemaBlueprint,
    ) -> Dict[str, Any]:
        """Create FK relationship definition."""
        def _extract_uris(resource):
            if not resource:
                return None, None
            if hasattr(resource, 'uri'):
                return getattr(resource, 'uri', None), getattr(resource, 'canonical_uri', None)
            if isinstance(resource, dict):
                return resource.get('uri'), resource.get('canonical_uri') or resource.get('uri')
            return None, None

        source_property_resource = None
        if blueprint:
            source_property_resource = blueprint.property_resources.get(column.column_name)
        source_property_uri, source_canonical_uri = _extract_uris(source_property_resource)

        target_dataset = column.fk_config.target_dataset
        target_property_resource = None
        if target_dataset and target_dataset in self.blueprints:
            target_blueprint = self.blueprints[target_dataset]
            target_property_resource = target_blueprint.property_resources.get(column.fk_config.target_column)
        target_property_uri, target_canonical_uri = _extract_uris(target_property_resource)

        return {
            'source_dataset': source_dataset,
            'source_column': column.column_name,
            'source_property': column.arkumu_type,
            'source_property_uri': source_property_uri,
            'source_canonical_property': source_canonical_uri,
            'target_dataset': target_dataset,
            'target_column': column.fk_config.target_column,
            'target_property_uri': target_property_uri,
            'target_canonical_property': target_canonical_uri,
            'relationship_type': column.arkumu_type,
            'is_multi_value': column.column_type.value == 'multi_value',
            'fk_config': column.fk_config
        }
    
    def _create_schema_metadata_triples(self):
        """Create schema metadata triples linking datasets to entity types and properties."""
        logger.info("   📊 Creating schema metadata triples...")
        
        for blueprint in self.blueprints.values():
            # Link dataset to entity type
            schema_property_uri = self._generate_property_uri("defines_entity_type")
            self.resource_manager.create_relationship_triple(
                blueprint.dataset_resource,
                schema_property_uri,
                blueprint.entity_type_resource
            )
            
            # Link entity type to all properties
            for column_name, property_resource in blueprint.property_resources.items():
                property_schema_uri = self._generate_property_uri("defines_property")
                self.resource_manager.create_relationship_triple(
                    blueprint.entity_type_resource,
                    property_schema_uri,
                    property_resource
                )
            
            logger.info(f"     📊 {blueprint.dataset_name}: schema metadata triples created")
    
    def _generate_property_uri(self, property_name: str) -> str:
        """Generate URI for a property."""
        return f"{self.base_uri}/property/{property_name}"
    
    def get_blueprint(self, dataset_name: str) -> Optional[SchemaBlueprint]:
        """Get schema blueprint for a dataset."""
        return self.blueprints.get(dataset_name)
    
    def get_all_blueprints(self) -> Dict[str, SchemaBlueprint]:
        """Get all schema blueprints."""
        return self.blueprints.copy()
    
    def validate_schema_consistency(self) -> List[str]:
        """
        Validate schema consistency across all blueprints.
        
        Returns:
            List of validation warnings/errors
        """
        warnings = []
        
        # Check FK relationship consistency
        for blueprint in self.blueprints.values():
            for fk_rel in blueprint.fk_relationships:
                target_dataset = fk_rel['target_dataset']
                
                # Check if target dataset has a blueprint
                if target_dataset not in self.blueprints:
                    warnings.append(
                        f"FK relationship in {blueprint.dataset_name}.{fk_rel['source_column']} "
                        f"points to missing dataset '{target_dataset}'"
                    )
                else:
                    # Check if target column exists in target dataset
                    target_blueprint = self.blueprints[target_dataset]
                    target_column = fk_rel['target_column']
                    
                    if target_column not in target_blueprint.property_resources:
                        warnings.append(
                            f"FK relationship in {blueprint.dataset_name}.{fk_rel['source_column']} "
                            f"points to missing column '{target_dataset}.{target_column}'"
                        )
        
        return warnings
