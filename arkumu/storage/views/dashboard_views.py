import json
import logging
import os
import time
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.views import View
from arkumu.storage.services.bucket_service import BucketService
from arkumu.storage.services.upload.upload_utils import normalize_s3_key
from django.http import HttpResponse, JsonResponse
from django.views.decorators.http import require_http_methods
from django.template.loader import render_to_string
from arkumu.users.mixins import GeneralLoginRequiredMixin, general_login_required
from arkumu.common.mixins.base_coordinator import BaseCoordinatorMixin
from arkumu.metadata.views.csv_mapping.mixins.template_helpers import CSVMappingTemplateHelperMixin

logger = logging.getLogger(__name__)


@general_login_required
def storage_dashboard(request):
    """
    Main storage dashboard - redirects to the archivist dashboard 
    which is the primary interface for organization bucket management.
    """
    from django.shortcuts import redirect
    return redirect('storage:archivist_dashboard')


class ArchivistDashboardView(GeneralLoginRequiredMixin, BaseCoordinatorMixin, CSVMappingTemplateHelperMixin, View):
    """
    Dashboard for archivists to manage organization buckets.
    
    Now uses BaseCoordinatorMixin for cross-view session persistence with 
    CSV mapping editor and Metadata Ingestion.
    """
    
    def render_organization_selectors(self, request, bucket_service, organizations, selected_org_slug):
        """Render organization selector and file browser content for OOB updates."""
        context = {
            'organizations': organizations,
            'selected_org_slug': selected_org_slug
        }

        refresh_button_html = render_to_string(
            'dashboard/partials/file_browser_refresh_button.html',
            context,
            request=request
        )

        bucket_size_action_html = render_to_string(
            'dashboard/partials/bucket_size_action.html',
            context,
            request=request
        )

        upload_selector = render_to_string(
            'dashboard/partials/upload_org_selector.html', 
            context,
            request=request  # Pass request to get CSRF token
        )
        
        # Render file browser content
        if selected_org_slug:
            # Use the same method as the working organization browser
            bucket_name = bucket_service.get_organization_bucket(selected_org_slug)
            contents = bucket_service.list_bucket_contents(bucket_name, '')
            
            # Add file counts for data and metadata folders
            for item in contents:
                if item['type'] == 'folder' and item['name'] in ['data', 'metadata']:
                    item['file_count'] = bucket_service.count_files_in_folder(bucket_name, item['path'])
            
            logger.info(f"Dashboard view: Loading files for {selected_org_slug}, bucket: {bucket_name}, found {len(contents)} items")
            
            file_browser_context = {
                'organization': selected_org_slug,
                'bucket_name': bucket_name,
                'contents': contents,
                'selected_org_slug': selected_org_slug,
                'prefix': ''
            }
            file_browser_content = render_to_string(
                'dashboard/organization_files_partial.html',
                file_browser_context,
                request=request  # Pass request to get CSRF token
            )
        else:
            # Empty state
            file_browser_content = '''
                <div class="alert alert-info">
                    <svg xmlns="http://www.w3.org/2000/svg" class="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                    </svg>
                    <span>Select an organization to browse its S3 files and folders</span>
                </div>
            '''
        
        # Render S3 browser title
        s3_browser_title = render_to_string(
            'dashboard/partials/s3_browser_title.html',
            {'selected_org_slug': selected_org_slug},
            request=request
        )
        
        # Render bucket size container update
        if selected_org_slug:
            bucket_size_html = f'''
                <div hx-get="/storage/dashboard/bucket-size/{selected_org_slug}/"
                     hx-trigger="load"
                     hx-swap="innerHTML"
                     class="min-h-[60px] flex items-center justify-center">
                    <!-- Loading indicator -->
                    <div class="flex items-center gap-2 text-base-content/50">
                        <div class="animate-spin rounded-full h-4 w-4 border-b-2 border-primary"></div>
                        <span class="text-sm">Calculating size...</span>
                    </div>
                </div>
            '''
        else:
            bucket_size_html = '''
                <div class="stats bg-base-200 shadow-inner opacity-50">
                    <div class="stat">
                        <div class="stat-figure text-secondary">
                            <svg xmlns="http://www.w3.org/2000/svg" class="h-8 w-8" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 8a2 2 0 012-2h10a2 2 0 012 2v10a2 2 0 01-2 2H7a2 2 0 01-2-2V8z" />
                            </svg>
                        </div>
                        <div class="stat-title text-xs">Bucket Size</div>
                        <div class="stat-value text-lg">---</div>
                        <div class="stat-desc">Select organization</div>
                    </div>
                </div>
            '''
        
        return {
            'upload-org-selector': upload_selector,
            'file-browser-content': file_browser_content,
            's3-browser-title': s3_browser_title,
            'bucket-size-container': bucket_size_html,
            'refresh-button-container': refresh_button_html,
            'bucket-size-action-container': bucket_size_action_html
        }
    
    def get(self, request):
        # Log and ignore GET requests with sensitive data in query params  
        if any(param in request.GET for param in ['csrfmiddlewaretoken', 'files']):
            logger.warning(f"Dashboard accessed with sensitive URL parameters, ignoring them")
        
        return self._handle_dashboard_request(request)
    
    def post(self, request):
        # Handle form submissions securely via POST
        return self._handle_dashboard_request(request)
    
    def _handle_dashboard_request(self, request):
        """Handle GET requests for the archivist dashboard."""
        logger.info(f"Archivist dashboard view called. Request method: {request.method}, User: {request.user}")
        try:
            logger.info("Attempting to initialize BucketService...")
            bucket_service = BucketService()
            logger.info("BucketService initialized.")
            
            # Handle organization parameter from URL (support both 'org' and 'organization')
            org_param = request.GET.get('org') or request.GET.get('organization')
            if org_param:
                # Set organization using BaseCoordinatorMixin
                self.set_current_organization(request, org_param)
            
            # Get current organization using BaseCoordinatorMixin
            # This will persist across page navigation
            current_org = self.get_current_organization(request)
            selected_org_slug = current_org['code'] if current_org else None
            
            # If no organization is selected but we have organizations available, 
            # don't auto-select - let user choose explicitly
            if not selected_org_slug and not org_param:
                logger.info("No organization selected in session or URL")
            
            logger.info("Attempting to get available organizations...")
            # Get organizations from database, auto-create if none exist
            from arkumu.users.models import Organization
            from arkumu.users.utils import ensure_predefined_organizations
            
            organizations = list(Organization.objects.filter(is_active=True))
            
            # Auto-populate organizations if none exist
            if not organizations:
                logger.info("No organizations found, creating predefined ones...")
                ensure_predefined_organizations()
                organizations = list(Organization.objects.filter(is_active=True))
            
            logger.info(f"Got {len(organizations)} available organizations from database.")
            
            organization_count = len(organizations)
            
            total_files_display = "N/A"
            storage_used_display = "N/A"
            
            organization_structure = None
            selected_org_data = None
            contents = []  # Initialize contents for the template

            if selected_org_slug:
                logger.info(f"Selected organization slug: {selected_org_slug}")
                try:
                    selected_org_data = next((org for org in organizations if org.code == selected_org_slug), None)

                    if selected_org_data:
                        logger.info(f"Fetching structure for existing org: {selected_org_slug}")
                        bucket_name = bucket_service.get_organization_bucket(selected_org_slug)
                        # Get bucket contents for the file browser
                        contents = bucket_service.list_bucket_contents(bucket_name, '')
                        
                        # Add file counts for data and metadata folders (same as dropdown change logic)
                        for item in contents:
                            if item['type'] == 'folder' and item['name'] in ['data', 'metadata']:
                                item['file_count'] = bucket_service.count_files_in_folder(bucket_name, item['path'])
                        
                        logger.info(f"Loaded {len(contents)} items for {selected_org_slug}")
                        # Also get root level items if needed for other purposes
                        organization_structure = bucket_service.get_root_level_items(bucket_name)
                        current_time = time.time()
                        logger.info(f"Structure fetched for {selected_org_slug} at {current_time:.3f}")
                        logger.info(f"⏱️ TIMING: About to initialize services for file operations...")
                    else:
                        logger.warning(f"Requested organization '{selected_org_slug}' not found in available organizations.")

                except Exception as e:
                    logger.error(f"Error loading organization structure for {selected_org_slug}: {str(e)}")
            
            logger.info("Preparing to render archivist_dashboard.html")
            
            # Check if this is an HTMX organization change request
            if request.headers.get('HX-Request') and org_param:
                # For HTMX organization changes, return OOB updates to sync both selectors
                logger.info(f"HTMX organization change detected: {org_param}")
                
                # Get OOB updates for organization selectors and file browser
                oob_updates = self.render_organization_selectors(request, bucket_service, organizations, selected_org_slug)
                
                # Build response with just the OOB updates (no main content needed)
                response_html = self.build_oob_response('', oob_updates)
                
                # Return response with out-of-band updates
                response = HttpResponse(response_html)
                return response
            
            # Regular non-HTMX request
            return render(request, "dashboard/archivist_dashboard.html", {
                "organizations": organizations,
                "organization_count": organization_count,
                "total_files_display": total_files_display,
                "storage_used_display": storage_used_display,
                "organization_structure": organization_structure,
                "selected_org_data": selected_org_data, 
                "selected_org_slug": selected_org_slug,
                "contents": contents,  # Pass contents for the file browser
                "organization": selected_org_slug,  # Pass organization for the template
                "bucket_name": bucket_service.get_organization_bucket(selected_org_slug) if selected_org_slug else None,
                "prefix": ""
            })
        except Exception as e:
            logger.exception(f"Outer exception in archivist_dashboard: {str(e)}")
            return render(request, "dashboard/archivist_dashboard.html", {
                "error": f"An error occurred while loading the dashboard: {str(e)}",
                "organizations": [],
                "organization_count": 0,
                "total_files_display": "Error",
                "storage_used_display": "Error",
                "selected_org_slug": selected_org_slug if 'selected_org_slug' in locals() else request.GET.get('org') 
            })


