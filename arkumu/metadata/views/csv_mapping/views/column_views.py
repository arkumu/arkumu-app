"""
CSV Mapping Column Views

This module contains views for column workspace management in the CSV mapping interface:
- Add/remove individual columns to/from workspace
- Select/deselect all columns from a dataset
- Set anchor columns and toggle multi-value columns

ARCHITECTURE: Uses coordinator-based architecture with template helpers to minimize duplication.
"""

import logging
from django.shortcuts import render
from django.http import HttpResponse
from django.views import View
from arkumu.users.mixins import GeneralLoginRequiredMixin

from arkumu.metadata.services.data_analysis.s3_direct_data_analyzer import S3DirectDataAnalyzer
from arkumu.metadata.views.csv_mapping.mixins.coordinator import CSVMappingCoordinatorMixin
from arkumu.metadata.views.csv_mapping.mixins.template_helpers import CSVMappingTemplateHelperMixin

logger = logging.getLogger(__name__)


class AddColumnToWorkspaceView(GeneralLoginRequiredMixin, 
    CSVMappingCoordinatorMixin, 
    CSVMappingTemplateHelperMixin,
    View):
    """
    Add column to workspace view using coordinator-based architecture.
    
    Uses coordinator for validated column addition with dataset checking and
    template helpers to reduce rendering duplication.
    """
    
    def post(self, request):
        """Handle POST requests for adding columns to workspace with validation."""
        try:
            # Get current organization using BaseCoordinatorMixin
            current_org = self.get_current_organization(request)
            if not current_org:
                return HttpResponse("No organization selected", status=400)
            organization_id = current_org['code']
            
            # Handle different POST data formats from the template
            column_name = request.POST.get('column') or request.POST.get('column_name')
            dataset_name = request.POST.get('dataset') or request.POST.get('dataset_name')
            source_name = request.POST.get('source') or request.POST.get('source_name')
            
            # Parse column_id if provided (format: "dataset_source_column")
            column_id = request.POST.get('column_id')
            if column_id and not all([column_name, dataset_name, source_name]):
                parts = column_id.split('_')
                if len(parts) >= 3:
                    dataset_name = parts[0]
                    source_name = parts[1]
                    column_name = '_'.join(parts[2:])  # Column name might contain underscores
            
            if not all([column_name, dataset_name, source_name]):
                return HttpResponse(f'<div class="alert alert-error">Column, dataset, and source parameters required</div>')
            
            # PERFORMANCE OPTIMIZATION: Use safe add method with automatic state correction
            success, new_column, total_columns, error_message = self.safe_add_column_with_validation(
                request, organization_id, column_name, dataset_name, source_name
            )
            
            if not success:
                return HttpResponse(f'<div class="alert alert-warning">{error_message}</div>')
            
            # Get updated dataset with column selection state using template helper
            column_badges_html = self.render_column_badges_template(
                request, organization_id, dataset_name, source_name
            )
            
            # WORKSPACE OPERATION: Update both column badges AND workspace
            workspace_html = self.render_workspace_template(request, organization_id)
            
            # Build OOB response - this is a workspace operation so it should update workspace
            oob_updates = {
                'workspace-content': workspace_html
            }
            response_html = self.build_oob_response(column_badges_html, oob_updates)
            
            # Add trigger for JSON tab refresh
            return self.add_workspace_update_trigger(response_html)
            
        except Exception as e:
            logger.error(f"ADD_COLUMN: Error adding column to workspace: {e}", exc_info=True)
            return HttpResponse(f'<div class="alert alert-error">Error: {str(e)}</div>')


