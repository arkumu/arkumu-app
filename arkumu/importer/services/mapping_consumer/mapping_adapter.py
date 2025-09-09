"""
Mapping Adapter

Loads and adapts mapping configurations from arkumu.metadata for execution.
"""

import logging
from typing import Dict, Any, Optional, List
from dataclasses import dataclass
from datetime import datetime

from django.core.exceptions import ObjectDoesNotExist
from arkumu.metadata.models.mappings import Mapping
from .config_translator import ConfigTranslator, ExecutionConfig
from arkumu.importer.services.mapping_validation.validator import MappingValidator
from dataclasses import dataclass, field
from typing import Dict, Any, List
from arkumu.common.uri_utils import normalize_string_nfc

@dataclass
class ValidationResult:
    """Result of mapping validation - compatibility layer"""
    is_valid: bool
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    summary: str = ""

logger = logging.getLogger(__name__)


@dataclass
class MappingInfo:
    """Basic information about a mapping"""
    id: int
    name: str
    organization: str
    created_at: datetime
    updated_at: datetime
    version: str
    datasets: List[str]
    total_columns: int
    fk_relationships: int
    external_ontologies: int


class MappingAdapter:
    """
    Adapts GUI mapping configurations for execution engine consumption.
    
    This class serves as the bridge between the CSV mapping GUI system
    (arkumu.metadata) and the execution engine (arkumu.importer).
    """
    
    def __init__(self):
        self.config_translator = ConfigTranslator()
        self.mapping_validator = MappingValidator()
    
    def _convert_to_validation_result(self, completeness_result: Dict[str, Any]) -> ValidationResult:
        """Convert new validator result to old ValidationResult format"""
        issues = completeness_result.get('issues', [])
        errors = [issue['message'] for issue in issues if issue.get('severity') == 'ERROR']
        warnings = [issue['message'] for issue in issues if issue.get('severity') == 'WARNING']
        
        is_valid = completeness_result.get('is_complete', True) and len(errors) == 0
        
        summary = f"Validation {'passed' if is_valid else 'failed'}"
        if errors or warnings:
            summary += f" - {len(errors)} errors, {len(warnings)} warnings"
            
        return ValidationResult(
            is_valid=is_valid,
            errors=errors,
            warnings=warnings,
            summary=summary
        )
        
    def load_mapping_config(self, mapping_id: int) -> Dict[str, Any]:
        """
        Load mapping configuration from database.
        
        Args:
            mapping_id: ID of the mapping to load
            
        Returns:
            Raw mapping configuration dictionary
            
        Raises:
            ObjectDoesNotExist: If mapping doesn't exist
            ValueError: If mapping configuration is invalid
        """
        try:
            mapping = Mapping.objects.get(id=mapping_id)
            logger.info(f"Loaded mapping '{mapping.name}' (ID: {mapping_id})")
            
            # Parse the mapping configuration
            config = mapping.mapping_config
            if not isinstance(config, dict):
                raise ValueError(f"Mapping {mapping_id} has invalid configuration format")
                
            # Add metadata
            config['_metadata'] = {
                'mapping_id': mapping.id,
                'mapping_name': mapping.name,
                'organization': mapping.organization_id,
                'created_at': mapping.created_at,
                'updated_at': mapping.updated_at,
                'created_by': mapping.created_by.username if mapping.created_by else None
            }
            
            return config
            
        except ObjectDoesNotExist:
            logger.error(f"Mapping with ID {mapping_id} not found")
            raise
        except Exception as e:
            logger.error(f"Failed to load mapping {mapping_id}: {e}")
            raise ValueError(f"Failed to load mapping configuration: {e}")
    
    def get_mapping_info(self, mapping_id: int) -> MappingInfo:
        """
        Get basic information about a mapping without loading full config.
        
        Args:
            mapping_id: ID of the mapping
            
        Returns:
            MappingInfo object with basic metadata
        """
        try:
            mapping = Mapping.objects.get(id=mapping_id)
            config = mapping.mapping_config
            
            # Extract basic statistics
            workspace_columns = config.get('workspace_columns', {})
            # Support both old 'selected_datasets' and new 'workspace_datasets'
            selected_datasets = [normalize_string_nfc(ds) for ds in config.get('workspace_datasets', config.get('selected_datasets', []))]
            fk_relationships = config.get('fk_relationships', {})
            external_ontologies = config.get('external_ontologies', {})
            
            # Calculate total columns - handle both old nested and new flat formats
            if workspace_columns and "::" in next(iter(workspace_columns.keys()), ""):
                # New flat format - count qualified keys
                total_columns = len(workspace_columns)
            else:
                # Old nested format - count nested columns
                total_columns = sum(len(columns) for columns in workspace_columns.values())
            
            # Use workspace_columns keys as datasets if selected_datasets is empty
            if selected_datasets:
                datasets = selected_datasets
            else:
                # Extract unique dataset names from workspace_columns keys
                # Keys are in format "org::dataset::column" or just "dataset"
                dataset_names = set()
                for key in workspace_columns.keys():
                    if '::' in key:
                        parts = key.split('::')
                        if len(parts) >= 2:
                            # Extract dataset name from "org::dataset::column" format
                            dataset_name = normalize_string_nfc(parts[1])
                            dataset_names.add(dataset_name)
                        else:
                            # Fallback to first part
                            dataset_names.add(normalize_string_nfc(parts[0]))
                    else:
                        # Direct dataset name
                        dataset_names.add(normalize_string_nfc(key))
                datasets = list(dataset_names)
            
            return MappingInfo(
                id=mapping.id,
                name=mapping.name,
                organization=mapping.organization_id,
                created_at=mapping.created_at,
                updated_at=mapping.updated_at,
                version=config.get('version', '1.0'),
                datasets=datasets,
                total_columns=total_columns,
                fk_relationships=len(fk_relationships),
                external_ontologies=len(external_ontologies)
            )
            
        except ObjectDoesNotExist:
            logger.error(f"Mapping with ID {mapping_id} not found")
            raise
    
    def list_mappings_for_organization(self, organization: str) -> List[MappingInfo]:
        """
        List all mappings for an organization.
        
        Args:
            organization: Organization identifier
            
        Returns:
            List of MappingInfo objects
        """
        try:
            mappings = Mapping.objects.filter(organization_id=organization).order_by('-updated_at')
            
            mapping_infos = []
            for mapping in mappings:
                try:
                    info = self.get_mapping_info(mapping.id)
                    mapping_infos.append(info)
                except Exception as e:
                    logger.warning(f"Failed to get info for mapping {mapping.id}: {e}")
                    continue
                    
            logger.info(f"Found {len(mapping_infos)} mappings for organization '{organization}'")
            return mapping_infos
            
        except Exception as e:
            logger.error(f"Failed to list mappings for organization '{organization}': {e}")
            return []
    
    def validate_mapping(self, mapping_id: int) -> ValidationResult:
        """
        Validate a mapping configuration for execution readiness.
        
        Args:
            mapping_id: ID of the mapping to validate
            
        Returns:
            ValidationResult with validation status and details
        """
        try:
            config = self.load_mapping_config(mapping_id)
            completeness_result = self.mapping_validator.validate_mapping_completeness(config)
            return self._convert_to_validation_result(completeness_result)
            
        except Exception as e:
            logger.error(f"Failed to validate mapping {mapping_id}: {e}")
            return ValidationResult(
                is_valid=False,
                errors=[f"Failed to load mapping: {e}"],
                warnings=[],
                summary="Mapping could not be loaded for validation"
            )
    
    def translate_to_execution_config(self, mapping_id: int) -> ExecutionConfig:
        """
        Load and translate mapping to execution configuration.
        
        Args:
            mapping_id: ID of the mapping to translate
            
        Returns:
            ExecutionConfig object ready for execution engine
            
        Raises:
            ValueError: If mapping is invalid or cannot be translated
        """
        # Load the mapping configuration
        config = self.load_mapping_config(mapping_id)
        
        # Validate mapping completeness using the new validator
        validation_result = self.mapping_validator.validate_mapping_completeness(config)
        if not validation_result['is_complete']:
            issues = validation_result.get('issues', [])
            error_messages = [issue['message'] for issue in issues if issue.get('severity') == 'ERROR']
            if error_messages:
                error_msg = f"Mapping {mapping_id} validation failed: {'; '.join(error_messages)}"
                logger.warning(error_msg)  # Changed to warning since your validator is more lenient
                # Don't raise error - let the execution proceed and handle issues gracefully
        
        # Translate to execution format
        execution_config = self.config_translator.translate_mapping_config(config)
        
        # Log correct column counts using MappingUtils analysis  
        from arkumu.importer.utils.mapping_utils import MappingUtils
        column_analysis = MappingUtils.analyze_mapping_structure(config)
        
        logger.info(f"Successfully translated mapping {mapping_id} to execution config")
        logger.debug(f"Execution config: {len(execution_config.datasets)} datasets, "
                    f"{column_analysis['total_columns']} total columns "
                    f"(regular: {column_analysis['regular_columns']}, "
                    f"FK: {column_analysis['foreign_key_columns']}, "
                    f"multi-value: {column_analysis['multi_value_columns']}, "
                    f"multi-value FK: {column_analysis['multi_value_fk_columns']}), "
                    f"{len(execution_config.fk_relationships)} FK relationships")
        
        return execution_config
    
    def get_mapping_summary(self, mapping_id: int) -> Dict[str, Any]:
        """
        Get a comprehensive summary of a mapping for display purposes.
        
        Args:
            mapping_id: ID of the mapping
            
        Returns:
            Dictionary with mapping summary information
        """
        try:
            info = self.get_mapping_info(mapping_id)
            validation_result = self.validate_mapping(mapping_id)
            
            return {
                'mapping_info': {
                    'id': info.id,
                    'name': info.name,
                    'organization': info.organization,
                    'created_at': info.created_at,
                    'updated_at': info.updated_at,
                    'version': info.version,
                    'datasets': info.datasets,
                    'total_columns': info.total_columns,
                    'fk_relationships': info.fk_relationships,
                    'external_ontologies': info.external_ontologies
                },
                'validation': {
                    'is_valid': validation_result.is_valid,
                    'error_count': len(validation_result.errors),
                    'warning_count': len(validation_result.warnings),
                    'summary': validation_result.summary
                },
                'execution_ready': validation_result.is_valid,
                'complexity_score': self._calculate_complexity_score(info)
            }
            
        except Exception as e:
            logger.error(f"Failed to get mapping summary for {mapping_id}: {e}")
            return {
                'error': str(e),
                'execution_ready': False
            }
    
    def _calculate_complexity_score(self, info: MappingInfo) -> str:
        """
        Calculate a simple complexity score for the mapping.
        
        Args:
            info: MappingInfo object
            
        Returns:
            Complexity score as string ("low", "medium", "high")
        """
        score = 0
        
        # Dataset count
        if len(info.datasets) > 3:
            score += 2
        elif len(info.datasets) > 1:
            score += 1
            
        # Column count
        if info.total_columns > 20:
            score += 2
        elif info.total_columns > 10:
            score += 1
            
        # FK relationships
        if info.fk_relationships > 5:
            score += 2
        elif info.fk_relationships > 0:
            score += 1
            
        # External ontologies
        if info.external_ontologies > 0:
            score += 1
            
        if score >= 5:
            return "high"
        elif score >= 3:
            return "medium"
        else:
            return "low"