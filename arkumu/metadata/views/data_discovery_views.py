from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse, HttpResponse, HttpResponseRedirect
from django.views import View
from django.views.decorators.http import require_http_methods
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.decorators import login_required
from django.db.models import Q, Count, Case, When, BooleanField
from django.utils.decorators import method_decorator
from django.core.paginator import Paginator
from django.template.loader import render_to_string
from django.urls import reverse
import json
import logging
from arkumu.users.mixins import general_login_required

from arkumu.storage.models import S3FileObject, UploadSession
from arkumu.metadata.models import Resource
from arkumu.metadata.services.metatdata_s3_mapping.map_resources_to_files import FileResourceMatcherService
from arkumu.storage.services.bucket_service import BucketService
from arkumu.storage.services.s3_sync_service import S3SyncService
from arkumu.common.mixins.base_coordinator import BaseCoordinatorMixin
from arkumu.metadata.views.csv_mapping.mixins.template_helpers import CSVMappingTemplateHelperMixin

logger = logging.getLogger(__name__)




class DataDiscoveryView(LoginRequiredMixin, BaseCoordinatorMixin, CSVMappingTemplateHelperMixin, View):
    """Main data discovery interface showing S3 files and their linking status."""
    template_name = 'data_discovery.html'

    def get(self, request, *args, **kwargs):
        # Get filters from request - check for organization change first
        requested_organization = request.GET.get('org_filter', '') or request.GET.get('org', '')
        status_filter = request.GET.get('status_filter', '')
        
        # Get available organizations from BucketService first
        bucket_service = BucketService()
        available_organizations = bucket_service.get_predefined_organizations()
        
        # Handle organization state using BaseCoordinatorMixin
        current_org = self.get_current_organization(request)
        
        # If organization is requested via URL parameter, update the session state
        if requested_organization:
            if not current_org or current_org.get('code') != requested_organization:
                # Update to new organization
                self.set_current_organization(request, requested_organization)
                current_org = self.get_current_organization(request)
        
        # Set default organization if none selected and organizations available
        if not current_org and available_organizations:
            self.set_current_organization(request, available_organizations[0])
            current_org = self.get_current_organization(request)
        
        # Use the organization code from session
        organization = current_org.get('code') if current_org else ''
        
        logger.info(f"DataDiscoveryView filters: org='{organization}', status='{status_filter}'")
        
        # Start with all S3 files, then filter by organization (required)
        s3_files = S3FileObject.objects.all().select_related(
            'related_resource', 'session', 'session__user'
        ).annotate(
            is_linked=Case(
                When(related_resource__isnull=False, then=True),
                default=False,
                output_field=BooleanField()
            )
        )
        
        logger.info(f"Initial S3 files count: {s3_files.count()}")
        
        # Log sample S3 keys to understand the bucket structure
        if s3_files.count() > 0:
            sample_all_keys = list(S3FileObject.objects.all().values_list('s3_key', flat=True)[:20])
            logger.info(f"Sample S3 keys from database (first 20): {sample_all_keys}")
            
            # Show unique bucket prefixes and session buckets
            all_keys = S3FileObject.objects.all().values_list('s3_key', flat=True)
            unique_prefixes = set()
            for key in all_keys:
                if '/' in key:
                    prefix = key.split('/')[0]
                    unique_prefixes.add(prefix)
                else:
                    unique_prefixes.add(key)
            logger.info(f"Unique s3_key prefixes found: {sorted(list(unique_prefixes))}")
            
            # Show session buckets
            session_buckets = set(S3FileObject.objects.values_list('session__s3_bucket', flat=True).distinct())
            logger.info(f"Session buckets found: {sorted(list(session_buckets))}")
        
        # Filter by organization bucket (required)
        if organization:
            s3_files = s3_files.filter(session__s3_bucket=organization)
            logger.info(f"After organization filter '{organization}': {s3_files.count()} files")
        
        # Filter by data folder within bucket (default behavior)
        s3_files = s3_files.filter(s3_key__startswith='data/')
        logger.info(f"After data folder filter: {s3_files.count()} files")
        
        # Filter by link status if specified
        if status_filter == 'linked':
            s3_files = s3_files.filter(related_resource__isnull=False)
            logger.info(f"After status filter 'linked': {s3_files.count()} files")
        elif status_filter == 'unlinked':
            s3_files = s3_files.filter(related_resource__isnull=True)
            logger.info(f"After status filter 'unlinked': {s3_files.count()} files")
        
        s3_files = s3_files.order_by('s3_key')

        # Log some sample s3_keys to see the filtered data
        sample_keys = list(s3_files.values_list('s3_key', flat=True)[:5])
        logger.info(f"Sample S3 keys after filtering: {sample_keys}")

        # Add pagination
        page_number = request.GET.get('page', 1)
        paginator = Paginator(s3_files, 50)  # Show 50 files per page
        page_obj = paginator.get_page(page_number)

        logger.info(f"Pagination: page {page_number}, total pages: {paginator.num_pages}, current page items: {len(page_obj)}")

        # Group paginated files by bucket (get bucket from session)
        files_by_bucket = {}
        buckets = set()
        
        for file in page_obj:
            # Get bucket name from session
            bucket_name = file.session.s3_bucket if file.session and file.session.s3_bucket else 'unknown'
            
            buckets.add(bucket_name)
            
            if bucket_name not in files_by_bucket:
                files_by_bucket[bucket_name] = []
            files_by_bucket[bucket_name].append(file)

        logger.info(f"Files grouped by bucket: {[(k, len(v)) for k, v in files_by_bucket.items()]}")

        # Get statistics for all files (not just current page)
        total_files = s3_files.count()
        linked_files = s3_files.filter(related_resource__isnull=False).count()
        unlinked_files = total_files - linked_files

        logger.info(f"Statistics: total={total_files}, linked={linked_files}, unlinked={unlinked_files}")

        # Build context using BaseCoordinatorMixin organization context
        org_context = self.get_organization_context(request)
        
        # Get select all state from session
        session_key = f'select_all_{organization}' if organization else 'select_all_global'
        select_all_checked = request.session.get(session_key, False)
        
        context = {
            'files_by_bucket': files_by_bucket,
            'available_organizations': available_organizations,
            'selected_organization': organization,
            'selected_status': status_filter,
            'page_obj': page_obj,
            'total_files': total_files,
            'linked_files': linked_files,
            'unlinked_files': unlinked_files,
            'link_percentage': round((linked_files / total_files * 100) if total_files > 0 else 0, 1),
            'select_all_checked': select_all_checked,
            # Add organization context for consistency with other views
            **org_context
        }

        # Return just the files container for HTMX requests
        if request.headers.get('HX-Request'):
            return render(request, 'partials/files_container.html', context)
        
        return render(request, self.template_name, context)



