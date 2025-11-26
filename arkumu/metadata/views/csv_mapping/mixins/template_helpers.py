"""
CSV Mapping Template Helpers

This mixin provides common template rendering and context preparation methods
to reduce code duplication across CSV mapping views.
"""

import logging
from django.template.loader import render_to_string
from django.middleware.csrf import get_token

from arkumu.storage.services.verification_service import annotate_verified_flags

logger = logging.getLogger(__name__)


class CSVMappingTemplateHelperMixin:
    """
    Mixin providing common template rendering methods for CSV mapping views.
    
    This reduces the significant code duplication found across csv_mapping_views.py
    and saved_mappings_ui.py where the same templates are rendered repeatedly
    with similar context preparation.
    """
    
    def render_workspace_template(self, request, organization_id, workspace_columns=None):
        """
        Render workspace template with standard context.
        
        Consolidates the repeated pattern:
        - Get workspace columns
        - Prepare datasets_with_columns 
        - Build context
        - Render template
        """
        if workspace_columns is None:
            workspace_columns = self.get_workspace_columns(request, organization_id)
        
        logger.info(f"🎨 TEMPLATE_HELPER: render_workspace_template called with {len(workspace_columns)} workspace columns")
        logger.info(f"🖥️ WORKSPACE_RENDER: About to call _prepare_datasets_with_columns with workspace_columns count: {len(workspace_columns)}")
        
        datasets_with_columns = self._prepare_datasets_with_columns(workspace_columns)
        
        logger.info(f"🖥️ WORKSPACE_RENDER: _prepare_datasets_with_columns returned {len(datasets_with_columns)} datasets")
        
        logger.info(f"🎨 TEMPLATE_HELPER: Final template render order - {len(datasets_with_columns)} datasets:")
        for i, dataset_group in enumerate(datasets_with_columns):
            logger.info(f"  Template position {i+1}: '{dataset_group['name']}' ({dataset_group['selected_count']} columns)")
        
        context = {
            'datasets_with_columns': datasets_with_columns,
            'organization_id': organization_id,
            'csrf_token': get_token(request),
        }
        
        return render_to_string(
            'csv_mapping/partials/selected_columns_workspace.html',
            context,
            request=request
        )
    
    def render_dataset_counter_template(self, request, organization_id, dataset_name):
        """
        Render just the counter badge for a specific dataset.
        
        Used for targeted OOB updates when columns are added/removed.
        """
        workspace_columns = self.get_workspace_columns(request, organization_id)
        
        # Count columns for this specific dataset
        dataset_column_count = 0
        for col in workspace_columns:
            if isinstance(col, dict):
                col_dataset = col.get('dataset')
                if col_dataset == dataset_name:
                    dataset_column_count += 1
            else:
                # Handle string format: "dataset_source_column"
                if col.startswith(f"{dataset_name}_"):
                    dataset_column_count += 1
        
        # Return just the counter content (without the ID, since OOB will target by ID)
        return f'{dataset_column_count} selected'
    
    def render_dataset_badges_template(self, request, organization_id, csv_datasets=None, selected_datasets=None):
        """
        Render dataset badges template with standard context.
        
        Consolidates the repeated pattern for dataset badges rendering.
        """
        if csv_datasets is None:
            csv_datasets = self.get_csv_datasets_for_organization(organization_id)
        
        if selected_datasets is None:
            selected_datasets = self.get_selected_dataset_names(request, organization_id)
        
        context = {
            'datasets': csv_datasets,
            'selected_datasets': selected_datasets,
            'organization_id': organization_id,
            'csrf_token': get_token(request),
        }
        
        return render_to_string(
            'csv_mapping/partials/dataset_badges.html',
            context,
            request=request
        )
    
    def render_table_content_template(self, request, organization_id, selected_datasets_with_details=None):
        """
        Render table content template with standard context.
        
        Includes column selection state for each dataset.
        """
        if selected_datasets_with_details is None:
            # Get basic selected datasets info
            selected_datasets = self.get_selected_dataset_names(request, organization_id)
            csv_datasets = self.get_csv_datasets_for_organization(organization_id)
            selected_datasets_with_details = [
                ds for ds in csv_datasets if ds.get('name') in selected_datasets
            ]
        
        # Get column selection state for all datasets
        selection_key = f"column_selection_{organization_id}"
        column_selections = request.session.get(selection_key, {})
        
        # Add column selection context to each dataset
        enhanced_datasets = []
        for dataset in selected_datasets_with_details:
            dataset_key = f"{dataset.get('name')}::{dataset.get('source')}"
            dataset_selected_columns = column_selections.get(dataset_key, [])
            
            # Create enhanced dataset with selection context
            enhanced_dataset = {
                **dataset,
                'dataset_selected_columns': dataset_selected_columns
            }
            enhanced_datasets.append(enhanced_dataset)
        
        context = {
            'selected_datasets_with_details': enhanced_datasets,  # Include selection context
            'organization_id': organization_id,
            'csrf_token': get_token(request),
        }
        
        return render_to_string(
            'csv_mapping/partials/table_content.html',
            context,
            request=request
        )
    
    def render_column_badges_template(self, request, organization_id, dataset_name, source_name, dataset_preview=None):
        """
        Render column badges template for a specific dataset.
        
        Uses separate column selection session (not workspace) for pure selection interface.
        """
        # Get column selection state from separate session key (not workspace)
        selection_key = f"column_selection_{organization_id}"
        column_selections = request.session.get(selection_key, {})
        dataset_key = f"{dataset_name}::{source_name}"
        dataset_selected_columns = column_selections.get(dataset_key, [])
        
        # Get dataset preview if not provided
        if dataset_preview is None:
            from arkumu.metadata.services.data_analysis.s3_direct_data_analyzer import S3DirectDataAnalyzer
            analyzer = S3DirectDataAnalyzer()
            # OPTIMIZATION: Use single dataset summary to avoid full S3 scan
            dataset_preview = analyzer.get_single_dataset_summary(organization_id, dataset_name, source_name)
        
        # Build dataset context
        dataset_context = {
            'name': dataset_name,
            'source': source_name,
        }
        
        # Always add preview data for column badges to render
        if dataset_preview:
            dataset_context['preview'] = {
                'colHeaders': dataset_preview.get('columns', dataset_preview.get('colHeaders', []))
            }
        else:
            # Fallback to prevent template errors
            dataset_context['preview'] = {
                'colHeaders': []
            }
        
        context = {
            'dataset': dataset_context,
            'dataset_selected_columns': dataset_selected_columns,  # From selection interface, not workspace
            'organization_id': organization_id,
            'csrf_token': get_token(request),
        }
        
        return render_to_string(
            'csv_mapping/partials/column_badges.html',
            context,
            request=request
        )
    
    def render_column_item_template(self, request, organization_id, column):
        """
        Render individual column item template.
        
        Consolidates the repeated pattern for column item rendering.
        """
        context = {
            'column': column,
            'organization_id': organization_id,
            'csrf_token': get_token(request),
        }
        
        return render_to_string(
            'csv_mapping/partials/column_item.html',
            context,
            request=request
        )
    
    def build_oob_response(self, main_html, oob_updates=None):
        """
        Build response with out-of-band updates.
        
        Consolidates the repeated pattern:
        response = f'{main_html}<div id="target" hx-swap-oob="innerHTML">{content}</div>'
        
        Args:
            main_html (str): The main response HTML
            oob_updates (dict): Dict of {target_id: content} for OOB updates
        
        Returns:
            str: Complete HTML response with OOB updates
        """
        logger.info(f"🔍 BUILD_OOB DEBUG: main_html length: {len(main_html)}")
        logger.info(f"🔍 BUILD_OOB DEBUG: oob_updates: {list(oob_updates.keys()) if oob_updates else 'None'}")
        
        if not oob_updates:
            logger.info(f"🔍 BUILD_OOB DEBUG: No OOB updates, returning main_html only")
            return main_html
        
        oob_html = ""
        for target_id, content in oob_updates.items():
            oob_element = f'<div id="{target_id}" hx-swap-oob="innerHTML">{content}</div>'
            oob_html += oob_element
            logger.info(f"🔍 BUILD_OOB DEBUG: Added OOB element for '{target_id}', content length: {len(content)}")
        
        final_response = f'{main_html}{oob_html}'
        logger.info(f"🔍 BUILD_OOB DEBUG: Final combined response length: {len(final_response)}")
        return final_response
    
    def add_workspace_update_trigger(self, html_content):
        """
        Add workspace update trigger for JSON view synchronization.
        
        This method adds an HX-Trigger header to fire a 'refreshJson' event
        that the JSON view listens for to update its content when workspace changes occur.
        
        Args:
            html_content (str): The HTML content to wrap in an HttpResponse
            
        Returns:
            HttpResponse: Response with HX-Trigger header for JSON synchronization
        """
        from django.http import HttpResponse
        import json
        
        response = HttpResponse(html_content)
        # Add HX-Trigger header to fire refreshJson event for JSON view synchronization
        trigger_data = {
            'refreshJson': True
        }
        response['HX-Trigger'] = json.dumps(trigger_data)
        return response
    
    def build_standard_ui_refresh_response(self, request, organization_id, main_html=""):
        """
        Build a standard response that refreshes all major UI components.
        
        This is commonly needed after operations that change the mapping state.
        Returns main_html + OOB updates for workspace, badges, and table content.
        """
        # Render all standard templates
        workspace_html = self.render_workspace_template(request, organization_id)
        badges_html = self.render_dataset_badges_template(request, organization_id)
        table_html = self.render_table_content_template(request, organization_id)
        
        # Build OOB updates
        oob_updates = {
            'workspace-content': workspace_html,
            'dataset-badges': badges_html,
            'table-content': table_html,
        }
        
        return self.build_oob_response(main_html, oob_updates)
    
    def render_file_browser_template(self, request, organization):
        """
        Render file browser template with eager loading for data/metadata folders.

        Consolidates the repeated pattern:
        - Get bucket service and contents
        - Pre-load data and metadata folder contents  
        - Prepare enhanced context
        - Render template
        """
        try:
            from arkumu.storage.services.bucket_service import BucketService
            
            bucket_service = BucketService()
            bucket_name = bucket_service.get_organization_bucket(organization)
            # Force fresh listing for OOB updates to ensure new files appear
            contents = bucket_service.list_bucket_contents(bucket_name, '', force_fresh=True)
            annotate_verified_flags(contents, organization)
            
            logger.info(f"🔍 FILE_BROWSER_TEMPLATE: organization={organization}")
            logger.info(f"🔍 FILE_BROWSER_TEMPLATE: bucket_name={bucket_name}")
            logger.info(f"🔍 FILE_BROWSER_TEMPLATE: contents count={len(contents) if contents else 0}")
            
            # Add eager loading for data and metadata folders to show uploaded files immediately
            enhanced_contents = []
            for item in contents:
                if item['type'] == 'folder' and item['name'] in ['data', 'metadata']:
                    logger.info(f"🔄 EAGER_LOADING: Pre-loading contents for {item['name']} folder")
                    try:
                        # Force fresh subfolder listing for OOB updates
                        subfolder_contents = bucket_service.list_bucket_contents(
                            bucket_name, 
                            item['path'],
                            force_fresh=True
                        )
                        annotate_verified_flags(subfolder_contents, organization)
                        item['preloaded_contents'] = subfolder_contents
                        # Add file count for data and metadata folders - force fresh count for OOB updates
                        item['file_count'] = bucket_service.count_files_in_folder(bucket_name, item['path'], force_fresh=True)
                        logger.info(f"✅ EAGER_LOADING: Loaded {len(subfolder_contents) if subfolder_contents else 0} items for {item['name']} folder")
                        logger.info(f"📊 FILE_COUNT: {item['name']} has {item['file_count']} files")
                        if subfolder_contents:
                            logger.info(f"📁 EAGER_LOADING: {item['name']} contents: {[sub_item.get('name', 'unknown') for sub_item in subfolder_contents[:5]]}")
                    except Exception as e:
                        logger.error(f"❌ EAGER_LOADING: Failed to pre-load {item['name']} folder contents: {e}")
                        item['preloaded_contents'] = []
                else:
                    item['preloaded_contents'] = None
                enhanced_contents.append(item)
            
            context = {
                'organization': organization,
                'bucket_name': bucket_name,
                'contents': enhanced_contents,
                'selected_org_slug': organization,
                'prefix': '',
                'csrf_token': get_token(request) if request else ''
            }
            
            rendered_html = render_to_string(
                'dashboard/organization_files_partial.html',
                context,
                request=request
            )
            
            logger.info(f"🔍 FILE_BROWSER_TEMPLATE: rendered HTML length={len(rendered_html)}")
            logger.info(f"🔍 FILE_BROWSER_TEMPLATE: HTML starts with: '{rendered_html[:100]}'")
            logger.info(f"🔍 FILE_BROWSER_TEMPLATE: HTML after strip starts with: '{rendered_html.strip()[:100]}'")
            return rendered_html
            
        except Exception as e:
            logger.error(f"❌ FILE_BROWSER_TEMPLATE: Error rendering file browser template: {e}")
            return f'<div class="alert alert-error"><span>Error loading file browser: {str(e)}</span></div>'

    # --------------------------------------------------------------
    # Navbar helpers (OOB updates for HTMX-enabled flows)
    # --------------------------------------------------------------
    def render_metadata_entry_nav_items(self, request, *, active: bool = False):
        """Render OOB payload for metadata entry navbar links."""

        context = {
            'active': active,
        }

        return render_to_string(
            'metadata/entry/partials/navbar_oob.html',
            context,
            request=request,
        )