@general_login_required
def archivist_dashboard(request):
    """
    Function-based wrapper for ArchivistDashboardView (for URL compatibility).
    """
    view = ArchivistDashboardView()
    return view.get(request)


@general_login_required
def load_folder_contents(request, bucket_type, folder_path):
    """
    Load contents of a specific folder when expanded.
    """
    bucket_service = BucketService()
    bucket = bucket_service.ingest_bucket if bucket_type == 'ingest' else bucket_service.production_bucket
    
    try:
        # Clean up the folder path to handle double slashes
        folder_path = folder_path.replace('//', '/')
        logger.info(f"Loading folder contents for {bucket_type} bucket, path: {folder_path}")
        
        # Get folder contents
        folder_contents = bucket_service.get_folder_contents(bucket, folder_path)
        logger.info(f"Folder contents for {folder_path}: {folder_contents}")
        
    except Exception as e:
        logger.error(f"Error loading folder contents for {folder_path}: {str(e)}")
        # Return empty list on error
        folder_contents = []
    
    return render(
        request,
        "dashboard/folder_contents_partial.html",
        {
            "folder_contents": folder_contents,
            "bucket_type": bucket_type,
            "folder_path": folder_path,
        },
    )


@general_login_required
def dashboard_content(request, bucket_type):
    """
    Return only the structure content for a specific bucket type.
    This is used for AJAX/HTMX refreshes of just one section of the dashboard.
    
    Args:
        bucket_type (str): Either "ingest" or "production"
        
    Returns:
        Rendered partial template with the requested bucket structure
    """
    try:
        bucket_service = BucketService()
        
        if bucket_type == "ingest":
            structure = bucket_service.get_root_level_items(bucket_service.ingest_bucket)
        elif bucket_type == "production":
            structure = bucket_service.get_root_level_items(bucket_service.production_bucket)
        else:
            return HttpResponse("Invalid bucket type", status=400)
            
        logger.info(f"Refreshing {bucket_type} structure with {len(structure.get('children', []))} items")
        
        # Render just the folder structure partial
        return render(
            request,
            "dashboard/folder_structure_partial.html",
            {"structure": structure, "bucket_type": bucket_type}
        )
    except Exception as e:
        logger.exception(f"Error loading dashboard content for {bucket_type}: {str(e)}")
        return HttpResponse(f"Error: {str(e)}", status=500)


