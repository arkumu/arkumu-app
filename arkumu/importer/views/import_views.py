import logging
import os
from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, HttpResponse
from django.contrib.auth import get_user_model
from django.core.cache import cache

from arkumu.storage.services.bucket_service import BucketService
from arkumu.common.enums import UpdateStrategy
from arkumu.importer.tasks.import_metadata import run_csv_import_workflow, run_csv_directory_import_workflow
from arkumu.importer.models import IngestSession
from arkumu.users.mixins import general_login_required

logger = logging.getLogger(__name__)



@general_login_required
def ingest_file(request):
    """
    Ingest a CSV file using the ImportWorkflowService
    """
    if request.method == "POST":
        # Support both old parameter names and new ones
        s3_object_key = request.POST.get('s3_object_key') or request.POST.get('file_path')
        organization_id = request.POST.get('organization_id') or request.POST.get('organization')
        
        # New parameters for mapping support
        mapping_id = request.POST.get('mapping_id')
        use_mapping = request.POST.get('use_mapping', 'false').lower() == 'true'
        use_table_services = request.POST.get('use_table_services', 'false').lower() == 'true'
        link_row_cells = request.POST.get('link_row_cells', 'true').lower() == 'true'

        if not s3_object_key or not organization_id:
            return JsonResponse({'error': 'Missing s3_object_key or organization_id'}, status=400)

        # Determine dataset name from file_path (e.g., remove extension)
        dataset_name = os.path.splitext(os.path.basename(s3_object_key))[0]
        
        # Get organization
        from arkumu.users.models import Organization
        try:
            organization = Organization.objects.get(id=organization_id)
            organization_slug = organization.slug
        except Organization.DoesNotExist:
            try:
                # Fallback: treat organization_id as slug
                organization = Organization.objects.get(slug=organization_id)
                organization_slug = organization_id
            except Organization.DoesNotExist:
                return JsonResponse({'error': 'Organization not found'}, status=404)
        
        # Instantiate bucket service
        bucket_service = BucketService()
        
        # Get bucket name for organization
        s3_bucket_name = bucket_service.get_organization_bucket(organization_slug)
        
        # Check if it's a CSV file
        if not s3_object_key.lower().endswith('.csv'):
            # For HTMX, return a partial that can be swapped into the UI
            # This assumes you have a way to display this message in your poller or target div
            return render(request, 'importer/partials/task_status_poller.html', {
                'task_id': 'error-non-csv', # Provide a dummy or identifiable ID
                'task_info': {
                    'status': 'failed',
                    'message': 'Only CSV files can be ingested.',
                    'error_type': 'ValidationError'
                },
                'should_poll': False 
            }, status=400)

        logger.info(
            f"Preparing to enqueue ingest of S3 object {s3_bucket_name}/{s3_object_key} as dataset '{dataset_name}' for organization {organization_slug}"
        )

        User = get_user_model()
        user_instance = User.objects.get(pk=request.user.pk) if request.user.is_authenticated else None

        # Create an IngestSession record to track this CSV ingestion
        ingest_session = IngestSession.objects.create(
            user=user_instance,
            dataset_name=dataset_name,
            organization=organization,
            s3_bucket=s3_bucket_name,
            s3_object_key=s3_object_key,
            status='pending',  # Will be updated when task starts
            delimiter=';',
            has_quoted_fields=True,
            base_uri="http://arkumu.org/data",
            task_id="",  # Will be set to the session ID after creation
        )
        
        # Use the session ID as the polling task ID for consistent cache keys
        polling_task_id = str(ingest_session.id)
        ingest_session.task_id = polling_task_id
        ingest_session.save()
        
        # Enqueue the Huey task with mapping support
        task_instance = run_csv_import_workflow(
            s3_bucket_name=s3_bucket_name,
            s3_object_key=s3_object_key,
            dataset_name=dataset_name,
            institution=organization_slug,
            base_uri="http://arkumu.org/data",
            delimiter=';',
            has_quoted_fields=True,
            link_row_cells=link_row_cells,
            link_to_first_column=False,
            update_strategy=UpdateStrategy.UPDATE_VALUES,
            task_id_for_cache=polling_task_id,  # Pass the polling task ID
            upload_session_id=ingest_session.id,
            # New mapping parameters
            mapping_id=mapping_id if use_mapping else None,
            use_mapping=use_mapping,
            use_table_services=use_table_services
        )
        
        # Update the ingest session with the Huey task ID
        ingest_session.huey_task_id = str(task_instance.id)
        ingest_session.save()
        
        # Store initial status for the HTMX poller using consistent cache key pattern
        cache_key = f"task_state_{polling_task_id}"
        initial_task_info = {
            "status": "pending", 
            "message": f"CSV ingestion for '{os.path.basename(s3_object_key)}' has been queued.",
            "progress": 0
        }
        cache.set(cache_key, initial_task_info, timeout=3600) # Cache for 1 hour

        logger.info(
            f"Enqueued CSV import task. Polling ID: {polling_task_id}, Huey Task ID: {task_instance.id} for S3 object '{s3_bucket_name}/{s3_object_key}'"
        )
        
        # Return the poller template immediately for HTMX
        return render(request, 'importer/partials/task_status_poller.html', {
            'task_id': polling_task_id,
            'task_info': initial_task_info,
            'should_poll': True # Start polling
        })

    return JsonResponse({'error': 'Invalid request method'}, status=405)