class RemoveColumnFromWorkspaceView(GeneralLoginRequiredMixin, 
    CSVMappingCoordinatorMixin, 
    CSVMappingTemplateHelperMixin,
    View):
    """
    Remove column from workspace view using coordinator-based architecture.
    
    Uses coordinator for column removal with dataset relationship awareness and
    template helpers to reduce rendering duplication.
    """
    
    def post(self, request):
        """Handle POST requests for removing columns from workspace."""
        try:
            # Get current organization using BaseCoordinatorMixin
            current_org = self.get_current_organization(request)
            if not current_org:
                return HttpResponse("No organization selected", status=400)
            organization_id = current_org['code']
            
            # Handle different POST data formats
            column_name = request.POST.get('column') or request.POST.get('column_name')
            dataset_name = request.POST.get('dataset') or request.POST.get('dataset_name')
            source_name = request.POST.get('source') or request.POST.get('source_name')
            
            if not all([column_name, dataset_name, source_name]):
                return HttpResponse(f'<div class="alert alert-error">Column, dataset, and source parameters required</div>')
            
            # Generate column ID using coordinator format (using organization_id as source)
            column_id = self.generate_column_id(dataset_name, column_name, organization_id)
            
            # Get current workspace columns
            workspace_columns = self.get_workspace_columns(request, organization_id)
            
            # Remove the column - handle both string and dict formats
            updated_columns = []
            for col in workspace_columns:
                if isinstance(col, dict):
                    col_id = col.get('id')
                    if col_id != column_id:
                        updated_columns.append(col)
                else:
                    if col != column_id:
                        updated_columns.append(col)
            self.update_workspace_columns(request, organization_id, updated_columns)
            
            # Clear loaded mapping context since workspace has been modified
            cleared_mapping = self.clear_current_mapping(request)
            if cleared_mapping:
                logger.info(f"REMOVE_COLUMN: Cleared loaded mapping '{cleared_mapping.get('name')}' due to workspace modification")
            
            # Return updated column badges HTML with workspace update via hx-swap-oob using template helpers
            column_badges_html = self.render_column_badges_template(
                request, organization_id, dataset_name, source_name
            )
            
            # WORKSPACE OPERATION: Update both column badges AND workspace
            workspace_html = self.render_workspace_template(request, organization_id)
            
            # Build OOB response - this is a workspace operation so it should update workspace
            oob_updates = {
                'workspace-content': workspace_html
            }
            
            # If we cleared a loaded mapping, silently continue
            if cleared_mapping:
                logger.info(f"REMOVE_COLUMN: Cleared loaded mapping '{cleared_mapping.get('mapping_name')}' due to workspace modification")
            
            response_html = self.build_oob_response(column_badges_html, oob_updates)
            
            # Add trigger for JSON tab refresh
            return self.add_workspace_update_trigger(response_html)
            
        except Exception as e:
            logger.error(f"REMOVE_COLUMN: Error removing column from workspace: {e}", exc_info=True)
            return HttpResponse(f'<div class="alert alert-error">Error: {str(e)}</div>')


class SelectAllDatasetColumnsView(GeneralLoginRequiredMixin, 
    CSVMappingCoordinatorMixin, 
    CSVMappingTemplateHelperMixin,
    View):
    """
    Select all columns from a dataset using coordinator-based architecture.
    
    Uses coordinator for batch column operations and template helpers for clean response building.
    """
    
    def post(self, request):
        """Handle POST requests for selecting all columns from a dataset."""
        try:
            # Get current organization using BaseCoordinatorMixin
            current_org = self.get_current_organization(request)
            if not current_org:
                return HttpResponse("No organization selected", status=400)
            organization_id = current_org['code']
            dataset_name = request.POST.get('dataset')
            source_name = request.POST.get('source')
            
            if not dataset_name or not source_name:
                return HttpResponse(f'<div class="alert alert-error">Dataset and source parameters required</div>')
            
            # Safe validation with auto-correction for dataset selection state
            is_valid, was_corrected, status_message = self.validate_and_fix_dataset_selection_state(
                request, organization_id, dataset_name, source_name
            )
            
            if not is_valid:
                return HttpResponse(f'<div class="alert alert-warning">{status_message}</div>')
            
            # Log if auto-correction was applied
            if was_corrected:
                logger.info(f"🔒 SELECT_ALL_COLUMNS: {status_message}")
                # Could optionally show a user-friendly message about the auto-correction
            
            # Get dataset preview to get all column names
            # OPTIMIZATION: Use single dataset summary to avoid full S3 scan
            analyzer = S3DirectDataAnalyzer()
            dataset_preview = analyzer.get_single_dataset_summary(organization_id, dataset_name, source_name)
            
            if dataset_preview.get('error'):
                return HttpResponse(f'<div class="alert alert-error">Dataset "{dataset_name}" error: {dataset_preview["error"]}</div>')
            
            # PERFORMANCE OPTIMIZATION: Use batch operation instead of individual column adds
            column_names = dataset_preview.get('columns', [])
            total_added, skipped_duplicates, final_count, error_message = self.batch_add_columns_with_validation(
                request, organization_id, column_names, dataset_name, source_name
            )
            
            if error_message:
                return HttpResponse(f'<div class="alert alert-error">Error: {error_message}</div>')
            
            logger.info(f"🚀 SELECT_ALL_OPTIMIZED: Added {total_added} columns, skipped {skipped_duplicates} duplicates, final count: {final_count}")
            
            # Return updated column badges HTML with workspace update via hx-swap-oob using template helpers
            column_badges_html = self.render_column_badges_template(
                request, organization_id, dataset_name, source_name, dataset_preview
            )
            
            # WORKSPACE OPERATION: Update both column badges AND workspace
            workspace_html = self.render_workspace_template(request, organization_id)
            
            # Build OOB response - this is a workspace operation so it should update workspace
            oob_updates = {
                'workspace-content': workspace_html
            }
            response_html = self.build_oob_response(column_badges_html, oob_updates)
            
            # Add trigger for JSON tab refresh
            return self.add_workspace_update_trigger(response_html)
            
        except Exception as e:
            logger.error(f"SELECT_ALL_DATASET_COLUMNS: Error selecting all columns: {e}", exc_info=True)
            return HttpResponse(f'<div class="alert alert-error">Error: {str(e)}</div>')