@require_http_methods(["POST"])
@general_login_required
def view_organization_bucket(request):
    """
    Handle organization bucket viewing, creating the bucket if it doesn't exist.
    """
    try:
        organization = request.POST.get('organization')
        if not organization:
            return JsonResponse({
                "success": False,
                "error": "Organization parameter is required"
            }, status=400)
        
        bucket_service = BucketService()
        
        # Ensure the organization bucket exists
        result = bucket_service.ensure_organization_bucket_exists(organization)
        
        if result['success']:
            # Get the bucket structure
            bucket_name = result['bucket_name']
            try:
                # Use list_bucket_contents instead of get_root_level_items for consistency
                contents = bucket_service.list_bucket_contents(bucket_name, '')
                
                # Return the HTML structure for the organization bucket
                from django.template.loader import render_to_string
                html_content = render_to_string(
                    "dashboard/organization_files_partial.html",
                    {
                        "organization": organization,
                        "bucket_name": bucket_name,
                        "contents": contents,
                        "prefix": ""
                    }
                )
                
                return JsonResponse({
                    "success": True,
                    "bucket_name": bucket_name,
                    "organization": organization,
                    "html_content": html_content,
                    "message": result.get('message', f"Organization bucket '{bucket_name}' is ready"),
                    "redirect_url": f"/storage/organizations/{organization}/"
                })
                
            except Exception as e:
                logger.error(f"Error getting organization structure: {str(e)}")
                return JsonResponse({
                    "success": False,
                    "error": f"Bucket created but error loading contents: {str(e)}"
                }, status=500)
        else:
            return JsonResponse({
                "success": False,
                "error": result.get('error', 'Unknown error creating organization bucket')
            }, status=500)
            
    except Exception as e:
        logger.exception(f"Error in view_organization_bucket: {str(e)}")
        return JsonResponse({
            "success": False,
            "error": str(e)
        }, status=500)