@require_http_methods(["GET"])
@general_login_required
def search_resources(request):
    """Search for resources that could be linked to files."""
    query = request.GET.get('q', '').strip()
    
    if not query or len(query) < 2:
        return render(request, 'partials/search_results.html', {
            'resources': [],
            'query': query
        })

    # Search resources by value (case-insensitive)
    resources = Resource.objects.filter(
        Q(value__icontains=query) | Q(uri__icontains=query)
    )[:20]  # Limit results

    return render(request, 'partials/search_results.html', {
        'resources': resources,
        'query': query
    })



@require_http_methods(["POST"])
@general_login_required
def link_file_to_resource(request):
    """Link a single file to a resource."""
    try:
        # Handle both JSON and form data
        if request.content_type == 'application/json':
            data = json.loads(request.body)
        else:
            data = request.POST
            
        file_id = data.get('file_id')
        resource_id = data.get('resource_id')

        if not file_id or not resource_id:
            if request.headers.get('HX-Request'):
                return render(request, 'partials/toast.html', {
                    'message': 'Missing file or resource information',
                    'type': 'error'
                })
            return HttpResponse("Missing file or resource information", status=400)

        # Get the objects
        s3_file = get_object_or_404(S3FileObject, id=file_id)
        resource = get_object_or_404(Resource, id=resource_id)

        # Link them
        s3_file.related_resource = resource
        s3_file.save()

        # Return updated files list for HTMX or redirect for regular requests
        if request.headers.get('HX-Request'):
            return _get_files_list_response(request)
        else:
            return HttpResponseRedirect(reverse('metadata:data_discovery'))

    except Exception as e:
        if request.headers.get('HX-Request'):
            return render(request, 'partials/toast.html', {
                'message': f'Error linking file: {str(e)}',
                'type': 'error'
            })
        return HttpResponse(f"Error linking file: {str(e)}", status=500)