class DeselectAllDatasetColumnsView(GeneralLoginRequiredMixin, 
    CSVMappingCoordinatorMixin, 
    CSVMappingTemplateHelperMixin,
    View):
    """
    Deselect all columns from a dataset using coordinator-based architecture.
    
    Uses coordinator for batch column removal and template helpers for clean response building.
    """
    
    def post(self, request):
        """Handle POST requests for deselecting all columns from a dataset."""
        try:
            logger.info(f"🗑️ DESELECT_ALL_DATASET: Starting deselect request")
            
            # Get current organization using BaseCoordinatorMixin
            current_org = self.get_current_organization(request)
            if not current_org:
                logger.error(f"🗑️ DESELECT_ALL_DATASET: No organization selected")
                return HttpResponse("No organization selected", status=400)
            organization_id = current_org['code']
            logger.info(f"🗑️ DESELECT_ALL_DATASET: Organization ID: '{organization_id}'")
            
            dataset_name = request.POST.get('dataset')
            source_name = request.POST.get('source')
            logger.info(f"🗑️ DESELECT_ALL_DATASET: POST params - dataset='{dataset_name}', source='{source_name}'")
            
            if not dataset_name or not source_name:
                logger.error(f"🗑️ DESELECT_ALL_DATASET: Missing required parameters")
                return HttpResponse(f'<div class="alert alert-error">Dataset and source parameters required</div>')
            
            # Get current workspace columns using coordinator
            logger.info(f"🗑️ DESELECT_ALL_DATASET: Getting workspace columns...")
            workspace_columns = self.get_workspace_columns(request, organization_id)
            logger.info(f"🗑️ DESELECT_ALL_DATASET: Found {len(workspace_columns)} total workspace columns")
            
            # Remove all columns belonging to this dataset using coordinator parsing
            logger.info(f"🗑️ DESELECT_ALL_DATASET: Processing columns to remove...")
            columns_removed = 0
            updated_columns = []
            
            for i, col_dict in enumerate(workspace_columns):
                # Extract the column ID string from the dictionary
                col_id = col_dict.get('id') if isinstance(col_dict, dict) else col_dict
                logger.info(f"🗑️ DESELECT_ALL_DATASET: Processing column {i+1}/{len(workspace_columns)}: '{col_id}'")
                
                if col_id:
                    parsed = self.parse_column_id(col_id)
                    logger.info(f"🗑️ DESELECT_ALL_DATASET: Parsed column '{col_id}' -> source='{parsed['source']}', dataset='{parsed['dataset']}', column='{parsed['column']}'")
                    
                    # Match dataset and source (source could be source_name OR organization_id)
                    dataset_matches = parsed['dataset'] == dataset_name
                    source_matches = (parsed['source'] == source_name or 
                                    parsed['source'] == organization_id)
                    
                    logger.info(f"🗑️ DESELECT_ALL_DATASET: Column '{col_id}' matches - dataset: {dataset_matches} ('{parsed['dataset']}' == '{dataset_name}'), source: {source_matches} ('{parsed['source']}' in ['{source_name}', '{organization_id}'])")
                    
                    if dataset_matches and source_matches:
                        columns_removed += 1
                        logger.info(f"✅🗑️ DESELECT_ALL_DATASET: REMOVING column '{col_id}' - matched target dataset and source")
                    else:
                        updated_columns.append(col_dict)
                        logger.info(f"➡️🗑️ DESELECT_ALL_DATASET: KEEPING column '{col_id}' - no match")
                else:
                    updated_columns.append(col_dict)
                    logger.warning(f"⚠️🗑️ DESELECT_ALL_DATASET: Column has no ID, keeping it: {col_dict}")
            
            logger.info(f"🗑️ DESELECT_ALL_DATASET: Column processing complete - {columns_removed} columns to remove, {len(updated_columns)} columns to keep")
            logger.info(f"🗑️ DESELECT_ALL_DATASET: Final result - {columns_removed} columns removed from dataset '{dataset_name}', {len(updated_columns)} remaining")
            
            # If no columns were removed, return a simple success message without full UI update
            if columns_removed == 0:
                logger.info(f"🗑️ DESELECT_ALL_DATASET: No columns to remove - returning simple success message")
                return HttpResponse(f'<div class="alert alert-success">Dataset "{dataset_name}" has no columns to remove</div>')
            
            # Update workspace using coordinator
            logger.info(f"🗑️ DESELECT_ALL_DATASET: Updating workspace with {len(updated_columns)} columns...")
            self.update_workspace_columns(request, organization_id, updated_columns)
            logger.info(f"🗑️ DESELECT_ALL_DATASET: Workspace update completed")
            
            # Also remove the dataset from selected datasets list
            logger.info(f"🗑️ DESELECT_ALL_DATASET: Removing dataset '{dataset_name}' from selected datasets list...")
            success, final_list, was_present, error = self.remove_selected_dataset(request, organization_id, dataset_name)
            if success and was_present:
                logger.info(f"🗑️ DESELECT_ALL_DATASET: Successfully removed '{dataset_name}' from selected datasets")
            elif success and not was_present:
                logger.info(f"🗑️ DESELECT_ALL_DATASET: Dataset '{dataset_name}' was not in selected datasets list")
            else:
                logger.warning(f"🗑️ DESELECT_ALL_DATASET: Failed to remove dataset from selected list: {error}")
            
            # Use standard UI refresh to update all components (workspace, badges, counters)
            logger.info(f"🗑️ DESELECT_ALL_DATASET: Building UI refresh response...")
            response_html = self.build_standard_ui_refresh_response(request, organization_id)
            logger.info(f"🗑️ DESELECT_ALL_DATASET: UI refresh response built successfully")
            
            # Add trigger for JSON tab refresh
            logger.info(f"🗑️ DESELECT_ALL_DATASET: Adding workspace update trigger...")
            final_response = self.add_workspace_update_trigger(response_html)
            logger.info(f"🗑️ DESELECT_ALL_DATASET: Final response prepared successfully")
            
            logger.info(f"✅🗑️ DESELECT_ALL_DATASET: Successfully completed deselect request")
            return final_response
            
        except Exception as e:
            logger.error(f"DESELECT_ALL_DATASET_COLUMNS: Error deselecting all columns: {e}", exc_info=True)
            return HttpResponse(f'<div class="alert alert-error">Error: {str(e)}</div>')