@general_login_required
def reset_database(request):
    """
    Reset the database by deleting all Resource and Triple records.
    This is useful for development and testing.
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    # Superuser-only restriction
    if not request.user.is_superuser:
        logger.warning(
            f"SECURITY: Unauthorized database reset attempt by user={request.user.username} "
            f"email={request.user.email} ip={request.META.get('REMOTE_ADDR', 'unknown')}"
        )
        return JsonResponse({'error': 'Only superusers can reset the database'}, status=403)

    try:
        from arkumu.metadata.models.resource import Resource
        from arkumu.metadata.models.triples import Triple
        from django.db import transaction

        with transaction.atomic():
            # Count records before deletion
            triple_count = Triple.objects.count()
            resource_count = Resource.objects.count()

            # AUDIT LOG: Record who is performing this dangerous operation
            logger.warning(
                f"DATABASE RESET INITIATED by user={request.user.username} "
                f"email={request.user.email} ip={request.META.get('REMOTE_ADDR', 'unknown')} "
                f"about_to_delete: {triple_count} triples, {resource_count} resources"
            )

            # Delete all triples first (due to foreign key constraints)
            Triple.objects.all().delete()

            # Delete all resources
            Resource.objects.all().delete()

        logger.warning(
            f"DATABASE RESET COMPLETED by user={request.user.username} "
            f"email={request.user.email} ip={request.META.get('REMOTE_ADDR', 'unknown')} "
            f"deleted: {triple_count} triples, {resource_count} resources"
        )
        
        # Return HTMX-friendly response
        if request.headers.get('HX-Request') == 'true':
            from django.template.loader import render_to_string
            success_html = f"""
            <div class="alert alert-success">
                <svg xmlns="http://www.w3.org/2000/svg" class="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
                <div>
                    <h3 class="font-bold">Database Reset Successful!</h3>
                    <div class="text-xs">Deleted {triple_count} triples and {resource_count} resources</div>
                </div>
            </div>
            """
            return HttpResponse(success_html)
        
        return JsonResponse({
            'success': True,
            'message': f'Database reset successful! Deleted {triple_count} triples and {resource_count} resources.',
            'triples_deleted': triple_count,
            'resources_deleted': resource_count
        })
        
    except Exception as e:
        error_message = f'Failed to reset database: {str(e)}'
        logger.error(f"Database reset error: {e}", exc_info=True)
        
        return JsonResponse({
            'error': error_message
        }, status=500)


@general_login_required
def delete_organization_triples(request):
    """
    Delete all triples associated with a specific organization.
    This allows selective cleanup of organization-specific data.
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    # Superuser-only restriction
    if not request.user.is_superuser:
        logger.warning(
            f"SECURITY: Unauthorized organization data deletion attempt by user={request.user.username} "
            f"email={request.user.email} ip={request.META.get('REMOTE_ADDR', 'unknown')}"
        )
        return JsonResponse({'error': 'Only superusers can delete organization data'}, status=403)

    organization_id = request.POST.get('organization_id')
    if not organization_id:
        return JsonResponse({'error': 'Organization ID is required'}, status=400)

    try:
        from arkumu.metadata.models.resource import Resource
        from arkumu.metadata.models.triples import Triple
        from arkumu.users.models import Organization
        from django.db import transaction

        # Get the organization
        try:
            organization = Organization.objects.get(id=organization_id)
        except Organization.DoesNotExist:
            return JsonResponse({'error': 'Organization not found'}, status=404)

        with transaction.atomic():
            # Count records before deletion
            org_triples = Triple.objects.for_organization(organization)
            org_resources = Resource.objects.for_organization(organization)

            triple_count = org_triples.count()
            resource_count = org_resources.count()

            # AUDIT LOG: Record who is deleting organization data
            logger.warning(
                f"ORGANIZATION DATA DELETION INITIATED by user={request.user.username} "
                f"email={request.user.email} ip={request.META.get('REMOTE_ADDR', 'unknown')} "
                f"organization={organization.name} (id={organization_id}) "
                f"about_to_delete: {triple_count} triples, {resource_count} resources"
            )
            
            # Strategy: Identify resources that will become orphaned BEFORE deleting triples
            
            # Get all resource IDs that are used in organization triples
            org_triple_resource_ids = set()
            for triple in org_triples.values('subject_id', 'predicate_id', 'object_id'):
                org_triple_resource_ids.update([
                    triple['subject_id'], 
                    triple['predicate_id'], 
                    triple['object_id']
                ])
            
            # Get all resource IDs currently used in NON-organization triples (triples from other orgs)
            non_org_triple_resource_ids = set()
            non_org_triples = Triple.objects.exclude(source=organization)
            for triple in non_org_triples.values('subject_id', 'predicate_id', 'object_id'):
                non_org_triple_resource_ids.update([
                    triple['subject_id'], 
                    triple['predicate_id'], 
                    triple['object_id']
                ])
            
            # Resources that will become orphaned: 
            # - Used in org triples BUT
            # - NOT used in any other organization's triples AND  
            # - Belong to this organization
            potentially_orphaned = org_triple_resource_ids - non_org_triple_resource_ids
            resources_to_delete = org_resources.filter(id__in=potentially_orphaned)
            
            # Delete organization-specific triples first
            deleted_triples = org_triples.delete()[0]

            # Delete the identified orphaned resources
            deleted_resources = resources_to_delete.delete()[0]

        logger.warning(
            f"ORGANIZATION DATA DELETION COMPLETED by user={request.user.username} "
            f"email={request.user.email} ip={request.META.get('REMOTE_ADDR', 'unknown')} "
            f"organization={organization.name} (id={organization_id}) "
            f"deleted: {deleted_triples} triples, {deleted_resources} orphaned resources"
        )
        
        # Return HTMX-friendly response
        if request.headers.get('HX-Request') == 'true':
            success_html = f"""
            <div class="alert alert-success">
                <svg xmlns="http://www.w3.org/2000/svg" class="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
                <div>
                    <h3 class="font-bold">Organization Data Deletion Successful!</h3>
                    <div class="text-xs">Deleted {deleted_triples} triples and {deleted_resources} orphaned resources from '{organization.name}'</div>
                </div>
            </div>
            """
            return HttpResponse(success_html)
        
        return JsonResponse({
            'success': True,
            'message': f"Organization data deletion successful! Deleted {deleted_triples} triples and {deleted_resources} orphaned resources from '{organization.name}'.",
            'organization': organization.name,
            'triples_deleted': deleted_triples,
            'resources_deleted': deleted_resources
        })
        
    except Exception as e:
        error_message = f'Failed to delete organization data: {str(e)}'
        logger.error(f"Organization data deletion error: {e}", exc_info=True)
        
        return JsonResponse({
            'error': error_message
        }, status=500)