@require_http_methods(["POST"])
@general_login_required
def batch_link_files(request):
    """Batch link multiple files using the automated service."""
    try:
        # Check if select all is enabled first (safety check)
        from arkumu.common.mixins.base_coordinator import BaseCoordinatorMixin
        coordinator = BaseCoordinatorMixin()
        current_org = coordinator.get_current_organization(request)
        organization = current_org.get('code') if current_org else ''
        
        session_key = f'select_all_{organization}' if organization else 'select_all_global'
        select_all_enabled = request.session.get(session_key, False)
        
        if not select_all_enabled:
            message = 'Batch linking is only available when "Select All" is enabled'
            logger.warning(f"Batch link blocked: Select All not enabled for org {organization}")
            if request.headers.get('HX-Request'):
                return render(request, 'partials/toast.html', {
                    'message': message,
                    'type': 'warning'
                })
            return HttpResponse(message, status=400)
        
        # Get selected file IDs from form data
        file_ids = request.POST.getlist('selected_files')
        
        logger.info(f"Batch link request received. Selected file IDs: {file_ids}")
        logger.info(f"Select all enabled: {select_all_enabled}, Organization: {organization}")

        if not file_ids:
            message = 'No files selected - this should not happen when Select All is enabled'
            logger.warning(f"Batch link failed: {message}")
            if request.headers.get('HX-Request'):
                return render(request, 'partials/toast.html', {
                    'message': message,
                    'type': 'warning'
                })
            return HttpResponse(message, status=400)

        # Get the queryset of selected files
        selected_files = S3FileObject.objects.filter(id__in=file_ids)
        
        # Use the same partial matching logic as manual search
        processed = 0
        linked = 0
        ambiguous = 0
        errors = 0
        
        for s3_file in selected_files:
            processed += 1
            try:
                # Use full filename including extension for search query
                query = s3_file.file_name
                
                # Use more precise endswith matching for batch operations
                matching_resources = Resource.objects.filter(
                    Q(value__iendswith=query) | Q(uri__iendswith=query)
                ).distinct()
                
                if matching_resources.count() == 1:
                    # Single match - link it
                    resource = matching_resources.first()
                    s3_file.related_resource = resource
                    s3_file.save()
                    linked += 1
                    logger.info(f"Linked {s3_file.file_name} to resource {resource.value}")
                elif matching_resources.count() > 1:
                    # Multiple matches - count as ambiguous but link to first one
                    resource = matching_resources.first()
                    s3_file.related_resource = resource
                    s3_file.save()
                    ambiguous += 1
                    logger.info(f"Ambiguous match for {s3_file.file_name}: {matching_resources.count()} resources found, linked to {resource.value}")
                else:
                    # No matches found
                    logger.info(f"No matching resources found for {s3_file.file_name} with query '{query}'")
                    
            except Exception as e:
                errors += 1
                logger.error(f"Error processing {s3_file.file_name}: {str(e)}")

        message = f'Batch processing complete. Processed: {processed}, Linked: {linked}, Ambiguous: {ambiguous}, Errors: {errors}'
        
        if request.headers.get('HX-Request'):
            # Clear select all state after batch operation
            from arkumu.common.mixins.base_coordinator import BaseCoordinatorMixin
            coordinator = BaseCoordinatorMixin()
            current_org = coordinator.get_current_organization(request)
            organization = current_org.get('code') if current_org else ''
            
            session_key = f'select_all_{organization}' if organization else 'select_all_global'
            request.session[session_key] = False
            request.session.modified = True
            
            # Use template helper for proper OOB updates (same approach as rescan and unlink)
            from django.template.loader import render_to_string
            
            # Render toast message for OOB update
            toast_html = render_to_string('partials/container_toast.html', {
                'message': message,
                'type': 'success'
            }, request=request)
            
            # Get updated files list using existing helper function
            files_response = _get_files_list_response(request)
            files_html = files_response.content.decode('utf-8')
            
            # Get updated batch buttons (since select_all state changed)
            batch_buttons_html = render_to_string('partials/batch_buttons.html', {
                'select_all_checked': False  # We cleared select_all state above
            }, request=request)
            
            # Build OOB updates manually to control swap methods
            oob_html = f'<div id="files-container" hx-swap-oob="innerHTML">{files_html}</div>'
            oob_html += f'<div id="toast-container" hx-swap-oob="beforeend">{toast_html}</div>'
            oob_html += f'<div id="batch-buttons-container" hx-swap-oob="innerHTML">{batch_buttons_html}</div>'
            
            return HttpResponse(oob_html)
        else:
            # For regular requests, redirect back to data discovery
            from django.contrib import messages
            messages.success(request, message)
            return HttpResponseRedirect(reverse('metadata:data_discovery'))

    except Exception as e:
        error_msg = f'Batch linking failed: {str(e)}'
        if request.headers.get('HX-Request'):
            return render(request, 'partials/toast.html', {
                'message': error_msg,
                'type': 'error'
            })
        return HttpResponse(error_msg, status=500)