class SetAnchorColumnView(GeneralLoginRequiredMixin, 
    CSVMappingCoordinatorMixin, 
    CSVMappingTemplateHelperMixin,
    View):
    """
    Set a column as the anchor column using the coordinator mixin.
    Only one column can be anchor at a time.
    
    Uses template helpers to reduce rendering duplication.
    """
    
    def post(self, request):
        try:
            # Get current organization using BaseCoordinatorMixin
            current_org = self.get_current_organization(request)
            if not current_org:
                return HttpResponse("No organization selected", status=400)
            organization_id = current_org['code']
            column_id = request.POST.get('column_id')
            
            logger.info(f"🚨 SET_ANCHOR: Received column_id='{column_id}' for org='{organization_id}'")
            
            if not column_id:
                return HttpResponse('<div class="alert alert-error">Missing column_id</div>')
            
            # UNIFIED TRACKING: Use coordinator method to find column (same as FK system)
            column = self.get_unified_column_by_id(request, organization_id, column_id)
            if not column:
                # Also validate workspace for duplicates and auto-clean (same as FK system)
                is_unique, duplicates, cleaned = self.validate_workspace_column_uniqueness(request, organization_id)
                if not is_unique:
                    logger.error(f"CSV_SET_ANCHOR: Found {len(duplicates)} workspace duplicates - auto-cleaned and retrying")
                    column = self.get_unified_column_by_id(request, organization_id, column_id)
                
                if not column:
                    logger.error(f"CSV_SET_ANCHOR: Column '{column_id}' not found even after cleanup")
                    return HttpResponse('<div class="alert alert-error">Column not found in workspace</div>')
            
            # Use mixin method to toggle anchor column (consistent with FK approach)
            success, updated_columns = self.toggle_anchor_column(request, organization_id, column_id)
            
            if not success:
                return HttpResponse('<div class="alert alert-error">Failed to toggle anchor column</div>')
            
            # Find the updated column to return just that column item (like FK save does)
            target_column = next((col for col in updated_columns if col.get('id') == column_id), None)
            if not target_column:
                return HttpResponse('<div class="alert alert-error">Updated column not found</div>')
            
            # Return just the updated column item using template helper
            column_html = self.render_column_item_template(request, organization_id, target_column)
            
            return HttpResponse(column_html)
            
        except Exception as e:
            logger.error(f"Error setting anchor column: {e}", exc_info=True)
            return HttpResponse(f'<div class="alert alert-error">Error: {str(e)}</div>')


