"""
File Browser Out-of-Band (OOB) Views

Handles HTMX out-of-band updates for the file browser component
when uploads complete or files are modified.
"""

import json
import logging
from django.http import HttpResponse
from django.template.loader import render_to_string
from django.views.decorators.http import require_http_methods
from django.middleware.csrf import get_token
from arkumu.users.mixins import general_login_required
from arkumu.metadata.views.csv_mapping.mixins.template_helpers import CSVMappingTemplateHelperMixin

logger = logging.getLogger(__name__)


class FileBrowserOOBMixin(CSVMappingTemplateHelperMixin):
    """
    Mixin providing template rendering methods for file browser OOB updates.
    
    Inherits from CSVMappingTemplateHelperMixin to reuse proven OOB patterns
    and response building methods, following DRY principles.
    """
    
    def render_organization_files_template(self, organization, request=None):
        """
        Render organization files partial template with standard context.
        
        Now implements eager loading to pre-load 'data' and 'metadata' folder contents
        to fix the folder refresh issue after uploads.
        
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
            # Force fresh listing for OOB updates
            contents = bucket_service.list_bucket_contents(bucket_name, '', force_fresh=True)
            
            logger.info(f"🔍 FILE_BROWSER_OOB DEBUG: organization={organization}")
            logger.info(f"🔍 FILE_BROWSER_OOB DEBUG: bucket_name={bucket_name}")
            logger.info(f"🔍 FILE_BROWSER_OOB DEBUG: contents type={type(contents)}")
            logger.info(f"🔍 FILE_BROWSER_OOB DEBUG: contents is None={contents is None}")
            logger.info(f"🔍 FILE_BROWSER_OOB DEBUG: contents count={len(contents) if contents else 0}")
            if contents:
                logger.info(f"🔍 FILE_BROWSER_OOB DEBUG: first few contents: {[item.get('name', 'unknown') for item in contents[:3]]}")
            else:
                logger.warning(f"⚠️ FILE_BROWSER_OOB DEBUG: Contents is empty or None! This will show 'No files found' message")
                # Force a non-empty contents for testing
                contents = []
            
            # ISSUE 1 FIX: Pre-load data and metadata folder contents for eager loading
            enhanced_contents = []
            for item in contents:
                if item['type'] == 'folder' and item['name'] in ['data', 'metadata']:
                    logger.info(f"🔄 EAGER_LOADING: Pre-loading contents for {item['name']} folder")
                    try:
                        # Load subfolder contents - force fresh for OOB updates
                        subfolder_contents = bucket_service.list_bucket_contents(
                            bucket_name, 
                            item['path'],
                            force_fresh=True
                        )
                        item['preloaded_contents'] = subfolder_contents
                        # Add file count for data and metadata folders - force fresh for OOB updates
                        item['file_count'] = bucket_service.count_files_in_folder(bucket_name, item['path'], force_fresh=True)
                        logger.info(f"✅ EAGER_LOADING: Loaded {len(subfolder_contents) if subfolder_contents else 0} items for {item['name']} folder")
                        if subfolder_contents:
                            logger.info(f"📁 EAGER_LOADING: {item['name']} contents: {[sub_item.get('name', 'unknown') for sub_item in subfolder_contents[:5]]}")
                    except Exception as e:
                        logger.error(f"❌ EAGER_LOADING: Failed to pre-load {item['name']} folder contents: {e}")
                        item['preloaded_contents'] = []
                else:
                    # For non-data/metadata folders, no preloading needed
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
            
            logger.info(f"🔍 FILE_BROWSER_OOB DEBUG: rendered HTML length={len(rendered_html)}")
            logger.info(f"🔍 FILE_BROWSER_OOB DEBUG: rendered HTML preview: {rendered_html[:300]}...")
            
            return rendered_html
        except Exception as e:
            logger.error(f"Error rendering organization files template: {e}")
            return f'<div class="error">Error loading files: {str(e)}</div>'


# Helper instance for functions that can't inherit from mixin
_file_browser_helper = FileBrowserOOBMixin()


@require_http_methods(["GET"])
@general_login_required
def test_oob_refresh(request, organization):
    """
    Simple test endpoint to trigger file browser OOB refresh.
    
    Use this to test the OOB mechanism without complex upload flows:
    GET /storage/test/oob-refresh/your-org/
    """
    logger.info(f"🧪 TEST: Manual OOB refresh triggered for organization: {organization}")
    
    try:
        # Use the same logic as the main refresh endpoint
        file_browser_html = _file_browser_helper.render_organization_files_template(
            organization, request
        )
        
        # Build OOB response
        oob_updates = {
            'file-browser-content': file_browser_html
        }
        
        response_html = _file_browser_helper.build_oob_response(
            '<div class="alert alert-info">🧪 Test OOB refresh completed!</div>', 
            oob_updates
        )
        
        logger.info(f"🧪 TEST: Generated response HTML length: {len(response_html)}")
        return HttpResponse(response_html)
        
    except Exception as e:
        logger.error(f"🧪 TEST: Error during OOB refresh test: {e}", exc_info=True)
        return HttpResponse(f'<div class="alert alert-error">Test failed: {str(e)}</div>')


@require_http_methods(["GET"])
@general_login_required
def file_browser_refresh(request, organization):
    """
    Return OOB update for the file browser content.
    
    This endpoint is triggered after upload completion to refresh
    the file browser without a full page reload.
    
    Uses the inherited template helper methods for consistency.
    """
    if not organization:
        logger.warning("No organization provided for file browser refresh")
        return HttpResponse("<!-- No organization specified -->")
    
    logger.info(f"🔄 OOB: Refreshing file browser for organization: {organization}")
    
    try:
        # Use the mixin method to render the template
        file_browser_html = _file_browser_helper.render_organization_files_template(
            organization, request
        )
        
        # Build OOB response using inherited method
        oob_updates = {
            'file-browser-content': file_browser_html
        }
        
        response_html = _file_browser_helper.build_oob_response("", oob_updates)
        
        logger.info(f"✅ OOB: File browser refreshed for organization {organization}")
        
        return HttpResponse(response_html)
        
    except Exception as e:
        logger.error(f"❌ OOB: Error refreshing file browser for {organization}: {str(e)}")
        return HttpResponse("<!-- Error refreshing file browser -->")


@require_http_methods(["POST"])
@general_login_required 
def trigger_file_browser_refresh(request):
    """
    Endpoint that can be called to trigger a file browser refresh.
    
    This is useful for upload completion handlers to trigger via HX-Trigger.
    Uses the inherited add_workspace_update_trigger pattern for consistency.
    """
    organization = request.POST.get('organization')
    
    if not organization:
        return HttpResponse("<!-- No organization specified -->")
    
    logger.info(f"🔔 TRIGGER: File browser refresh triggered for organization: {organization}")
    
    # Use the inherited trigger pattern with custom trigger data
    triggers = {
        "refreshFileBrowser": organization
    }
    
    # Create response using inherited method pattern
    response = HttpResponse("<!-- Refresh triggered -->")
    response['HX-Trigger'] = json.dumps(triggers)
    
    return response