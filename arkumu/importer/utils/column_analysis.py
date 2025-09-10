"""
Centralized utility for analyzing workspace columns consistently.

This module provides the CORRECT method for analyzing mapping column configurations
using raw workspace_columns format, which preserves multi-value FK information.
"""

from typing import Dict, Any, List


def analyze_workspace_columns(mapping_config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Analyze columns using raw workspace_columns format (CORRECT method).
    
    This function uses the same logic that correctly identifies multi-value FK columns,
    avoiding the ConfigTranslator issue where multi-value FK information is lost.
    
    Args:
        mapping_config: Raw mapping configuration dict
        
    Returns:
        dict: Analysis results with correct column type counts
    """
    workspace_columns = mapping_config.get('workspace_columns', {})
    
    # Initialize counters
    mv_count = 0
    fk_count = 0 
    mv_fk_count = 0
    anchor_count = 0
    external_ontology_count = 0
    relationship_context_count = 0
    regular_count = 0
    
    mv_fk_details = []
    dataset_breakdown = {}
    
    # Analyze each column using raw format
    for key, col_config in workspace_columns.items():
        is_mv = col_config.get('is_multi_value', False)
        is_fk = col_config.get('is_fk', False) or col_config.get('fk_config')
        is_anchor = col_config.get('is_anchor', False)
        is_external_ontology = col_config.get('is_external_ontology', False)
        is_relationship_context = col_config.get('is_relationship_context', False)
        dataset_name = col_config.get('dataset', '')
        
        # Initialize dataset breakdown if not exists
        if dataset_name and dataset_name not in dataset_breakdown:
            dataset_breakdown[dataset_name] = {
                'regular': 0,
                'anchor': 0,
                'foreign_key': 0,
                'multi_value': 0,
                'multi_value_fk': 0,
                'relationship_context': 0,
                'external_ontology': 0,
                'total': 0
            }
        
        # Classify column type (order matters!)
        if is_anchor:
            anchor_count += 1
            if dataset_name:
                dataset_breakdown[dataset_name]['anchor'] += 1
        elif is_relationship_context:
            relationship_context_count += 1
            if dataset_name:
                dataset_breakdown[dataset_name]['relationship_context'] += 1
        elif is_external_ontology:
            external_ontology_count += 1
            if dataset_name:
                dataset_breakdown[dataset_name]['external_ontology'] += 1
        elif is_mv and is_fk:
            # CRITICAL: Multi-value FK columns counted separately
            mv_fk_count += 1
            mv_fk_details.append({
                'column_key': key,
                'dataset': dataset_name,
                'column_name': col_config.get('name', ''),
                'fk_config': col_config.get('fk_config', {})
            })
            if dataset_name:
                dataset_breakdown[dataset_name]['multi_value_fk'] += 1
        elif is_mv:
            mv_count += 1
            if dataset_name:
                dataset_breakdown[dataset_name]['multi_value'] += 1
        elif is_fk:
            fk_count += 1
            if dataset_name:
                dataset_breakdown[dataset_name]['foreign_key'] += 1
        else:
            regular_count += 1
            if dataset_name:
                dataset_breakdown[dataset_name]['regular'] += 1
        
        # Update dataset total
        if dataset_name:
            dataset_breakdown[dataset_name]['total'] += 1
    
    return {
        'total_columns': len(workspace_columns),
        'regular_columns': regular_count,
        'anchor_columns': anchor_count,
        'foreign_key_columns': fk_count,
        'multi_value_columns': mv_count,
        'multi_value_fk_columns': mv_fk_count,  # KEY: Separate count for MV+FK
        'relationship_context_columns': relationship_context_count,
        'external_ontology_columns': external_ontology_count,
        'multi_value_fk_details': mv_fk_details,
        'dataset_breakdown': dataset_breakdown
    }