class ToggleMultiValueColumnView(GeneralLoginRequiredMixin, 
    CSVMappingCoordinatorMixin, 
    CSVMappingTemplateHelperMixin,
    View):
    """
    Toggle the multi-value status of a column using the coordinator mixin.
    
    Uses template helpers to reduce rendering duplication.
    """
    
    def post(self, request):
        try:
            # Get current organization using BaseCoordinatorMixin
            current_org = self.get_current_organization(request)
            if not current_org:
                return HttpResponse("No organization selected", status=400)
            organization_id = current_org['code']
            column_id = request.POST.get('column_id')
            
            logger.info(f"🚨 TOGGLE_MULTI_VALUE: Received column_id='{column_id}' for org='{organization_id}'")
            
            if not column_id:
                return HttpResponse('<div class="alert alert-error">Missing column_id</div>')
            
            # UNIFIED TRACKING: Use coordinator method to find column (same as FK system)
            column = self.get_unified_column_by_id(request, organization_id, column_id)
            if not column:
                # Also validate workspace for duplicates and auto-clean (same as FK system)
                is_unique, duplicates, cleaned = self.validate_workspace_column_uniqueness(request, organization_id)
                if not is_unique:
                    logger.error(f"CSV_TOGGLE_MULTI_VALUE: Found {len(duplicates)} workspace duplicates - auto-cleaned and retrying")
                    column = self.get_unified_column_by_id(request, organization_id, column_id)
                
                if not column:
                    logger.error(f"CSV_TOGGLE_MULTI_VALUE: Column '{column_id}' not found even after cleanup")
                    return HttpResponse('<div class="alert alert-error">Column not found in workspace</div>')
            
            # Use mixin method to toggle multi-value column (consistent with FK approach)
            success, updated_columns = self.toggle_multi_value_column(request, organization_id, column_id)
            
            if not success:
                return HttpResponse('<div class="alert alert-error">Failed to toggle multi-value column</div>')
            
            # Find the updated column to return just that column item (like FK save does)
            updated_column = next((col for col in updated_columns if col.get('id') == column_id), None)
            if not updated_column:
                return HttpResponse('<div class="alert alert-error">Updated column not found</div>')
            
            # Return just the updated column item using template helper
            column_html = self.render_column_item_template(request, organization_id, updated_column)
            
            return HttpResponse(column_html)
            
        except Exception as e:
            logger.error(f"Error toggling multi-value column: {e}", exc_info=True)
            return HttpResponse(f'<div class="alert alert-error">Error: {str(e)}</div>')


# ==============================================================================
# Pure Selection Interface Views (No Workspace Operations)
# ==============================================================================

