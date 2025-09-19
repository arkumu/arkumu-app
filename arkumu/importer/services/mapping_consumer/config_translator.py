"""
Config Translator

Converts GUI mapping configurations to execution engine format.
"""

import logging
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from enum import Enum

from arkumu.common.uri_utils import normalize_string_nfc
from arkumu.importer.utils.mapping_utils import MappingUtils

logger = logging.getLogger(__name__)


class ColumnType(Enum):
    """Types of columns in mapping configuration"""
    REGULAR = "regular"
    ANCHOR = "anchor"
    FOREIGN_KEY = "foreign_key"
    MULTI_VALUE = "multi_value"
    MULTI_VALUE_FOREIGN_KEY = "multi_value_foreign_key"
    RELATIONSHIP_CONTEXT = "relationship_context"
    EXTERNAL_ONTOLOGY = "external_ontology"


class ProcessingStrategy(Enum):
    """Processing strategy - simplified to single approach"""
    STREAMING_ENTITY_CENTRIC = "streaming_entity_centric"


@dataclass
class ColumnConfig:
    """Configuration for a single column"""
    column_name: str
    dataset_name: str
    arkumu_type: str
    datatype: str = "http://www.w3.org/2001/XMLSchema#string"
    column_type: ColumnType = ColumnType.REGULAR
    is_anchor: bool = False
    is_multi_value: bool = False
    multi_value_separator: str = ","
    confidence: Optional[float] = None
    
    # FK configuration
    is_fk: bool = False
    fk_config: Optional[Dict[str, Any]] = None
    
    # External ontology configuration
    is_external_ontology: bool = False
    external_ontology_config: Optional[Dict[str, Any]] = None
    
    # Original GUI configuration (for debugging)
    original_config: Optional[Dict[str, Any]] = None


@dataclass
class FKRelationship:
    """Configuration for a foreign key relationship"""
    source_column: str
    source_dataset: str
    target_column: str
    target_dataset: str
    relationship_type: str
    direction: str = "outgoing"  # "outgoing" or "incoming"
    is_multi_value: bool = False
    multi_value_separator: str = ","
    confidence: Optional[float] = None


@dataclass
class RelationshipContext:
    """Configuration for relationship context (junction table attributes)"""
    context_id: str
    primary_fk: str
    secondary_fk: str
    context_columns: List[str]
    context_type: str
    dataset_name: str


@dataclass
class ExternalOntology:
    """Configuration for external ontology integration"""
    column_name: str
    dataset_name: str
    ontology_type: str  # "orcid", "wikidata", "dublin_core", etc.
    uri_template: str
    identifier_column: Optional[str] = None
    validation_enabled: bool = True


@dataclass
class DatasetConfig:
    """Configuration for a dataset"""
    dataset_name: str
    columns: List[ColumnConfig]
    primary_key_columns: List[str] = field(default_factory=list)
    dependencies: List[str] = field(default_factory=list)  # Datasets this depends on


@dataclass
class ExecutionPhase:
    """A phase in the execution plan"""
    phase_number: int
    phase_name: str
    datasets: List[str]
    description: str
    dependencies: List[str] = field(default_factory=list)


@dataclass
class ExecutionConfig:
    """Complete configuration for execution engine"""
    mapping_id: int
    mapping_name: str
    organization: str
    version: str = "1.1"
    
    # Core configuration
    datasets: List[DatasetConfig] = field(default_factory=list)
    processing_strategy: ProcessingStrategy = ProcessingStrategy.STREAMING_ENTITY_CENTRIC
    column_configurations: Dict[str, ColumnConfig] = field(default_factory=dict)
    fk_relationships: List[FKRelationship] = field(default_factory=list)
    relationship_contexts: List[RelationshipContext] = field(default_factory=list)
    external_ontologies: List[ExternalOntology] = field(default_factory=list)
    
    # Execution planning
    processing_phases: List[ExecutionPhase] = field(default_factory=list)
    estimated_complexity: str = "medium"
    
    # Import strategy settings
    import_strategy: Dict[str, Any] = field(default_factory=dict)
    
    def get_dataset_config(self, dataset_name: str) -> Optional[DatasetConfig]:
        """Get configuration for a specific dataset"""
        for dataset in self.datasets:
            if dataset.dataset_name == dataset_name:
                return dataset
        return None
    
    def get_column_config(self, dataset_name: str, column_name: str) -> Optional[ColumnConfig]:
        """Get configuration for a specific column"""
        key = f"{dataset_name}.{column_name}"
        return self.column_configurations.get(key)
    
    def get_fk_relationships_for_dataset(self, dataset_name: str) -> List[FKRelationship]:
        """Get all FK relationships for a dataset"""
        return [fk for fk in self.fk_relationships 
                if fk.source_dataset == dataset_name or fk.target_dataset == dataset_name]
    
    @property
    def organization_id(self) -> str:
        """Backward compatibility property for organization_id"""
        return self.organization