@general_login_required
def upload_mode_toggle(request):
    """
    HTMX endpoint for toggling upload mode using out-of-band swaps.
    Returns HTML fragments that replace the upload input area - no JavaScript needed!
    """
    from django.template.loader import render_to_string
    
    logger.info(f"⏱️ UPLOAD MODE TOGGLE: Received at {time.strftime('%H:%M:%S', time.localtime())}.{int((time.time() % 1) * 1000):03d}")
    
    mode = request.GET.get('mode', 'files')
    
    # Prepare context for template
    context = {
        'mode': mode,
        'is_folder_mode': mode == 'folder',
    }
    
    # Render the upload input template
    upload_input_html = render_to_string(
        'dashboard/partials/upload_input.html',
        context,
        request=request
    )
    
    # Return with out-of-band swap
    return HttpResponse(upload_input_html)


@require_http_methods(["GET"])
@general_login_required
def refresh_file_browser(request, organization):
    """
    Refresh file browser with retry logic and file existence verification.
    
    This handles the timing issue where files uploaded directly to S3 might not
    be immediately visible due to eventual consistency. It can verify that
    specific expected files exist before returning success.
    """
    logger.info(f"🔄 REFRESH: Refreshing file browser for organization: {organization}")
    
    # Get retry parameters and expected files
    retry_count = int(request.GET.get('retry', 0))
    max_retries = 3
    
    # Extract expected files from query parameters
    expected_files = []
    for key, value in request.GET.items():
        if key.startswith('expected_'):
            expected_files.append(value)

        if expected_files:
            expected_count = len(expected_files)
            logger.info("📋 REFRESH: Looking for %d expected files", expected_count)
            logger.debug("📋 REFRESH expected files: %s", expected_files)
    
    try:
        # Clear all possible cache keys for this organization
        from django.core.cache import cache
        cache_patterns = [
            f"bucket_contents_{organization}_",
            f"bucket_contents_{bucket_name}_" if 'bucket_name' in locals() else None,
            f"file_count_{organization}_",
            f"file_count_{organization}_data_",
            f"file_count_{organization}_metadata_",
        ]
        
        # Clear cache keys that exist
        for pattern in cache_patterns:
            if pattern:
                cache.delete(pattern)
                logger.info(f"🗑️ REFRESH: Cleared cache key: {pattern}")
        
        bucket_service = BucketService()
        bucket_name = bucket_service.get_organization_bucket(organization)
        
        # Clear bucket-specific cache too
        cache.delete(f"bucket_contents_{bucket_name}_")
        logger.info(f"🗑️ REFRESH: Cleared cache key: bucket_contents_{bucket_name}_")
        
        # Always use force_fresh to bypass cache
        contents = bucket_service.list_bucket_contents(bucket_name, '', force_fresh=True)
        
        missing_files = []

        # If we have expected files, verify they exist
        if expected_files:
            # Get all file names from the listing (including in subfolders)
            all_files = []
            for item in contents:
                if item['type'] == 'file':
                    all_files.append(item['name'])
                elif item['type'] == 'folder':
                    # Check subfolders for files
                    try:
                        subfolder_contents = bucket_service.list_bucket_contents(
                            bucket_name, item['path'], force_fresh=True
                        )
                        for subitem in subfolder_contents:
                            if subitem['type'] == 'file':
                                all_files.append(subitem['name'])
                    except:
                        pass  # Continue if subfolder check fails
            
            available_names = set(all_files)

            def _matches_available(name: str) -> bool:
                # Check if the expected filename (after S3 normalization) exists in the available files
                normalized_expected = normalize_s3_key(name)
                return normalized_expected in available_names

            missing_files = [f for f in expected_files if not _matches_available(f)]
            retry_payload = None
            exhausted_attempts = False

            if missing_files:
                missing_preview = ', '.join(missing_files[:5])
                if len(missing_files) > 5:
                    missing_preview += ", …"
                logger.debug(
                    "📋 REFRESH missing %d file(s) (sample: %s)",
                    len(missing_files),
                    missing_preview,
                )

            if missing_files and retry_count < max_retries:
                retry_delay = (retry_count + 1) * 1000  # 1s, 2s, 3s delays
                logger.info(
                    "⏳ REFRESH: Missing files %s, retrying in %sms (attempt %s/%s)",
                    missing_files,
                    retry_delay,
                    retry_count + 1,
                    max_retries,
                )

                params = request.GET.copy()
                params['retry'] = retry_count + 1
                retry_url = f"/storage/dashboard/refresh/{organization}/?{params.urlencode()}"

                retry_payload = {
                    'retry_url': retry_url,
                    'delay': retry_delay,
                    'missing_files': missing_files[:3],
                    'retry': retry_count + 1,
                    'max_retries': max_retries + 1,
                }
            elif missing_files:
                exhausted_attempts = True
                logger.warning("⚠️ REFRESH: Files still missing after max retries: %s", missing_files)
            else:
                missing_files = []
                logger.info(f"✅ REFRESH: All expected files found: {expected_files}")
        
            if retry_payload:
                response = HttpResponse(status=204)
                response['HX-Reswap'] = 'none'
                response['HX-Trigger'] = json.dumps({'upload-refresh-retry': retry_payload})
                return response

        # Add file counts for data and metadata folders
        for item in contents:
            if item['type'] == 'folder' and item['name'] in ['data', 'metadata']:
                item['file_count'] = bucket_service.count_files_in_folder(bucket_name, item['path'], force_fresh=True)

        logger.info(f"✅ REFRESH: Found {len(contents)} items for {organization}")
        
        # Render the organization files partial
        context = {
            'organization': organization,
            'bucket_name': bucket_name,
            'contents': contents,
            'selected_org_slug': organization,
            'prefix': ''
        }
        
        html = render_to_string(
            'dashboard/organization_files_partial.html',
            context,
            request=request
        )

        response = HttpResponse(html)

        if expected_files and missing_files:
            response['HX-Trigger'] = json.dumps({
                'upload-refresh-missing': {
                    'missing_files': missing_files[:3],
                    'total_missing': len(missing_files)
                }
            })
        return response
        
    except Exception as e:
        logger.error(f"❌ REFRESH: Error refreshing file browser for {organization}: {str(e)}")
        
        # If we haven't exceeded max retries, instruct frontend to retry silently
        if retry_count < max_retries:
            retry_delay = (retry_count + 1) * 1000  # 1s, 2s, 3s delays
            logger.info(
                "🔄 REFRESH: Retrying due to error in %sms (attempt %s/%s)",
                retry_delay,
                retry_count + 1,
                max_retries,
            )

            params = request.GET.copy()
            params['retry'] = retry_count + 1
            retry_url = f"/storage/dashboard/refresh/{organization}/?{params.urlencode()}"

            response = HttpResponse(status=204)
            response['HX-Reswap'] = 'none'
            response['HX-Trigger'] = json.dumps({
                'upload-refresh-retry': {
                    'retry_url': retry_url,
                    'delay': retry_delay,
                    'missing_files': [],
                    'retry': retry_count + 1,
                    'max_retries': max_retries + 1,
                    'reason': 'error'
                },
                'upload-refresh-warning': {
                    'message': 'Temporary issue checking files; retrying…',
                    'attempt': retry_count + 1,
                    'max_attempts': max_retries + 1
                }
            })
            return response
        else:
            # Max retries exceeded
            response = HttpResponse(status=204)
            response['HX-Reswap'] = 'none'
            response['HX-Trigger'] = json.dumps({
                'upload-refresh-error': {
                    'message': f'Unable to refresh files: {str(e)}'
                }
            })
            return response