@require_http_methods(["POST"])
@general_login_required
def batch_unlink_files(request):
    """Batch unlink multiple files from their resources."""
    try:
        # Check if select all is enabled first (safety check)
        from arkumu.common.mixins.base_coordinator import BaseCoordinatorMixin
        coordinator = BaseCoordinatorMixin()
        current_org = coordinator.get_current_organization(request)
        organization = current_org.get('code') if current_org else ''
        
        session_key = f'select_all_{organization}' if organization else 'select_all_global'
        select_all_enabled = request.session.get(session_key, False)
        
        if not select_all_enabled:
            message = 'Batch unlinking is only available when "Select All" is enabled'
            logger.warning(f"Batch unlink blocked: Select All not enabled for org {organization}")
            if request.headers.get('HX-Request'):
                return render(request, 'partials/toast.html', {
                    'message': message,
                    'type': 'warning'
                })
            return HttpResponse(message, status=400)
        
        # Get selected file IDs from form data
        file_ids = request.POST.getlist('selected_files')
        
        logger.info(f"Batch unlink request received. Selected file IDs: {file_ids}")
        logger.info(f"Select all enabled: {select_all_enabled}, Organization: {organization}")

        if not file_ids:
            message = 'No files selected - this should not happen when Select All is enabled'
            logger.warning(f"Batch unlink failed: {message}")
            if request.headers.get('HX-Request'):
                return render(request, 'partials/toast.html', {
                    'message': message,
                    'type': 'warning'
                })
            return HttpResponse(message, status=400)

        # Get the queryset of selected files
        selected_files = S3FileObject.objects.filter(id__in=file_ids)
        
        # Process files for unlinking
        processed = 0
        unlinked = 0
        errors = 0
        
        for s3_file in selected_files:
            processed += 1
            try:
                if s3_file.related_resource:
                    # Store resource info for logging
                    old_resource = s3_file.related_resource.value
                    # Unlink the file
                    s3_file.related_resource = None
                    s3_file.save()
                    unlinked += 1
                    logger.info(f"Unlinked {s3_file.file_name} from resource {old_resource}")
                else:
                    # File was already unlinked
                    logger.info(f"File {s3_file.file_name} was already unlinked")
                    
            except Exception as e:
                errors += 1
                logger.error(f"Error processing {s3_file.file_name}: {str(e)}")

        message = f'Batch unlinking complete. Processed: {processed}, Unlinked: {unlinked}, Errors: {errors}'
        
        if request.headers.get('HX-Request'):
            # Clear select all state after batch operation
            from arkumu.common.mixins.base_coordinator import BaseCoordinatorMixin
            coordinator = BaseCoordinatorMixin()
            current_org = coordinator.get_current_organization(request)
            organization = current_org.get('code') if current_org else ''
            
            session_key = f'select_all_{organization}' if organization else 'select_all_global'
            request.session[session_key] = False
            request.session.modified = True
            
            # Use template helper for proper OOB updates (same approach as rescan)
            from django.template.loader import render_to_string
            
            # Render toast message for OOB update
            toast_html = render_to_string('partials/container_toast.html', {
                'message': message,
                'type': 'success'
            }, request=request)
            
            # Get updated files list using existing helper function
            files_response = _get_files_list_response(request)
            files_html = files_response.content.decode('utf-8')
            
            # Get updated batch buttons (since select_all state changed)
            batch_buttons_html = render_to_string('partials/batch_buttons.html', {
                'select_all_checked': False  # We cleared select_all state above
            }, request=request)
            
            # Build OOB updates manually to control swap methods
            oob_html = f'<div id="files-container" hx-swap-oob="innerHTML">{files_html}</div>'
            oob_html += f'<div id="toast-container" hx-swap-oob="beforeend">{toast_html}</div>'
            oob_html += f'<div id="batch-buttons-container" hx-swap-oob="innerHTML">{batch_buttons_html}</div>'
            
            return HttpResponse(oob_html)
        else:
            # For regular requests, redirect back to data discovery
            from django.contrib import messages
            messages.success(request, message)
            return HttpResponseRedirect(reverse('metadata:data_discovery'))

    except Exception as e:
        error_msg = f'Batch unlinking failed: {str(e)}'
        if request.headers.get('HX-Request'):
            return render(request, 'partials/toast.html', {
                'message': error_msg,
                'type': 'error'
            })
        return HttpResponse(error_msg, status=500)