@general_login_required
def task_status_view(request, task_id):
    """
    Provides the status of a background task for HTMX polling.
    Reads the status from Django's cache.
    """
    cache_key = f"task_state_{task_id}"
    task_info = cache.get(cache_key)

    logger.info(f"Task status check for {task_id}: cache_key={cache_key}, task_info={task_info}")

    if not task_info:
        task_info = {
            "status": "pending",
            "message": "Task status not yet available or task ID is invalid. Waiting for initialization...",
            "progress": 0
        }

    # Determine if polling should continue
    # Stop polling if status is 'completed' or 'failed'
    should_poll = task_info.get("status") not in ["completed", "failed"]
    
    logger.info(f"Task {task_id}: status='{task_info.get('status')}', should_poll={should_poll}")
    
    # Default polling interval is 2 seconds, can be adjusted
    # If task is completed or failed, hx-trigger can be set to none or a very long interval if needed
    # but the template itself will handle not re-triggering via hx-swap conditional.

    return render(request, "importer/partials/task_status_poller.html", {
        "task_id": task_id,
        "task_info": task_info,
        "should_poll": should_poll 
    })



@general_login_required
def clear_upload_sessions(request):
    """
    Clear all UploadSession records.
    This is useful for development and testing.
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    # Superuser-only restriction
    if not request.user.is_superuser:
        logger.warning(
            f"SECURITY: Unauthorized upload sessions clear attempt by user={request.user.username} "
            f"email={request.user.email} ip={request.META.get('REMOTE_ADDR', 'unknown')}"
        )
        return JsonResponse({'error': 'Only superusers can clear upload sessions'}, status=403)

    try:
        from arkumu.storage.models.upload_tracking import AsyncUploadSession
        from arkumu.storage.models.upload_sessions import UploadSession
        from django.db import transaction

        with transaction.atomic():
            # Count before deletion
            async_count = AsyncUploadSession.objects.count()
            legacy_count = UploadSession.objects.count()

            # AUDIT LOG: Record who is clearing upload sessions
            logger.warning(
                f"UPLOAD SESSIONS CLEAR INITIATED by user={request.user.username} "
                f"email={request.user.email} ip={request.META.get('REMOTE_ADDR', 'unknown')} "
                f"about_to_delete: {async_count} async sessions, {legacy_count} legacy sessions"
            )

            # Delete all upload sessions in both tables
            AsyncUploadSession.objects.all().delete()
            UploadSession.objects.all().delete()
            upload_count = async_count + legacy_count

        logger.warning(
            f"UPLOAD SESSIONS CLEAR COMPLETED by user={request.user.username} "
            f"email={request.user.email} ip={request.META.get('REMOTE_ADDR', 'unknown')} "
            f"deleted: {upload_count} upload sessions (async={async_count}, legacy={legacy_count})"
        )
        
        # Return HTMX-friendly response
        if request.headers.get('HX-Request') == 'true':
            success_html = f"""
            <div class="alert alert-success">
                <svg xmlns="http://www.w3.org/2000/svg" class="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
                <div>
                    <h3 class="font-bold">Upload Sessions Cleared!</h3>
                    <div class="text-xs">Deleted {upload_count} upload sessions</div>
                </div>
            </div>
            """
            return HttpResponse(success_html)
        
        return JsonResponse({
            'success': True,
            'message': f'Upload sessions cleared! Deleted {upload_count} upload sessions.',
            'upload_sessions_deleted': upload_count
        })
        
    except Exception as e:
        error_message = f'Failed to clear upload sessions: {str(e)}'
        logger.error(f"Clear upload sessions error: {e}", exc_info=True)
        
        return JsonResponse({
            'error': error_message
        }, status=500)



@general_login_required
def clear_ingest_sessions(request):
    """
    Clear all IngestSession records.
    This is useful for development and testing.
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    # Superuser-only restriction
    if not request.user.is_superuser:
        logger.warning(
            f"SECURITY: Unauthorized ingest sessions clear attempt by user={request.user.username} "
            f"email={request.user.email} ip={request.META.get('REMOTE_ADDR', 'unknown')}"
        )
        return JsonResponse({'error': 'Only superusers can clear ingest sessions'}, status=403)

    try:
        from arkumu.importer.models.ingest_sessions import IngestSession
        from django.db import transaction

        with transaction.atomic():
            # Count before deletion
            ingest_count = IngestSession.objects.count()

            # AUDIT LOG: Record who is clearing ingest sessions
            logger.warning(
                f"INGEST SESSIONS CLEAR INITIATED by user={request.user.username} "
                f"email={request.user.email} ip={request.META.get('REMOTE_ADDR', 'unknown')} "
                f"about_to_delete: {ingest_count} ingest sessions"
            )

            # Delete all ingest sessions
            IngestSession.objects.all().delete()

        logger.warning(
            f"INGEST SESSIONS CLEAR COMPLETED by user={request.user.username} "
            f"email={request.user.email} ip={request.META.get('REMOTE_ADDR', 'unknown')} "
            f"deleted: {ingest_count} ingest sessions"
        )
        
        # Return HTMX-friendly response
        if request.headers.get('HX-Request') == 'true':
            success_html = f"""
            <div class="alert alert-success">
                <svg xmlns="http://www.w3.org/2000/svg" class="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
                <div>
                    <h3 class="font-bold">Ingest Sessions Cleared!</h3>
                    <div class="text-xs">Deleted {ingest_count} ingest sessions</div>
                </div>
            </div>
            """
            return HttpResponse(success_html)
        
        return JsonResponse({
            'success': True,
            'message': f'Ingest sessions cleared! Deleted {ingest_count} ingest sessions.',
            'ingest_sessions_deleted': ingest_count
        })
        
    except Exception as e:
        error_message = f'Failed to clear ingest sessions: {str(e)}'
        logger.error(f"Clear ingest sessions error: {e}", exc_info=True)
        
        return JsonResponse({
            'error': error_message
        }, status=500)



