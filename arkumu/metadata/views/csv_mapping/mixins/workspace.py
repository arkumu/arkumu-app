"""
Workspace Mixins for CSV Mapping

Contains mixins for handling column workspace and session management:
- MappingWorkspaceMixin: Column workspace and session management functionality
"""

import logging
from datetime import datetime

from arkumu.common.uri_utils import slugify_uri_part
from arkumu.importer.utils.mapping_utils import MappingUtils

logger = logging.getLogger(__name__)


class MappingWorkspaceMixin:
    """
    Mixin for handling column workspace and session management.
    Provides methods for managing selected columns, workspace state, and column configurations.
    """
    
    def get_workspace_columns(self, request, organization_id):
        """
        Get workspace columns from session (single source of truth).
        
        Args:
            request: Django request object
            organization_id (str): Organization ID
            
        Returns:
            list: List of workspace columns
        """
        # Use coordinator's session key format if get_session_key is available (via MRO)
        # Otherwise fall back to direct format for standalone usage
        if hasattr(self, 'get_session_key'):
            workspace_key = self.get_session_key('workspace_columns', organization_id)
        else:
            workspace_key = f"workspace_columns_{organization_id}"
        
        columns = request.session.get(workspace_key, [])
        
        # DEBUG: Log every time workspace is accessed
        logger.info(f"🔍 WORKSPACE_ACCESS: Getting workspace for key '{workspace_key}' - found {len(columns)} columns")
        if columns:
            logger.info(f"🔍 WORKSPACE_ACCESS: First column ID: '{columns[0].get('id')}'")
        
        return columns
    
    def update_workspace_columns(self, request, organization_id, columns):
        """
        Update workspace columns in session.
        
        Args:
            request: Django request object
            organization_id (str): Organization ID
            columns (list): List of column configurations
        """
        # Use coordinator's session key format if get_session_key is available (via MRO)
        # Otherwise fall back to direct format for standalone usage
        if hasattr(self, 'get_session_key'):
            workspace_key = self.get_session_key('workspace_columns', organization_id)
        else:
            workspace_key = f"workspace_columns_{organization_id}"
        
        request.session[workspace_key] = columns
        request.session.modified = True
        
        # DEBUG: Verify the session was actually updated
        verification = request.session.get(workspace_key, [])
        logger.info(f"WORKSPACE_MIXIN: Updated workspace with {len(columns)} columns for org={organization_id}")
        logger.info(f"WORKSPACE_MIXIN: Verification check shows {len(verification)} columns in session")
        logger.info(f"WORKSPACE_MIXIN: Session key '{workspace_key}' exists: {workspace_key in request.session}")
        
        # DEBUG: Show first few column IDs for verification
        if verification:
            for i, col in enumerate(verification[:3]):
                logger.info(f"  - Column {i}: '{col.get('id')}' from dataset '{col.get('dataset')}'")
        
        # DEBUG: Force session save
        request.session.save()
    
    def clear_workspace_columns(self, request, organization_id):
        """
        Clear all workspace columns.
        
        Args:
            request: Django request object
            organization_id (str): Organization ID
        """
        # Use coordinator's session key format if get_session_key is available (via MRO)
        # Otherwise fall back to direct format for standalone usage
        if hasattr(self, 'get_session_key'):
            workspace_key = self.get_session_key('workspace_columns', organization_id)
        else:
            workspace_key = f"workspace_columns_{organization_id}"
        
        request.session[workspace_key] = []
        request.session.modified = True
        logger.info(f"WORKSPACE_MIXIN: Cleared workspace for org={organization_id}")
    
    def add_column_to_workspace(self, request, organization_id, column_id, column_name, dataset_name, source_name):
        """
        Add a column to the mapping workspace.
        
        Args:
            request: Django request object
            organization_id (str): Organization ID
            column_id (str): Unique column identifier
            column_name (str): Column name
            dataset_name (str): Dataset name
            source_name (str): Source name
            
        Returns:
            tuple: (success, new_column, total_columns)
        """
        # Get current workspace columns
        existing_columns = self.get_workspace_columns(request, organization_id)
        
        # Debug: Log ALL configurations before adding new column
        fk_columns_before = [col for col in existing_columns if col.get('is_fk', False)]
        anchor_columns_before = [col for col in existing_columns if col.get('is_anchor', False)]
        multi_value_columns_before = [col for col in existing_columns if col.get('is_multi_value', False)]
        
        logger.info(f"🔥🔥🔥 WORKSPACE_MIXIN: BEFORE adding column '{column_id}':")
        logger.info(f"  - Existing columns: {len(existing_columns)}")
        logger.info(f"  - FK columns before: {len(fk_columns_before)}")
        logger.info(f"  - Anchor columns before: {len(anchor_columns_before)}")
        logger.info(f"  - Multi-value columns before: {len(multi_value_columns_before)}")
        
        for col in existing_columns:
            logger.info(f"    - Column '{col.get('id')}': FK={col.get('is_fk', False)}, Anchor={col.get('is_anchor', False)}, Multi={col.get('is_multi_value', False)}, FK_config={col.get('fk_config', {})}")
        
        # Check if column already exists (UNIFIED TRACKING ENFORCEMENT)
        column_exists = any(col.get('id') == column_id for col in existing_columns)
        if column_exists:
            logger.warning(f"🔍 WORKSPACE_MIXIN: DUPLICATE PREVENTED - Column '{column_id}' already exists in workspace")
            # Return the existing column instead of None for consistency
            existing_column = next((col for col in existing_columns if col.get('id') == column_id), None)
            return False, existing_column, len(existing_columns)
        
        # Create new column entry with precise timestamp
        # Normalize dataset name: convert spaces to underscores to match mapping expectations
        # This ensures consistency between file names with spaces and dataset names in mappings
        normalized_dataset_name = dataset_name.replace(' ', '_')
        timestamp = datetime.now().isoformat()
        
        if normalized_dataset_name != dataset_name:
            logger.info(f"🔄 DATASET NORMALIZATION - Original: '{dataset_name}' -> Normalized: '{normalized_dataset_name}'")
        
        new_column = {
            'id': column_id,
            'name': column_name,
            'dataset': normalized_dataset_name,  # Use normalized dataset name
            'source': source_name,
            'type': 'string',  # Could be enhanced with type detection
            'is_fk': False,
            'is_anchor': False,
            'is_multi_value': False,
            'added_at': timestamp
        }
        
        existing_columns.append(new_column)
        
        logger.info(f"🔥 WORKSPACE_MIXIN: Created new column '{column_id}' for dataset '{dataset_name}' with timestamp '{timestamp}'")
        
        # Debug: Log ALL configurations after adding new column
        fk_columns_after = [col for col in existing_columns if col.get('is_fk', False)]
        anchor_columns_after = [col for col in existing_columns if col.get('is_anchor', False)]
        multi_value_columns_after = [col for col in existing_columns if col.get('is_multi_value', False)]
        
        logger.info(f"🔥🔥🔥 WORKSPACE_MIXIN: AFTER adding column '{column_id}':")
        logger.info(f"  - Total columns: {len(existing_columns)}")
        logger.info(f"  - FK columns after: {len(fk_columns_after)}")
        logger.info(f"  - Anchor columns after: {len(anchor_columns_after)}")
        logger.info(f"  - Multi-value columns after: {len(multi_value_columns_after)}")
        
        for col in existing_columns:
            logger.info(f"    - Column '{col.get('id')}': FK={col.get('is_fk', False)}, Anchor={col.get('is_anchor', False)}, Multi={col.get('is_multi_value', False)}, FK_config={col.get('fk_config', {})}")
        
        self.update_workspace_columns(request, organization_id, existing_columns)
        
        logger.info(f"WORKSPACE_MIXIN: Added column {column_id} to workspace")
        return True, new_column, len(existing_columns)
    
    def remove_column_from_workspace(self, request, organization_id, column_id):
        """
        Remove a column from the mapping workspace.
        
        Args:
            request: Django request object
            organization_id (str): Organization ID
            column_id (str): Column ID to remove
            
        Returns:
            tuple: (success, total_columns)
        """
        # Get current workspace columns
        existing_columns = self.get_workspace_columns(request, organization_id)
        
        # Remove the column
        updated_columns = [col for col in existing_columns if col.get('id') != column_id]
        
        if len(updated_columns) == len(existing_columns):
            logger.warning(f"WORKSPACE_MIXIN: Column {column_id} not found in workspace")
            return False, len(existing_columns)
        
        self.update_workspace_columns(request, organization_id, updated_columns)
        
        logger.info(f"WORKSPACE_MIXIN: Removed column {column_id} from workspace")
        return True, len(updated_columns)
    
    def update_column_configuration(self, request, organization_id, column_id, **config_updates):
        """
        Update configuration for a specific column.
        
        Args:
            request: Django request object
            organization_id (str): Organization ID
            column_id (str): Column ID to update
            **config_updates: Configuration updates (e.g., is_fk=True, is_anchor=True)
            
        Returns:
            tuple: (success, updated_column)
        """
        existing_columns = self.get_workspace_columns(request, organization_id)
        
        # Find and update the column
        updated_column = None
        for col in existing_columns:
            if col.get('id') == column_id:
                col.update(config_updates)
                updated_column = col
                break
        
        if updated_column is None:
            logger.warning(f"WORKSPACE_MIXIN: Column {column_id} not found for configuration update")
            return False, None
        
        self.update_workspace_columns(request, organization_id, existing_columns)
        logger.info(f"WORKSPACE_MIXIN: Updated column {column_id} configuration: {config_updates}")
        return True, updated_column
    
    def toggle_anchor_column(self, request, organization_id, column_id):
        """
        Toggle a column as the anchor column (only one anchor allowed per dataset).
        If the column is already an anchor, it will be unset. If it's not an anchor,
        it will be set as anchor and clear any other anchors in the same dataset.
        
        Args:
            request: Django request object
            organization_id (str): Organization ID
            column_id (str): Column ID to toggle as anchor
            
        Returns:
            tuple: (success, updated_columns)
        """
        existing_columns = self.get_workspace_columns(request, organization_id)
        
        # Find the target column and its dataset
        target_dataset = None
        anchor_found = False
        current_anchor_status = False
        
        logger.info(f"🔍 TOGGLE_ANCHOR_MIXIN: Looking for column_id='{column_id}' in {len(existing_columns)} columns")
        for col in existing_columns:
            col_id = col.get('id')
            if col_id == column_id:
                target_dataset = col.get('dataset')
                current_anchor_status = col.get('is_anchor', False)
                # TOGGLE the anchor status
                col['is_anchor'] = not current_anchor_status
                anchor_found = True
                logger.info(f"🔍 TOGGLE_ANCHOR_MIXIN: Found column! Toggling anchor from {current_anchor_status} to {col['is_anchor']} for dataset '{target_dataset}'")
                break
        
        if not anchor_found:
            logger.warning(f"🔍 TOGGLE_ANCHOR_MIXIN: Column {column_id} not found for anchor toggling")
            return False, existing_columns
        
        # If we're SETTING this column as anchor (was False, now True), 
        # clear all other anchors in the SAME dataset only
        if not current_anchor_status:  # Was False, now True - clear others
            for col in existing_columns:
                if col.get('dataset') == target_dataset and col.get('id') != column_id:
                    col['is_anchor'] = False
            logger.info(f"WORKSPACE_MIXIN: Set column {column_id} as anchor for dataset {target_dataset} and cleared others")
        else:  # Was True, now False - just unset this one
            logger.info(f"WORKSPACE_MIXIN: Unset column {column_id} as anchor for dataset {target_dataset}")
        
        self.update_workspace_columns(request, organization_id, existing_columns)
        return True, existing_columns

    def toggle_multi_value_column(self, request, organization_id, column_id):
        """
        Toggle the multi-value status of a column.
        
        Args:
            request: Django request object
            organization_id (str): Organization ID
            column_id (str): Column ID to toggle multi-value status
            
        Returns:
            tuple: (success, updated_columns)
        """
        existing_columns = self.get_workspace_columns(request, organization_id)
        
        # Find and toggle the column's multi-value status
        column_found = False
        
        logger.info(f"🔍 TOGGLE_MULTI_VALUE_MIXIN: Looking for column_id='{column_id}' in {len(existing_columns)} columns")
        for col in existing_columns:
            if col.get('id') == column_id:
                # Toggle multi-value status
                current_status = col.get('is_multi_value', False)
                col['is_multi_value'] = not current_status
                column_found = True
                logger.info(f"TOGGLE_MULTI_VALUE_MIXIN: Toggled column '{column_id}' multi-value from {current_status} to {col['is_multi_value']}")
                break
        
        if not column_found:
            logger.warning(f"TOGGLE_MULTI_VALUE_MIXIN: Column {column_id} not found for multi-value toggling")
            return False, existing_columns
        
        self.update_workspace_columns(request, organization_id, existing_columns)
        return True, existing_columns
    
    def get_workspace_statistics(self, request, organization_id):
        """
        Get comprehensive statistics about the current workspace using MappingUtils.
        
        Args:
            request: Django request object
            organization_id (str): Organization ID
            
        Returns:
            dict: Comprehensive workspace statistics and analysis
        """
        columns = self.get_workspace_columns(request, organization_id)
        
        if not columns:
            return {
                'total_columns': 0,
                'mapping_analysis': {},
                'validation': {'is_valid': True, 'warnings': [], 'errors': []},
                'complexity': {'complexity_score': 0, 'is_simple': True}
            }
        
        # Convert session columns to mapping config format for MappingUtils
        mapping_config = MappingUtils.convert_from_session_format(columns)
        
        # Get comprehensive analysis using MappingUtils
        mapping_analysis = MappingUtils.analyze_mapping_structure(mapping_config)
        validation_results = MappingUtils.validate_mapping_structure(mapping_config)
        complexity_analysis = MappingUtils.calculate_mapping_complexity(mapping_config)
        
        # Legacy stats for backward compatibility
        basic_stats = {
            'total_columns': len(columns),
            'anchor_columns': mapping_analysis.get('anchor_columns', 0),
            'fk_columns': mapping_analysis.get('foreign_key_columns', 0),
            'multi_value_columns': mapping_analysis.get('multi_value_columns', 0),
            'multi_value_fk_columns': mapping_analysis.get('multi_value_fk_columns', 0),
            'relationship_context_columns': mapping_analysis.get('relationship_context_columns', 0),
            'external_ontology_columns': mapping_analysis.get('external_ontology_columns', 0),
            'datasets_represented': len(set(col.get('dataset') for col in columns if col.get('dataset'))),
        }
        
        # Combine all analyses
        return {
            **basic_stats,
            'mapping_analysis': mapping_analysis,
            'validation': validation_results,
            'complexity': complexity_analysis,
            'column_combinations': mapping_analysis.get('combination_details', {}),
            'special_combinations': mapping_analysis.get('special_combinations', [])
        }
    
    def get_dataset_selected_columns(self, request, organization_id, dataset_name, source_name):
        """
        Get selected columns for a specific dataset.
        
        Args:
            request: Django request object
            organization_id (str): Organization ID
            dataset_name (str): Dataset name
            source_name (str): Source name
            
        Returns:
            list: List of selected column names for the dataset
        """
        workspace_columns = self.get_workspace_columns(request, organization_id)
        return [
            col['name'] for col in workspace_columns 
            if col.get('dataset') == dataset_name and col.get('source') == source_name
        ]
    
    def validate_workspace(self, request, organization_id):
        """
        Validate the current workspace configuration using MappingUtils.
        
        Args:
            request: Django request object
            organization_id (str): Organization ID
            
        Returns:
            dict: Validation results with errors, warnings, and suggestions
        """
        columns = self.get_workspace_columns(request, organization_id)
        
        if not columns:
            return {
                'is_valid': True,
                'errors': [],
                'warnings': [],
                'info': [],
                'suggestions': ['Add some columns to start building your mapping']
            }
        
        # Convert to mapping config format for validation
        mapping_config = MappingUtils.convert_from_session_format(columns)
        
        # Use MappingUtils for comprehensive validation
        validation_results = MappingUtils.validate_mapping_structure(mapping_config)
        
        # Add workspace-specific suggestions
        suggestions = []
        analysis = MappingUtils.analyze_mapping_structure(mapping_config)
        
        # Check for common issues and provide suggestions
        if analysis.get('anchor_columns', 0) == 0:
            suggestions.append("Consider setting anchor columns for your datasets to improve data quality")
        
        if analysis.get('multi_value_fk_columns', 0) > 0:
            mv_fk_details = analysis.get('multi_value_fk_details', [])
            suggestions.append(f"You have {len(mv_fk_details)} multi-value FK columns that will require special processing")
        
        complexity = MappingUtils.calculate_mapping_complexity(mapping_config)
        if complexity.get('is_complex', False):
            suggestions.append(f"This mapping has a complexity score of {complexity.get('complexity_score', 0)}. Consider reviewing for optimization opportunities")
        
        # Combine with workspace validation results
        validation_results['suggestions'] = suggestions
        
        return validation_results
    
    def get_column_type_analysis(self, request, organization_id):
        """
        Get detailed column type analysis using MappingUtils.
        
        Args:
            request: Django request object
            organization_id (str): Organization ID
            
        Returns:
            dict: Detailed column type analysis
        """
        columns = self.get_workspace_columns(request, organization_id)
        
        if not columns:
            return {
                'column_groups': {},
                'characteristic_groups': {},
                'combinations': {},
                'total_columns': 0
            }
        
        # Convert to mapping config format
        mapping_config = MappingUtils.convert_from_session_format(columns)
        
        # Get detailed column analysis
        column_groups = MappingUtils.group_columns_by_type(mapping_config)
        characteristic_groups = MappingUtils.group_columns_by_characteristics(mapping_config)
        
        # Get combination analysis
        combinations = {
            'anchor_fk': MappingUtils.get_columns_with_combination(mapping_config, ['is_anchor', 'is_fk']),
            'anchor_multi_value': MappingUtils.get_columns_with_combination(mapping_config, ['is_anchor', 'is_multi_value']),
            'multi_value_fk': MappingUtils.get_columns_with_combination(mapping_config, ['is_multi_value', 'is_fk']),
            'anchor_multi_value_fk': MappingUtils.get_columns_with_combination(mapping_config, ['is_anchor', 'is_multi_value', 'is_fk'])
        }
        
        return {
            'column_groups': column_groups,
            'characteristic_groups': characteristic_groups,
            'combinations': combinations,
            'total_columns': len(columns)
        } 