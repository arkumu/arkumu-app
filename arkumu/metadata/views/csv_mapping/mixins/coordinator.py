"""
Coordinator Mixin for CSV Mapping

This mixin coordinates between CSVDataMixin and MappingWorkspaceMixin to properly
handle the fundamental relationship between datasets and their columns.

Key principles:
- Columns belong to datasets (dataset-column relationship is explicit)
- Dataset deselection cascades to remove related columns
- Column addition validates dataset selection
- Column IDs include dataset context for uniqueness

This refactored version focuses on CSV-specific functionality while leveraging
the enhanced BaseCoordinatorMixin for generic operations.
"""

import logging
from .csv_data import CSVDataMixin
from .workspace import MappingWorkspaceMixin
from arkumu.common.mixins.base_coordinator import BaseCoordinatorMixin
from django.utils import timezone
from datetime import datetime

logger = logging.getLogger(__name__)


class CSVMappingCoordinatorMixin(BaseCoordinatorMixin, CSVDataMixin, MappingWorkspaceMixin):
    """
    Coordinator mixin that properly handles dataset-column relationships for CSV mapping.
    
    This refactored mixin inherits from BaseCoordinatorMixin for shared organization management,
    CSVDataMixin for dataset operations, and MappingWorkspaceMixin for workspace operations
    to provide coordinated operations that maintain the integrity of dataset-column relationships.
    
    Focuses on CSV-specific functionality:
    - CSV column ID parsing and generation
    - CSV dataset discovery and S3 integration
    - CSV-specific FK configuration and UI logic
    - Dataset-column relationship management specific to CSV format
    """
    
    # NOTE: SESSION_PREFIX removed to implement single source of truth session keys
    # CSV coordinator now uses shared keys without prefixes
    
    # ==========================================================================
    # CSV-Specific Column ID Management
    # ==========================================================================
    
    @staticmethod
    def generate_column_id(dataset_name, column_name, source_name=None):
        """
        Generate a unique column ID that includes dataset context.
        
        Args:
            dataset_name (str): Name of the dataset
            column_name (str): Name of the column
            source_name (str, optional): Source name for additional context
            
        Returns:
            str: Unique column ID like "dataset.csv::column_name" or "source::dataset.csv::column_name"
        """
        if source_name:
            return f"{source_name}::{dataset_name}::{column_name}"
        return f"{dataset_name}::{column_name}"
    
    @staticmethod
    def parse_column_id(column_id):
        """
        Parse a column ID to extract its components.
        
        Args:
            column_id (str): Column ID to parse
            
        Returns:
            dict: Parsed components with keys: source, dataset, column
        """
        # Handle None and empty values gracefully
        if not column_id:
            return {
                'source': None,
                'dataset': None,
                'column': None
            }
        
        parts = column_id.split("::")
        if len(parts) == 3:
            return {
                'source': parts[0],
                'dataset': parts[1], 
                'column': parts[2]
            }
        elif len(parts) == 2:
            return {
                'source': None,
                'dataset': parts[0],
                'column': parts[1]
            }
        else:
            # Fallback for legacy IDs
            return {
                'source': None,
                'dataset': None,
                'column': column_id
            }
    
    # ==========================================================================
    # Compatibility Layer - Dataset Selection (wrapper methods)
    # ==========================================================================
    
    def get_selected_dataset_names(self, request, organization_id):
        """
        Get only the selected dataset names from session (lightweight).
        
        This is more efficient than get_selected_datasets_with_details() when
        you only need the names and not the full dataset objects.
        
        This method now uses the generic base coordinator dataset selection method
        for consistency and shared functionality.
        
        Args:
            request: Django request object
            organization_id (int): Organization numeric ID
            
        Returns:
            list: List of selected dataset names
        """
        # Use base coordinator method for consistency
        return self.get_selected_datasets(request, organization_id, 'datasets')
    
    def toggle_dataset_selection(self, request, organization_id, dataset_name):
        """
        Toggle dataset selection without column cascade (CSV mapping compatibility).
        
        This method provides compatibility with the original CSV mapping interface
        by returning the expected tuple format (selected_datasets, was_added).
        
        Args:
            request: Django request object
            organization_id (int): Organization numeric ID
            dataset_name (str): Dataset name to toggle
            
        Returns:
            tuple: (updated_selected_datasets, was_added)
        """
        # Use base coordinator method and adapt return format
        success, final_list, was_added, error = super().toggle_dataset_selection(
            request, organization_id, dataset_name, 'datasets'
        )
        
        if not success:
            logger.error(f"CSV_COORDINATOR: Failed to toggle dataset selection: {error}")
            return [], False
        
        return final_list, was_added

    def clear_selected_datasets(self, request, organization_id):
        """
        Clear all selected datasets (CSV mapping compatibility).
        
        This method provides compatibility with the original CSV mapping interface.
        
        Args:
            request: Django request object
            organization_id (int): Organization numeric ID
        """
        # Use base coordinator method
        success, items_cleared, error = super().clear_selected_datasets(
            request, organization_id, 'datasets'
        )
        
        if not success:
            logger.error(f"CSV_COORDINATOR: Failed to clear selected datasets: {error}")
        
        logger.info(f"CSV_COORDINATOR: Cleared {items_cleared} selected datasets for org={organization_id}")
    
    # ==========================================================================
    # Compatibility Layer - Workspace Column Management (wrapper methods)
    # ==========================================================================
    
    def get_workspace_columns(self, request, organization_id):
        """
        Get workspace columns from session (CSV mapping compatibility).
        
        Wrapper around BaseCoordinatorMixin.get_workspace_items for backward compatibility.
        
        Args:
            request: Django request object
            organization_id (int): Organization numeric ID
            
        Returns:
            list: List of workspace column dictionaries
        """
        return self.get_workspace_items(request, organization_id, 'columns')
    
    def update_workspace_columns(self, request, organization_id, columns):
        """
        Update workspace columns in session (CSV mapping compatibility).
        
        Wrapper around BaseCoordinatorMixin.update_workspace_items for backward compatibility.
        
        Args:
            request: Django request object
            organization_id (int): Organization numeric ID
            columns (list): List of column dictionaries to store
        """
        return self.update_workspace_items(request, organization_id, columns, 'columns')
    
    def clear_workspace_columns(self, request, organization_id):
        """
        Clear workspace columns (CSV mapping compatibility).
        
        Wrapper around BaseCoordinatorMixin.clear_workspace_items for backward compatibility.
        
        Args:
            request: Django request object
            organization_id (int): Organization numeric ID
        """
        return self.clear_workspace_items(request, organization_id, 'columns')
    
    def add_column_to_workspace(self, request, organization_id, column_id, column_name, dataset_name, source_name):
        """
        Add a column to workspace (CSV mapping compatibility).
        
        Wrapper around BaseCoordinatorMixin.add_workspace_item for backward compatibility.
        
        Args:
            request: Django request object
            organization_id (int): Organization numeric ID
            column_id (str): Column ID
            column_name (str): Column name
            dataset_name (str): Dataset name
            source_name (str): Source name
            
        Returns:
            tuple: (success, new_column, total_columns)
        """
        # Create column data structure
        column_data = {
            'id': column_id,
            'name': column_name,
            'dataset': dataset_name,
            'source': source_name,
            'type': 'string',
            'is_fk': False,
            'is_anchor': False,
            'is_multi_value': False,
            'added_at': datetime.now().isoformat()
        }
        
        # Use base coordinator method
        success, new_column, total_columns, error = self.add_workspace_item(
            request, organization_id, column_data, 'columns'
        )
        
        if success:
            return True, new_column, total_columns
        else:
            return False, None, total_columns
    
    def get_workspace_statistics(self, request, organization_id):
        """
        Get workspace statistics (CSV mapping compatibility).
        
        Wrapper around BaseCoordinatorMixin.get_workspace_statistics for backward compatibility.
        
        Args:
            request: Django request object
            organization_id (int): Organization numeric ID
            
        Returns:
            dict: Workspace statistics
        """
        return super().get_workspace_statistics(request, organization_id, 'columns')
    
    # ==========================================================================
    # CSV-Specific Coordinated Dataset Selection (with Column Cascade)
    # ==========================================================================
    
    def toggle_dataset_selection_with_cascade(self, request, organization_id, dataset_name):
        """
        Toggle dataset selection and handle column cascade operations.
        
        ⚠️  WARNING: CASCADE BEHAVIOR ⚠️
        When a dataset is deselected, all its columns are automatically removed
        from the workspace to maintain consistency.
        
        USE CASES:
        - Database-style interfaces where dataset selection directly controls workspace
        - Interfaces where dataset deselection should clear related workspace content
        
        DO NOT USE FOR:
        - CSV mapping interfaces where dataset selection is just UI browsing state
        - Interfaces where users build mappings from multiple datasets independently
        
        For CSV mapping, use toggle_dataset_selection() instead (no cascade).
        
        Args:
            request: Django request object
            organization_id (str): Organization ID
            dataset_name (str): Dataset to toggle
            
        Returns:
            tuple: (updated_selected_datasets, was_added, columns_affected)
        """
        logger.info(f"COORDINATOR: Toggling dataset '{dataset_name}' with cascade for org='{organization_id}'")
        
        # Toggle dataset selection using compatibility method
        selected_datasets, was_added = self.toggle_dataset_selection(
            request, organization_id, dataset_name
        )
        
        columns_affected = 0
        
        if not was_added:  # Dataset was REMOVED
            logger.info(f"COORDINATOR: Dataset '{dataset_name}' was deselected, cascading to remove columns")
            columns_affected = self._remove_columns_for_dataset(
                request, organization_id, dataset_name
            )
            logger.info(f"COORDINATOR: Removed {columns_affected} columns for dataset '{dataset_name}'")
        
        return selected_datasets, was_added, columns_affected
    
    def _remove_columns_for_dataset(self, request, organization_id, dataset_name):
        """
        Remove all workspace columns that belong to a specific dataset.
        Also clears column selection state to prevent orphaned HTMX requests.
        
        Args:
            request: Django request object
            organization_id (str): Organization ID
            dataset_name (str): Dataset name
            
        Returns:
            int: Number of columns removed
        """
        workspace_columns = self.get_workspace_columns(request, organization_id)
        initial_count = len(workspace_columns)
        
        # Filter out columns belonging to the deselected dataset
        remaining_columns = [
            col for col in workspace_columns 
            if col.get('dataset') != dataset_name
        ]
        
        # Update workspace
        self.update_workspace_columns(request, organization_id, remaining_columns)
        
        # CRITICAL: Also clear column selection state for this dataset to prevent htmx:targetError
        # When dataset is deselected, its column badges container is removed from DOM,
        # but pending HTMX requests might still try to update it
        selection_key = self.get_session_key('column_selection', organization_id)
        column_selections = request.session.get(selection_key, {})
        
        # Find all dataset keys that match this dataset name (could have different sources)
        keys_to_remove = []
        for dataset_key in column_selections.keys():
            # dataset_key format: "dataset_name::source_name"
            if dataset_key.startswith(f"{dataset_name}::"):
                keys_to_remove.append(dataset_key)
        
        # Remove column selections for this dataset
        for key in keys_to_remove:
            del column_selections[key]
            logger.info(f"COORDINATOR: Cleared column selection state for '{key}'")
        
        # Save updated column selections
        if keys_to_remove:
            request.session[selection_key] = column_selections
            request.session.modified = True
        
        columns_removed = initial_count - len(remaining_columns)
        logger.info(f"COORDINATOR: Removed {columns_removed} workspace columns and cleared {len(keys_to_remove)} column selection states for dataset '{dataset_name}'")
        return columns_removed
    
    # ==========================================================================
    # CSV-Specific Coordinated Column Management (with Dataset Validation)
    # ==========================================================================
    
    def add_column_with_validation(self, request, organization_id, column_name, dataset_name, source_name):
        """
        Add a column to workspace with proper dataset validation.
        
        This method ensures that:
        1. The dataset is currently selected
        2. The column ID includes dataset context
        3. The column doesn't already exist
        
        Args:
            request: Django request object
            organization_id (str): Organization ID
            column_name (str): Column name
            dataset_name (str): Dataset name
            source_name (str): Source name
            
        Returns:
            tuple: (success, new_column, total_columns, error_message)
        """
        logger.info(f"🎯 COORDINATOR MIXIN: add_column_with_validation() IS BEING CALLED!")
        logger.info(f"🎯 COORDINATOR: Adding column '{column_name}' from dataset '{dataset_name}' with validation")
        
        # Debug: Log current workspace state before adding column
        current_workspace = self.get_workspace_columns(request, organization_id)
        fk_columns_before = [col for col in current_workspace if col.get('is_fk', False)]
        anchor_columns_before = [col for col in current_workspace if col.get('is_anchor', False)]
        multi_value_columns_before = [col for col in current_workspace if col.get('is_multi_value', False)]
        
        logger.info(f"🔥🔥🔥 COORDINATOR: BEFORE adding column '{column_name}' from '{dataset_name}':")
        logger.info(f"  - Current workspace: {len(current_workspace)} columns")
        logger.info(f"  - FK columns before: {len(fk_columns_before)}")
        logger.info(f"  - Anchor columns before: {len(anchor_columns_before)}")
        logger.info(f"  - Multi-value columns before: {len(multi_value_columns_before)}")
        
        for col in current_workspace:
            logger.info(f"    - Column '{col.get('id')}': FK={col.get('is_fk', False)}, Anchor={col.get('is_anchor', False)}, Multi={col.get('is_multi_value', False)}, FK_config={col.get('fk_config', {})}")
        
        # CRITICAL: Store FK configurations snapshot before adding new column
        fk_configurations_snapshot = {}
        for col in current_workspace:
            if col.get('is_fk', False):
                fk_configurations_snapshot[col.get('id')] = {
                    'is_fk': col.get('is_fk', False),
                    'fk_config': col.get('fk_config', {}),
                }
        logger.info(f"🔥 COORDINATOR: FK SNAPSHOT - {len(fk_configurations_snapshot)} FK configs preserved")
        
        # 1. Validate that dataset is selected
        if not self._is_dataset_selected(request, organization_id, dataset_name):
            error_msg = f"Cannot add column '{column_name}': dataset '{dataset_name}' is not selected"
            logger.warning(f"COORDINATOR: {error_msg}")
            return False, None, 0, error_msg
        
        # 2. Generate proper column ID with dataset context (using organization_id as source)
        column_id = self.generate_column_id(dataset_name, column_name, organization_id)
        
        # 2.5. UNIFIED TRACKING: Validate workspace before adding column
        is_unique, duplicates, _ = self.validate_workspace_column_uniqueness(request, organization_id)
        if not is_unique:
            logger.warning(f"🔍 COORDINATOR: Found {len(duplicates)} duplicates before adding '{column_id}' - auto-cleaned")
        
        # 3. Add column using compatibility method
        success, new_column, total_columns = self.add_column_to_workspace(
            request, organization_id, column_id, column_name, dataset_name, source_name
        )
        
        if success:
            # CRITICAL: Verify FK configurations are still intact after adding column
            updated_workspace = self.get_workspace_columns(request, organization_id)
            fk_columns_after = [col for col in updated_workspace if col.get('is_fk', False)]
            
            logger.info(f"🔥🔥🔥 COORDINATOR: AFTER adding column '{column_name}' to workspace:")
            logger.info(f"  - Total columns: {len(updated_workspace)}")
            logger.info(f"  - FK columns after: {len(fk_columns_after)}")
            
            # Verify FK configurations are preserved
            fk_configs_lost = 0
            for col_id, fk_data in fk_configurations_snapshot.items():
                current_col = next((col for col in updated_workspace if col.get('id') == col_id), None)
                if current_col:
                    if not current_col.get('is_fk', False) or not current_col.get('fk_config', {}):
                        fk_configs_lost += 1
                        logger.error(f"🔥 COORDINATOR: FK CONFIG LOST for column '{col_id}'")
                    else:
                        logger.info(f"🔥 COORDINATOR: FK CONFIG PRESERVED for column '{col_id}': {current_col.get('fk_config', {})}")
                else:
                    logger.error(f"🔥 COORDINATOR: COLUMN LOST: '{col_id}'")
            
            if fk_configs_lost > 0:
                logger.error(f"🔥🔥🔥 COORDINATOR: CRITICAL ERROR - {fk_configs_lost} FK configurations were lost during column addition!")
            else:
                logger.info(f"🔥 COORDINATOR: SUCCESS - All {len(fk_configurations_snapshot)} FK configurations preserved")
            
            logger.info(f"COORDINATOR: Successfully added column '{column_id}' to workspace")
            return True, new_column, total_columns, None
        else:
            error_msg = f"Column '{column_id}' already exists in workspace"
            return False, None, total_columns, error_msg
    
    def _is_dataset_selected(self, request, organization_id, dataset_name):
        """
        Check if a dataset is currently selected.
        
        Args:
            request: Django request object
            organization_id (str): Organization ID
            dataset_name (str): Dataset name to check
            
        Returns:
            bool: True if dataset is selected
        """
        selected_datasets = self.get_selected_dataset_names(request, organization_id)
        return dataset_name in selected_datasets
    
    def validate_and_fix_dataset_selection_state(self, request, organization_id, dataset_name, source_name, allow_auto_select_empty=False):
        """
        Safe validation for dataset selection state with auto-correction.
        
        This method detects state inconsistencies where:
        - A dataset has columns in the workspace but isn't marked as "selected"
        - Auto-corrects by selecting the dataset if it has workspace columns
        
        ENHANCED FOR POST-CLEAR OPERATIONS:
        - Always allows auto-selection when dataset has orphaned columns
        - Gracefully handles "Clear Selected Datasets" workflow
        - Maintains coordinator integrity during mixed operations
        
        SAFETY FEATURES:
        - Non-destructive: Only adds to selection, never removes
        - Logs all actions for debugging
        - Maintains backward compatibility
        - Returns detailed status for error handling
        
        Args:
            request: Django request object
            organization_id (str): Organization ID
            dataset_name (str): Dataset name to validate
            source_name (str): Source name for the dataset
            allow_auto_select_empty (bool): If True, auto-select dataset even if it has no columns (for "select all" operations)
            
        Returns:
            tuple: (is_valid, was_corrected, status_message)
                - is_valid (bool): Whether dataset is now in valid state for operations
                - was_corrected (bool): Whether auto-correction was applied
                - status_message (str): Descriptive message about the validation
        """
        logger.info(f"🔒 SAFE_VALIDATION: Validating dataset selection state for '{dataset_name}' from '{source_name}' (allow_auto_select_empty={allow_auto_select_empty})")
        
        # Check current selection state
        is_currently_selected = self._is_dataset_selected(request, organization_id, dataset_name)
        
        if is_currently_selected:
            logger.info(f"🔒 SAFE_VALIDATION: Dataset '{dataset_name}' is properly selected - no action needed")
            return True, False, f"Dataset '{dataset_name}' is already selected"
        
        # Dataset not selected - check if it has columns in workspace
        workspace_columns = self.get_workspace_columns(request, organization_id)
        dataset_has_columns = False
        column_count = 0
        
        for col_dict in workspace_columns:
            if isinstance(col_dict, dict):
                col_id = col_dict.get('id', '')
                parsed = self.parse_column_id(col_id)
                if parsed['dataset'] == dataset_name and (parsed['source'] == source_name or parsed['source'] == organization_id):
                    dataset_has_columns = True
                    column_count += 1
        
        # ENHANCED LOGIC: Always allow auto-selection for column operations
        # This handles the "Clear Selected Datasets" → "Add Column" workflow gracefully
        should_auto_select = dataset_has_columns or allow_auto_select_empty
        
        # NEW: If user is trying to add a column to any dataset, allow auto-selection
        # This makes the coordinator more forgiving after clear operations
        if not should_auto_select:
            logger.info(f"🔒 SAFE_VALIDATION: AUTO-SELECTING dataset '{dataset_name}' for column operation (post-clear recovery)")
            should_auto_select = True
            allow_auto_select_empty = True
        
        # Auto-select the dataset
        if dataset_has_columns:
            logger.warning(f"🔒 SAFE_VALIDATION: STATE INCONSISTENCY DETECTED - Dataset '{dataset_name}' has {column_count} columns but is not selected")
            reason = f"existing columns ({column_count} columns found)"
        elif allow_auto_select_empty:
            logger.info(f"🔒 SAFE_VALIDATION: AUTO-SELECTING dataset '{dataset_name}' for column operation")
            reason = "column addition operation"
        else:
            logger.info(f"🔒 SAFE_VALIDATION: Dataset '{dataset_name}' not selected and has no columns - validation failed")
            return False, False, f"Dataset '{dataset_name}' is not selected and operation requires selection"
        
        logger.info(f"🔒 SAFE_VALIDATION: Auto-correcting by selecting dataset '{dataset_name}'")
        
        # Auto-correct by adding dataset to selection
        try:
            # Get current selected datasets
            current_selected = self.get_selected_dataset_names(request, organization_id)
            
            # Add this dataset to the selection if not already there
            if dataset_name not in current_selected:
                updated_selected = list(current_selected) + [dataset_name]
                
                # Update the selection
                session_key = self.get_session_key('selected_datasets', organization_id)
                request.session[session_key] = updated_selected
                request.session.modified = True
                
                logger.info(f"🔒 SAFE_VALIDATION: Successfully auto-selected dataset '{dataset_name}' - state corrected")
                return True, True, f"Dataset '{dataset_name}' was auto-selected due to {reason}"
            else:
                logger.info(f"🔒 SAFE_VALIDATION: Dataset '{dataset_name}' already in selection - no correction needed")
                return True, False, f"Dataset '{dataset_name}' was already selected"
            
        except Exception as e:
            logger.error(f"🔒 SAFE_VALIDATION: Failed to auto-select dataset '{dataset_name}': {e}")
            return False, False, f"Failed to auto-correct dataset selection for '{dataset_name}': {str(e)}"
    
    def safe_add_column_with_validation(self, request, organization_id, column_name, dataset_name, source_name):
        """
        Safely add a column with automatic dataset selection validation and correction.
        
        This wrapper around add_column_with_validation ensures that:
        1. Dataset selection state is validated and corrected if needed
        2. Column addition proceeds only after state consistency is ensured
        3. All operations are logged for debugging
        
        Args:
            request: Django request object
            organization_id (str): Organization ID
            column_name (str): Name of the column to add
            dataset_name (str): Dataset name
            source_name (str): Source name
            
        Returns:
            tuple: (success, new_column, total_columns, error_message)
                Same as add_column_with_validation but with safe state handling
        """
        logger.info(f"🔒 SAFE_ADD_COLUMN: Safely adding column '{column_name}' from dataset '{dataset_name}' (source: '{source_name}')")
        
        # First, validate and fix dataset selection state
        is_valid, was_corrected, status_message = self.validate_and_fix_dataset_selection_state(
            request, organization_id, dataset_name, source_name
        )
        
        if was_corrected:
            logger.info(f"🔒 SAFE_ADD_COLUMN: State auto-corrected - {status_message}")
        
        # Now proceed with column addition using the standard method
        return self.add_column_with_validation(request, organization_id, column_name, dataset_name, source_name)
    
    def batch_add_columns_with_validation(self, request, organization_id, column_names, dataset_name, source_name):
        """
        Efficiently add multiple columns from a dataset in a single operation.
        
        PERFORMANCE OPTIMIZATION: This method:
        1. Validates dataset selection state once
        2. Batch processes all columns
        3. Updates workspace only once at the end
        4. Skips duplicates efficiently
        5. Preserves existing FK configurations
        
        Args:
            request: Django request object
            organization_id (str): Organization ID
            column_names (list): List of column names to add
            dataset_name (str): Dataset name
            source_name (str): Source name
            
        Returns:
            tuple: (total_added, skipped_duplicates, final_column_count, error_message)
        """
        logger.info(f"🚀 BATCH_ADD: Adding {len(column_names)} columns from dataset '{dataset_name}' (source: '{source_name}')")
        
        # Step 1: Validate and fix dataset selection state once
        is_valid, was_corrected, status_message = self.validate_and_fix_dataset_selection_state(
            request, organization_id, dataset_name, source_name, allow_auto_select_empty=True
        )
        
        if not is_valid:
            return 0, 0, 0, status_message
            
        if was_corrected:
            logger.info(f"🚀 BATCH_ADD: State auto-corrected - {status_message}")
        
        # Step 2: Get current workspace columns once
        existing_columns = self.get_workspace_columns(request, organization_id)
        existing_column_ids = {col.get('id') for col in existing_columns if isinstance(col, dict)}
        
        logger.info(f"🚀 BATCH_ADD: Current workspace has {len(existing_columns)} columns")
        
        # Step 3: Prepare new columns (skip duplicates)
        new_columns = []
        skipped_duplicates = 0
        
        for column_name in column_names:
            column_id = self.generate_column_id(dataset_name, column_name, organization_id)
            
            if column_id in existing_column_ids:
                skipped_duplicates += 1
                logger.debug(f"🚀 BATCH_ADD: Skipping duplicate column '{column_id}'")
                continue
            
            # Create new column entry
            new_column = {
                'id': column_id,
                'name': column_name,
                'dataset': dataset_name,
                'source': source_name,
                'type': 'string',
                'is_fk': False,
                'is_anchor': False,
                'is_multi_value': False,
                'added_at': datetime.now().isoformat()
            }
            new_columns.append(new_column)
            existing_column_ids.add(column_id)  # Prevent duplicates within this batch
        
        # Step 4: Add all new columns to workspace in one operation
        final_columns = existing_columns + new_columns
        self.update_workspace_columns(request, organization_id, final_columns)
        
        total_added = len(new_columns)
        final_count = len(final_columns)
        
        logger.info(f"🚀 BATCH_ADD: Successfully added {total_added} columns, skipped {skipped_duplicates} duplicates")
        logger.info(f"🚀 BATCH_ADD: Final workspace size: {final_count} columns")
        
        return total_added, skipped_duplicates, final_count, None
    
    # ==========================================================================
    # CSV-Specific Validation & Tracking
    # ==========================================================================
    
    def validate_workspace_column_uniqueness(self, request, organization_id):
        """
        Validate that all workspace columns have unique IDs.
        
        UNIFIED TRACKING: Ensures no duplicate column IDs exist in the workspace.
        This validation is specific to workspace state management and remains here
        rather than in MappingValidator.
        
        Args:
            request: Django request object
            organization_id (str): Organization ID
            
        Returns:
            tuple: (is_unique, duplicates_found, cleaned_columns)
        """
        workspace_columns = self.get_workspace_columns(request, organization_id)
        seen_ids = set()
        duplicates = []
        cleaned_columns = []
        
        for col in workspace_columns:
            if isinstance(col, dict):
                col_id = col.get('id')
                if col_id:
                    if col_id in seen_ids:
                        duplicates.append(col_id)
                        logger.warning(f"🔍 COORDINATOR: DUPLICATE DETECTED: '{col_id}'")
                    else:
                        seen_ids.add(col_id)
                        cleaned_columns.append(col)
                else:
                    logger.warning(f"🔍 COORDINATOR: Column without ID detected: {col}")
            else:
                logger.warning(f"🔍 COORDINATOR: Non-dict column detected: {col}")
        
        is_unique = len(duplicates) == 0
        
        # Auto-clean if duplicates found
        if not is_unique:
            logger.info(f"🔍 COORDINATOR: Auto-cleaning {len(duplicates)} duplicate columns")
            self.update_workspace_columns(request, organization_id, cleaned_columns)
        
        return is_unique, duplicates, cleaned_columns
    
    def get_unified_column_by_id(self, request, organization_id, column_id):
        """
        Get a column by ID from workspace with validation.
        
        UNIFIED TRACKING: Single method to retrieve columns by ID.
        
        Args:
            request: Django request object
            organization_id (str): Organization ID
            column_id (str): Column ID to find
            
        Returns:
            dict or None: Column dictionary if found
        """
        workspace_columns = self.get_workspace_columns(request, organization_id)
        
        for col in workspace_columns:
            if isinstance(col, dict) and col.get('id') == column_id:
                return col
        
        logger.warning(f"🔍 COORDINATOR: Column '{column_id}' not found in workspace")
        return None

    # ==========================================================================
    # CSV-Specific Dataset Operations
    # ==========================================================================
    
    def get_columns_by_dataset(self, request, organization_id):
        """
        Get workspace columns grouped by dataset.
        
        Args:
            request: Django request object
            organization_id (str): Organization ID
            
        Returns:
            dict: Columns grouped by dataset name
        """
        workspace_columns = self.get_workspace_columns(request, organization_id)
        columns_by_dataset = {}
        
        for col in workspace_columns:
            dataset_name = col.get('dataset', 'unknown')
            if dataset_name not in columns_by_dataset:
                columns_by_dataset[dataset_name] = []
            columns_by_dataset[dataset_name].append(col)
        
        return columns_by_dataset
    
    def get_workspace_summary(self, request, organization_id):
        """
        Get a comprehensive summary of the current workspace state.
        
        Args:
            request: Django request object
            organization_id (str): Organization ID
            
        Returns:
            dict: Comprehensive workspace summary
        """
        # Get basic workspace statistics
        workspace_stats = self.get_workspace_statistics(request, organization_id)
        
        # Get columns grouped by dataset
        columns_by_dataset = self.get_columns_by_dataset(request, organization_id)
        
        # Get selected datasets (names only - more efficient)
        selected_datasets = self.get_selected_dataset_names(request, organization_id)
        
        # Calculate additional metrics
        datasets_with_columns = set(columns_by_dataset.keys())
        orphaned_datasets = datasets_with_columns - set(selected_datasets)
        
        return {
            **workspace_stats,
            'selected_datasets_count': len(selected_datasets),
            'datasets_with_columns': len(datasets_with_columns),
            'columns_by_dataset': {
                dataset: len(columns) for dataset, columns in columns_by_dataset.items()
            },
            'orphaned_datasets': list(orphaned_datasets),  # Datasets with columns but not selected
            'is_consistent': len(orphaned_datasets) == 0,  # True if no orphaned datasets
        }
    
    # ==========================================================================
    # CSV-Specific Template Data Preparation
    # ==========================================================================
    
    def _prepare_datasets_with_columns(self, workspace_columns):
        """
        Prepare datasets_with_columns structure for templates.
        
        UNIFIED TRACKING: This is the single source of truth for rendering datasets with columns.
        Ensures no duplicates and proper column ID consistency.
        
        Args:
            workspace_columns (list): List of workspace column dictionaries
            
        Returns:
            list: Datasets grouped with their columns
        """
        # Group columns by dataset with deduplication
        datasets_map = {}
        column_ids_seen = set()  # Track unique column IDs to prevent duplicates
        
        logger.info(f"🔍 COORDINATOR: _prepare_datasets_with_columns() called with {len(workspace_columns)} columns")
        
        # Log all incoming columns with timestamps
        for i, col_dict in enumerate(workspace_columns):
            if isinstance(col_dict, dict):
                column_id = col_dict.get('id')
                dataset_name = col_dict.get('dataset')
                added_at = col_dict.get('added_at')
                logger.info(f"🔍 COORDINATOR: Input column {i}: '{column_id}' from '{dataset_name}' added at '{added_at}'")
        
        for col_dict in workspace_columns:
            if isinstance(col_dict, dict):
                column_id = col_dict.get('id')
                dataset_name = col_dict.get('dataset')
                source_name = col_dict.get('source')
                
                # Skip invalid columns
                if not column_id or not dataset_name:
                    logger.warning(f"🔍 COORDINATOR: Skipping invalid column: id={column_id}, dataset={dataset_name}")
                    continue
                
                # Skip duplicate column IDs
                if column_id in column_ids_seen:
                    logger.warning(f"🔍 COORDINATOR: DUPLICATE COLUMN ID DETECTED: '{column_id}' - skipping duplicate")
                    continue
                
                column_ids_seen.add(column_id)
                dataset_key = f"{source_name}::{dataset_name}"
                
                if dataset_key not in datasets_map:
                    datasets_map[dataset_key] = {
                        'name': dataset_name,
                        'source': source_name,
                        'selected_count': 0,
                        'columns': []
                    }
                
                datasets_map[dataset_key]['columns'].append(col_dict)
                datasets_map[dataset_key]['selected_count'] += 1
                
                logger.info(f"🔍 COORDINATOR: Added column '{column_id}' to dataset group '{dataset_key}' (group now has {datasets_map[dataset_key]['selected_count']} columns)")
        
        # Convert to list and sort by most recent workspace activity
        datasets_with_columns = list(datasets_map.values())
        
        logger.info(f"🔍 COORDINATOR: Before sorting - {len(datasets_with_columns)} dataset groups:")
        for i, dataset_group in enumerate(datasets_with_columns):
            latest_col = max(dataset_group['columns'], key=lambda c: c.get('added_at', '0000'), default={})
            latest_time = latest_col.get('added_at', 'No timestamp')
            logger.info(f"  {i+1}. '{dataset_group['name']}' ({dataset_group['selected_count']} columns) - latest: {latest_time}")
        
        # Sort by the most recent column addition to workspace (newest workspace activity first)
        def get_latest_workspace_activity(dataset_group):
            latest_timestamp = '0000-00-00T00:00:00'  # Default very old timestamp
            for col in dataset_group['columns']:
                added_at = col.get('added_at')
                if added_at and added_at > latest_timestamp:
                    latest_timestamp = added_at
            return latest_timestamp
        
        # Sort with explicit reverse=True to ensure newest datasets appear first
        datasets_with_columns.sort(key=get_latest_workspace_activity, reverse=True)
        
        # Add debug logging to verify sorting
        logger.info(f"🔍 COORDINATOR: Dataset sorting order:")
        for i, dataset_group in enumerate(datasets_with_columns):
            latest_activity = get_latest_workspace_activity(dataset_group)
            logger.info(f"  {i+1}. '{dataset_group['name']}' - latest activity: {latest_activity}")
        
        logger.info(f"🔍 COORDINATOR: Prepared {len(datasets_with_columns)} dataset groups with total {len(column_ids_seen)} unique columns")
        
        return datasets_with_columns

    # ==========================================================================
    # CSV-Specific State Reset Operations
    # ==========================================================================
    
    def reset_all_coordinator_state(self, request, organization_id):
        """
        Completely reset all coordinator state - datasets, columns, and relationships.
        
        UNIFIED RESET: This is the definitive "Clear All" method that resets everything.
        
        Args:
            request: Django request object
            organization_id (str): Organization ID
            
        Returns:
            tuple: (datasets_cleared, columns_cleared, summary)
        """
        logger.info(f"🔄 COORDINATOR: COMPLETE STATE RESET for org='{organization_id}'")
        
        # 1. Get current state before reset
        current_workspace = self.get_workspace_columns(request, organization_id)
        selected_datasets = self.get_selected_dataset_names(request, organization_id)
        
        # 2. Clear ALL workspace columns first (most important)
        self.clear_workspace_columns(request, organization_id)
        columns_cleared = len(current_workspace)
        
        # 3. Clear ALL dataset selections
        self.clear_selected_datasets(request, organization_id)
        datasets_cleared = len(selected_datasets)
        
        # 4. Clear any cached FK datasets (optional cleanup)
        self.clear_fk_datasets_cache(request, organization_id)
        
        # 5. Verify complete reset
        final_workspace = self.get_workspace_columns(request, organization_id)
        final_datasets = self.get_selected_dataset_names(request, organization_id)
        
        is_clean = len(final_workspace) == 0 and len(final_datasets) == 0
        
        summary = {
            'datasets_cleared': datasets_cleared,
            'columns_cleared': columns_cleared,
            'is_completely_clean': is_clean,
            'final_workspace_count': len(final_workspace),
            'final_datasets_count': len(final_datasets)
        }
        
        logger.info(f"🔄 COORDINATOR: RESET COMPLETE - Cleared {datasets_cleared} datasets, {columns_cleared} columns, clean={is_clean}")
        
        return datasets_cleared, columns_cleared, summary

    def clear_selected_datasets_only(self, request, organization_id):
        """
        Clear ONLY selected datasets (keep workspace columns intact).
        Also clears column selection state to prevent conflicts.
        
        SPECIFIC OPERATION: This is for the dataset badges "Clear Selected" button.
        Only removes dataset selections but preserves all workspace columns and their configurations.
        
        Args:
            request: Django request object
            organization_id (str): Organization ID
            
        Returns:
            tuple: (datasets_cleared, workspace_preserved_count)
        """
        logger.info(f"🗂️ COORDINATOR: CLEAR SELECTED DATASETS ONLY for org='{organization_id}'")
        
        # Get current state
        selected_datasets = self.get_selected_dataset_names(request, organization_id)
        workspace_columns = self.get_workspace_columns(request, organization_id)
        
        # Clear ONLY dataset selections
        self.clear_selected_datasets(request, organization_id)
        datasets_cleared = len(selected_datasets)
        
        # CRITICAL: Also clear ALL column selection state to prevent conflicts
        # When datasets are cleared, any lingering column selections can cause htmx:targetError
        # when new datasets are selected and try to update non-existent elements
        selection_key = self.get_session_key('column_selection', organization_id)
        column_selections = request.session.get(selection_key, {})
        columns_selections_cleared = len(column_selections)
        
        if column_selections:
            request.session[selection_key] = {}
            request.session.modified = True
            logger.info(f"🗂️ COORDINATOR: Cleared {columns_selections_cleared} column selection states to prevent conflicts")
        
        # Workspace remains untouched
        workspace_preserved_count = len(workspace_columns)
        
        logger.info(f"🗂️ COORDINATOR: DATASETS ONLY CLEAR - Cleared {datasets_cleared} datasets and {columns_selections_cleared} column selections, preserved {workspace_preserved_count} workspace columns")
        
        return datasets_cleared, workspace_preserved_count

    def clear_workspace_columns_only(self, request, organization_id):
        """
        Clear ONLY workspace columns (keep selected datasets intact).
        
        SPECIFIC OPERATION: This is for the workspace "Clear Workspace" button.
        Only removes workspace columns but preserves all dataset selections.
        
        Args:
            request: Django request object
            organization_id (str): Organization ID
            
        Returns:
            tuple: (columns_cleared, datasets_preserved_count)
        """
        logger.info(f"🏗️ COORDINATOR: CLEAR WORKSPACE COLUMNS ONLY for org='{organization_id}'")
        
        # Get current state
        workspace_columns = self.get_workspace_columns(request, organization_id)
        selected_datasets = self.get_selected_dataset_names(request, organization_id)
        
        # Clear ONLY workspace columns
        self.clear_workspace_columns(request, organization_id)
        columns_cleared = len(workspace_columns)
        
        # Selected datasets remain untouched
        datasets_preserved_count = len(selected_datasets)
        
        logger.info(f"🏗️ COORDINATOR: WORKSPACE ONLY CLEAR - Cleared {columns_cleared} workspace columns, preserved {datasets_preserved_count} selected datasets")
        
        return columns_cleared, datasets_preserved_count

    def get_clear_operation_context(self, request, organization_id):
        """
        Get context data needed for clear operation responses.
        
        UNIFIED CONTEXT: This provides all the data needed to render responses after clear operations.
        
        Args:
            request: Django request object
            organization_id (str): Organization ID
            
        Returns:
            dict: Context data for templates
        """
        # Get updated state
        updated_selected_datasets = self.get_selected_dataset_names(request, organization_id)
        updated_workspace_columns = self.get_workspace_columns(request, organization_id)
        csv_datasets = self.get_csv_datasets_for_organization(organization_id)
        
        # Prepare template contexts
        badges_context = {
            'datasets': csv_datasets,
            'selected_datasets': updated_selected_datasets,
            'organization_id': organization_id,
            'csrf_token': request.META.get('CSRF_COOKIE'),
        }
        
        datasets_with_columns = self._prepare_datasets_with_columns(updated_workspace_columns)
        workspace_context = {
            'datasets_with_columns': datasets_with_columns,
            'workspace_columns_count': len(updated_workspace_columns),  # Add raw count for button visibility
            'organization_id': organization_id,
            'csrf_token': request.META.get('CSRF_COOKIE'),
        }
        
        # Table content context for dataset cards (right side)
        table_content_context = {
            'selected_datasets_with_details': [],  # Will be populated based on operation type
            'organization_id': organization_id,
            'csrf_token': request.META.get('CSRF_COOKIE'),
        }
        
        return {
            'badges_context': badges_context,
            'workspace_context': workspace_context,
            'table_content_context': table_content_context,
            'updated_selected_datasets': updated_selected_datasets,
            'updated_workspace_columns': updated_workspace_columns,
            'csv_datasets': csv_datasets
        }

    # ==========================================================================
    # CSV-Specific FK Configuration Support (All Available Datasets with Session Caching)
    # ==========================================================================
    
    def get_all_datasets_with_columns_for_fk(self, request, organization_id, force_refresh=False):
        """
        Get ALL available datasets with their columns for FK configuration, with session caching.
        
        This method gets all datasets in the organization (not just selected ones)
        with their column information, formatted for FK form usage. Results are cached
        in session to avoid expensive S3 calls on every FK form open.
        
        Args:
            request: Django request object (for session access)
            organization_id (str): Organization ID
            force_refresh (bool): If True, bypass cache and refresh data
            
        Returns:
            list: All datasets with their column details
        """
        cache_key = self.get_session_key('all_datasets_fk', organization_id)
        
        # Check if we have cached data and don't need refresh
        if not force_refresh and cache_key in request.session:
            cached_data = request.session[cache_key]
            logger.info(f"COORDINATOR: Using cached FK datasets data, org='{organization_id}' ({len(cached_data)} datasets)")
            return cached_data
        
        logger.info(f"COORDINATOR: Loading ALL datasets with columns for FK configuration, org='{organization_id}'")
        
        try:
            from arkumu.metadata.services.data_analysis.s3_direct_data_analyzer import S3DirectDataAnalyzer
            analyzer = S3DirectDataAnalyzer()
            
            # Get all sources for the organization
            sources = analyzer.discover_s3_data_sources(organization_id)
            all_datasets_with_columns = []
            
            for source in sources:
                logger.info(f"COORDINATOR: Processing source '{source.name}'")
                
                try:
                    # Get source summary which includes all datasets with previews
                    source_summary = analyzer.get_s3_source_summary(organization_id, source.name)
                    
                    # Process each dataset in the source
                    for dataset_info in source_summary.get('datasets', []):
                        dataset_name = dataset_info.get('name')
                        
                        # Only include CSV-compatible datasets
                        if self._is_csv_dataset(dataset_name, source):
                            dataset_with_columns = {
                                'name': dataset_name,
                                'source': source.name,
                                'preview': {
                                    'colHeaders': dataset_info.get('columns', []),
                                    'data': dataset_info.get('sample_data', []),
                                    'total_rows': dataset_info.get('row_count', 0),
                                }
                            }
                            all_datasets_with_columns.append(dataset_with_columns)
                            
                except Exception as e:
                    logger.warning(f"COORDINATOR: Error processing source '{source.name}': {e}")
                    continue
            
            # Cache the results in session
            request.session[cache_key] = all_datasets_with_columns
            request.session.modified = True
            
            logger.info(f"COORDINATOR: Loaded and cached {len(all_datasets_with_columns)} datasets with columns for FK")
            return all_datasets_with_columns
            
        except Exception as e:
            logger.error(f"COORDINATOR: Error getting all datasets with columns: {e}", exc_info=True)
            return []
    
    def clear_fk_datasets_cache(self, request, organization_id):
        """
        Clear the cached FK datasets data for an organization.
        
        Args:
            request: Django request object
            organization_id (str): Organization ID
        """
        cache_key = self.get_session_key('all_datasets_fk', organization_id)
        if cache_key in request.session:
            del request.session[cache_key]
            request.session.modified = True
            logger.info(f"COORDINATOR: Cleared FK datasets cache for org='{organization_id}'")
    
    def refresh_fk_datasets_cache(self, request, organization_id):
        """
        Refresh the cached FK datasets data for an organization.
        
        Args:
            request: Django request object
            organization_id (str): Organization ID
            
        Returns:
            list: Refreshed datasets data
        """
        logger.info(f"COORDINATOR: Refreshing FK datasets cache for org='{organization_id}'")
        return self.get_all_datasets_with_columns_for_fk(request, organization_id, force_refresh=True)
            
    def _is_csv_dataset(self, dataset_name, source):
        """
        Check if a dataset is a CSV/parseable format.
        
        Args:
            dataset_name (str): Name of the dataset
            source: Source object with format information
            
        Returns:
            bool: True if dataset is CSV-compatible
        """
        dataset_lower = dataset_name.lower()
        return (dataset_lower.endswith(('.csv', '.tsv', '.txt')) or 
                'csv' in dataset_lower or 
                (source.format and source.format.lower() in ['csv', 'tsv', 'text']))

    # ==========================================================================
    # CSV-Specific Mapping Persistence (Save/Load State)
    # ==========================================================================
    
    def serialize_current_mapping_state(self, request, organization_id, mapping_name=None):
        """
        Serialize current coordinator state to a mapping configuration.
        
        This captures all current UI state including selected datasets,
        workspace columns, FK relationships, and entity configurations.
        
        Args:
            request: Django request object
            organization_id (str): Organization ID
            mapping_name (str, optional): Name for the mapping
            
        Returns:
            dict: Serialized mapping configuration suitable for Mapping.mapping_config
        """
        logger.info(f"SERIALIZE_MAPPING: Starting serialization for organization {organization_id}")
        
        # Get current workspace state
        workspace_columns = self.get_workspace_columns(request, organization_id)
        
        # Extract datasets that actually have columns in workspace (not UI browsing state)
        workspace_datasets = set()
        for column_data in workspace_columns:
            dataset_name = column_data.get('dataset')
            if dataset_name:
                workspace_datasets.add(dataset_name)
        workspace_datasets = list(workspace_datasets)
        
        # Serialize FK relationships and relationship contexts from workspace columns
        fk_relationships = {}
        relationship_contexts = {}
        external_ontologies = {}
        entity_mappings = {}
        
        # Handle workspace_columns as list (current format)
        for column_data in workspace_columns:
            column_id = column_data.get('id')
            if not column_id:
                continue
                
            # Extract FK configurations
            if column_data.get('fk_config'):
                # Parse source info from the column_id key (e.g., 'org::dataset::column' or 'dataset::column')
                parsed = self.parse_column_id(column_id)
                source_dataset = parsed.get('dataset') or ''
                source_column = parsed.get('column') or ''
                # Normalize dataset: strip optional .csv suffix
                if source_dataset.endswith('.csv'):
                    source_dataset = source_dataset[:-4]

                fk_relationships[column_id] = {
                    'source_dataset': source_dataset,
                    'source_column': source_column,
                    'target_dataset': column_data['fk_config'].get('target_dataset'),
                    'target_column': column_data['fk_config'].get('target_column'),
                    'display_column': column_data['fk_config'].get('display_column'),
                    'relationship_type': column_data['fk_config'].get('relationship_type', 'reference'),
                    'direction': column_data['fk_config'].get('direction', 'outbound')
                }
            
            # Extract relationship context configurations
            if column_data.get('is_relationship_context') and column_data.get('relationship_context'):
                relationship_contexts[column_id] = {
                    'context_type': column_data['relationship_context'].get('context_type'),
                    'primary_fk': column_data['relationship_context'].get('primary_fk'),
                    'secondary_fk': column_data['relationship_context'].get('secondary_fk'),
                    'context_predicate': column_data['relationship_context'].get('context_predicate')
                }
            
            # Extract external ontology configurations (support multiple ontologies)
            if column_data.get('is_external_ontology'):
                # Support both single (legacy) and multiple ontologies format
                if column_data.get('external_ontologies'):
                    # New format: multiple ontologies
                    external_ontologies[column_id] = column_data['external_ontologies']
                elif column_data.get('external_ontology'):
                    # Legacy format: single ontology - convert to list
                    external_ontologies[column_id] = [{
                        'ontology_type': column_data['external_ontology'].get('ontology_type'),
                        'uri_template': column_data['external_ontology'].get('uri_template'),
                        'identifier_pattern': column_data['external_ontology'].get('identifier_pattern'),
                        'validation_enabled': column_data['external_ontology'].get('validation_enabled', True)
                    }]
            
            # Extract RDF predicate mappings (if any)
            if column_data.get('rdf_predicate'):
                if 'predicate_mappings' not in entity_mappings:
                    entity_mappings['predicate_mappings'] = {}
                entity_mappings['predicate_mappings'][column_id] = column_data['rdf_predicate']
            
            # Extract subject column designation (if any)
            if column_data.get('is_subject_column'):
                entity_mappings['subject_column'] = column_id
        
        # Convert workspace_columns list to dict for easier storage/lookup
        workspace_columns_dict = {}
        for column_data in workspace_columns:
            column_id = column_data.get('id')
            if column_id:
                workspace_columns_dict[column_id] = column_data
        
        # Build complete mapping configuration
        mapping_config = {
            'version': '1.2',  # Updated version to include external ontologies
            'created_at': timezone.now().isoformat(),
            'organization_id': organization_id,
            'workspace_datasets': workspace_datasets,  # Only datasets with actual workspace columns
            'workspace_columns': workspace_columns_dict,  # Store as dict for easier lookup
            'fk_relationships': fk_relationships,
            'relationship_contexts': relationship_contexts,  # New: relationship context configurations
            'external_ontologies': external_ontologies,  # New: external ontology configurations
            'entity_mappings': entity_mappings,
            'metadata': {
                'total_datasets': len(workspace_datasets),  # Only count datasets that have columns
                'total_columns': len(workspace_columns),
                'total_fk_relationships': len(fk_relationships),
                'total_relationship_contexts': len(relationship_contexts),
                'total_external_ontologies': len(external_ontologies),
                'mapping_name': mapping_name or f"Mapping_{timezone.now().strftime('%Y%m%d_%H%M%S')}"
            }
        }
        
        logger.info(f"SERIALIZE_MAPPING: Serialized {len(workspace_datasets)} workspace datasets, {len(workspace_columns)} columns, {len(fk_relationships)} FK relationships, {len(relationship_contexts)} relationship contexts, {len(external_ontologies)} external ontologies")
        return mapping_config
    
    def deserialize_mapping_state(self, request, organization_id, mapping_config, mapping_id=None, mapping_name=None):
        """
        Restore coordinator state from a mapping configuration.
        
        This loads a saved mapping and restores all UI state including
        selected datasets, workspace columns, and FK relationships.
        
        Args:
            request: Django request object
            organization_id (str): Organization ID
            mapping_config (dict): Mapping configuration from Mapping.mapping_config
            mapping_id (str, optional): ID of the loaded mapping for tracking
            mapping_name (str, optional): Name of the loaded mapping for tracking
            
        Returns:
            dict: Summary of restored state
        """
        logger.info(f"🟡 DESERIALIZE_MAPPING: Starting deserialization for organization {organization_id}")
        logger.info(f"🟡 DESERIALIZE_MAPPING: Mapping config keys: {list(mapping_config.keys()) if mapping_config else 'None'}")
        
        # Validate mapping config
        if not mapping_config:
            logger.error(f"🔴 DESERIALIZE_MAPPING: Invalid mapping config - no config")
            raise ValueError(f"Invalid mapping config for organization {organization_id}")
        
        # Check organization_id if present in config (legacy mappings may not have it)
        config_org_id = mapping_config.get('organization_id')
        if config_org_id and config_org_id != organization_id:
            logger.error(f"🔴 DESERIALIZE_MAPPING: Organization mismatch - config: {config_org_id}, expected: {organization_id}")
            raise ValueError(f"Invalid mapping config for organization {organization_id}")
        
        logger.info(f"🟡 DESERIALIZE_MAPPING: Clearing current state...")
        
        # Clear current state first
        self.reset_all_coordinator_state(request, organization_id)
        
        logger.info(f"🟡 DESERIALIZE_MAPPING: Tracking loaded mapping context...")
        
        # Track loaded mapping context using shared mapping state
        if mapping_id and mapping_name:
            self.set_current_mapping(request, mapping_id, mapping_name, organization_id)
            logger.info(f"🟢 DESERIALIZE_MAPPING: Set current mapping to '{mapping_name}' (ID: {mapping_id})")
        else:
            logger.warning(f"🟡 DESERIALIZE_MAPPING: No mapping_id or mapping_name provided - not setting current mapping")
        
        # NOTE: Do NOT restore selected datasets from mapping
        # Selected datasets are UI browsing state, not mapping configuration state
        # Loading a mapping should only restore workspace columns, not change dataset browsing
        # Support both old format (selected_datasets) and new format (workspace_datasets)
        workspace_datasets = mapping_config.get('workspace_datasets', mapping_config.get('selected_datasets', []))
        logger.info(f"🟡 DESERIALIZE_MAPPING: Found {len(workspace_datasets)} workspace datasets in mapping (but not restoring to UI)")
        
        logger.info(f"🟡 DESERIALIZE_MAPPING: Restoring workspace columns...")
        
        # Restore workspace columns (convert dict back to list format)
        workspace_columns_dict = mapping_config.get('workspace_columns', {})
        logger.info(f"🟡 DESERIALIZE_MAPPING: Found {len(workspace_columns_dict)} workspace columns in mapping")
        
        if workspace_columns_dict:
            # Convert dict back to list format expected by workspace
            workspace_columns_list = list(workspace_columns_dict.values())
            workspace_key = self.get_session_key('workspace_columns', organization_id)
            request.session[workspace_key] = workspace_columns_list
            logger.info(f"🟢 DESERIALIZE_MAPPING: Restored {len(workspace_columns_list)} workspace columns to session")
            
            # Debug: Log first few columns
            for i, col in enumerate(workspace_columns_list[:3]):
                logger.info(f"🟡 DESERIALIZE_MAPPING: Column {i}: {col.get('id', 'unknown')} from {col.get('dataset', 'unknown')}")
        else:
            workspace_columns_list = []
            logger.info(f"🟡 DESERIALIZE_MAPPING: No workspace columns to restore")
        
        logger.info(f"🟡 DESERIALIZE_MAPPING: Saving session changes...")
        
        # Save session changes
        request.session.modified = True
        
        logger.info(f"🟡 DESERIALIZE_MAPPING: Building restoration summary...")
        
        # Build restoration summary
        fk_relationships = mapping_config.get('fk_relationships', {})
        relationship_contexts = mapping_config.get('relationship_contexts', {})
        external_ontologies = mapping_config.get('external_ontologies', {})
        metadata = mapping_config.get('metadata', {})
        
        summary = {
            'datasets_restored': len(workspace_datasets),
            'columns_restored': len(workspace_columns_list),
            'fk_relationships_restored': len(fk_relationships),
            'relationship_contexts_restored': len(relationship_contexts),
            'external_ontologies_restored': len(external_ontologies),
            'mapping_name': metadata.get('mapping_name', 'Unknown'),
            'original_created_at': mapping_config.get('created_at'),
            'version': mapping_config.get('version', 'Unknown')
        }
        
        logger.info(f"🟢 DESERIALIZE_MAPPING: Successfully restored mapping '{summary['mapping_name']}' with {summary['datasets_restored']} workspace datasets, {summary['columns_restored']} columns, {summary['fk_relationships_restored']} FK relationships, {summary['relationship_contexts_restored']} relationship contexts, and {summary['external_ontologies_restored']} external ontologies")
        return summary
    
    def validate_mapping_compatibility(self, request, organization_id, mapping_config):
        """
        Validate that a mapping configuration is compatible with current datasets.
        
        This checks if the datasets and columns referenced in the mapping
        are still available in the current organization context.
        
        Args:
            request: Django request object  
            organization_id (str): Organization ID
            mapping_config (dict): Mapping configuration to validate
            
        Returns:
            dict: Validation results with warnings/errors
        """
        logger.info(f"🔍 VALIDATE_MAPPING: Starting validation for organization {organization_id}")
        logger.info(f"🔍 VALIDATE_MAPPING: Mapping config keys: {list(mapping_config.keys())}")
        
        validation_result = {
            'is_valid': True,
            'warnings': [],
            'errors': [],
            'missing_datasets': [],
            'missing_columns': []
        }
        
        # Get available datasets for this organization
        try:
            logger.info(f"🔍 VALIDATE_MAPPING: Getting available datasets for organization {organization_id}")
            available_datasets = self.get_csv_datasets_for_organization(organization_id)
            available_dataset_names = [ds['name'] for ds in available_datasets]
            logger.info(f"🔍 VALIDATE_MAPPING: Found {len(available_dataset_names)} available datasets: {available_dataset_names[:5]}{'...' if len(available_dataset_names) > 5 else ''}")
        except Exception as e:
            logger.error(f"🔴 VALIDATE_MAPPING: Failed to get available datasets: {str(e)}", exc_info=True)
            validation_result['errors'].append(f"Failed to get available datasets: {str(e)}")
            validation_result['is_valid'] = False
            return validation_result
        
        # Check dataset availability (support both old and new format)
        required_datasets = mapping_config.get('workspace_datasets', mapping_config.get('selected_datasets', []))
        logger.info(f"🔍 VALIDATE_MAPPING: Required datasets from mapping: {required_datasets}")
        
        for dataset_name in required_datasets:
            if dataset_name not in available_dataset_names:
                logger.warning(f"🟡 VALIDATE_MAPPING: Missing dataset '{dataset_name}' not found in available datasets")
                validation_result['missing_datasets'].append(dataset_name)
                # Convert missing datasets to warnings instead of errors to allow mapping load
                validation_result['warnings'].append(f"Dataset '{dataset_name}' is not currently available")
            else:
                logger.info(f"✅ VALIDATE_MAPPING: Dataset '{dataset_name}' is available")
        
        # Check column availability
        workspace_columns = mapping_config.get('workspace_columns', {})
        for column_id in workspace_columns.keys():
            # Parse column ID: "source::dataset::column_name"
            parts = column_id.split('::', 2)
            if len(parts) == 3:
                source, dataset_name, column_name = parts
                if dataset_name not in available_dataset_names:
                    validation_result['missing_columns'].append(column_id)
                    if dataset_name not in validation_result['missing_datasets']:
                        validation_result['missing_datasets'].append(dataset_name)
                        # Add warning for missing dataset (not error)
                        validation_result['warnings'].append(f"Dataset '{dataset_name}' is not currently available")
        
        # Check relationship context consistency
        relationship_contexts = mapping_config.get('relationship_contexts', {})
        for context_id, context_config in relationship_contexts.items():
            primary_fk = context_config.get('primary_fk')
            secondary_fk = context_config.get('secondary_fk')
            
            # Check that referenced FK columns exist in workspace
            if primary_fk and primary_fk not in workspace_columns:
                validation_result['warnings'].append(f"Relationship context '{context_id}' references missing primary FK: {primary_fk}")
            
            if secondary_fk and secondary_fk not in workspace_columns:
                validation_result['warnings'].append(f"Relationship context '{context_id}' references missing secondary FK: {secondary_fk}")
        
        # Generate warnings/errors
        if validation_result['missing_datasets']:
            # Treat missing datasets as warnings, not fatal errors
            validation_result['warnings'].append(f"Some datasets may not be available: {', '.join(validation_result['missing_datasets'])}")
            logger.warning(f"🟡 VALIDATE_MAPPING: Warning - Missing datasets: {validation_result['missing_datasets']}")
        
        if validation_result['missing_columns']:
            validation_result['warnings'].append(f"Some columns may not be available: {len(validation_result['missing_columns'])} columns")
            logger.warning(f"🟡 VALIDATE_MAPPING: Warning - Missing columns: {len(validation_result['missing_columns'])}")
        
        if validation_result['is_valid']:
            logger.info(f"✅ VALIDATE_MAPPING: Validation PASSED - Valid: {validation_result['is_valid']}, Warnings: {len(validation_result['warnings'])}")
        else:
            logger.error(f"🔴 VALIDATE_MAPPING: Validation FAILED - Valid: {validation_result['is_valid']}, Errors: {validation_result['errors']}")
        
        return validation_result
    
    # ==========================================================================
    # Loaded Mapping Context Management (Using BaseCoordinatorMixin)
    # ==========================================================================
    
    def is_mapping_loaded(self, request):
        """
        Check if a mapping is currently loaded.
        
        Returns:
            bool: True if a mapping is loaded, False otherwise
        """
        return self.get_current_mapping(request) is not None
    
    # ==========================================================================
    # Organization Change Handling (BaseCoordinatorMixin Integration)
    # ==========================================================================
    
    def handle_organization_change(self, request, new_organization_id):
        """
        Handle organization change with CSV mapping-specific state cleanup.
        
        Extends BaseCoordinatorMixin.handle_organization_change with CSV mapping cleanup.
        
        Args:
            request: Django request object
            new_organization_id: New organization ID or code
            
        Returns:
            tuple: (new_org_data, old_org_data) - New and old organization data
        """
        logger.info(f"CSV_COORDINATOR: Handling organization change to {new_organization_id}")
        
        # Call parent to handle organization change safely
        return super().handle_organization_change(request, new_organization_id)
    
    def clear_organization_specific_state(self, request, organization_id):
        """
        Clear all CSV mapping state specific to an organization.
        
        Overrides BaseCoordinatorMixin to provide CSV mapping-specific cleanup.
        
        Args:
            request: Django request object
            organization_id (int): Organization numeric ID to clear state for
        """
        logger.info(f"CSV_COORDINATOR: Clearing organization-specific state for org ID {organization_id}")
        
        # Clear all CSV mapping session keys for this organization
        keys_to_clear = [
            self.get_session_key('selected_datasets', organization_id),
            self.get_session_key('column_selection', organization_id),
            self.get_session_key('workspace_columns', organization_id),
            self.get_session_key('all_datasets_fk', organization_id),
            # Note: loaded_mapping is now managed at the base level as current_mapping
        ]
        
        for key in keys_to_clear:
            if key in request.session:
                del request.session[key]
                logger.info(f"CSV_COORDINATOR: Cleared session key: {key}")
        
        request.session.modified = True
        
        # Call parent implementation
        super().clear_organization_specific_state(request, organization_id)
    
    def validate_mapping_structure(self, request, organization_id, file_columns=None):
        """
        Validate the current mapping structure against file columns.
        
        This method now delegates to the centralized MappingValidator while
        maintaining backward compatibility with the original interface.
        
        Args:
            request: Django request object
            organization_id (int): Organization numeric ID
            file_columns (list, optional): List of file column names to validate against
            
        Returns:
            dict: Validation result containing:
                - mapped_columns: Dict of mapped column names to their arkumu types
                - unmapped_columns: List of columns that exist in files but aren't mapped
                - missing_required_columns: List of required columns missing from files
                - coverage_percentage: Percentage of file columns that are mapped
                - issues: List of validation issues found
        """
        from arkumu.importer.services.mapping_validation import MappingValidator
        
        # Get workspace columns from session
        workspace_columns = self.get_workspace_columns(request, organization_id)
        
        # Convert list format to dict format for validator
        workspace_columns_dict = {}
        for col in workspace_columns:
            if isinstance(col, dict):
                col_id = col.get('id')
                if col_id:
                    workspace_columns_dict[col_id] = col
        
        # If no file columns provided, we can only validate the mapping structure itself
        if file_columns is None:
            file_columns = []
        
        # Delegate to centralized validator
        return MappingValidator.validate_column_mappings(workspace_columns_dict, file_columns)