class ToggleColumnSelectionView(GeneralLoginRequiredMixin, 
    CSVMappingCoordinatorMixin, 
    CSVMappingTemplateHelperMixin,
    View):
    """
    Toggle column selection in the browsing interface ONLY.
    
    This is pure selection interface - does not affect workspace.
    Stores selection state in session under a separate key.
    """
    
    def post(self, request):
        """Handle POST requests for toggling column selection (browsing only)."""
        try:
            # Get current organization using BaseCoordinatorMixin
            current_org = self.get_current_organization(request)
            if not current_org:
                return HttpResponse("No organization selected", status=400)
            organization_id = current_org['code']
            column_name = request.POST.get('column')
            dataset_name = request.POST.get('dataset')
            source_name = request.POST.get('source')
            
            logger.info(f"🔄 TOGGLE_COLUMN_SELECTION: org={organization_id}, dataset={dataset_name}, source={source_name}, column={column_name}")
            
            if not all([column_name, dataset_name, source_name]):
                return HttpResponse('<div class="alert alert-error">Column, dataset, and source parameters required</div>')
            
            # Use separate session key for column selection (not workspace)
            selection_key = f"column_selection_{organization_id}"
            column_selections = request.session.get(selection_key, {})
            
            # Dataset-specific selections
            dataset_key = f"{dataset_name}::{source_name}"
            if dataset_key not in column_selections:
                column_selections[dataset_key] = []
            
            # Toggle column selection
            was_selected = column_name in column_selections[dataset_key]
            if was_selected:
                column_selections[dataset_key].remove(column_name)
                action = "REMOVED"
            else:
                column_selections[dataset_key].append(column_name)
                action = "ADDED"
            
            # Save to session
            request.session[selection_key] = column_selections
            request.session.modified = True
            
            # Get updated selection state
            dataset_selected_columns = column_selections.get(dataset_key, [])
            
            logger.info(f"🔄 TOGGLE_COLUMN_SELECTION: {action} '{column_name}' - Now {len(dataset_selected_columns)} columns selected: {dataset_selected_columns}")
            
            # Return updated column badges (selection interface only)
            column_badges_html = self.render_column_badges_template(
                request, organization_id, dataset_name, source_name
            )
            
            return HttpResponse(column_badges_html)
            
        except Exception as e:
            logger.error(f"TOGGLE_COLUMN_SELECTION: Error: {e}", exc_info=True)
            return HttpResponse(f'<div class="alert alert-error">Error: {str(e)}</div>')


class SelectAllColumnsView(GeneralLoginRequiredMixin, 
    CSVMappingCoordinatorMixin, 
    CSVMappingTemplateHelperMixin,
    View):
    """
    Select all columns in dataset (browsing interface only).
    
    This is pure selection interface - does not affect workspace.
    """
    
    def post(self, request):
        """Handle POST requests for selecting all columns (browsing only)."""
        try:
            # Get current organization using BaseCoordinatorMixin
            current_org = self.get_current_organization(request)
            if not current_org:
                return HttpResponse("No organization selected", status=400)
            organization_id = current_org['code']
            dataset_name = request.POST.get('dataset')
            source_name = request.POST.get('source')
            
            if not dataset_name or not source_name:
                return HttpResponse('<div class="alert alert-error">Dataset and source parameters required</div>')
            
            # Get all columns from dataset
            # OPTIMIZATION: Use single dataset summary to avoid full S3 scan
            analyzer = S3DirectDataAnalyzer()
            dataset_preview = analyzer.get_single_dataset_summary(organization_id, dataset_name, source_name)
            
            if dataset_preview.get('error'):
                return HttpResponse(f'<div class="alert alert-error">Dataset error: {dataset_preview["error"]}</div>')
            
            # Use separate session key for column selection (not workspace)
            selection_key = f"column_selection_{organization_id}"
            column_selections = request.session.get(selection_key, {})
            
            # Dataset-specific selections - select all columns
            dataset_key = f"{dataset_name}::{source_name}"
            column_selections[dataset_key] = dataset_preview.get('columns', [])
            
            # Save to session
            request.session[selection_key] = column_selections
            request.session.modified = True
            
            # Return updated column badges (selection interface only)
            column_badges_html = self.render_column_badges_template(
                request, organization_id, dataset_name, source_name, dataset_preview
            )
            
            return HttpResponse(column_badges_html)
            
        except Exception as e:
            logger.error(f"SELECT_ALL_COLUMNS: Error: {e}", exc_info=True)
            return HttpResponse(f'<div class="alert alert-error">Error: {str(e)}</div>')


