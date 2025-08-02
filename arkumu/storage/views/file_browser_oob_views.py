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
        
        Consolidates the repeated pattern:
        - Get bucket service and contents
        - Prepare context
        - Render template
        """
        try:
            from arkumu.storage.services.bucket_service import BucketService
            
            bucket_service = BucketService()
            bucket_name = bucket_service.get_organization_bucket(organization)
            contents = bucket_service.list_bucket_contents(bucket_name, '')
            
            context = {
                'organization': organization,
                'bucket_name': bucket_name,
                'contents': contents,
                'selected_org_slug': organization,
                'prefix': ''
            }
            
            return render_to_string(
                'dashboard/organization_files_partial.html',
                context,
                request=request
            )
        except Exception as e:
            logger.error(f"Error rendering organization files template: {e}")
            return f'<div class="error">Error loading files: {str(e)}</div>'


# Helper instance for functions that can't inherit from mixin
_file_browser_helper = FileBrowserOOBMixin()


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