@general_login_required
def start_directory_import(request):
    """
    Start a directory import for all CSV files in an S3 folder using the directory import Huey task
    """
    if request.method == "POST":
        organization_slug = request.POST.get('organization')
        s3_folder_path = request.POST.get('s3_folder_path')
        folder_name = request.POST.get('folder_name')

        if not organization_slug or not s3_folder_path:
            return HttpResponse(
                '<div class="alert alert-error"><span>Missing required fields: organization or folder path</span></div>',
                status=400
            )

        # Clean up folder path (remove trailing slash if present)
        s3_folder_path = s3_folder_path.rstrip('/')
        
        # Use folder name as base dataset name, fallback to folder path
        dataset_name = folder_name or s3_folder_path.split('/')[-1] or 'directory_import'
        
        # Instantiate bucket service
        bucket_service = BucketService()
        
        # Get bucket name for organization
        s3_bucket_name = bucket_service.get_organization_bucket(organization_slug)
        
        logger.info(
            f"Preparing to enqueue directory import of S3 folder {s3_bucket_name}/{s3_folder_path} "
            f"as dataset '{dataset_name}' for organization {organization_slug}"
        )

        User = get_user_model()
        user_instance = User.objects.get(pk=request.user.pk) if request.user.is_authenticated else None

        # Create an IngestSession record to track this directory import
        ingest_session = IngestSession.objects.create(
            user=user_instance,
            dataset_name=dataset_name,
            organization=organization,
            s3_bucket=s3_bucket_name,
            s3_object_key=s3_folder_path,  # Store folder path in s3_object_key field
            status='pending',
            delimiter=';',
            has_quoted_fields=True,
            base_uri="http://arkumu.org/data",
            task_id="",  # Will be set to the session ID after creation
        )
        
        # Use the session ID as the polling task ID for consistent cache keys
        polling_task_id = str(ingest_session.id)
        ingest_session.task_id = polling_task_id
        ingest_session.save()
        
        # Enqueue the directory import Huey task
        task_instance = run_csv_directory_import_workflow(
            s3_bucket_name=s3_bucket_name,
            s3_folder_prefix=s3_folder_path,
            dataset_name=dataset_name,
            institution=organization_slug,
            base_uri="http://arkumu.org/data",
            delimiter=';',
            has_quoted_fields=True,
            link_row_cells=True,
            link_to_first_column=False,
            use_smart_updater=False,  # Default to false for faster processing
            use_polars=True,  # Enable for better performance
            update_strategy=UpdateStrategy.UPDATE_VALUES,
            relationship_config_json=None,  # No relationship config by default
            file_columns=None,  # No specific file columns
            timestamp_column=None,  # No timestamp column
            task_id_for_cache=polling_task_id,  # Pass the polling task ID
            upload_session_id=ingest_session.id
        )
        
        # Update the ingest session with the Huey task ID
        ingest_session.huey_task_id = str(task_instance.id)
        ingest_session.save()
        
        # Store initial status for the HTMX poller using consistent cache key pattern
        cache_key = f"task_state_{polling_task_id}"
        initial_task_info = {
            "status": "pending", 
            "message": f"Directory import for '{folder_name or s3_folder_path}' has been queued. Discovering CSV files...",
            "progress": 0
        }
        cache.set(cache_key, initial_task_info, timeout=3600)

        logger.info(
            f"Enqueued directory import task. Polling ID: {polling_task_id}, "
            f"Huey Task ID: {task_instance.id} for S3 folder '{s3_bucket_name}/{s3_folder_path}'"
        )
        
        # Return the directory-specific poller template for HTMX
        return render(request, 'importer/partials/directory_import_status_poller.html', {
            'task_id': polling_task_id,
            'task_info': initial_task_info,
            'should_poll': True,
            'import_type': 'directory'  # To distinguish from single file imports
        })

    return HttpResponse(
        '<div class="alert alert-error"><span>Invalid request method</span></div>',
        status=405
    ) 