@require_http_methods(["POST"])  
@general_login_required
def unlink_file(request):
    """Unlink a file from its resource."""
    try:
        # Handle both JSON and form data
        if request.content_type == 'application/json':
            data = json.loads(request.body)
        else:
            data = request.POST
            
        file_id = data.get('file_id')

        if not file_id:
            message = 'Missing file information'
            if request.headers.get('HX-Request'):
                return render(request, 'partials/toast.html', {
                    'message': message,
                    'type': 'error'
                })
            return HttpResponse(message, status=400)

        s3_file = get_object_or_404(S3FileObject, id=file_id)
        
        # Store the old resource for the message
        old_resource = s3_file.related_resource.value if s3_file.related_resource else None
        
        # Unlink
        s3_file.related_resource = None
        s3_file.save()

        # Return updated files list for HTMX or redirect for regular requests
        if request.headers.get('HX-Request'):
            return _get_files_list_response(request)
        else:
            from django.contrib import messages
            messages.success(request, f'File unlinked from {old_resource}' if old_resource else 'File unlinked')
            return HttpResponseRedirect(reverse('metadata:data_discovery'))

    except Exception as e:
        error_msg = f'Error unlinking file: {str(e)}'
        if request.headers.get('HX-Request'):
            return render(request, 'partials/toast.html', {
                'message': error_msg,
                'type': 'error'
            })
        return HttpResponse(error_msg, status=500)



@require_http_methods(["POST"])
@general_login_required
def auto_link_all(request):
    """Automatically link all unlinked files."""
    try:
        # Get all unlinked files
        unlinked_files = S3FileObject.objects.filter(
            related_resource__isnull=True
        )
        
        if not unlinked_files.exists():
            message = 'No unlinked files found'
            if request.headers.get('HX-Request'):
                return render(request, 'partials/toast.html', {
                    'message': message,
                    'type': 'info'
                })
            from django.contrib import messages
            messages.info(request, message)
            return HttpResponseRedirect(reverse('metadata:data_discovery'))
        
        # Use the matching service for batch processing
        service = FileResourceMatcherService()
        processed, linked, ambiguous, errors = service.match_and_link_by_filename_to_resource_value(unlinked_files)

        message = f'Auto-linking complete. Processed: {processed}, Linked: {linked}, Ambiguous: {ambiguous}, Errors: {errors}'
        
        if request.headers.get('HX-Request'):
            # Return success response and refresh page
            response = HttpResponse()
            response['HX-Refresh'] = 'true'  # Tell HTMX to refresh the page
            
            return render(request, 'partials/toast.html', {
                'message': message,
                'type': 'success' if errors == 0 else 'warning'
            })
        else:
            from django.contrib import messages
            messages.success(request, message)
            return HttpResponseRedirect(reverse('metadata:data_discovery'))

    except Exception as e:
        error_msg = f'Auto-linking failed: {str(e)}'
        if request.headers.get('HX-Request'):
            return render(request, 'partials/toast.html', {
                'message': error_msg,
                'type': 'error'
            })
        return HttpResponse(error_msg, status=500)



