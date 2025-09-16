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
from arkumu.metadata.services.resource_traversal_service import ResourceTraversalService
from arkumu.storage.services.bucket_service import BucketService
from arkumu.storage.services.s3_sync_service import S3SyncService
from arkumu.common.mixins.base_coordinator import BaseCoordinatorMixin
from arkumu.metadata.views.csv_mapping.mixins.template_helpers import CSVMappingTemplateHelperMixin
from arkumu.oaipmh.cache_service import OAIPMHCacheService

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
                # Guard against null s3_key values during logging
                if not key:
                    continue
                if '/' in key:
                    prefix = key.split('/')[0]
                    unique_prefixes.add(prefix)
                else:
                    unique_prefixes.add(key)
            # Sort in a None-safe way for logging
            try:
                prefixes_sorted = sorted(unique_prefixes)
            except TypeError:
                prefixes_sorted = sorted((str(p) if p is not None else 'unknown' for p in unique_prefixes))
            logger.info(f"Unique s3_key prefixes found: {prefixes_sorted}")
            
            # Show session buckets
            session_buckets = set(S3FileObject.objects.values_list('session__s3_bucket', flat=True).distinct())
            # Sort with None-safe representation for logging only
            session_buckets_sorted = sorted((str(b) if b is not None else 'unknown' for b in session_buckets))
            logger.info(f"Session buckets found: {session_buckets_sorted}")
        
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

        # Find the project entity associated with this resource
        traversal_service = ResourceTraversalService()
        project_entity = traversal_service.get_project_entity_for_resource(resource)

        if project_entity:
            # Link to the project entity instead of the literal/intermediate resource
            s3_file.related_resource = project_entity
            s3_file.save()
            logger.info(f"Linked S3FileObject {s3_file.id} to project entity {project_entity.uri} via resource {resource.value}")
        else:
            # No project entity found, fallback to original resource (for backward compatibility)
            s3_file.related_resource = resource
            s3_file.save()
            logger.warning(f"No project entity found for resource {resource.value}, linked directly to resource")

        # Trigger OAI-PMH cache warming for the affected resource
        try:
            # Get the final linked resource (project entity or fallback resource)
            final_resource = s3_file.related_resource
            if final_resource and final_resource.organization:
                logger.debug(f"🔥 SINGLE CACHE DEBUG: Warming cache for {final_resource.uri} (org: {final_resource.organization.code})")

                # Warm cache for both metadata formats using centralized service
                for metadata_prefix in ['oai_dc', 'mets']:
                    OAIPMHCacheService.warm_record(final_resource, metadata_prefix)

                logger.info(f"Warmed OAI-PMH cache for resource {final_resource.uri}")
            else:
                logger.debug(f"🔥 SINGLE CACHE DEBUG: Skipping cache warming - resource has no organization")
        except Exception as e:
            logger.error(f"Error warming OAI-PMH cache: {str(e)}")

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
        
        # When Select All is enabled, process ALL filtered files instead of just selected ones
        if select_all_enabled:
            # Recreate the same filter logic as the main view
            selected_files = S3FileObject.objects.select_related(
                'related_resource', 'session', 'session__user'
            )

            # Filter by organization bucket if one is selected
            if organization:
                selected_files = selected_files.filter(session__s3_bucket=organization)

            # Filter by data folder within bucket
            selected_files = selected_files.filter(s3_key__startswith='data/')

            # Apply any status filters from the request
            status_filter = request.POST.get('status_filter', '') or request.GET.get('status_filter', '')
            if status_filter == 'linked':
                selected_files = selected_files.filter(related_resource__isnull=False)
            elif status_filter == 'unlinked':
                selected_files = selected_files.filter(related_resource__isnull=True)

            # Apply date filters if they exist (for future extensibility)
            from_date = request.POST.get('from_date', '') or request.GET.get('from_date', '')
            until_date = request.POST.get('until_date', '') or request.GET.get('until_date', '')
            if from_date:
                from django.utils.dateparse import parse_date
                try:
                    from_date_parsed = parse_date(from_date)
                    if from_date_parsed:
                        selected_files = selected_files.filter(created_at__gte=from_date_parsed)
                except:
                    pass
            if until_date:
                from django.utils.dateparse import parse_date
                try:
                    until_date_parsed = parse_date(until_date)
                    if until_date_parsed:
                        selected_files = selected_files.filter(created_at__lte=until_date_parsed)
                except:
                    pass

            logger.info(f"Batch link request: Select All enabled, processing {selected_files.count()} files for org {organization}")
        else:
            # Fallback to individual file selection (current page only)
            file_ids = request.POST.getlist('selected_files')
            logger.info(f"Batch link request received. Selected file IDs: {file_ids}")

            if not file_ids:
                message = 'No files selected'
                logger.warning(f"Batch link failed: {message}")
                if request.headers.get('HX-Request'):
                    return render(request, 'partials/toast.html', {
                        'message': message,
                        'type': 'warning'
                    })
                return HttpResponse(message, status=400)

            # Get the queryset of selected files
            selected_files = S3FileObject.objects.filter(id__in=file_ids)
        
        # Schedule background task for batch linking
        try:
            from arkumu.oaipmh.tasks import batch_link_files_task

            # Get file IDs for the task
            file_ids = list(selected_files.values_list('id', flat=True))

            # Schedule the background task
            batch_link_files_task.schedule(
                args=(file_ids, organization, request.user.id),
                delay=5  # Small delay to let UI respond first
            )

            message = f'Batch linking started for {len(file_ids)} files. Processing in background...'
            logger.info(f"Scheduled batch linking task for {len(file_ids)} files")

        except ImportError:
            logger.error("Could not import batch linking task - falling back to synchronous processing")
            # Fallback to synchronous processing if task system unavailable
            message = 'Task system unavailable - batch linking will be processed synchronously'
        except Exception as e:
            logger.error(f"Error scheduling batch link task: {str(e)}")
            message = f'Error starting batch linking: {str(e)}'

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
        
        # When Select All is enabled, process ALL filtered files instead of just selected ones
        if select_all_enabled:
            # Recreate the same filter logic as the main view
            selected_files = S3FileObject.objects.select_related(
                'related_resource', 'session', 'session__user'
            )

            # Filter by organization bucket if one is selected
            if organization:
                selected_files = selected_files.filter(session__s3_bucket=organization)

            # Filter by data folder within bucket
            selected_files = selected_files.filter(s3_key__startswith='data/')

            # Apply any status filters from the request
            status_filter = request.POST.get('status_filter', '') or request.GET.get('status_filter', '')
            if status_filter == 'linked':
                selected_files = selected_files.filter(related_resource__isnull=False)
            elif status_filter == 'unlinked':
                selected_files = selected_files.filter(related_resource__isnull=True)

            # Apply date filters if they exist (for future extensibility)
            from_date = request.POST.get('from_date', '') or request.GET.get('from_date', '')
            until_date = request.POST.get('until_date', '') or request.GET.get('until_date', '')
            if from_date:
                from django.utils.dateparse import parse_date
                try:
                    from_date_parsed = parse_date(from_date)
                    if from_date_parsed:
                        selected_files = selected_files.filter(created_at__gte=from_date_parsed)
                except:
                    pass
            if until_date:
                from django.utils.dateparse import parse_date
                try:
                    until_date_parsed = parse_date(until_date)
                    if until_date_parsed:
                        selected_files = selected_files.filter(created_at__lte=until_date_parsed)
                except:
                    pass

            logger.info(f"Batch unlink request: Select All enabled, processing {selected_files.count()} files for org {organization}")
        else:
            # Fallback to individual file selection (current page only)
            file_ids = request.POST.getlist('selected_files')
            logger.info(f"Batch unlink request received. Selected file IDs: {file_ids}")

            if not file_ids:
                message = 'No files selected'
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
        unlinked_resources = set()  # Track resources that were unlinked for cache warming

        logger.debug(f"🔍 BATCH UNLINK DEBUG: Starting batch unlinking for {selected_files.count()} files")
        
        for s3_file in selected_files:
            processed += 1
            try:
                logger.debug(f"🔍 BATCH UNLINK DEBUG: Processing file {s3_file.file_name} (ID: {s3_file.id})")

                if s3_file.related_resource:
                    # Store original resource info before unlinking
                    resource = s3_file.related_resource
                    old_resource = resource.value
                    logger.debug(f"🔍 BATCH UNLINK DEBUG: Unlinking from {resource.resource_type}: {resource.uri} (org: {resource.organization.code if resource.organization else 'None'})")

                    # Track the resource for cache warming
                    if resource.organization:
                        unlinked_resources.add((resource.uri, resource.organization.code))

                    # Unlink the file
                    s3_file.related_resource = None
                    s3_file.save()
                    unlinked += 1
                    logger.info(f"Unlinked {s3_file.file_name} from resource {old_resource}")
                else:
                    # File was already unlinked
                    logger.debug(f"🔍 BATCH UNLINK DEBUG: File was already unlinked, skipping")
                    logger.info(f"File {s3_file.file_name} was already unlinked")
                    
            except Exception as e:
                errors += 1
                logger.error(f"Error processing {s3_file.file_name}: {str(e)}")

        message = f'Batch unlinking complete. Processed: {processed}, Unlinked: {unlinked}, Errors: {errors}'

        # Trigger OAI-PMH cache warming for affected resources if any files were unlinked
        if unlinked > 0:
            logger.debug(f"🔥 CACHE WARM DEBUG: Starting cache warming for {len(unlinked_resources)} unlinked resources")

            try:
                # Warm cache for each unlinked resource directly using centralized service
                for i, (uri, org_code) in enumerate(unlinked_resources):
                    logger.debug(f"🔥 CACHE WARM DEBUG: Warming unlinked resource {i+1}: {uri} (org: {org_code})")

                    try:
                        resource = Resource.objects.get(uri=uri, organization__code=org_code)
                        # Warm cache for both metadata formats
                        for metadata_prefix in ['oai_dc', 'mets']:
                            OAIPMHCacheService.warm_record(resource, metadata_prefix)
                    except Resource.DoesNotExist:
                        logger.warning(f"Resource not found for cache warming: {uri}")
                    except Exception as resource_error:
                        logger.error(f"Error warming cache for resource {uri}: {str(resource_error)}")

                logger.info(f"Warmed OAI-PMH cache for {len(unlinked_resources)} resources after unlinking {unlinked} files")

            except Exception as e:
                logger.error(f"Error warming OAI-PMH cache: {str(e)}")
        else:
            logger.debug(f"🔥 CACHE WARM DEBUG: No files unlinked, skipping cache warming")

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