@require_http_methods(["GET"])
@general_login_required
def dismiss_message(request):
    """
    HTMX endpoint for dismissing upload success messages.
    Returns empty response to remove the element from DOM.
    """
    # Return empty response - this will cause HTMX to remove the target element
    return HttpResponse('')


@require_http_methods(["GET"])
@general_login_required
def bucket_size_info(request, organization):
    """
    HTMX endpoint for getting bucket size information.
    Calculates total bucket size and returns formatted display.
    
    Args:
        organization (str): Organization ID (e.g., 'fuk', 'khm', 'det', etc.)
    
    Returns:
        Rendered partial template with bucket size information
    """
    logger.info(f"📊 BUCKET SIZE: Getting size info for organization: {organization}")
    
    try:
        bucket_service = BucketService()
        
        # Get force_fresh parameter from query
        force_fresh = request.GET.get('force_fresh', 'false').lower() == 'true'
        
        # Calculate bucket size (this method includes caching)
        size_result = bucket_service.get_organization_bucket_size(organization, force_fresh=force_fresh)
        
        if size_result['success']:
            logger.info(f"📊 BUCKET SIZE: {organization} = {size_result['total_size_formatted']} ({size_result['object_count']} objects)")
            
            # Render the bucket size partial template
            context = {
                'organization': organization,
                'bucket_name': size_result['bucket_name'],
                'total_size': size_result['total_size'],
                'total_size_formatted': size_result['total_size_formatted'],
                'object_count': size_result['object_count'],
                'calculation_duration': size_result.get('calculation_duration', 0),
                'success': True
            }
            
            html = render_to_string(
                'dashboard/partials/bucket_size_info.html',
                context,
                request=request
            )
            
            return HttpResponse(html)
        else:
            # Error case
            logger.error(f"❌ BUCKET SIZE: Error for {organization}: {size_result.get('error', 'Unknown error')}")
            
            context = {
                'organization': organization,
                'error': size_result.get('error', 'Unknown error'),
                'success': False
            }
            
            html = render_to_string(
                'dashboard/partials/bucket_size_info.html',
                context,
                request=request
            )
            
            return HttpResponse(html)
            
    except Exception as e:
        logger.exception(f"❌ BUCKET SIZE: Unexpected error for {organization}: {str(e)}")
        
        context = {
            'organization': organization,
            'error': f"Unexpected error: {str(e)}",
            'success': False
        }
        
        html = render_to_string(
            'dashboard/partials/bucket_size_info.html',
            context,
            request=request
        )
        
        return HttpResponse(html)