@require_http_methods(["POST"])
@general_login_required
def rescan_s3_files(request):
    """Rescan S3 buckets for new files and sync them to the database."""
    try:
        # Initialize the S3 sync service
        sync_service = S3SyncService()
        
        # Sync all buckets
        results = sync_service.sync_all_buckets(prefix='data/', dry_run=False)
        
        # Calculate totals
        total_found = sum(result.get('found_in_s3', 0) for result in results.values())
        total_existing = sum(result.get('existing_in_db', 0) for result in results.values())
        total_created = sum(result.get('created', 0) for result in results.values())
        total_errors = sum(1 for result in results.values() if 'error' in result)
        
        # Create message based on results
        if total_created > 0:
            message = f'S3 Rescan complete. Found {total_found} files, {total_existing} already existed, {total_created} new files added'
        elif total_found > 0:
            message = f'S3 Rescan complete. Found {total_found} files, all were already in database'
        else:
            message = 'S3 Rescan complete. No files found in S3 buckets'
            
        if total_errors > 0:
            message += f' ({total_errors} bucket(s) had errors)'
        
        logger.info(f"S3 rescan results: {results}")
        
        if request.headers.get('HX-Request'):
            # Use template helper to render empty main response + OOB updates  
            from django.template.loader import render_to_string
            
            # Render toast message for OOB update (container-specific template without fixed positioning)
            toast_html = render_to_string('partials/container_toast.html', {
                'message': message,
                'type': 'success' if total_errors == 0 else 'warning'
            }, request=request)
            
            # Get updated files list using existing helper function
            files_response = _get_files_list_response(request)
            files_html = files_response.content.decode('utf-8')
            
            # Use template helper for OOB updates - empty main response, all via OOB
            helper = CSVMappingTemplateHelperMixin()
            
            # Build OOB updates manually to control swap methods
            oob_html = f'<div id="files-container" hx-swap-oob="innerHTML">{files_html}</div>'
            oob_html += f'<div id="toast-container" hx-swap-oob="beforeend">{toast_html}</div>'
            
            return HttpResponse(oob_html)
        else:
            from django.contrib import messages
            messages.success(request, message)
            return HttpResponseRedirect(reverse('metadata:data_discovery'))

    except Exception as e:
        error_msg = f'S3 rescan failed: {str(e)}'
        logger.error(f"S3 rescan error: {error_msg}")
        
        if request.headers.get('HX-Request'):
            return render(request, 'partials/toast.html', {
                'message': error_msg,
                'type': 'error'
            })
        return HttpResponse(error_msg, status=500)


@login_required
def toggle_select_all(request):
    """Toggle select all state and return updated files list with selection state."""
    
    # Create a temporary coordinator instance to access organization state
    from arkumu.common.mixins.base_coordinator import BaseCoordinatorMixin
    coordinator = BaseCoordinatorMixin()
    
    # Get current organization from session
    current_org = coordinator.get_current_organization(request)
    organization = current_org.get('code') if current_org else ''
    
    # Get current select all state from request
    select_all_checked = request.POST.get('select-all-checkbox') == 'on'
    
    # Store the select all state in session
    session_key = f'select_all_{organization}' if organization else 'select_all_global'
    request.session[session_key] = select_all_checked
    request.session.modified = True
    
    logger.info(f"Toggle select all: {select_all_checked} for org: {organization}")
    logger.info(f"Session key: {session_key}, POST data: {dict(request.POST)}")
    
    # Get the updated files container
    view = DataDiscoveryView()
    response = view.get(request)
    files_html = response.content.decode('utf-8')
    
    # Use existing template helper to render batch buttons and build OOB response
    from django.template.loader import render_to_string
    batch_buttons_html = render_to_string('partials/batch_buttons.html', {
        'select_all_checked': select_all_checked
    }, request=request)
    
    # Use the CSV mapping template helper for OOB updates
    helper = CSVMappingTemplateHelperMixin()
    oob_updates = {
        'batch-buttons-container': batch_buttons_html
    }
    
    final_html = helper.build_oob_response(files_html, oob_updates)
    return HttpResponse(final_html)


def _get_files_list_response(request):
    """Helper function to get updated files list HTML respecting organization state."""
    # Create a temporary coordinator instance to access organization state
    from arkumu.common.mixins.base_coordinator import BaseCoordinatorMixin
    coordinator = BaseCoordinatorMixin()
    
    # Get current organization from session
    current_org = coordinator.get_current_organization(request)
    organization = current_org.get('code') if current_org else ''
    
    # Re-fetch files data using same filter as main view with proper related resource loading
    s3_files = S3FileObject.objects.select_related(
        'related_resource', 'session', 'session__user'
    ).annotate(
        is_linked=Case(
            When(related_resource__isnull=False, then=True),
            default=False,
            output_field=BooleanField()
        )
    )
    
    # Filter by organization bucket if one is selected
    if organization:
        s3_files = s3_files.filter(session__s3_bucket=organization)
    
    # Filter by data folder within bucket
    s3_files = s3_files.filter(s3_key__startswith='data/').order_by('s3_key')

    # Get select all state from session
    session_key = f'select_all_{organization}' if organization else 'select_all_global'
    select_all_checked = request.session.get(session_key, False)
    
    # Group files by bucket
    files_by_bucket = {}
    for file in s3_files:
        bucket_name = file.session.s3_bucket if file.session and file.session.s3_bucket else 'unknown'
        
        if bucket_name not in files_by_bucket:
            files_by_bucket[bucket_name] = []
        files_by_bucket[bucket_name].append(file)

    return render(request, 'partials/files_list.html', {
        'files_by_bucket': files_by_bucket,
        'select_all_checked': select_all_checked
    }) 