class DeselectAllColumnsView(GeneralLoginRequiredMixin, 
    CSVMappingCoordinatorMixin, 
    CSVMappingTemplateHelperMixin,
    View):
    """
    Deselect all columns in dataset (browsing interface only).
    
    This is pure selection interface - does not affect workspace.
    """
    
    def post(self, request):
        """Handle POST requests for deselecting all columns (browsing only)."""
        try:
            # Get current organization using BaseCoordinatorMixin
            current_org = self.get_current_organization(request)
            if not current_org:
                return HttpResponse("No organization selected", status=400)
            organization_id = current_org['code']
            dataset_name = request.POST.get('dataset')
            source_name = request.POST.get('source')
            
            if not dataset_name or not source_name:
                return HttpResponse('<div class="alert alert-error">Dataset and source parameters required</div>')
            
            # Use separate session key for column selection (not workspace)
            selection_key = f"column_selection_{organization_id}"
            column_selections = request.session.get(selection_key, {})
            
            # Dataset-specific selections - clear all
            dataset_key = f"{dataset_name}::{source_name}"
            column_selections[dataset_key] = []
            
            # Save to session
            request.session[selection_key] = column_selections
            request.session.modified = True
            
            # Return updated column badges (selection interface only)
            column_badges_html = self.render_column_badges_template(
                request, organization_id, dataset_name, source_name
            )
            
            return HttpResponse(column_badges_html)
            
        except Exception as e:
            logger.error(f"DESELECT_ALL_COLUMNS: Error: {e}", exc_info=True)
            return HttpResponse(f'<div class="alert alert-error">Error: {str(e)}</div>')


class AddSelectedColumnsToWorkspaceView(GeneralLoginRequiredMixin, 
    CSVMappingCoordinatorMixin, 
    CSVMappingTemplateHelperMixin,
    View):
    """
    Add selected columns to workspace (workspace operation only).
    
    This transfers columns from selection interface to workspace.
    Only affects workspace, not selection interface.
    """
    
    def post(self, request):
        """Handle POST requests for adding selected columns to workspace."""
        try:
            # Get current organization using BaseCoordinatorMixin
            current_org = self.get_current_organization(request)
            if not current_org:
                return HttpResponse("No organization selected", status=400)
            organization_id = current_org['code']
            dataset_name = request.POST.get('dataset')
            source_name = request.POST.get('source')
            selected_columns = request.POST.getlist('columns')
            
            logger.info(f"➕ ADD_SELECTED_TO_WORKSPACE: org={organization_id}, dataset={dataset_name}, source={source_name}")
            logger.info(f"➕ ADD_SELECTED_TO_WORKSPACE: columns={selected_columns}")
            
            if not dataset_name or not source_name or not selected_columns:
                logger.error(f"➕ ADD_SELECTED_TO_WORKSPACE: Missing required parameters")
                return HttpResponse('<div class="alert alert-error">Dataset, source, and columns parameters required</div>')
            
            # Add columns to workspace using coordinator
            total_added = 0
            errors = []
            
            for column_name in selected_columns:
                success, new_column, total_columns, error_message = self.safe_add_column_with_validation(
                    request, organization_id, column_name, dataset_name, source_name
                )
                if success:
                    total_added += 1
                    logger.info(f"➕ ADD_SELECTED_TO_WORKSPACE: Successfully added '{column_name}'")
                else:
                    errors.append(f"{column_name}: {error_message}")
                    logger.error(f"➕ ADD_SELECTED_TO_WORKSPACE: Failed to add '{column_name}': {error_message}")
            
            logger.info(f"➕ ADD_SELECTED_TO_WORKSPACE: Added {total_added}/{len(selected_columns)} columns")
            
            # Return updated workspace (workspace operation only)
            workspace_html = self.render_workspace_template(request, organization_id)
            
            # Add trigger for JSON tab refresh since this modifies workspace
            return self.add_workspace_update_trigger(workspace_html)
            
        except Exception as e:
            logger.error(f"ADD_SELECTED_TO_WORKSPACE: Error: {e}", exc_info=True)
            return HttpResponse(f'<div class="alert alert-error">Error: {str(e)}</div>')


# ============================================================================== 