class ConfigTranslator:
    """
    Translates between GUI mapping format and execution format.
    
    Converts the workspace_columns, fk_relationships, and other GUI configurations
    into structured ExecutionConfig objects that the execution engine can consume.
    """
    
    def translate_mapping_config(self, mapping_config: Dict[str, Any]) -> ExecutionConfig:
        """
        Translate complete mapping configuration to execution format.
        
        Args:
            mapping_config: Raw mapping configuration from GUI
            
        Returns:
            ExecutionConfig object ready for execution
        """
        metadata = mapping_config.get('_metadata', {})
        
        execution_config = ExecutionConfig(
            mapping_id=metadata.get('mapping_id', 0),
            mapping_name=metadata.get('mapping_name', 'Unknown'),
            organization=metadata.get('organization', 'Unknown'),
            version=mapping_config.get('version', '1.1')
        )
        
        # Translate workspace columns
        workspace_columns = mapping_config.get('workspace_columns', {})
        # Support both old 'selected_datasets' and new 'workspace_datasets'
        selected_datasets = mapping_config.get('workspace_datasets', mapping_config.get('selected_datasets', []))
        
        self._translate_workspace_columns(workspace_columns, selected_datasets, execution_config)
        
        # Translate import strategy
        import_strategy = mapping_config.get('import_strategy', {})
        self._translate_import_strategy(import_strategy, execution_config)
        
        # Build dataset configurations
        self._build_dataset_configurations(execution_config)
        
        logger.info(f"Translated mapping config: {len(execution_config.datasets)} datasets, "
                   f"{len(execution_config.column_configurations)} columns, "
                   f"{len(execution_config.fk_relationships)} FK relationships")
        
        return execution_config
    
    def _normalize_workspace_columns(self, workspace_columns: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
        """
        Normalize workspace columns to old nested format for compatibility.
        Handles both old nested format and new flat qualified-key format.
        
        Returns: {dataset_name: {column_name: config}}
        """
        # Check if this is the new flat format (qualified keys like "org::dataset::column")
        sample_key = next(iter(workspace_columns.keys()), "")
        if "::" in sample_key:
            # New flat format - convert to nested
            normalized = {}
            for qualified_key, config in workspace_columns.items():
                parts = qualified_key.split("::")
                if len(parts) >= 3:
                    # Format: org::dataset[.csv]::column (column may itself contain '::')
                    org, dataset, column = (
                        normalize_string_nfc(parts[0]),
                        normalize_string_nfc(parts[1].removesuffix('.csv')),
                        normalize_string_nfc("::".join(parts[2:]))
                    )
                    if dataset not in normalized:
                        normalized[dataset] = {}
                    normalized[dataset][column] = config
                elif len(parts) == 2:
                    # Legacy format without org: dataset[.csv]::column
                    dataset = normalize_string_nfc(parts[0].removesuffix('.csv'))
                    column = normalize_string_nfc("::".join(parts[1:]))
                    if dataset not in normalized:
                        normalized[dataset] = {}
                    normalized[dataset][column] = config
                else:
                    logger.warning(f"Invalid qualified key format: {qualified_key}")
            return normalized
        else:
            # Old nested format - return as-is
            return workspace_columns

    def _translate_workspace_columns(self, workspace_columns: Dict[str, Any], 
                                   selected_datasets: List[str],
                                   execution_config: ExecutionConfig):
        """Translate workspace columns to column configurations"""
        
        # Normalize to nested format for compatibility
        normalized_columns = self._normalize_workspace_columns(workspace_columns)
        
        for dataset_name, columns in normalized_columns.items():
            # Normalize dataset name for consistent comparison
            normalized_dataset_name = normalize_string_nfc(dataset_name)
            
            # Check if normalized dataset name is in selected datasets (also normalize those)
            normalized_selected = [normalize_string_nfc(ds) for ds in selected_datasets]
            if normalized_dataset_name not in normalized_selected:
                logger.debug(f"Skipping dataset {dataset_name} - not in selected datasets")
                continue
                
            for column_name, column_config in columns.items():
                raw_separator = column_config.get('multi_value_separator')
                separator = raw_separator if raw_separator not in (None, "") else ','

                # Create column configuration with normalized dataset name
                col_config = ColumnConfig(
                    column_name=normalize_string_nfc(column_name),
                    dataset_name=normalized_dataset_name,
                    arkumu_type=normalize_string_nfc(column_config.get('arkumu_type', column_name)),
                    datatype=column_config.get('datatype', 'http://www.w3.org/2001/XMLSchema#string'),
                    is_anchor=column_config.get('is_anchor', False),
                    is_multi_value=column_config.get('is_multi_value', False),
                    multi_value_separator=separator,
                    confidence=column_config.get('confidence'),
                    is_fk=column_config.get('is_fk', False) or bool(column_config.get('fk_config')),
                    fk_config=column_config.get('fk_config'),
                    is_external_ontology=column_config.get('is_external_ontology', False),
                    external_ontology_config=column_config.get('external_ontology'),
                    original_config=column_config
                )
                
                # Determine column type using centralized MappingUtils
                # Create a proper config dict for MappingUtils from the ColumnConfig object
                mapping_utils_config = {
                    'is_fk': col_config.is_fk,
                    'fk_config': col_config.fk_config,
                    'is_anchor': col_config.is_anchor,
                    'is_multi_value': col_config.is_multi_value,
                    'is_external_ontology': col_config.is_external_ontology,
                    'is_relationship_context': False  # Will be set later by relationship context processing
                }
                detected_type = MappingUtils.detect_column_type(mapping_utils_config)
                col_config.column_type = ColumnType(detected_type)
                
                # Store in execution config
                key = f"{dataset_name}.{column_name}"
                execution_config.column_configurations[key] = col_config
                
                # Process FK relationship directly from workspace column
                if col_config.is_fk and col_config.fk_config:
                    self._process_fk_from_workspace_column(key, col_config, execution_config)
                
                # Process external ontology directly from workspace column
                if col_config.is_external_ontology and col_config.external_ontology_config:
                    self._process_external_ontology_from_workspace_column(key, col_config, execution_config)
                
                # Process relationship context directly from workspace column
                if column_config.get('is_relationship_context'):
                    self._process_relationship_context_from_workspace_column(key, col_config, column_config, execution_config)
    
    def _process_fk_from_workspace_column(self, column_key: str, col_config: ColumnConfig, execution_config: ExecutionConfig):
        """Process FK relationship directly from workspace column configuration"""
        fk_config = col_config.fk_config
        
        # Create FKRelationship from workspace column data
        fk_relationship = FKRelationship(
            source_column=normalize_string_nfc(col_config.column_name),
            source_dataset=normalize_string_nfc(col_config.dataset_name),
            target_column=normalize_string_nfc(fk_config.get('target_column', '')),
            target_dataset=normalize_string_nfc(fk_config.get('target_dataset', '')),
            relationship_type=fk_config.get('relationship_type', 'reference'),
            direction=fk_config.get('direction', 'outbound'),
            # Use multi-value info from column config (no "correction" needed!)
            is_multi_value=col_config.is_multi_value,
            multi_value_separator=col_config.multi_value_separator,
            confidence=col_config.confidence
        )
        
        execution_config.fk_relationships.append(fk_relationship)
    
    def _process_external_ontology_from_workspace_column(self, column_key: str, col_config: ColumnConfig, execution_config: ExecutionConfig):
        """Process external ontology directly from workspace column configuration"""
        ontology_config = col_config.external_ontology_config
        
        # Create ExternalOntology from workspace column data
        external_ontology = ExternalOntology(
            column_name=normalize_string_nfc(col_config.column_name),
            dataset_name=normalize_string_nfc(col_config.dataset_name),
            ontology_type=ontology_config.get('ontology_type', ''),
            uri_template=ontology_config.get('uri_template', ''),
            identifier_column=ontology_config.get('identifier_column'),
            validation_enabled=ontology_config.get('validation_enabled', True)
        )
        
        execution_config.external_ontologies.append(external_ontology)
    
    def _process_relationship_context_from_workspace_column(self, column_key: str, col_config: ColumnConfig, column_config: dict, execution_config: ExecutionConfig):
        """Process relationship context directly from workspace column configuration"""
        context_config = column_config.get('relationship_context_config', {})
        
        # Create RelationshipContext from workspace column data
        relationship_context = RelationshipContext(
            context_id=context_config.get('context_id', column_key),
            primary_fk=context_config.get('primary_fk', ''),
            secondary_fk=context_config.get('secondary_fk', ''),
            context_columns=[col_config.column_name],
            context_type=context_config.get('context_type', 'attribute'),
            dataset_name=normalize_string_nfc(col_config.dataset_name)
        )
        
        execution_config.relationship_contexts.append(relationship_context)
    
    def _translate_import_strategy(self, import_strategy: Dict[str, Any],
                                 execution_config: ExecutionConfig):
        """Translate import strategy settings"""
        
        execution_config.import_strategy = {
            'update_strategy': import_strategy.get('update_strategy', 'SKIP_EXISTING'),
            'bulk_size': import_strategy.get('bulk_size', 1000),
            'multi_value_threshold': import_strategy.get('multi_value_threshold', 0.2),
            'enable_progress_tracking': import_strategy.get('enable_progress_tracking', True),
            'batch_processing': import_strategy.get('batch_processing', True)
        }
        
        # Processing strategy is always STREAMING_ENTITY_CENTRIC (simplified architecture)
        execution_config.processing_strategy = ProcessingStrategy.STREAMING_ENTITY_CENTRIC
        
        # Log if user tried to specify a different strategy
        if 'processing_strategy' in import_strategy and import_strategy['processing_strategy'] != 'streaming_entity_centric':
            logger.info(f"Processing strategy {import_strategy['processing_strategy']} requested, but using STREAMING_ENTITY_CENTRIC (simplified architecture)")
    
    def _build_dataset_configurations(self, execution_config: ExecutionConfig):
        """Build dataset configurations from column configurations"""
        
        # Group columns by dataset
        dataset_columns: Dict[str, List[ColumnConfig]] = {}
        
        for column_config in execution_config.column_configurations.values():
            dataset_name = column_config.dataset_name
            if dataset_name not in dataset_columns:
                dataset_columns[dataset_name] = []
            dataset_columns[dataset_name].append(column_config)
        
        # Create dataset configurations
        for dataset_name, columns in dataset_columns.items():
            # Normalize dataset name
            dataset_name = normalize_string_nfc(dataset_name)
            # Find anchor columns (primary keys)
            anchor_columns = [col.column_name for col in columns if col.is_anchor]
            
            # Determine dependencies based on FK relationships
            dependencies = []
            for fk in execution_config.fk_relationships:
                if fk.source_dataset == dataset_name and fk.target_dataset != dataset_name:
                    if fk.target_dataset not in dependencies:
                        dependencies.append(fk.target_dataset)
            
            dataset_config = DatasetConfig(
                dataset_name=dataset_name,
                columns=columns,
                primary_key_columns=anchor_columns,
                dependencies=dependencies
            )
            
            execution_config.datasets.append(dataset_config)
        
        logger.debug(f"Built {len(execution_config.datasets)} dataset configurations")
        
        # Log dataset dependencies
        for dataset in execution_config.datasets:
            if dataset.dependencies:
                logger.debug(f"Dataset '{dataset.dataset_name}' depends on: {dataset.dependencies}")
    
    def get_execution_summary(self, execution_config: ExecutionConfig) -> Dict[str, Any]:
        """
        Generate a summary of the execution configuration.
        
        Args:
            execution_config: ExecutionConfig object
            
        Returns:
            Dictionary with summary information
        """
        column_types = {}
        for col_config in execution_config.column_configurations.values():
            col_type = col_config.column_type.value
            column_types[col_type] = column_types.get(col_type, 0) + 1
        
        return {
            'mapping_info': {
                'id': execution_config.mapping_id,
                'name': execution_config.mapping_name,
                'organization': execution_config.organization,
                'version': execution_config.version
            },
            'datasets': {
                'count': len(execution_config.datasets),
                'names': [d.dataset_name for d in execution_config.datasets],
                'with_dependencies': len([d for d in execution_config.datasets if d.dependencies])
            },
            'columns': {
                'total': len(execution_config.column_configurations),
                'types': column_types,
                'anchor_columns': sum(1 for col in execution_config.column_configurations.values() if col.is_anchor),
                'multi_value_columns': sum(1 for col in execution_config.column_configurations.values() if col.is_multi_value)
            },
            'relationships': {
                'fk_relationships': len(execution_config.fk_relationships),
                'relationship_contexts': len(execution_config.relationship_contexts),
                'external_ontologies': len(execution_config.external_ontologies)
            },
            'processing': {
                'strategy': execution_config.processing_strategy.value,
                'estimated_complexity': execution_config.estimated_complexity,
                'phases': len(execution_config.processing_phases)
            }
        }
