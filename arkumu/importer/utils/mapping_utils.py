"""
Centralized Mapping Utilities

This module provides a comprehensive set of utilities for consistent mapping manipulation
across the entire Arkumu codebase. It centralizes all mapping-related operations that
were previously scattered across multiple files.

Key Features:
- Workspace columns manipulation (get, set, update, clear)
- Column type detection and classification
- Mapping configuration processing and validation
- Data structure conversions
- Consistent mapping analysis

This module serves as the SINGLE SOURCE OF TRUTH for all mapping operations.
"""

import logging
from typing import Dict, Any, List, Optional, Union, Tuple, Set
from datetime import datetime

logger = logging.getLogger(__name__)


class MappingUtils:
    """
    Centralized utilities for mapping operations.
    
    This class provides all the methods needed to manipulate mappings consistently
    across the codebase, replacing scattered implementations.
    """
    
    # ============================================================================
    # WORKSPACE COLUMNS MANIPULATION
    # ============================================================================
    
    @staticmethod
    def get_workspace_columns(mapping_config: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
        """
        Get workspace columns from mapping configuration.
        
        Args:
            mapping_config: Raw mapping configuration dict
            
        Returns:
            Dict[str, Dict]: Workspace columns keyed by column name
        """
        return mapping_config.get('workspace_columns', {})
    
    @staticmethod
    def get_workspace_column(mapping_config: Dict[str, Any], column_name: str) -> Optional[Dict[str, Any]]:
        """
        Get a specific workspace column by name.
        
        Args:
            mapping_config: Raw mapping configuration dict
            column_name: Name of the column to retrieve
            
        Returns:
            Optional[Dict]: Column configuration or None if not found
        """
        workspace_columns = MappingUtils.get_workspace_columns(mapping_config)
        return workspace_columns.get(column_name)
    
    @staticmethod
    def update_workspace_column(mapping_config: Dict[str, Any], column_name: str, 
                              column_config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Update a specific workspace column.
        
        Args:
            mapping_config: Raw mapping configuration dict
            column_name: Name of the column to update
            column_config: New column configuration
            
        Returns:
            Dict: Updated mapping configuration
        """
        if 'workspace_columns' not in mapping_config:
            mapping_config['workspace_columns'] = {}
        
        mapping_config['workspace_columns'][column_name] = column_config
        return mapping_config
    
    @staticmethod
    def remove_workspace_column(mapping_config: Dict[str, Any], column_name: str) -> Dict[str, Any]:
        """
        Remove a workspace column.
        
        Args:
            mapping_config: Raw mapping configuration dict
            column_name: Name of the column to remove
            
        Returns:
            Dict: Updated mapping configuration
        """
        workspace_columns = mapping_config.get('workspace_columns', {})
        if column_name in workspace_columns:
            del workspace_columns[column_name]
        
        return mapping_config
    
    # ============================================================================
    # COLUMN TYPE DETECTION AND CLASSIFICATION
    # ============================================================================
    
    @staticmethod
    def get_column_characteristics(column_config: Dict[str, Any]) -> Dict[str, bool]:
        """
        Get all characteristics of a column (can have multiple).
        
        Args:
            column_config: Column configuration dict
            
        Returns:
            Dict[str, bool]: All characteristics this column has
        """
        return {
            'is_anchor': column_config.get('is_anchor', False),
            'is_fk': column_config.get('is_fk', False) or bool(column_config.get('fk_config')),
            'is_multi_value': column_config.get('is_multi_value', False),
            'is_external_ontology': column_config.get('is_external_ontology', False),
            'is_relationship_context': column_config.get('is_relationship_context', False),
        }
    
    @staticmethod
    def get_column_type_combination(column_config: Dict[str, Any]) -> str:
        """
        Get the full type combination string for a column.
        
        This properly handles ALL combinations like:
        - anchor_foreign_key 
        - multi_value_foreign_key
        - anchor_multi_value_foreign_key
        - etc.
        
        Args:
            column_config: Column configuration dict
            
        Returns:
            str: Full combination type (e.g., "anchor_multi_value_foreign_key")
        """
        characteristics = MappingUtils.get_column_characteristics(column_config)
        
        # Build type combination in consistent order
        type_parts = []
        
        # Order matters for consistency
        if characteristics['is_anchor']:
            type_parts.append('anchor')
        if characteristics['is_multi_value']:
            type_parts.append('multi_value')
        if characteristics['is_fk']:
            type_parts.append('foreign_key')
        if characteristics['is_relationship_context']:
            type_parts.append('relationship_context')
        if characteristics['is_external_ontology']:
            type_parts.append('external_ontology')
        
        if not type_parts:
            return 'regular'
        
        return '_'.join(type_parts)
    
    @staticmethod
    def detect_column_type(column_config: Dict[str, Any]) -> str:
        """
        Detect the primary type of a column for backwards compatibility.
        
        Args:
            column_config: Column configuration dict
            
        Returns:
            str: Primary column type
        """
        # For backwards compatibility, return the most specific single type
        combination = MappingUtils.get_column_type_combination(column_config)
        
        # Map combinations to primary types for backwards compatibility
        if 'anchor' in combination:
            return 'anchor'
        elif 'relationship_context' in combination:
            return 'relationship_context'
        elif 'external_ontology' in combination:
            return 'external_ontology'
        elif 'multi_value' in combination and 'foreign_key' in combination:
            return 'multi_value_foreign_key'
        elif 'foreign_key' in combination:
            return 'foreign_key'
        elif 'multi_value' in combination:
            return 'multi_value'
        else:
            return 'regular'
    
    @staticmethod
    def is_multi_value_fk_column(column_config: Dict[str, Any]) -> bool:
        """
        Check if a column is both multi-value AND foreign key.
        
        Args:
            column_config: Column configuration dict
            
        Returns:
            bool: True if column is multi-value FK
        """
        return MappingUtils.detect_column_type(column_config) == 'multi_value_foreign_key'
    
    @staticmethod
    def group_columns_by_type(mapping_config: Dict[str, Any]) -> Dict[str, List[str]]:
        """
        Group workspace columns by their detected types.
        
        Args:
            mapping_config: Raw mapping configuration dict
            
        Returns:
            Dict[str, List[str]]: Column names grouped by primary type
        """
        workspace_columns = MappingUtils.get_workspace_columns(mapping_config)
        
        groups = {
            'regular': [],
            'anchor': [],
            'foreign_key': [],
            'multi_value': [],
            'multi_value_foreign_key': [],
            'relationship_context': [],
            'external_ontology': []
        }
        
        for column_name, column_config in workspace_columns.items():
            column_type = MappingUtils.detect_column_type(column_config)
            groups[column_type].append(column_name)
        
        return groups
    
    @staticmethod
    def group_columns_by_characteristics(mapping_config: Dict[str, Any]) -> Dict[str, List[str]]:
        """
        Group columns by ALL their characteristics (not just primary type).
        
        This allows you to get all anchor columns, all FK columns, all multi-value columns, etc.
        regardless of their other characteristics.
        
        Args:
            mapping_config: Raw mapping configuration dict
            
        Returns:
            Dict[str, List[str]]: Column names grouped by each characteristic
        """
        workspace_columns = MappingUtils.get_workspace_columns(mapping_config)
        
        characteristic_groups = {
            'all_anchors': [],
            'all_foreign_keys': [], 
            'all_multi_values': [],
            'all_relationship_contexts': [],
            'all_external_ontologies': [],
            'regular': []  # Only columns with no special characteristics
        }
        
        for column_name, column_config in workspace_columns.items():
            characteristics = MappingUtils.get_column_characteristics(column_config)
            
            # Add to characteristic groups
            if characteristics['is_anchor']:
                characteristic_groups['all_anchors'].append(column_name)
            if characteristics['is_fk']:
                characteristic_groups['all_foreign_keys'].append(column_name)
            if characteristics['is_multi_value']:
                characteristic_groups['all_multi_values'].append(column_name)
            if characteristics['is_relationship_context']:
                characteristic_groups['all_relationship_contexts'].append(column_name)
            if characteristics['is_external_ontology']:
                characteristic_groups['all_external_ontologies'].append(column_name)
            
            # Regular only if it has NO special characteristics
            if not any(characteristics.values()):
                characteristic_groups['regular'].append(column_name)
        
        return characteristic_groups
    
    @staticmethod
    def get_columns_with_combination(mapping_config: Dict[str, Any], 
                                   required_characteristics: List[str]) -> List[str]:
        """
        Get columns that have ALL the specified characteristics.
        
        Example: get_columns_with_combination(config, ['is_anchor', 'is_fk'])
        returns all columns that are BOTH anchor AND foreign key
        
        Args:
            mapping_config: Raw mapping configuration dict
            required_characteristics: List of characteristics that must ALL be true
            
        Returns:
            List[str]: Column names that have all specified characteristics
        """
        workspace_columns = MappingUtils.get_workspace_columns(mapping_config)
        matching_columns = []
        
        for column_name, column_config in workspace_columns.items():
            characteristics = MappingUtils.get_column_characteristics(column_config)
            
            # Check if column has ALL required characteristics
            if all(characteristics.get(char, False) for char in required_characteristics):
                matching_columns.append(column_name)
        
        return matching_columns
    
    # ============================================================================
    # COMPREHENSIVE MAPPING ANALYSIS
    # ============================================================================
    
    @staticmethod
    def analyze_mapping_structure(mapping_config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Comprehensive analysis of mapping structure that properly handles ALL combinations.
        
        This is the MAIN analysis method that should replace all scattered
        column analysis throughout the codebase.
        
        Args:
            mapping_config: Raw mapping configuration dict
            
        Returns:
            Dict: Comprehensive analysis results including:
                - Column counts by primary type
                - Column counts by characteristics (all anchors, all FKs, etc.)
                - Combination details (anchor+FK, multi-value+FK, etc.)
                - Dataset breakdown
                - Validation results
        """
        workspace_columns = MappingUtils.get_workspace_columns(mapping_config)
        column_groups = MappingUtils.group_columns_by_type(mapping_config)
        characteristic_groups = MappingUtils.group_columns_by_characteristics(mapping_config)
        
        # Primary type counts (backwards compatibility)
        analysis = {
            'total_columns': len(workspace_columns),
            'regular_columns': len(column_groups['regular']),
            'anchor_columns': len(column_groups['anchor']),
            'foreign_key_columns': len(column_groups['foreign_key']),
            'multi_value_columns': len(column_groups['multi_value']),
            'multi_value_fk_columns': len(column_groups['multi_value_foreign_key']),
            'relationship_context_columns': len(column_groups['relationship_context']),
            'external_ontology_columns': len(column_groups['external_ontology']),
        }
        
        # Characteristic counts (comprehensive)
        analysis['characteristics'] = {
            'total_anchors': len(characteristic_groups['all_anchors']),
            'total_foreign_keys': len(characteristic_groups['all_foreign_keys']),
            'total_multi_values': len(characteristic_groups['all_multi_values']),
            'total_relationship_contexts': len(characteristic_groups['all_relationship_contexts']),
            'total_external_ontologies': len(characteristic_groups['all_external_ontologies']),
            'purely_regular': len(characteristic_groups['regular'])
        }
        
        # Combination analysis
        combinations = {
            'anchor_fk': MappingUtils.get_columns_with_combination(mapping_config, ['is_anchor', 'is_fk']),
            'anchor_multi_value': MappingUtils.get_columns_with_combination(mapping_config, ['is_anchor', 'is_multi_value']),
            'anchor_multi_value_fk': MappingUtils.get_columns_with_combination(mapping_config, ['is_anchor', 'is_multi_value', 'is_fk']),
            'multi_value_fk': MappingUtils.get_columns_with_combination(mapping_config, ['is_multi_value', 'is_fk']),
        }
        
        analysis['combinations'] = {k: len(v) for k, v in combinations.items()}
        analysis['combination_details'] = combinations
        
        # Detailed breakdown for special combinations
        special_combinations = []
        for column_name, column_config in workspace_columns.items():
            combination_type = MappingUtils.get_column_type_combination(column_config)
            if combination_type != 'regular' and '_' in combination_type:  # Has multiple characteristics
                special_combinations.append({
                    'column_name': column_name,
                    'combination_type': combination_type,
                    'dataset': column_config.get('dataset', ''),
                    'characteristics': MappingUtils.get_column_characteristics(column_config),
                    'config_details': {
                        'fk_config': column_config.get('fk_config', {}),
                        'multi_value_separator': column_config.get('multi_value_separator', ','),
                        'arkumu_type': column_config.get('arkumu_type', '')
                    }
                })
        
        analysis['special_combinations'] = special_combinations
        
        # Multi-value FK details (backwards compatibility)
        mv_fk_details = []
        for column_name in characteristic_groups['all_multi_values']:
            column_config = workspace_columns[column_name]
            if MappingUtils.get_column_characteristics(column_config)['is_fk']:
                mv_fk_details.append({
                    'column_key': column_name,
                    'dataset': column_config.get('dataset', ''),
                    'column_name': column_config.get('name', column_name),
                    'fk_config': column_config.get('fk_config', {}),
                    'multi_value_separator': column_config.get('multi_value_separator', ','),
                    'is_also_anchor': MappingUtils.get_column_characteristics(column_config)['is_anchor']
                })
        
        analysis['multi_value_fk_details'] = mv_fk_details
        
        # Dataset breakdown with proper combination handling
        dataset_breakdown = {}
        for column_name, column_config in workspace_columns.items():
            dataset_name = column_config.get('dataset', 'unknown')
            characteristics = MappingUtils.get_column_characteristics(column_config)
            
            if dataset_name not in dataset_breakdown:
                dataset_breakdown[dataset_name] = {
                    'regular': 0, 'anchor': 0, 'foreign_key': 0,
                    'multi_value': 0, 'multi_value_fk': 0,
                    'relationship_context': 0, 'external_ontology': 0,
                    'total': 0,
                    # NEW: characteristic totals
                    'total_anchors': 0, 'total_fks': 0, 'total_multi_values': 0,
                    'combinations': []
                }
            
            # Count by primary type (backwards compatibility)
            primary_type = MappingUtils.detect_column_type(column_config)
            if primary_type == 'multi_value_foreign_key':
                dataset_breakdown[dataset_name]['multi_value_fk'] += 1
            else:
                dataset_breakdown[dataset_name][primary_type] += 1
            
            # Count by characteristics
            if characteristics['is_anchor']:
                dataset_breakdown[dataset_name]['total_anchors'] += 1
            if characteristics['is_fk']:
                dataset_breakdown[dataset_name]['total_fks'] += 1
            if characteristics['is_multi_value']:
                dataset_breakdown[dataset_name]['total_multi_values'] += 1
            
            # Track combinations
            combination_type = MappingUtils.get_column_type_combination(column_config)
            if combination_type != 'regular' and '_' in combination_type:
                dataset_breakdown[dataset_name]['combinations'].append({
                    'column_name': column_name,
                    'combination_type': combination_type
                })
                
            dataset_breakdown[dataset_name]['total'] += 1
        
        analysis['dataset_breakdown'] = dataset_breakdown
        
        # Structure validation
        validation_results = MappingUtils.validate_mapping_structure(mapping_config)
        analysis['validation'] = validation_results
        
        return analysis
    
    # ============================================================================
    # MAPPING VALIDATION
    # ============================================================================
    
    @staticmethod
    def validate_mapping_structure(mapping_config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate mapping configuration structure.
        
        Args:
            mapping_config: Raw mapping configuration dict
            
        Returns:
            Dict: Validation results with errors, warnings, and status
        """
        validation = {
            'is_valid': True,
            'errors': [],
            'warnings': [],
            'info': []
        }
        
        # Check workspace_columns exists
        if 'workspace_columns' not in mapping_config:
            validation['errors'].append('Missing workspace_columns in mapping configuration')
            validation['is_valid'] = False
            return validation
        
        workspace_columns = mapping_config['workspace_columns']
        
        # Check if empty
        if not workspace_columns:
            validation['warnings'].append('No columns defined in workspace_columns')
        
        # Validate each column
        for column_name, column_config in workspace_columns.items():
            # Check required fields
            if not column_config.get('name') and not column_config.get('column_name'):
                validation['errors'].append(f"Column '{column_name}' missing name/column_name")
                validation['is_valid'] = False
            
            # Check multi-value FK consistency
            if MappingUtils.is_multi_value_fk_column(column_config):
                if not column_config.get('multi_value_separator'):
                    validation['warnings'].append(
                        f"Multi-value FK column '{column_name}' missing separator"
                    )
                
                validation['info'].append(
                    f"Column '{column_name}' is multi-value FK - will need special processing"
                )
        
        return validation
    
    # ============================================================================
    # DATA STRUCTURE CONVERSIONS
    # ============================================================================
    
    @staticmethod
    def convert_to_execution_format(mapping_config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Convert mapping config to execution format.
        
        Args:
            mapping_config: Raw mapping configuration dict
            
        Returns:
            Dict: Configuration in execution format
        """
        # This would replace the logic currently in ConfigTranslator
        # but maintain multi-value FK information correctly
        workspace_columns = MappingUtils.get_workspace_columns(mapping_config)
        
        execution_format = {
            'datasets': {},
            'columns': {},
            'fk_relationships': [],
            'multi_value_fk_relationships': []  # NEW: preserve multi-value FK info
        }
        
        for column_name, column_config in workspace_columns.items():
            column_type = MappingUtils.detect_column_type(column_config)
            dataset = column_config.get('dataset', 'default')
            
            # Group by dataset
            if dataset not in execution_format['datasets']:
                execution_format['datasets'][dataset] = []
            
            execution_format['datasets'][dataset].append({
                'column_name': column_name,
                'column_type': column_type,
                'config': column_config
            })
            
            # Track FK relationships
            if column_type in ['foreign_key', 'multi_value_foreign_key']:
                fk_config = column_config.get('fk_config', {})
                relationship = {
                    'source_column': column_name,
                    'source_dataset': dataset,
                    'target_dataset': fk_config.get('target_dataset'),
                    'target_column': fk_config.get('target_column'),
                    'relationship_type': column_config.get('arkumu_type', 'related_to')
                }
                
                if column_type == 'multi_value_foreign_key':
                    relationship['is_multi_value'] = True
                    relationship['separator'] = column_config.get('multi_value_separator', ',')
                    execution_format['multi_value_fk_relationships'].append(relationship)
                else:
                    execution_format['fk_relationships'].append(relationship)
        
        return execution_format
    
    @staticmethod
    def convert_from_session_format(session_columns: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Convert session column format to mapping config format.
        
        Args:
            session_columns: List of column dicts from session
            
        Returns:
            Dict: Mapping configuration format
        """
        mapping_config = {'workspace_columns': {}}
        
        for column in session_columns:
            column_name = column.get('name') or column.get('column_name')
            if column_name:
                mapping_config['workspace_columns'][column_name] = column
        
        return mapping_config
    
    # ============================================================================
    # COMPLEXITY ANALYSIS
    # ============================================================================
    
    @staticmethod
    def calculate_mapping_complexity(mapping_config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Calculate mapping complexity score and breakdown.
        
        Args:
            mapping_config: Raw mapping configuration dict
            
        Returns:
            Dict: Complexity analysis with scores and breakdown
        """
        analysis = MappingUtils.analyze_mapping_structure(mapping_config)
        
        # Base complexity factors
        complexity_factors = {
            'total_columns': analysis['total_columns'],
            'datasets': len(analysis['dataset_breakdown']),
            'foreign_keys': analysis['foreign_key_columns'],
            'multi_value_columns': analysis['multi_value_columns'],
            'multi_value_fks': analysis['multi_value_fk_columns'],  # Most complex
            'external_ontologies': analysis['external_ontology_columns'],
            'relationship_contexts': analysis['relationship_context_columns']
        }
        
        # Complexity categories
        complexity_breakdown = {
            'low': ['regular_columns', 'anchor_columns'],
            'medium': ['foreign_key_columns', 'multi_value_columns', 'external_ontology_columns'], 
            'high': ['multi_value_fk_columns', 'relationship_context_columns']
        }
        
        # Calculate relative complexity
        total_complexity_points = 0
        for category, column_types in complexity_breakdown.items():
            weight = {'low': 1, 'medium': 3, 'high': 5}[category]
            for col_type in column_types:
                count = analysis.get(col_type, 0)
                total_complexity_points += count * weight
        
        return {
            'complexity_score': total_complexity_points,
            'complexity_factors': complexity_factors,
            'complexity_breakdown': complexity_breakdown,
            'is_simple': total_complexity_points < 20,
            'is_complex': total_complexity_points > 50,
            'has_multi_value_fks': analysis['multi_value_fk_columns'] > 0
        }

    # ============================================================================
    # CENTRALIZED FK + URI HELPERS (for processor and viewer)
    # ============================================================================

    @staticmethod
    def get_fk_target_info(column_config: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Return FK target info from a MappingUtils-style column_config.

        Expected keys: fk_config.target_dataset, fk_config.target_column, arkumu_type
        """
        fk_cfg = column_config.get('fk_config') or {}
        target_dataset = fk_cfg.get('target_dataset')
        target_column = fk_cfg.get('target_column')
        if not target_dataset:
            return None
        return {
            'target_dataset': target_dataset,
            'target_column': target_column,
            'relationship_type': column_config.get('arkumu_type')
        }

    @staticmethod
    def normalize_fk_value(value: Any) -> str:
        """Normalize FK values consistently (strip + NFC)."""
        import unicodedata
        if value is None:
            return ''
        s = str(value).strip()
        return unicodedata.normalize('NFC', s)

    @staticmethod
    def mint_property_uri(base_uri: str, org_code: str, arkumu_type: str) -> str:
        """Mint property URI exactly like the processor does."""
        from arkumu.common.uri_utils import mint_uri, slugify_uri_part
        return mint_uri(base_uri, org_code, 'properties', slugify_uri_part(arkumu_type))

    @staticmethod
    def mint_entity_uri(base_uri: str, org_code: str, dataset_name: str, anchor_value: str) -> str:
        """Mint entity URI mirroring ResourceManager logic (centralized path).

        Note: This assumes ResourceManager uses base/institution/dataset/anchor composition.
        """
        from arkumu.common.uri_utils import mint_uri, slugify_uri_part
        return mint_uri(base_uri, org_code, 'entities', f"{slugify_uri_part(dataset_name)}/{slugify_uri_part(anchor_value)}")


# ============================================================================
# CONVENIENCE FUNCTIONS (Module-level functions for backward compatibility)
# ============================================================================

def analyze_workspace_columns(mapping_config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Convenience function that maintains backward compatibility.
    
    This is the function that should replace the current analyze_workspace_columns
    throughout the codebase, but now it uses the comprehensive MappingUtils class.
    """
    return MappingUtils.analyze_mapping_structure(mapping_config)


def get_column_complexity_score(mapping_config: Dict[str, Any]) -> int:
    """
    Convenience function for getting just the complexity score.
    """
    complexity = MappingUtils.calculate_mapping_complexity(mapping_config)
    return complexity['complexity_score']


def detect_multi_value_fk_columns(mapping_config: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Convenience function to get multi-value FK column details.
    """
    analysis = MappingUtils.analyze_mapping_structure(mapping_config)
    return analysis['multi_value_fk_details']