@require_http_methods(["GET"])
@general_login_required
def export_successful_imports_csv(request, organization: str):
    """
    Download a CSV of all files in the S3 bucket with checksums.
    Uses Huey background task for non-blocking processing.
    """
    try:
        from arkumu.storage.tasks import export_successful_imports_task
        
        logger.info(f"📊 CSV EXPORT: Starting background export for organization '{organization}' (user: {request.user.id})")
        
        # Start background task and wait for result
        task_result = export_successful_imports_task(organization, request.user.id)
        result = task_result(blocking=True)
        
        # Check if result is a dict (success) or string (error)
        if isinstance(result, str):
            # Task failed and returned error message
            return HttpResponse(f"Export failed: {result}", status=500)
        elif not result.get("success"):
            return HttpResponse(f"Export failed: {result.get('error', 'Unknown error')}", status=500)

        filename = result.get("filename", f"s3_export_{organization}.csv")
        content = result.get("content", b"")
        
        response = HttpResponse(content, content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = f"attachment; filename=\"{filename}\""
        
        logger.info(f"✅ CSV EXPORT: Generated export {filename} with {result.get('count', 0)} files for user {request.user.id}")
        return response
        
    except Exception as e:
        logger.exception(f"❌ EXPORT CSV: Unexpected error for {organization}: {str(e)}")
        return HttpResponse(f"Unexpected error: {str(e)}", status=500)

 
