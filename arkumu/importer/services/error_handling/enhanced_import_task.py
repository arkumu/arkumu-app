"""
Enhanced import task with structured error handling and persistence.
Integrates comprehensive error tracking with the existing import pipeline.
"""

import logging
import os
import tempfile
from typing import Dict, Any, Optional, List
from uuid import UUID

from huey.contrib.djhuey import db_task
from django.core.cache import cache
from django.utils import timezone

from arkumu.importer.models.ingest_sessions import IngestSession
from arkumu.importer.services.error_handling.pipeline_integration import (
    PipelineErrorHandler, 
    StructuredImportPipeline
)
from arkumu.importer.services.mapping_consumer.mapping_adapter import MappingAdapter
from arkumu.importer.services.execution.mapping_aware_processor import MappingAwareProcessor
from arkumu.importer.services.orchestrator.import_orchestrator import ImportOrchestrator
from arkumu.common.enums import UpdateStrategy
from arkumu.common.data_types import BulkUpdateStats
# REMOVED: from arkumu.common.import_service_bridge import bridge_service  # OLD SYSTEM ELIMINATED
from arkumu.storage.services.bucket_service import BucketService
from arkumu.metadata.models import Organization, Mapping
from arkumu.projects.services import ProjectSnapshotService


logger = logging.getLogger(__name__)


@db_task(retries=1, retry_delay=60)
def run_csv_import_with_structured_error_handling(
    s3_bucket_name: str,
    s3_object_key: str,
    dataset_name: str,
    institution: str,
    base_uri: str = "http://arkumu.org/data",
    delimiter: str = ';',
    has_quoted_fields: bool = True,
    link_row_cells: bool = True,
    link_to_first_column: bool = False,
    update_strategy: UpdateStrategy = UpdateStrategy.SKIP_EXISTING,
    task_id_for_cache: Optional[str] = None,
    upload_session_id: Optional[UUID] = None,
    # Enhanced mapping parameters
    mapping_id: Optional[str] = None,
    use_mapping: bool = False,
    use_table_services: bool = False,
    validation_mode: bool = True,
    notify_on_error: bool = True,
    admin_emails: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    Enhanced CSV import task with comprehensive error handling and persistence.
    
    This task provides:
    - Structured error tracking and persistence
    - Mapping validation with issue recording
    - Phase-specific error handling
    - Communication of errors to administrators
    - Detailed error reporting and recovery guidance
    
    Args:
        s3_bucket_name: S3 bucket containing the CSV file
        s3_object_key: S3 object key for the CSV file
        dataset_name: Name of the dataset
        institution: Organization identifier
        base_uri: Base URI for resource generation
        delimiter: CSV delimiter
        has_quoted_fields: Whether CSV has quoted fields
        link_row_cells: Whether to link row cells
        link_to_first_column: Linking strategy
        update_strategy: Data update strategy
        task_id_for_cache: Task ID for cache operations
        upload_session_id: Ingest session ID
        mapping_id: Optional mapping ID for complex imports
        use_mapping: Whether to use mapping-based import
        use_table_services: Whether to use table services
        validation_mode: Whether to validate before execution
        notify_on_error: Whether to send error notifications
        admin_emails: List of admin emails for notifications
    
    Returns:
        Dict containing import results and error information
    """
    
    # Initialize task tracking
    actual_task_id = task_id_for_cache or getattr(run_csv_import_with_structured_error_handling, 'request', {}).get('id')
    cache_key = f"task_status_{actual_task_id}" if actual_task_id else None
    
    # Get or create ingest session
    ingest_session = None
    if upload_session_id:
        try:
            ingest_session = IngestSession.objects.get(id=upload_session_id)
            ingest_session.mark_started()
        except IngestSession.DoesNotExist:
            logger.error(f"IngestSession {upload_session_id} not found")
    
    # Initialize structured error handling
    error_handler = PipelineErrorHandler(ingest_session)
    structured_pipeline = StructuredImportPipeline(ingest_session) if ingest_session else None
    
    # Initialize cache update function
    def update_cache(status: str, message: str, progress: int, details: Optional[Dict] = None, error_info: Optional[Dict] = None):
        if cache_key:
            payload = {
                "status": status,
                "message": message,
                "progress": progress,
                "timestamp": timezone.now().isoformat()
            }
            if details:
                payload["details"] = details
            if error_info:
                payload["error_info"] = error_info
            cache.set(cache_key, payload, timeout=3600)
    
    def update_cache_with_phase_info(status: str, message: str, progress: int, 
                                   phase_info: Optional[Dict] = None, 
                                   details: Optional[Dict] = None, 
                                   error_info: Optional[Dict] = None):
        """Enhanced cache update function with phase information support for structured error handling."""
        if cache_key:
            payload = {
                "status": status,
                "message": message,
                "progress": progress,
                "timestamp": timezone.now().isoformat()
            }
            
            if phase_info:
                payload["phase_info"] = {
                    "current_phase": phase_info.get("current_phase", "unknown"),
                    "current_phase_index": phase_info.get("current_phase_index", 0),
                    "total_phases": phase_info.get("total_phases", 1),
                    "phase_progress": phase_info.get("phase_progress", 0),
                    "phase_description": phase_info.get("phase_description", ""),
                    "execution_strategy": phase_info.get("execution_strategy", "structured")
                }
            
            if details:
                payload["details"] = details
            if error_info:
                payload["error_info"] = error_info
                
            cache.set(cache_key, payload, timeout=3600)
    
    # Initialize result structure
    result = {
        "status": "processing",
        "dataset_name": dataset_name,
        "s3_object_key": s3_object_key,
        "institution": institution,
        "errors": [],
        "warnings": [],
        "validation_issues": [],
        "execution_phases": [],
        "final_stats": {}
    }
    
    temp_local_path = None
    
    # Initialize phase tracking for structured error handling
    structured_phases = [
        "file_download",
        "mapping_validation", 
        "data_import",
        "finalization"
    ]
    
    def get_structured_phase_info(phase_name: str, phase_progress: int = 0) -> Dict:
        """Get phase information for structured error handling progress tracking."""
        try:
            phase_index = structured_phases.index(phase_name)
        except ValueError:
            phase_index = 0
        
        return {
            "current_phase": phase_name,
            "current_phase_index": phase_index,
            "total_phases": len(structured_phases),
            "phase_progress": phase_progress,
            "phase_description": get_structured_phase_description(phase_name),
            "execution_strategy": "structured"
        }
    
    def get_structured_phase_description(phase_name: str) -> str:
        """Get user-friendly description for each structured error handling phase."""
        descriptions = {
            "file_download": "Downloading and preparing file",
            "mapping_validation": "Validating mapping configuration",
            "data_import": "Importing data with error tracking",
            "finalization": "Finalizing and reporting results"
        }
        return descriptions.get(phase_name, "Processing")
    
    try:
        # Phase 1: File Download
        phase_info = get_structured_phase_info("file_download", 0)
        update_cache_with_phase_info("processing", "Starting file download from S3...", 5, phase_info)
        
        with error_handler.error_context("file_download", "storage") as ctx:
            bucket_service = BucketService()
            
            # Create temporary file
            with tempfile.NamedTemporaryFile(mode='w+b', suffix='.csv', delete=False) as temp_file:
                temp_local_path = temp_file.name
            
            # Download file
            try:
                bucket_service.base_s3_service.s3_client.download_file(
                    s3_bucket_name, s3_object_key, temp_local_path
                )
                logger.info(f"Downloaded {s3_object_key} to {temp_local_path}")
                
            except Exception as e:
                error_handler.handle_file_error(s3_object_key, e)
                raise
        
        # Update file download phase completion
        phase_info = get_structured_phase_info("file_download", 100)
        update_cache_with_phase_info("processing", "File downloaded successfully", 15, phase_info)
        
        # Phase 2: Mapping Validation (if using mapping)
        mapping_config = None
        validation_result = None
        
        if use_mapping and mapping_id and validation_mode:
            # Phase 2: Mapping Validation
            phase_info = get_structured_phase_info("mapping_validation", 25)
            update_cache_with_phase_info("processing", "Validating mapping configuration...", 20, phase_info)
            
            with error_handler.error_context("mapping_validation", "validation") as ctx:
                try:
                    # Get mapping and organization
                    mapping = Mapping.objects.get(id=mapping_id)
                    organization = Organization.objects.get(code=institution)
                    
                    # Load and validate mapping
                    adapter = MappingAdapter()
                    validation_result = adapter.validate_mapping(mapping_id)
                    
                    # Record validation issues
                    if structured_pipeline:
                        validation_info = structured_pipeline.validate_before_execution(
                            mapping_id=mapping_id,
                            mapping_name=mapping.name,
                            organization=organization.code,
                            validation_result=validation_result
                        )
                        
                        result["validation_issues"] = validation_info["issues_recorded"]
                        
                        # Check if we can proceed
                        if not validation_info["can_proceed"]:
                            error_msg = f"Mapping validation failed with {len(validation_result.errors)} errors"
                            ctx.record_error(
                                error_code="MAPPING_VALIDATION_FAILED",
                                error_message=error_msg,
                                severity="critical"
                            )
                            
                            # Update session and cache
                            if ingest_session:
                                ingest_session.mark_failed(error_msg)
                            
                            phase_info = get_structured_phase_info("mapping_validation", 100)
                            update_cache_with_phase_info("failed", error_msg, 0, phase_info, error_info={
                                "phase": "mapping_validation",
                                "validation_errors": validation_result.errors[:5]  # First 5 errors
                            })
                            
                            result["status"] = "failed"
                            result["error_message"] = error_msg
                            return result
                    
                    # Load mapping configuration if validation passed
                    if validation_result.is_valid or len(validation_result.errors) == 0:
                        mapping_config = adapter.translate_to_execution_config(mapping_id)
                        logger.info(f"Loaded mapping configuration for {mapping.name}")
                    
                except Exception as e:
                    ctx.record_error(
                        error_code="MAPPING_LOAD_ERROR",
                        error_message=f"Failed to load mapping: {str(e)}",
                        severity="critical"
                    )
                    raise
        
        # Update mapping validation phase completion
        phase_info = get_structured_phase_info("mapping_validation", 100)
        update_cache_with_phase_info("processing", "Mapping validation completed", 30, phase_info)
        
        # Phase 3: Data Import Execution
        phase_info = get_structured_phase_info("data_import", 10)
        update_cache_with_phase_info("processing", "Starting data import execution...", 35, phase_info)
        
        with error_handler.error_context("data_import", "execution") as ctx:
            try:
                # Get organization
                organization = Organization.objects.get(code=institution)
                
                # Use NEW mapping-aware import system instead of old bridge_service
                logger.info("Using NEW MappingAwareProcessor system with dataset-entity linking")
                
                # Upload file to S3 temporarily so NEW system can process it
                temp_s3_key = f"temp_error_handling/{institution}/{dataset_name}.csv"
                bucket_service.base_s3_service.s3_client.upload_file(temp_local_path, s3_bucket_name, temp_s3_key)
                
                # Import the NEW system
                from arkumu.importer.tasks.import_metadata import run_mapping_aware_import_workflow
                
                # Execute with NEW mapping-aware processor
                import_result = run_mapping_aware_import_workflow(
                    s3_bucket_name=s3_bucket_name,
                    s3_object_key=temp_s3_key,
                    dataset_name=dataset_name,
                    institution=institution,
                    mapping_id=mapping_id or "auto-generated",
                    base_uri=base_uri,
                    upload_session_id=upload_session_id,
                    csv_sources=None,
                    update_progress=None,
                    task_context=None
                )
                
                # Clean up temp S3 file
                try:
                    bucket_service.base_s3_service.s3_client.delete_object(Bucket=s3_bucket_name, Key=temp_s3_key)
                except Exception as cleanup_error:
                    logger.warning(f"Failed to cleanup temp S3 file {temp_s3_key}: {cleanup_error}")
                
                # Convert result to BulkUpdateStats format for compatibility
                stats = {
                    "stats": {
                        "rows_processed": import_result.get("rows_processed", 0),
                        "resources_created": import_result.get("resources_created", 0),
                        "triples_created": import_result.get("triples_created", 0),
                        "datasets_skipped": import_result.get("datasets_skipped", 0),
                        "errors": 0 if import_result.get("status") == "success" else 1
                    }
                }
                
                # Extract statistics
                actual_stats = stats.get("stats", {})
                result["final_stats"] = {
                    "rows_processed": actual_stats.get("rows_processed", 0),
                    "cells_processed": actual_stats.get("cells_processed", 0),
                    "resources_created": actual_stats.get("resources_created", 0),
                    "resources_updated": actual_stats.get("resources_updated", 0),
                    "resources_skipped": actual_stats.get("resources_skipped", 0),
                    "triples_created": actual_stats.get("triples_created", 0),
                    "triples_updated": actual_stats.get("triples_updated", 0),
                    "triples_skipped": actual_stats.get("triples_skipped", 0),
                    "datasets_skipped": actual_stats.get("datasets_skipped", 0),
                    "errors": actual_stats.get("errors", 0),
                }
                
                # Record any errors from the import process
                if actual_stats.get("errors", 0) > 0:
                    ctx.record_warning(
                        warning_code="IMPORT_ERRORS_DETECTED",
                        warning_message=f"Import completed with {actual_stats['errors']} errors"
                    )
                
            except Exception as e:
                ctx.record_error(
                    error_code="IMPORT_EXECUTION_ERROR",
                    error_message=f"Import execution failed: {str(e)}",
                    severity="critical"
                )
                raise
        
        # Update data import phase completion
        phase_info = get_structured_phase_info("data_import", 100)
        update_cache_with_phase_info("processing", "Data import completed", 80, phase_info)
        
        # Phase 4: Finalization
        phase_info = get_structured_phase_info("finalization", 50)
        update_cache_with_phase_info("processing", "Finalizing import results...", 90, phase_info)
        
        with error_handler.error_context("finalization", "system") as ctx:
            # Update ingest session
            if ingest_session:
                ingest_session.mark_completed(result["final_stats"])

                # Refresh project snapshot and schema caches so explorer views stay consistent.
                try:
                    logger.info(
                        "Refreshing cross-institutional project snapshot after import for org %s",
                        institution,
                    )
                    ProjectSnapshotService().refresh_cross_institutional_snapshot()
                except Exception:  # pragma: no cover - defensive safety
                    logger.exception(
                        "Failed to refresh project snapshot after import for org %s",
                        institution,
                    )

                from arkumu.cache.services import SchemaMapCacheService
                from arkumu.catalog.services.schema_manifest_service import SchemaManifestService

                try:
                    logger.info(
                        "Refreshing schema manifest cache for org %s",
                        institution,
                    )
                    SchemaManifestService().get_card_schema(institution)
                except Exception:  # pragma: no cover - defensive safety
                    logger.exception(
                        "Failed to refresh schema manifest cache for org %s",
                        institution,
                    )

                try:
                    logger.info("Refreshing schema map cache after import")
                    SchemaMapCacheService().refresh_cache()
                except Exception:  # pragma: no cover - defensive safety
                    logger.exception("Failed to refresh schema map cache after import")

            # Generate success message
            success_message = (
                f"Dataset '{dataset_name}' imported successfully. "
                f"Processed: {result['final_stats'].get('rows_processed', 0)} rows. "
                f"Created: {result['final_stats'].get('resources_created', 0)} resources, "
                f"{result['final_stats'].get('triples_created', 0)} triples. "
                f"Errors: {result['final_stats'].get('errors', 0)}."
            )
            
            # Collect error summary
            error_summary = error_handler.error_manager.get_error_summary()
            result["error_summary"] = error_summary
            
            # Update cache with success
            phase_info = get_structured_phase_info("finalization", 100)
            update_cache_with_phase_info("completed", success_message, 100, 
                        phase_info,
                        details=result["final_stats"],
                        error_info=error_summary)
            
            result["status"] = "success"
            result["message"] = success_message
            
            logger.info(f"Import completed successfully: {success_message}")
        
        return result
        
    except Exception as e:
        # Handle any uncaught exceptions
        error_message = f"Import failed: {str(e)}"
        logger.error(f"Import task failed: {e}", exc_info=True)
        
        # Record the error
        error_handler.error_manager.record_error(
            error_code="IMPORT_TASK_FAILURE",
            error_type=type(e).__name__,
            error_message=error_message,
            error_category="system",
            severity="critical"
        )
        
        # Update session and cache
        if ingest_session:
            ingest_session.mark_failed(error_message)
        
        error_summary = error_handler.error_manager.get_error_summary()
        
        # Use generic error phase info if no specific phase is available
        phase_info = get_structured_phase_info("file_download", 0)
        update_cache_with_phase_info("failed", error_message, 0, phase_info, error_info=error_summary)
        
        # Send notifications if enabled
        if notify_on_error and admin_emails:
            try:
                error_handler.error_manager.notify_error(
                    error=error_handler.error_manager.get_session_errors()["pipeline_errors"][0],
                    recipients=admin_emails
                )
            except Exception as notify_error:
                logger.error(f"Failed to send error notification: {notify_error}")
        
        result.update({
            "status": "failed",
            "error_message": error_message,
            "error_type": type(e).__name__,
            "error_summary": error_summary
        })
        
        return result
        
    finally:
        # Cleanup temporary file
        if temp_local_path and os.path.exists(temp_local_path):
            try:
                os.unlink(temp_local_path)
                logger.info(f"Cleaned up temporary file: {temp_local_path}")
            except OSError as e:
                logger.error(f"Failed to cleanup temporary file: {e}")


def create_enhanced_import_task(
    ingest_session: IngestSession,
    mapping_id: Optional[str] = None,
    use_mapping: bool = False,
    **kwargs
) -> Dict[str, Any]:
    """
    Create and enqueue an enhanced import task with structured error handling.
    
    Args:
        ingest_session: IngestSession instance
        mapping_id: Optional mapping ID
        use_mapping: Whether to use mapping-based import
        **kwargs: Additional task parameters
    
    Returns:
        Dict containing task information
    """
    
    # Prepare task parameters
    task_params = {
        's3_bucket_name': ingest_session.s3_bucket,
        's3_object_key': ingest_session.s3_object_key,
        'dataset_name': ingest_session.dataset_name,
        'institution': ingest_session.organization,
        'base_uri': ingest_session.base_uri,
        'delimiter': ingest_session.delimiter,
        'has_quoted_fields': ingest_session.has_quoted_fields,
        'upload_session_id': ingest_session.id,
        'mapping_id': mapping_id,
        'use_mapping': use_mapping,
        **kwargs
    }
    
    # Enqueue task
    task = run_csv_import_with_structured_error_handling(**task_params)
    
    # Update ingest session with task ID
    ingest_session.task_id = str(task.id)
    ingest_session.save()
    
    return {
        'task_id': str(task.id),
        'session_id': str(ingest_session.id),
        'status': 'enqueued',
        'message': f'Import task enqueued for dataset: {ingest_session.dataset_name}'
    }
