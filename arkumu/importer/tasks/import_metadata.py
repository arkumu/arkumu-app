"""
Enhanced Import Metadata Tasks

This module provides Huey tasks for CSV import with enhanced mapping integration support.
The tasks now support:

1. Mapping-driven imports with MappingAdapter integration
2. Automatic execution strategy selection
3. File-to-dataset validation and matching
4. Enhanced error handling and progress tracking
5. Backward compatibility with existing API

Key Features:
- run_csv_import_workflow_with_mapping: Enhanced task with mapping support
- run_csv_import_workflow: Legacy wrapper for backward compatibility
- Execution strategies: auto, mapping_driven, entity_centric
- File validation against mapping requirements
- Enhanced progress tracking with mapping-aware status updates
"""

import logging
import uuid
from typing import List, Dict, Optional, Tuple, Set, Any
from uuid import UUID
import os
import tempfile # Added for temporary file creation in the task

# Huey imports
from huey.contrib.djhuey import db_task, task, db_periodic_task
# Try importing configured Huey instance, fallback to default djhuey
# This mirrors the pattern in lacos/lacos/ingest/tasks.py for consistency
try:
    # Assuming arkumu might have a similar central huey config in the future
    # For now, this will likely use the except block if 'arkumu.config.huey' doesn't exist.
    from arkumu.config.huey import HUEY as arkumu_huey_instance
except ImportError:
    # Fallback to the HUEY instance presumably configured for djhuey globally, 
    # often imported from settings or a central djhuey config.
    # If config.settings.base.HUEY is the one djhuey uses by default, 
    # then @db_task() will pick it up automatically.
    from config.settings.base import HUEY as arkumu_huey_instance 
    # If huey is imported here, it represents the default instance djhuey should be using.
    # Thus, it should not be passed explicitly to @db_task.

# Arkumu specific imports
from arkumu.importer.services.orchestrator.import_orchestrator import ImportOrchestrator
from arkumu.common.enums import UpdateStrategy
from arkumu.common.data_types import BulkUpdateStats
from arkumu.common.uri_utils import normalize_string_nfc
# REMOVED: from arkumu.common.import_service_bridge import bridge_service  # OLD SYSTEM ELIMINATED
from arkumu.storage.services.bucket_service import BucketService # Added to download S3 file

# Django cache
from django.core.cache import cache
from arkumu.importer.models import IngestSession # Import IngestSession instead of UploadSession
from django.utils import timezone
from arkumu.importer.services.task_manager import get_task_manager, cancellable_task, CancellationReason
from huey.exceptions import CancelExecution

# Import progress estimation
from arkumu.importer.services.progress import progress_estimator, ExecutionStrategy

# Schema service for complete schema management
from arkumu.importer.services.schema_service import SchemaService

logger = logging.getLogger(__name__)

@cancellable_task()
@db_task(retries=1, retry_delay=60)
def run_mapping_aware_import_workflow(
    s3_bucket_name: str,
    s3_object_key: str,
    dataset_name: str,
    institution: str,
    mapping_id: str,
    base_uri: str = "http://arkumu.org/data",
    upload_session_id: Optional[UUID] = None,
    csv_sources: Optional[Dict[str, Any]] = None,
    update_progress: Optional[callable] = None,
    task_context: Optional[Any] = None,
    processing_strategy: Optional[str] = None
) -> Dict[str, Any]:
    """
    Mapping-aware Huey task that implements the full production integration workflow
    from test_00_full_integration.py. This task processes CSV files using the
    MappingAwareProcessor with real execution config and CSV data.

    Args:
        s3_bucket_name: Name of the S3 bucket where the CSV file is located
        s3_object_key: The S3 object key (path) for the CSV file
        dataset_name: Name to assign to the dataset being imported
        institution: Identifier for the institution owning the data
        mapping_id: ID of the mapping configuration to use (required)
        base_uri: Base URI for generating resource URIs
        task_id_for_cache: Explicit task ID for caching
        upload_session_id: ID of the IngestSession to update
        csv_sources: Optional pre-loaded CSV data sources

    Returns:
        A dictionary containing the status of the import and execution metrics
    """
    # Check if we have an ImportTask record for this dataset and session
    actual_task_id = None
    if upload_session_id:
        from arkumu.importer.models import ImportTask
        try:
            import_task = ImportTask.objects.get(
                ingest_session_id=upload_session_id,
                dataset_name=dataset_name,
                file_path=s3_object_key
            )
            actual_task_id = import_task.task_id
            logger.info(f"Found ImportTask for dataset '{dataset_name}' with task_id: {actual_task_id}")
        except ImportTask.DoesNotExist:
            logger.warning(f"No ImportTask found for dataset '{dataset_name}' in session {upload_session_id} - Creating one automatically")
            # Create missing ImportTask record
            try:
                ingest_session = IngestSession.objects.get(id=upload_session_id)
                unique_task_id = str(uuid.uuid4())
                
                import_task = ImportTask.objects.create(
                    ingest_session=ingest_session,
                    dataset_name=dataset_name,
                    file_path=s3_object_key,
                    task_id=unique_task_id,
                    status='pending'
                )
                actual_task_id = import_task.task_id
                logger.info(f"Created ImportTask for dataset '{dataset_name}' with task_id: {actual_task_id}")
            except IngestSession.DoesNotExist:
                logger.error(f"CRITICAL: IngestSession {upload_session_id} not found - Cannot create ImportTask")
                raise Exception(f"IngestSession {upload_session_id} not found for dataset '{dataset_name}'")
    
    if not actual_task_id:
        raise Exception("No task ID available - ImportTask record is required")
    
    # Use consistent cache key pattern with progress view
    cache_key = f"task_state_{actual_task_id}" if actual_task_id else None

    def update_cache_with_phase_info(status: str, message: str, progress: int, 
                                   phase_info: Optional[Dict] = None, 
                                   details: Optional[Dict] = None, 
                                   error_type: Optional[str] = None):
        # Use the task manager's progress update if available
        if 'update_progress' in locals() and callable(locals()['update_progress']):
            try:
                locals()['update_progress'](progress, phase_info.get('current_phase', 'processing'), message, details)
            except CancelExecution:
                raise  # Re-raise cancellation
            except Exception as e:
                logger.warning(f"Failed to update via task manager: {e}")
        
        if cache_key:
            payload = {
                "status": status,
                "message": message,
                "percentage": progress,  # Use 'percentage' to match progress view expectations
                "event_type": "progress",
                "timestamp": timezone.now().isoformat()
            }
            
            if phase_info:
                payload["phase_info"] = phase_info
            if details:
                payload["details"] = details
            if error_type:
                payload["error_type"] = error_type
                
            cache.set(cache_key, payload, timeout=3600)
            logger.info(f"Task {actual_task_id or 'UnknownID'}: Cache updated - Key: {cache_key}, Status: {status}, Message: {message[:50]}...")
            logger.info(f"Task {actual_task_id or 'UnknownID'}: Cache payload: {payload}")

    def update_upload_session_status(status: str, message: Optional[str] = None, files_processed: int = 0, errors_count: int = 0, detailed_stats: Optional[Dict] = None):
        if upload_session_id:
            try:
                session = IngestSession.objects.get(id=upload_session_id)
                session.status = status
                session.completed_at = timezone.now()
                if message:
                    session.error_message = message[:1024]
                if status == 'completed':
                    session.successful_rows = files_processed
                    session.failed_rows = errors_count
                    # Save detailed stats to ingestion_stats field
                    if detailed_stats:
                        session.ingestion_stats = detailed_stats
                elif status == 'failed':
                    session.failed_rows = 1
                session.save()
            except IngestSession.DoesNotExist:
                logger.error(f"Task {actual_task_id or 'UnknownID'}: IngestSession with ID {upload_session_id} not found")
            except Exception as e:
                logger.error(f"Task {actual_task_id or 'UnknownID'}: Error updating IngestSession {upload_session_id}: {e}")

    # Initialize mapping-aware phases
    mapping_phases = [
        "initialization",
        "mapping_load",
        "data_preparation", 
        "mapping_aware_processing",
        "finalization"
    ]
    
    def get_mapping_phase_info(phase_name: str, phase_progress: int = 0) -> Dict:
        try:
            phase_index = mapping_phases.index(phase_name)
        except ValueError:
            phase_index = 0
        
        return {
            "current_phase": phase_name,
            "current_phase_index": phase_index,
            "total_phases": len(mapping_phases),
            "phase_progress": phase_progress,
            "phase_description": get_mapping_phase_description(phase_name),
            "execution_strategy": "mapping_aware"
        }
    
    def get_mapping_phase_description(phase_name: str) -> str:
        descriptions = {
            "initialization": "Initializing mapping-aware import",
            "mapping_load": "Loading and translating mapping configuration",
            "data_preparation": "Preparing CSV data sources",
            "mapping_aware_processing": "Processing with MappingAwareProcessor",
            "finalization": "Finalizing mapping-aware import"
        }
        return descriptions.get(phase_name, "Processing")
    
    logger.info(
        f"Task {actual_task_id or 'UnknownID'}: Starting mapping-aware import workflow for dataset '{dataset_name}' "
        f"from S3 object '{s3_bucket_name}/{s3_object_key}' with mapping ID '{mapping_id}' for institution '{institution}'"
    )
    
    final_metrics = {}

    try:
        # Add cleanup callback for temporary files
        if 'task_context' in locals() and actual_task_id:
            from arkumu.importer.services.task_manager import get_task_manager
            task_manager = get_task_manager()
            task_manager.add_cleanup_callback(actual_task_id, lambda: logger.info(f"Cleaning up task {actual_task_id}"))
        
        # Phase 1: Initialization
        phase_info = get_mapping_phase_info("initialization", 100)
        update_cache_with_phase_info("processing", f"Starting mapping-aware import for {dataset_name}...", 5, phase_info)
        
        # Update ImportTask status to 'processing' in database
        if upload_session_id and import_task:
            from django.utils import timezone
            import_task.status = 'processing'
            import_task.started_at = timezone.now()
            import_task.save()
            logger.info(f"Updated ImportTask {import_task.id} status to 'processing' for dataset '{dataset_name}'")
        
        # Check for cancellation early
        from huey.exceptions import CancelExecution
        if cache.get(f"task_cancel_{actual_task_id}", False):
            logger.info(f"Task {actual_task_id} cancelled during initialization")
            raise CancelExecution(f"Task {actual_task_id} cancelled during initialization")
        
        # Phase 2: Load and translate mapping using MappingAdapter
        phase_info = get_mapping_phase_info("mapping_load", 25)
        update_cache_with_phase_info("processing", "Loading mapping configuration...", 15, phase_info)
        
        from arkumu.metadata.models import Mapping
        from arkumu.importer.services.mapping_consumer.mapping_adapter import MappingAdapter
        from arkumu.importer.services.execution.mapping_aware_processor import MappingAwareProcessor
        from arkumu.importer.services.execution.statistics import ExecutionStatistics
        from arkumu.importer.services.mapping_consumer.config_translator import ProcessingStrategy, ExecutionConfig
        
        # Ensure mapping exists
        try:
            mapping = Mapping.objects.get(id=mapping_id)
        except Mapping.DoesNotExist:
            error_msg = f"Mapping with ID '{mapping_id}' not found. Please create a mapping using the Mapping Generator at /mappings/create before importing."
            logger.error(f"Task {actual_task_id or 'UnknownID'}: {error_msg}")
            phase_info = get_mapping_phase_info("mapping_load", 0)
            update_cache_with_phase_info("failed", error_msg, 0, phase_info, error_type="MappingNotFound")
            update_upload_session_status('failed', error_msg)
            return {
                "status": "error",
                "dataset_name": dataset_name,
                "s3_object_key": s3_object_key,
                "error_message": error_msg,
                "error_type": "MappingNotFound",
                "recovery_suggestion": "Create a mapping using the Mapping Generator GUI at /mappings/create"
            }
        mapping_adapter = MappingAdapter()
        
        # Load and translate mapping using the automated system from test
        logger.info(f"Task {actual_task_id or 'UnknownID'}: Loading mapping: ID={mapping.id}, Name={mapping.name}")
        
        # Load the complete execution config (all datasets for blueprint creation)
        execution_config = mapping_adapter.translate_to_execution_config(mapping_id)
        
        logger.info(f"Task {actual_task_id or 'UnknownID'}: Loaded execution config with {len(execution_config.datasets)} datasets")
        
        # Verify the target dataset exists in the mapping (with consistent URI slugification)
        from arkumu.common.uri_utils import slugify_uri_part
        
        # Apply same slugification to both sides for consistent comparison
        slugified_target_name = slugify_uri_part(dataset_name)
        target_dataset_exists = any(
            slugify_uri_part(ds.dataset_name) == slugified_target_name 
            for ds in execution_config.datasets
        )
        
        if not target_dataset_exists:
            # Log available datasets for debugging
            available_datasets = [ds.dataset_name for ds in execution_config.datasets]
            logger.error(f"Task {actual_task_id or 'UnknownID'}: Dataset '{dataset_name}' (slugified: '{slugified_target_name}') not found. Available: {available_datasets}")
            raise ValueError(f"Dataset '{dataset_name}' not found in mapping configuration")
        
        phase_info = get_mapping_phase_info("mapping_load", 100)
        update_cache_with_phase_info("processing", "Mapping configuration loaded", 25, phase_info)
        
        # Phase 3: Prepare CSV data sources
        phase_info = get_mapping_phase_info("data_preparation", 25)
        update_cache_with_phase_info("processing", "Preparing CSV data sources...", 35, phase_info)
        
        if csv_sources is None:
            # Download and parse CSV from S3 using the same pattern as tests
            import csv
            import io
            
            bucket_service = BucketService()
            
            logger.info(f"Task {actual_task_id or 'UnknownID'}: 📁 Loading CSV data from S3 object {s3_bucket_name}/{s3_object_key}")
            logger.info(f"Task {actual_task_id or 'UnknownID'}: 🔍 BucketService initialized: {bucket_service}")
            
            # Get file content directly using BucketService (same as tests)
            try:
                logger.info(f"Task {actual_task_id or 'UnknownID'}: 📥 Attempting to get file content from S3...")
                result = bucket_service.get_file_content(s3_bucket_name, s3_object_key)
                logger.info(f"Task {actual_task_id or 'UnknownID'}: 📥 S3 get_file_content result type: {type(result)}, keys: {result.keys() if isinstance(result, dict) else 'N/A'}")
                
                if isinstance(result, dict) and 'content' in result:
                    content = result['content']
                    if isinstance(content, bytes):
                        content = content.decode('utf-8')
                    logger.info(f"Task {actual_task_id or 'UnknownID'}: ✅ Successfully extracted content, size: {len(content) if content else 0} bytes")
                else:
                    logger.error(f"Task {actual_task_id or 'UnknownID'}: ❌ Unexpected result format from get_file_content: {result}")
                    raise Exception(f"Unexpected result format from get_file_content: {result}")
            except Exception as s3_error:
                error_msg = (
                    f"Failed to download CSV file '{s3_object_key}' from S3 bucket '{s3_bucket_name}'. "
                    f"Please verify the file exists and you have access permissions."
                )
                logger.error(f"Task {actual_task_id or 'UnknownID'}: ❌ S3 download failed: {s3_error}")
                logger.error(f"Task {actual_task_id or 'UnknownID'}: 📊 S3 Error Details - Type: {type(s3_error).__name__}, Message: {str(s3_error)}")
                phase_info = get_mapping_phase_info("data_preparation", 0)
                update_cache_with_phase_info("failed", error_msg, 0, phase_info, error_type="S3DownloadError")
                update_upload_session_status('failed', error_msg)
                return {
                    "status": "error",
                    "dataset_name": dataset_name,
                    "s3_object_key": s3_object_key,
                    "error_message": error_msg,
                    "error_type": "S3DownloadError",
                    "recovery_suggestion": "Check if the file exists in S3 and verify access permissions",
                    "technical_details": str(s3_error)
                }
            
            # Parse CSV with semicolon delimiter (same as tests)
            logger.info(f"Task {actual_task_id or 'UnknownID'}: 📊 Starting CSV parsing, content preview: {content[:200] if content else 'EMPTY'}...")
            try:
                csv_reader = csv.DictReader(io.StringIO(content), delimiter=';')
                rows = list(csv_reader)
                
                logger.info(f"Task {actual_task_id or 'UnknownID'}: 📋 CSV headers: {csv_reader.fieldnames}")
                logger.info(f"Task {actual_task_id or 'UnknownID'}: ✅ Successfully parsed {len(rows)} rows from S3 CSV")
                
                if len(rows) > 0:
                    logger.info(f"Task {actual_task_id or 'UnknownID'}: 📊 Sample row data: {dict(list(rows[0].items())[:3])}...")
                else:
                    logger.warning(f"Task {actual_task_id or 'UnknownID'}: ⚠️  CSV file appears to be empty or has no data rows")
                
                # Create csv_sources dict in the same format as test fixture
                csv_sources = {dataset_name: {
                    'headers': csv_reader.fieldnames,
                    'rows': rows,
                    'row_count': len(rows)
                }}
                
                logger.info(f"Task {actual_task_id or 'UnknownID'}: 📦 Created csv_sources dict with {len(rows)} rows for dataset '{dataset_name}'")
            except Exception as csv_error:
                logger.error(f"Task {actual_task_id or 'UnknownID'}: ❌ CSV parsing failed: {csv_error}")
                logger.error(f"Task {actual_task_id or 'UnknownID'}: 📊 Content that failed to parse: {content[:500]}...")
                raise
            
            # Only provide CSV data for the target dataset - processor will naturally skip others
        
        logger.info(f"Task {actual_task_id or 'UnknownID'}: Providing CSV data for target dataset: '{dataset_name}'")
        
        phase_info = get_mapping_phase_info("data_preparation", 100)
        update_cache_with_phase_info("processing", "CSV data sources prepared", 45, phase_info)
        
        # Check for cancellation before processing
        if cache.get(f"task_cancel_{actual_task_id}", False):
            logger.info(f"Task {actual_task_id} cancelled before processing")
            raise CancelExecution(f"Task {actual_task_id} cancelled before processing")
        
        # Phase 4: Initialize MappingAwareProcessor and execute
        phase_info = get_mapping_phase_info("mapping_aware_processing", 10)
        update_cache_with_phase_info("processing", "Initializing MappingAwareProcessor with schema-first blueprints...", 50, phase_info)
        
        # Initialize execution statistics
        execution_statistics = ExecutionStatistics()
        
        # Get session and organization for progress updates
        session = None
        channel_id = None
        organization = None
        if upload_session_id:
            try:
                session = IngestSession.objects.get(id=upload_session_id)
                organization = session.organization
                from arkumu.importer.utils.progress import create_channel_id
                channel_id = create_channel_id(session.pk)
            except IngestSession.DoesNotExist:
                logger.warning(f"Task {actual_task_id or 'UnknownID'}: IngestSession with ID {upload_session_id} not found")
        
        # Fallback: resolve organization from institution string if session not available
        if not organization:
            from arkumu.users.models import Organization
            try:
                organization = Organization.objects.get(code=institution)
            except Organization.DoesNotExist:
                logger.error(f"Organization with code '{institution}' not found")
                raise ValueError(f"Organization with code '{institution}' not found")
        
        # Initialize schema service for complete schema management (fix URI consistency)
        schema_service = SchemaService(mapping_id, institution=organization.code, base_uri=base_uri)
        
        # Initialize processor with organization and session for progress updates
        processor = MappingAwareProcessor(
            organization=organization,
            base_uri=base_uri,
            statistics=execution_statistics,
            ingest_session=session,
            channel_id=channel_id
        )
        
        # Ensure schema service has the complete schema cached for post-import operations
        try:
            schema_result = schema_service.create_complete_schema()
            logger.info(f"Schema service cached complete schema for mapping {mapping_id}")
        except Exception as e:
            logger.warning(f"Schema service caching failed (using fallback): {e}")
        
        # Track processing time like in the test
        from datetime import datetime, timezone as dt_timezone
        start_time = datetime.now(dt_timezone.utc)
        
        phase_info = get_mapping_phase_info("mapping_aware_processing", 30)
        update_cache_with_phase_info("processing", "Executing mapping-aware processing...", 60, phase_info)
        
        # Final cancellation check before intensive processing
        if cache.get(f"task_cancel_{actual_task_id}", False):
            logger.info(f"Task {actual_task_id} cancelled before intensive processing")
            raise CancelExecution(f"Task {actual_task_id} cancelled before intensive processing")
        
        # FIXED: Pre-create URI only for the target dataset being processed
        logger.info(f"Task {actual_task_id or 'UnknownID'}: Pre-creating dataset URI for target dataset: '{dataset_name}'")
        
        from arkumu.importer.services.execution.resource_manager import ResourceManager
        resource_manager = ResourceManager(
            institution=institution,
            base_uri=base_uri,
            statistics=execution_statistics
        )
        
        try:
            dataset_resource = resource_manager.create_dataset_resource(dataset_name)
            if dataset_resource:
                logger.info(f"Task {actual_task_id or 'UnknownID'}: Successfully created/verified dataset URI for '{dataset_name}'")
            else:
                logger.warning(f"Task {actual_task_id or 'UnknownID'}: Failed to create dataset URI for '{dataset_name}'")
        except Exception as e:
            logger.error(f"Task {actual_task_id or 'UnknownID'}: Error creating dataset URI for '{dataset_name}': {e}")
            raise
        
        # Execute the mapping-aware processing using STREAMING_ENTITY_CENTRIC strategy
        logger.info(f"Task {actual_task_id or 'UnknownID'}: 🔄 HANDOFF TO PROCESSOR - About to pass csv_sources to MappingAwareProcessor")
        logger.info(f"Task {actual_task_id or 'UnknownID'}: 📊 csv_sources structure: {list(csv_sources.keys()) if csv_sources else 'None'}")
        if csv_sources:
            for ds_name, ds_data in csv_sources.items():
                logger.info(f"Task {actual_task_id or 'UnknownID'}: 📋 Dataset '{ds_name}': {ds_data.get('row_count', 0)} rows, headers: {ds_data.get('headers', [])}")
        logger.info(f"Task {actual_task_id or 'UnknownID'}: 🎯 Target dataset for processing: '{dataset_name}'")
        
        metrics = processor.process_with_execution_config(
            execution_config=execution_config,
            csv_sources=csv_sources,
            strategy=ProcessingStrategy.STREAMING_ENTITY_CENTRIC
        )
        
        end_time = datetime.now(dt_timezone.utc)
        processing_time = (end_time - start_time).total_seconds()
        
        phase_info = get_mapping_phase_info("mapping_aware_processing", 100)
        update_cache_with_phase_info("processing", "Mapping-aware processing completed", 80, phase_info)
        
        # Phase 5: Finalization
        phase_info = get_mapping_phase_info("finalization", 50)
        update_cache_with_phase_info("processing", "Finalizing mapping-aware import...", 85, phase_info)
        
        # Verify processing completed successfully
        if not hasattr(metrics, 'rows_processed') or metrics.rows_processed <= 0:
            error_msg = (
                f"Import completed but no data was processed from '{dataset_name}'. "
                f"This could indicate an empty CSV file, mismatched mapping configuration, "
                f"or data format issues."
            )
            logger.error(f"Task {actual_task_id or 'UnknownID'}: No data processed: {error_msg}")
            phase_info = get_mapping_phase_info("mapping_aware_processing", 100)
            update_cache_with_phase_info("failed", error_msg, 0, phase_info, error_type="NoDataProcessed")
            update_upload_session_status('failed', error_msg)
            return {
                "status": "error",
                "dataset_name": dataset_name,
                "s3_object_key": s3_object_key,
                "error_message": error_msg,
                "error_type": "NoDataProcessed",
                "recovery_suggestion": "Check if CSV file contains data and mapping configuration matches the file structure",
                "debugging_steps": [
                    "Verify CSV file is not empty",
                    "Check mapping configuration matches CSV headers",
                    "Review import logs for data validation errors"
                ]
            }
        
        # Get all detailed metrics from ExecutionMetrics
        detailed_metrics = metrics.to_dict()
        
        # Add mapping-specific metadata
        final_metrics = {
            **detailed_metrics,  # Include ALL ExecutionMetrics stats
            "execution_strategy": "mapping_aware",
            "mapping_id": mapping_id,
            "mapping_name": mapping.name,
            "datasets_processed": len(csv_sources),
            "execution_config_datasets": len(execution_config.datasets),
            "execution_config_columns": sum(len(ds.columns) for ds in execution_config.datasets),
            "execution_config_relationships": len(execution_config.fk_relationships),
            "skipped_datasets": detailed_metrics.get("datasets_skipped", 0)
        }
        
        success_message = (
            f"Mapping-aware import for '{dataset_name}' completed successfully using mapping '{mapping.name}'. "
            f"Processed: {metrics.rows_processed} rows in {processing_time:.2f}s. "
            f"Created: {metrics.resources_created} resources, {metrics.triples_created} triples, {metrics.properties_created} properties."
        )
        
        logger.info("=== MAPPING-AWARE IMPORT RESULTS ===")
        logger.info(f"Task {actual_task_id or 'UnknownID'}: METRICS DEBUG - resources_created: {metrics.resources_created}, triples_created: {metrics.triples_created}, properties_created: {metrics.properties_created}")
        logger.info(f"Task {actual_task_id or 'UnknownID'}: {success_message}")
        logger.info(f"Task {actual_task_id or 'UnknownID'}: Execution config: {len(execution_config.datasets)} datasets, {sum(len(ds.columns) for ds in execution_config.datasets)} columns, {len(execution_config.fk_relationships)} FK relationships")
        logger.info("=== MAPPING-AWARE IMPORT COMPLETED ===")
        
        phase_info = get_mapping_phase_info("finalization", 100)
        update_cache_with_phase_info("completed", success_message, 100, phase_info, details=final_metrics)
        update_upload_session_status('completed', success_message, 1, 0, final_metrics)
        
        # Update ImportTask status to 'completed' in database
        if upload_session_id and import_task:
            from django.utils import timezone
            import_task.status = 'completed'
            import_task.completed_at = timezone.now()
            import_task.rows_processed = metrics.rows_processed
            import_task.save()
            logger.info(f"Updated ImportTask {import_task.id} status to 'completed' for dataset '{dataset_name}'")
        
        return {
            "status": "success",
            "dataset_name": dataset_name,
            "s3_object_key": s3_object_key,
            **final_metrics
        }
        
    except CancelExecution as e:
        cancel_message = f"Task cancelled: {str(e)}"
        logger.info(f"Task {actual_task_id or 'UnknownID'}: {cancel_message}")
        
        # Update cache with cancelled status
        phase_info = get_mapping_phase_info("initialization", 0)
        update_cache_with_phase_info("cancelled", cancel_message, 0, phase_info, error_type="CancelExecution")
        update_upload_session_status('cancelled', cancel_message)
        
        # Update ImportTask status to 'cancelled' in database
        if upload_session_id and 'import_task' in locals():
            import_task.status = 'cancelled'
            import_task.save()
            logger.info(f"Updated ImportTask {import_task.id} status to 'cancelled' for dataset '{dataset_name}'")
        
        return {
            "status": "cancelled",
            "dataset_name": dataset_name,
            "message": cancel_message,
            "cancelled": True
        }
        
    except Exception as e:
        # Enhanced error handling with specific error types and recovery suggestions
        error_type = type(e).__name__
        error_str = str(e)
        
        if "is not a valid UUID" in error_str:
            # Extract the problematic URI from the error message
            uri_match = error_str.split('"')[1] if '"' in error_str else "property URI"
            error_message = (
                f"Mapping configuration error for '{dataset_name}': Invalid UUID format detected. "
                f"The system found a URI ('{uri_match}') where a UUID was expected. "
                f"This usually indicates a mapping configuration issue."
            )
            recovery_suggestion = "Update the mapping configuration to use proper UUID values instead of URIs for property definitions"
            error_type = "MappingConfigurationError"
        elif "ValidationError" in error_type and "property" in error_str.lower():
            error_message = (
                f"Property validation error in mapping for '{dataset_name}'. "
                f"The mapping contains invalid property definitions that don't match the expected format."
            )
            recovery_suggestion = "Review and update the mapping configuration using the Mapping Generator to fix property definitions"
            error_type = "PropertyValidationError"
        elif "permission" in error_str.lower() or "access" in error_str.lower():
            error_message = f"Access denied while importing '{dataset_name}'. Please check S3 permissions and file access rights."
            recovery_suggestion = "Verify S3 bucket permissions and ensure the file is accessible"
        elif "connection" in error_str.lower() or "network" in error_str.lower():
            error_message = f"Network error during import of '{dataset_name}'. Please check your connection and try again."
            recovery_suggestion = "Check network connectivity and retry the import"
        elif "memory" in error_str.lower() or "out of memory" in error_str.lower():
            error_message = f"Insufficient memory to process '{dataset_name}'. The file may be too large for current resources."
            recovery_suggestion = "Try importing a smaller file or contact system administrator for resource allocation"
        elif "timeout" in error_str.lower():
            error_message = f"Import of '{dataset_name}' timed out. The file may be too large or complex."
            recovery_suggestion = "Try splitting the data into smaller files or contact support"
        else:
            error_message = f"Unexpected error importing '{dataset_name}': {str(e)}"
            recovery_suggestion = "Please contact support with the error details below"
        
        logger.error(
            f"Task {actual_task_id or 'UnknownID'}: Mapping-aware import failed: {e}",
            exc_info=True
        )
        
        phase_info = get_mapping_phase_info("initialization", 0)
        update_cache_with_phase_info("failed", error_message, 0, phase_info, error_type=error_type)
        update_upload_session_status('failed', error_message)
        
        # Update ImportTask status to 'failed' in database
        if upload_session_id and 'import_task' in locals():
            import_task.status = 'failed'
            import_task.error_message = error_message[:1024]  # Truncate to fit field
            import_task.save()
            logger.info(f"Updated ImportTask {import_task.id} status to 'failed' for dataset '{dataset_name}'")
        
        return {
            "status": "error",
            "dataset_name": dataset_name,
            "s3_object_key": s3_object_key,
            "error_message": error_message,
            "error_type": error_type,
            "recovery_suggestion": recovery_suggestion,
            "technical_details": str(e),
            "contact_support": True if "unexpected error" in error_message.lower() else False,
            "gui_redirect": "/mappings/" + mapping_id + "/edit" if "mapping" in error_message.lower() and mapping_id else None,
            "user_action_required": "mapping" in error_message.lower() or "configuration" in error_message.lower()
        }
    
    finally:
        # No cleanup needed - using in-memory processing like tests
        pass


@db_task(retries=1, retry_delay=60)
def run_csv_import_workflow_with_mapping(
    # csv_path: str, # Removed: task will download its own file
    s3_bucket_name: str, # Added
    s3_object_key: str,  # Added
    dataset_name: str,
    institution: str,
    base_uri: str = "http://arkumu.org/data",
    delimiter: str = ';',
    has_quoted_fields: bool = True,
    link_row_cells: bool = True,
    link_to_first_column: bool = False,
    update_strategy: UpdateStrategy = UpdateStrategy.SKIP_EXISTING,
    task_id_for_cache: Optional[str] = None,
    upload_session_id: Optional[UUID] = None, # Added ingest_session_id (keeping param name for compatibility)
    # Enhanced mapping parameters
    mapping_id: Optional[str] = None,
    execution_strategy: str = "auto",
    validation_mode: bool = True,
    file_dataset_mapping: Optional[Dict[str, str]] = None,
    use_mapping: bool = False,
    use_table_services: bool = False
) -> Dict[str, Any]:
    """
    Enhanced Huey task to import a CSV file with mapping integration support.
    The task now downloads the CSV from S3 to a local temporary file before processing.
    It updates its status in Django's cache, updates the corresponding IngestSession,
    and cleans up the temporary file.

    Args:
        s3_bucket_name: Name of the S3 bucket where the CSV file is located.
        s3_object_key: The S3 object key (path) for the CSV file.
        dataset_name: Name to assign to the dataset being imported.
        institution: Identifier for the institution owning the data.
        base_uri: Base URI for generating resource URIs.
        delimiter: Character used as a delimiter in the CSV file.
        has_quoted_fields: Boolean indicating if fields in CSV are quoted.
        link_row_cells: Whether to create links between cells of the same row.
        link_to_first_column: Specific linking strategy (maps to SmartBulkUpdater's topology via WorkflowService).
        update_strategy: The strategy to use for handling existing data (e.g., SKIP_EXISTING, UPDATE_VALUES).
        task_id_for_cache: Explicit task ID for caching.
        upload_session_id: ID of the IngestSession to update (keeping param name for compatibility).
        mapping_id: Optional ID of the mapping configuration to use.
        execution_strategy: Strategy for execution ("auto", "entity_centric", "mapping_driven").
        validation_mode: Whether to validate files against mapping requirements.
        file_dataset_mapping: Optional manual mapping of files to datasets.
        use_mapping: Whether to use mapping-based processing.
        use_table_services: Whether to use table-based services.

    Returns:
        A dictionary containing the status of the import and key statistics.
    """
    # Use task_id_for_cache if provided, otherwise fall back to upload_session_id
    # Check if we have an ImportTask record for this dataset and session
    actual_task_id = None
    if upload_session_id:
        from arkumu.importer.models import ImportTask
        try:
            import_task = ImportTask.objects.get(
                ingest_session_id=upload_session_id,
                dataset_name=dataset_name,
                file_path=s3_object_key
            )
            actual_task_id = import_task.task_id
            logger.info(f"Found ImportTask for dataset '{dataset_name}' with task_id: {actual_task_id}")
        except ImportTask.DoesNotExist:
            logger.info(f"No ImportTask found for dataset '{dataset_name}' in session {upload_session_id}")
    
    # Fallback to generated ID if no ImportTask found
    if not actual_task_id:
        actual_task_id = task_id_for_cache if task_id_for_cache else str(uuid.uuid4())
    
    # Only use Huey's task ID if no custom ID was provided
    if not actual_task_id and hasattr(run_csv_import_workflow_with_mapping, 'request') and run_csv_import_workflow_with_mapping.request.id:
        actual_task_id = run_csv_import_workflow_with_mapping.request.id
    
    if not actual_task_id:
        logger.warning(f"Task ID for caching not available for CSV import: {dataset_name}, S3 key: {s3_object_key}. Status polling may not work.")
    
    logger.info(f"Task {actual_task_id}: Starting CSV import for dataset '{dataset_name}' with unique task ID (session: {upload_session_id})")
    
    cache_key = f"task_state_{actual_task_id}" if actual_task_id else None

    def update_cache(status: str, message: str, progress: int, details: Optional[Dict] = None, error_type: Optional[str] = None):
        if cache_key:
            payload = {"status": status, "message": message, "progress": progress}
            if details:
                payload["details"] = details
            if error_type:
                payload["error_type"] = error_type
            cache.set(cache_key, payload, timeout=3600)
            logger.info(f"Task {actual_task_id or 'UnknownID'}: Cache updated - Key: {cache_key}, Status: {status}, Message: {message[:50]}...")
        else:
            logger.warning(f"Task {actual_task_id or 'UnknownID'}: Cannot update cache - cache_key is None")
    
    def update_cache_with_phase_info(status: str, message: str, progress: int, 
                                   phase_info: Optional[Dict] = None, 
                                   details: Optional[Dict] = None, 
                                   error_type: Optional[str] = None):
        """
        Enhanced cache update function with phase information support.
        
        Args:
            status: Task status (pending, processing, completed, failed)
            message: Progress message
            progress: Overall progress percentage (0-100)
            phase_info: Dict containing phase information:
                - current_phase: Name of current phase
                - current_phase_index: Index of current phase (0-based)
                - total_phases: Total number of phases
                - phase_progress: Progress within current phase (0-100)
                - phase_description: Description of current phase
                - execution_strategy: Strategy being used (mapping_driven, entity_centric, etc.)
            details: Additional details about the task
            error_type: Error type if status is failed
        """
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
                    "execution_strategy": phase_info.get("execution_strategy", "standard")
                }
            
            if details:
                payload["details"] = details
            if error_type:
                payload["error_type"] = error_type
                
            cache.set(cache_key, payload, timeout=3600)
            
            phase_msg = f" (Phase {phase_info.get('current_phase_index', 0) + 1}/{phase_info.get('total_phases', 1)}: {phase_info.get('current_phase', 'unknown')})" if phase_info else ""
            logger.info(f"Task {actual_task_id or 'UnknownID'}: Cache updated - Key: {cache_key}, Status: {status}, Message: {message[:50]}...{phase_msg}")
        else:
            logger.warning(f"Task {actual_task_id or 'UnknownID'}: Cannot update cache - cache_key is None")

    # Update IngestSession helper (updated from UploadSession)
    def update_upload_session_status(status: str, message: Optional[str] = None, files_processed: int = 0, errors_count: int = 0):
        if upload_session_id:
            try:
                session = IngestSession.objects.get(id=upload_session_id)
                session.status = status
                session.completed_at = timezone.now()
                if message:
                    session.error_message = message[:1024] # Using error_message field from IngestSession
                if status == 'completed':
                    session.successful_rows = files_processed # Track successful rows instead of files processed
                    session.failed_rows = errors_count
                elif status == 'failed':
                    session.failed_rows = 1 # Or a more specific count if available
                session.save()
            except IngestSession.DoesNotExist:
                logger.error(f"Task {actual_task_id or 'UnknownID'}: IngestSession with ID {upload_session_id} not found for update.")
            except Exception as e_us:
                logger.error(f"Task {actual_task_id or 'UnknownID'}: Error updating IngestSession {upload_session_id}: {e_us}", exc_info=True)

    # Initialize phase tracking
    execution_phases = [
        "initialization",
        "file_download", 
        "mapping_validation",
        "file_validation",
        "strategy_selection",
        "data_import",
        "finalization"
    ]
    
    def get_phase_info(phase_name: str, phase_progress: int = 0) -> Dict:
        """Get phase information for progress tracking with complexity estimation."""
        try:
            phase_index = execution_phases.index(phase_name)
        except ValueError:
            phase_index = 0
        
        # Basic phase info
        phase_info = {
            "current_phase": phase_name,
            "current_phase_index": phase_index,
            "total_phases": len(execution_phases),
            "phase_progress": phase_progress,
            "phase_description": get_phase_description(phase_name),
            "execution_strategy": chosen_strategy if 'chosen_strategy' in locals() else "auto"
        }
        
        # Enhance with complexity-aware progress estimation if mapping is available
        if 'execution_config' in locals() and execution_config:
            try:
                strategy = ExecutionStrategy.MAPPING_DRIVEN if chosen_strategy == "mapping_driven" else ExecutionStrategy.ENTITY_CENTRIC
                enhanced_info = progress_estimator.get_enhanced_progress_info(
                    current_phase=phase_name,
                    phase_progress=phase_progress,
                    strategy=strategy,
                    mapping_config=execution_config.dict() if hasattr(execution_config, 'dict') else None
                )
                
                # Add enhanced information
                phase_info.update({
                    "enhanced_progress": enhanced_info["overall_progress"],
                    "complexity_score": enhanced_info["complexity_score"],
                    "estimated_duration": enhanced_info["current_phase_estimate"]["estimated_duration"] if enhanced_info["current_phase_estimate"] else None,
                    "complexity_factor": enhanced_info["current_phase_estimate"]["complexity_factor"] if enhanced_info["current_phase_estimate"] else None
                })
            except Exception as e:
                logger.warning(f"Failed to get enhanced progress info: {e}")
        
        return phase_info
    
    def get_phase_description(phase_name: str) -> str:
        """Get user-friendly description for each phase."""
        descriptions = {
            "initialization": "Preparing import task",
            "file_download": "Downloading file from S3",
            "mapping_validation": "Validating mapping configuration",
            "file_validation": "Validating file structure",
            "strategy_selection": "Selecting execution strategy",
            "data_import": "Importing data",
            "finalization": "Finalizing import"
        }
        return descriptions.get(phase_name, "Processing")
    
    # Phase 1: Initialization
    phase_info = get_phase_info("initialization", 50)
    update_cache_with_phase_info("processing", f"Starting import for {dataset_name} from S3: {s3_bucket_name}/{s3_object_key}...", 5, phase_info)

    logger.info(
        f"Task {actual_task_id or 'UnknownID'}: Starting CSV import workflow for dataset '{dataset_name}' "
        f"from S3 object '{s3_bucket_name}/{s3_object_key}' for institution '{institution}'. Strategy: {update_strategy.name}. "
        f"IngestSession ID: {upload_session_id}. Cache key: {cache_key}"
    )
    
    temp_local_path = None # To store the path of the downloaded temp file
    final_stats_dict = {}

    try:
        bucket_service = BucketService() # Instantiate service for S3 ops

        # Create a temporary file for downloading the CSV
        # The file will be created in the Huey worker's /tmp directory (or OS default)
        with tempfile.NamedTemporaryFile(mode='w+b', suffix='.csv', delete=False) as temp_file_obj:
            temp_local_path = temp_file_obj.name
        
        logger.info(f"Task {actual_task_id or 'UnknownID'}: Downloading S3 object {s3_bucket_name}/{s3_object_key} to temporary file {temp_local_path}")
        
        # Phase 2: File Download
        phase_info = get_phase_info("file_download", 25)
        update_cache_with_phase_info("processing", f"Downloading file {os.path.basename(s3_object_key)}...", 10, phase_info)

        bucket_service.base_s3_service.s3_client.download_file(
            s3_bucket_name, 
            s3_object_key, 
            temp_local_path
        )
        logger.info(f"Task {actual_task_id or 'UnknownID'}: Successfully downloaded to {temp_local_path}")
        
        # Update file download phase completion
        phase_info = get_phase_info("file_download", 100)
        update_cache_with_phase_info("processing", f"File download completed", 15, phase_info)
        
        # Transition to next phase
        phase_info = get_phase_info("mapping_validation", 0)
        update_cache_with_phase_info("processing", f"Processing downloaded file {os.path.basename(temp_local_path)} for {dataset_name}...", 20, phase_info)
        
        # Enhanced mapping configuration handling
        mapping_config = None
        execution_config = None
        file_matcher = None
        
        # Phase 1: Load and validate mapping configuration
        if use_mapping and mapping_id:
            try:
                from arkumu.metadata.models import Mapping
                from arkumu.importer.services.mapping_consumer.mapping_adapter import MappingAdapter
                from arkumu.importer.services.file_matching.file_dataset_matcher import FileDatasetMatcher
                
                # Phase 3: Mapping Validation - Loading
                phase_info = get_phase_info("mapping_validation", 20)
                update_cache_with_phase_info("processing", f"Loading mapping configuration...", 25, phase_info)
                
                # Load the mapping
                try:
                    mapping = Mapping.objects.get(id=mapping_id)
                except Mapping.DoesNotExist:
                    error_msg = (
                        f"Mapping with ID '{mapping_id}' not found. "
                        f"Please create the mapping using the Mapping Generator before importing."
                    )
                    logger.error(f"Task {actual_task_id or 'UnknownID'}: {error_msg}")
                    phase_info = get_phase_info("mapping_validation", 0)
                    update_cache_with_phase_info("failed", error_msg, 0, phase_info, error_type="MappingNotFound")
                    update_upload_session_status('failed', error_msg)
                    return {
                        "status": "error",
                        "dataset_name": dataset_name,
                        "s3_object_key": s3_object_key,
                        "error_message": error_msg,
                        "error_type": "MappingNotFound",
                        "recovery_suggestion": "Create a mapping using the Mapping Generator GUI",
                        "gui_redirect": "/mappings/create"
                    }
                adapter = MappingAdapter()
                
                # Validate mapping if validation mode is enabled
                if validation_mode:
                    # Phase 3: Mapping Validation - Validating
                    phase_info = get_phase_info("mapping_validation", 50)
                    update_cache_with_phase_info("processing", f"Validating mapping configuration...", 27, phase_info)
                    validation_result = adapter.validate_mapping(mapping_id)
                    
                    if not validation_result.is_valid:
                        error_msg = f"Mapping validation failed: {'; '.join(validation_result.errors)}"
                        logger.error(f"Task {actual_task_id or 'UnknownID'}: {error_msg}")
                        phase_info = get_phase_info("mapping_validation", 100)
                        update_cache_with_phase_info("failed", error_msg, 0, phase_info, error_type="MappingValidationError")
                        update_upload_session_status('failed', error_msg)
                        return {
                            "status": "error",
                            "dataset_name": dataset_name,
                            "s3_object_key": s3_object_key,
                            "error_message": error_msg,
                            "error_type": "MappingValidationError"
                        }
                
                # Translate mapping to execution config
                execution_config = adapter.translate_to_execution_config(mapping_id)
                
                # Initialize file matcher for dataset matching
                file_matcher = FileDatasetMatcher()
                
                logger.info(f"Task {actual_task_id or 'UnknownID'}: Using mapping '{mapping.name}' (ID: {mapping_id})")
                logger.info(f"Task {actual_task_id or 'UnknownID'}: Execution config loaded with {len(execution_config.datasets)} datasets")
                
            except Exception as e:
                error_msg = f"Failed to load mapping {mapping_id}: {str(e)}"
                logger.warning(f"Task {actual_task_id or 'UnknownID'}: {error_msg}")
                
                if validation_mode:
                    # In validation mode, mapping errors are fatal
                    phase_info = get_phase_info("mapping_validation", 100)
                    update_cache_with_phase_info("failed", error_msg, 0, phase_info, error_type="MappingLoadError")
                    update_upload_session_status('failed', error_msg)
                    return {
                        "status": "error",
                        "dataset_name": dataset_name,
                        "s3_object_key": s3_object_key,
                        "error_message": error_msg,
                        "error_type": "MappingLoadError"
                    }
                else:
                    # In non-validation mode, fall back to entity-based import
                    phase_info = get_phase_info("mapping_validation", 100)
                    update_cache_with_phase_info("processing", f"Warning: Failed to load mapping, using entity-based import", 30, phase_info)
        
        # Phase 4: File validation and dataset matching
        if execution_config and file_matcher:
            try:
                # Phase 4: File Validation
                phase_info = get_phase_info("file_validation", 30)
                update_cache_with_phase_info("processing", f"Validating file structure against mapping...", 35, phase_info)
                
                # Validate file against mapping requirements
                selected_files = [temp_local_path]
                match_result = file_matcher.match_files_to_datasets(
                    selected_files=selected_files,
                    execution_config=execution_config,
                    base_directory=None
                )
                
                if not match_result.successful_matches:
                    if validation_mode:
                        error_msg = (
                            f"CSV file '{os.path.basename(temp_local_path)}' structure does not match any dataset "
                            f"in the selected mapping. The file headers or format may not align with the mapping configuration."
                        )
                        logger.error(f"Task {actual_task_id or 'UnknownID'}: {error_msg}")
                        phase_info = get_phase_info("file_validation", 100)
                        update_cache_with_phase_info("failed", error_msg, 0, phase_info, error_type="FileStructureMismatch")
                        update_upload_session_status('failed', error_msg)
                        return {
                            "status": "error",
                            "dataset_name": dataset_name,
                            "s3_object_key": s3_object_key,
                            "error_message": error_msg,
                            "error_type": "FileStructureMismatch",
                            "recovery_suggestion": "Update the mapping to match your CSV file structure or modify the CSV to match the mapping",
                            "debugging_steps": [
                                "Compare CSV headers with mapping dataset definitions",
                                "Check for extra/missing columns in CSV",
                                "Verify CSV delimiter and format settings",
                                "Update mapping using the Mapping Generator if needed"
                            ],
                            "gui_redirect": f"/mappings/{mapping_id}/edit"
                        }
                    else:
                        logger.warning(f"Task {actual_task_id or 'UnknownID'}: File validation failed, proceeding with entity-based import")
                else:
                    # Log successful matches
                    for match in match_result.successful_matches:
                        logger.info(f"Task {actual_task_id or 'UnknownID'}: File matched to dataset '{match.dataset_name}' with confidence {match.confidence:.2f}")
                        
                        # Update file_dataset_mapping if not provided
                        if not file_dataset_mapping:
                            file_dataset_mapping = {temp_local_path: match.dataset_name}
                
            except Exception as e:
                error_msg = f"File validation failed: {str(e)}"
                logger.error(f"Task {actual_task_id or 'UnknownID'}: {error_msg}")
                
                if validation_mode:
                    phase_info = get_phase_info("file_validation", 100)
                    update_cache_with_phase_info("failed", error_msg, 0, phase_info, error_type="FileValidationError")
                    update_upload_session_status('failed', error_msg)
                    return {
                        "status": "error",
                        "dataset_name": dataset_name,
                        "s3_object_key": s3_object_key,
                        "error_message": error_msg,
                        "error_type": "FileValidationError"
                    }
                else:
                    logger.warning(f"Task {actual_task_id or 'UnknownID'}: File validation failed, proceeding with entity-based import")
        
        # Phase 5: Always use STREAMING_ENTITY_CENTRIC strategy
        chosen_strategy = "streaming_entity_centric"
        
        # Phase 5: Strategy Selection
        phase_info = get_phase_info("strategy_selection", 50)
        update_cache_with_phase_info("processing", f"Using STREAMING_ENTITY_CENTRIC strategy for dataset-entity linking...", 38, phase_info)
        
        logger.info(f"Task {actual_task_id or 'UnknownID'}: Always using STREAMING_ENTITY_CENTRIC strategy to ensure dataset-entity linking")
        
        # Update strategy selection completion
        phase_info = get_phase_info("strategy_selection", 100)
        phase_info["execution_strategy"] = chosen_strategy
        update_cache_with_phase_info("processing", f"Using {chosen_strategy} strategy with guaranteed dataset-entity linking...", 40, phase_info)
        
        # Phase 6: Execute import based on chosen strategy
        # Get organization (this is a simplified version - in production you'd get it from the session)
        from arkumu.metadata.models import Organization
        organization = Organization.objects.get(code=institution)
        
        # Prepare session dictionary for advanced features
        session_dict = {}
        if execution_config:
            session_dict['execution_config'] = execution_config
        if file_dataset_mapping:
            session_dict['file_dataset_mapping'] = file_dataset_mapping
        
        # Ensure we have a valid mapping_id for STREAMING_ENTITY_CENTRIC strategy
        if not mapping_id:
            error_msg = (
                f"A mapping is required for importing dataset '{dataset_name}'. "
                f"Please create a mapping using the Mapping Generator before importing this CSV file."
            )
            logger.error(f"Task {actual_task_id or 'UnknownID'}: {error_msg}")
            phase_info = get_phase_info("data_import", 0)
            update_cache_with_phase_info("failed", error_msg, 0, phase_info, error_type="MappingRequired")
            update_upload_session_status('failed', error_msg)
            return {
                "status": "error",
                "dataset_name": dataset_name,
                "s3_object_key": s3_object_key,
                "error_message": error_msg,
                "error_type": "MappingRequired",
                "recovery_suggestion": "Create a mapping for this dataset using the Mapping Generator GUI at /mappings/create",
                "user_action_required": True,
                "gui_redirect": "/mappings/create"
            }
        
        # Always use mapping processor with STREAMING_ENTITY_CENTRIC strategy  
        logger.info(f"Task {actual_task_id or 'UnknownID'}: Using MappingAwareProcessor with schema-first blueprints and STREAMING_ENTITY_CENTRIC strategy for dataset-entity linking")
        
        # Phase 6: Data Import - Mapping-aware with STREAMING_ENTITY_CENTRIC
        phase_info = get_phase_info("data_import", 10)
        phase_info["execution_strategy"] = "streaming_entity_centric"
        update_cache_with_phase_info("processing", f"Executing STREAMING_ENTITY_CENTRIC import with dataset-entity linking...", 45, phase_info)
        
        # Always call the mapping-aware import workflow with STREAMING_ENTITY_CENTRIC
        result = run_mapping_aware_import_workflow(
            s3_bucket_name=s3_bucket_name,
            s3_object_key=s3_object_key, 
            dataset_name=dataset_name,
            institution=institution,
            mapping_id=mapping_id,
            base_uri=base_uri,
            upload_session_id=upload_session_id,
            csv_sources=None,  # Let it load from S3
            update_progress=None,
            task_context=None
        )
        
        # Convert result to BulkUpdateStats format for compatibility
        stats = BulkUpdateStats(stats={
            "rows_processed": result.get("rows_processed", 0),
            "resources_created": result.get("resources_created", 0), 
            "triples_created": result.get("triples_created", 0),
            "errors": 0 if result.get("status") == "success" else 1
        })
        
        # Phase 6: Data Import - Completion
        phase_info = get_phase_info("data_import", 100)
        phase_info["execution_strategy"] = chosen_strategy
        update_cache_with_phase_info("processing", f"Data import completed, processing results...", 70, phase_info)
        
        # Phase 7: Finalization
        phase_info = get_phase_info("finalization", 30)
        phase_info["execution_strategy"] = chosen_strategy
        update_cache_with_phase_info("processing", f"Finalizing import for {dataset_name}...", 80, phase_info)

        # The 'stats' variable here is the dictionary returned by ImportWorkflowService,
        # and the actual BulkUpdateStats fields are in a nested dictionary under the key "stats".
        actual_stats_data = stats.get("stats", {}) 

        final_stats_dict = {
            "rows_processed": actual_stats_data.get("rows_processed", 0),
            "cells_processed": actual_stats_data.get("cells_processed", 0),
            "resources_created": actual_stats_data.get("resources_created", 0),
            "resources_updated": actual_stats_data.get("resources_updated", 0),
            "resources_skipped": actual_stats_data.get("resources_skipped", 0),
            "triples_created": actual_stats_data.get("triples_created", 0),
            "triples_updated": actual_stats_data.get("triples_updated", 0),
            "triples_skipped": actual_stats_data.get("triples_skipped", 0),
            # "row_links_created": actual_stats_data.get("row_links_created", 0), # This might not be in smart_updater stats, check SmartBulkUpdater return
            "errors": actual_stats_data.get("errors", 0),
            # "truncated_values": actual_stats_data.get("truncated_values", 0) # This might not be in smart_updater stats
            # Enhanced mapping-aware statistics
            "execution_strategy": chosen_strategy,
            "mapping_used": mapping_id is not None,
            "mapping_id": mapping_id,
            "file_dataset_mapping": file_dataset_mapping,
            "validation_mode": validation_mode
        }
        
        # Enhanced success message with mapping information
        success_message = (
            f"Dataset '{dataset_name}' (from S3 object {s3_object_key}) imported successfully using {chosen_strategy} strategy. "
            f"Processed: {actual_stats_data.get('rows_processed', 0)} rows. "
            f"Created: {actual_stats_data.get('resources_created', 0)} resources, {actual_stats_data.get('triples_created', 0)} triples. "
            f"Errors: {actual_stats_data.get('errors', 0)}."
        )
        
        if mapping_id:
            success_message += f" Mapping ID: {mapping_id}."
        
        if file_dataset_mapping:
            matched_dataset = file_dataset_mapping.get(temp_local_path, "unknown")
            success_message += f" Matched to dataset: {matched_dataset}."
        # Phase 7: Finalization - Complete
        phase_info = get_phase_info("finalization", 100)
        phase_info["execution_strategy"] = chosen_strategy
        update_cache_with_phase_info("completed", success_message, 100, phase_info, details=final_stats_dict)
        logger.info(f"Task {actual_task_id or 'UnknownID'}: Updated cache with 'completed' status. Cache key: {cache_key}")
        update_upload_session_status('completed', success_message, 1, final_stats_dict['errors']) # 1 file processed
        
        logger.info(
            f"Task {actual_task_id or 'UnknownID'}: CSV import workflow for dataset '{dataset_name}' (from S3 object {s3_object_key}) completed successfully. "
            f"Stats - Rows: {actual_stats_data.get('rows_processed', 0)}, Resources Created: {actual_stats_data.get('resources_created', 0)}, "
            f"Triples Created: {actual_stats_data.get('triples_created', 0)}, Errors: {actual_stats_data.get('errors', 0)}"
        )
        
        return {
            "status": "success",
            "dataset_name": dataset_name,
            "s3_object_key": s3_object_key, # For reference
            **final_stats_dict
        }
        
    except Exception as e:
        # Enhanced error handling with detailed categorization
        error_type = type(e).__name__
        error_str = str(e)
        
        # Categorize common import errors with user-friendly messages
        if "is not a valid UUID" in error_str:
            # Extract the problematic URI from the error message
            uri_match = error_str.split('"')[1] if '"' in error_str else "property URI"
            error_message = (
                f"Mapping configuration error for '{dataset_name}': Invalid UUID format detected. "
                f"The system found a URI ('{uri_match}') where a UUID was expected. "
                f"This usually indicates a mapping configuration issue."
            )
            recovery_suggestion = "Update the mapping configuration to use proper UUID values instead of URIs for property definitions"
            error_type = "MappingConfigurationError"
        elif "ValidationError" in error_type and "property" in error_str.lower():
            error_message = (
                f"Property validation error in mapping for '{dataset_name}'. "
                f"The mapping contains invalid property definitions that don't match the expected format."
            )
            recovery_suggestion = "Review and update the mapping configuration using the Mapping Generator to fix property definitions"
            error_type = "PropertyValidationError"
        elif "S3" in error_str or "bucket" in error_str.lower():
            error_message = f"S3 storage error while importing '{dataset_name}'. File may not exist or access is denied."
            recovery_suggestion = "Check if the file exists in S3 and verify access permissions"
        elif "CSV" in error_str or "delimiter" in error_str.lower() or "encoding" in error_str.lower():
            error_message = f"CSV format error in '{dataset_name}'. The file format may be invalid or corrupted."
            recovery_suggestion = "Verify CSV file format, encoding (UTF-8), and delimiter settings"
        elif "mapping" in error_str.lower():
            error_message = f"Mapping configuration error for '{dataset_name}'. The mapping may be invalid or incompatible."
            recovery_suggestion = "Review and update the mapping configuration using the Mapping Generator"
        elif "database" in error_str.lower() or "connection" in error_str.lower():
            error_message = f"Database error during import of '{dataset_name}'. System may be temporarily unavailable."
            recovery_suggestion = "Wait a moment and try again. If the problem persists, contact support"
        else:
            error_message = f"Import failed for '{dataset_name}': {str(e)}"
            recovery_suggestion = "Please contact support with the error details below"
        
        logger.error(
            f"Task {actual_task_id or 'UnknownID'}: Error during CSV import workflow for dataset '{dataset_name}' from S3 object '{s3_bucket_name}/{s3_object_key}': {e}",
            exc_info=True
        )
        
        # Use generic error phase info if no specific phase is available
        phase_info = get_phase_info("initialization", 0)
        update_cache_with_phase_info("failed", error_message, 0, phase_info, error_type=error_type)
        update_upload_session_status('failed', error_message)
        
        return {
            "status": "error",
            "dataset_name": dataset_name,
            "s3_object_key": s3_object_key,
            "error_message": error_message,
            "error_type": error_type,
            "recovery_suggestion": recovery_suggestion,
            "technical_details": str(e),
            "timestamp": timezone.now().isoformat(),
            "support_needed": "mapping" not in error_message.lower() and "csv" not in error_message.lower(),
            "gui_redirect": f"/mappings/{mapping_id}/edit" if "mapping" in error_message.lower() and mapping_id else None,
            "user_action_required": "mapping" in error_message.lower() or "configuration" in error_message.lower()
        }
    finally:
        # Clean up the temporary file created by this task
        if temp_local_path and os.path.exists(temp_local_path):
            try:
                os.unlink(temp_local_path)
                logger.info(f"Task {actual_task_id or 'UnknownID'}: Successfully deleted temporary file {temp_local_path} created by task.")
            except OSError as e_unlink:
                logger.error(f"Task {actual_task_id or 'UnknownID'}: Error deleting temporary file {temp_local_path} created by task: {e_unlink}")
        elif temp_local_path: # If path was set but file doesn't exist (e.g. download failed before file fully written)
             logger.warning(f"Task {actual_task_id or 'UnknownID'}: Temporary file {temp_local_path} (intended for task use) not found for deletion.")


@db_task(retries=1, retry_delay=60)
def run_csv_import_workflow(
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
    # Legacy mapping parameters for backward compatibility
    mapping_id: Optional[str] = None,
    use_mapping: bool = False,
    use_table_services: bool = False
) -> Dict[str, Any]:
    """
    Legacy wrapper function for backward compatibility.
    
    This function maintains the existing API while delegating to the enhanced
    run_csv_import_workflow_with_mapping function with default parameters.
    """
    logger.info(f"Legacy function called, delegating to enhanced function with default parameters")
    
    return run_csv_import_workflow_with_mapping(
        s3_bucket_name=s3_bucket_name,
        s3_object_key=s3_object_key,
        dataset_name=dataset_name,
        institution=institution,
        base_uri=base_uri,
        delimiter=delimiter,
        has_quoted_fields=has_quoted_fields,
        link_row_cells=link_row_cells,
        link_to_first_column=link_to_first_column,
        update_strategy=update_strategy,
        task_id_for_cache=task_id_for_cache,
        upload_session_id=upload_session_id,
        mapping_id=mapping_id,
        execution_strategy="auto",
        validation_mode=False,
        file_dataset_mapping=None,
        use_mapping=use_mapping,
        use_table_services=use_table_services
    )


def _initialize_mapping_schemas_sync(
    mapping_id: str,
    institution: str,
    base_uri: str = "http://arkumu.org/data",
    upload_session_id: Optional[UUID] = None
) -> Dict[str, Any]:
    """
    Synchronous blueprint creation for view calls.
    
    Creates complete schema blueprints for ALL datasets in a mapping synchronously.
    This function can be called directly from views before queueing dataset processing tasks.
    """
    logger.info(f"🏗️  SYNC SCHEMA INITIALIZATION: Starting schema creation for mapping {mapping_id}")
    
    try:
        # Load mapping and translate to execution config
        from arkumu.metadata.models import Mapping
        from arkumu.importer.services.mapping_consumer.mapping_adapter import MappingAdapter
        from arkumu.importer.services.execution.mapping_aware_processor import MappingAwareProcessor
        from arkumu.importer.services.execution.statistics import ExecutionStatistics
        
        try:
            mapping = Mapping.objects.get(id=mapping_id)
        except Mapping.DoesNotExist:
            error_msg = f"Mapping with ID '{mapping_id}' not found"
            logger.error(error_msg)
            return {"status": "error", "error_message": error_msg, "error_type": "MappingNotFound"}
        
        # Load complete execution config (all datasets)
        mapping_adapter = MappingAdapter()
        execution_config = mapping_adapter.translate_to_execution_config(mapping_id)
        
        logger.info(f"🗺️  Loaded mapping '{mapping.name}' with {len(execution_config.datasets)} datasets")
        
        # Resolve organization from institution string
        from arkumu.users.models import Organization
        try:
            organization = Organization.objects.get(code=institution)
        except Organization.DoesNotExist:
            logger.error(f"Organization with code '{institution}' not found")
            return {"status": "error", "error_message": f"Organization with code '{institution}' not found", "error_type": "OrganizationNotFound"}
        
        # Initialize schema service for complete schema management (fix URI consistency)
        schema_service = SchemaService(mapping_id, institution=organization.code, base_uri=base_uri)
        
        # Initialize processor 
        statistics = ExecutionStatistics()
        processor = MappingAwareProcessor(
            organization=organization,
            base_uri=base_uri,
            statistics=statistics
        )
        
        # Create complete schema blueprints - now using schema service internally
        # This will be updated to use schema_service in the processor
        processor._create_complete_schema_blueprints(execution_config)
        
        # Additionally, ensure schema service has the complete schema cached
        try:
            schema_result = schema_service.create_complete_schema()
            logger.info(f"Schema service cached complete schema for mapping {mapping_id}")
        except Exception as e:
            logger.warning(f"Schema service caching failed (using fallback): {e}")
        
        # Calculate schema statistics
        total_properties = sum(len(bp.get('property_resources', {})) for bp in processor.dataset_blueprints.values())
        total_datasets = len(processor.dataset_blueprints)
        
        success_message = (
            f"Schema initialization completed for mapping '{mapping.name}'. "
            f"Created schemas for {total_datasets} datasets with {total_properties} total properties."
        )
        
        logger.info(f"✅ {success_message}")
        
        return {
            "status": "success",
            "mapping_id": mapping_id,
            "mapping_name": mapping.name,
            "datasets_schema_created": total_datasets,
            "total_properties": total_properties,
            "message": success_message
        }
        
    except Exception as e:
        error_msg = f"Schema initialization failed for mapping {mapping_id}: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return {
            "status": "error",
            "mapping_id": mapping_id,
            "error_message": error_msg,
            "error_type": type(e).__name__
        }


@cancellable_task()
@db_task(retries=1, retry_delay=60)
def initialize_mapping_schemas(
    mapping_id: str,
    institution: str,
    base_uri: str = "http://arkumu.org/data",
    upload_session_id: Optional[UUID] = None
) -> Dict[str, Any]:
    """
    Phase 1: Schema Initialization Task
    
    Creates complete schema blueprints for ALL datasets in a mapping.
    This task runs ONCE per mapping and caches the results for subsequent data processing tasks.
    
    Args:
        mapping_id: ID of the mapping configuration to use
        institution: Institution identifier
        base_uri: Base URI for generating resource URIs
        upload_session_id: Optional IngestSession ID for progress tracking
        
    Returns:
        Dictionary containing schema initialization results
    """
    logger.info(f"🏗️  SCHEMA INITIALIZATION: Starting schema creation for mapping {mapping_id}")
    
    try:
        # Load mapping and translate to execution config
        from arkumu.metadata.models import Mapping
        from arkumu.importer.services.mapping_consumer.mapping_adapter import MappingAdapter
        from arkumu.importer.services.execution.mapping_aware_processor import MappingAwareProcessor
        from arkumu.importer.services.execution.statistics import ExecutionStatistics
        
        try:
            mapping = Mapping.objects.get(id=mapping_id)
        except Mapping.DoesNotExist:
            error_msg = f"Mapping with ID '{mapping_id}' not found"
            logger.error(error_msg)
            return {"status": "error", "error_message": error_msg, "error_type": "MappingNotFound"}
        
        # Load complete execution config (all datasets)
        mapping_adapter = MappingAdapter()
        execution_config = mapping_adapter.translate_to_execution_config(mapping_id)
        
        logger.info(f"🗺️  Loaded mapping '{mapping.name}' with {len(execution_config.datasets)} datasets")
        
        # Resolve organization from institution string
        from arkumu.users.models import Organization
        try:
            organization = Organization.objects.get(code=institution)
        except Organization.DoesNotExist:
            logger.error(f"Organization with code '{institution}' not found")
            return {"status": "error", "error_message": f"Organization with code '{institution}' not found", "error_type": "OrganizationNotFound"}
        
        # Initialize schema service for complete schema management (fix URI consistency)
        schema_service = SchemaService(mapping_id, institution=organization.code, base_uri=base_uri)
        
        # Initialize processor 
        statistics = ExecutionStatistics()
        processor = MappingAwareProcessor(
            organization=organization,
            base_uri=base_uri,
            statistics=statistics
        )
        
        # Create complete schema blueprints - now using schema service internally
        # This will be updated to use schema_service in the processor
        processor._create_complete_schema_blueprints(execution_config)
        
        # Additionally, ensure schema service has the complete schema cached
        try:
            schema_result = schema_service.create_complete_schema()
            logger.info(f"Schema service cached complete schema for mapping {mapping_id}")
        except Exception as e:
            logger.warning(f"Schema service caching failed (using fallback): {e}")
        
        # Calculate schema statistics
        total_properties = sum(len(bp.get('property_resources', {})) for bp in processor.dataset_blueprints.values())
        total_datasets = len(processor.dataset_blueprints)
        
        success_message = (
            f"Schema initialization completed for mapping '{mapping.name}'. "
            f"Created schemas for {total_datasets} datasets with {total_properties} total properties."
        )
        
        logger.info(f"✅ {success_message}")
        
        return {
            "status": "success",
            "mapping_id": mapping_id,
            "mapping_name": mapping.name,
            "datasets_schema_created": total_datasets,
            "total_properties": total_properties,
            "message": success_message
        }
        
    except Exception as e:
        error_msg = f"Schema initialization failed for mapping {mapping_id}: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return {
            "status": "error",
            "mapping_id": mapping_id,
            "error_message": error_msg,
            "error_type": type(e).__name__
        }


@cancellable_task()
@db_task(retries=1, retry_delay=60)
def process_dataset_data(
    s3_bucket_name: str,
    s3_object_key: str,
    dataset_name: str,
    institution: str,
    mapping_id: str,
    base_uri: str = "http://arkumu.org/data",
    upload_session_id: Optional[UUID] = None,
    task_context: Optional[Any] = None,
    update_progress: Optional[Any] = None
) -> Dict[str, Any]:
    """
    Phase 2: Data Processing Task
    
    Processes CSV data for ONE dataset only. Assumes schemas already exist from initialize_mapping_schemas.
    This task runs ONCE per dataset and focuses purely on data processing.
    
    Args:
        s3_bucket_name: Name of the S3 bucket where the CSV file is located
        s3_object_key: The S3 object key (path) for the CSV file
        dataset_name: Name of the dataset being imported
        institution: Institution identifier
        mapping_id: ID of the mapping configuration (schemas must already exist)
        base_uri: Base URI for generating resource URIs
        upload_session_id: Optional IngestSession ID for progress tracking
        task_context: Optional task context
        
    Returns:
        Dictionary containing data processing results
    """
    # Check if we have an ImportTask record for this dataset and session
    actual_task_id = None
    if upload_session_id:
        from arkumu.importer.models import ImportTask
        try:
            import_task = ImportTask.objects.get(
                ingest_session_id=upload_session_id,
                dataset_name=dataset_name,
                file_path=s3_object_key
            )
            actual_task_id = import_task.task_id
            logger.info(f"Found ImportTask for dataset '{dataset_name}' with task_id: {actual_task_id}")
        except ImportTask.DoesNotExist:
            logger.warning(f"No ImportTask found for dataset '{dataset_name}' in session {upload_session_id}")
    
    if not actual_task_id:
        actual_task_id = str(uuid.uuid4())
    
    cache_key = f"task_state_{actual_task_id}"
    
    def update_cache_with_phase_info(status: str, message: str, progress: int, 
                                   phase_info: Optional[Dict] = None, 
                                   details: Optional[Dict] = None, 
                                   error_type: Optional[str] = None):
        payload = {
            "status": status,
            "message": message,
            "percentage": progress,
            "event_type": "progress",
            "timestamp": timezone.now().isoformat()
        }
        
        if phase_info:
            payload["phase_info"] = phase_info
        if details:
            payload["details"] = details
        if error_type:
            payload["error_type"] = error_type
            
        cache.set(cache_key, payload, timeout=3600)
        logger.info(f"Task {actual_task_id}: {status} - {message}")
    
    def update_upload_session_status(status: str, message: Optional[str] = None, files_processed: int = 0, errors_count: int = 0, detailed_stats: Optional[Dict] = None):
        if upload_session_id:
            try:
                session = IngestSession.objects.get(id=upload_session_id)
                session.status = status
                session.completed_at = timezone.now()
                if message:
                    session.error_message = message[:1024]
                if status == 'completed':
                    session.successful_rows = files_processed
                    session.failed_rows = errors_count
                    if detailed_stats:
                        session.ingestion_stats = detailed_stats
                elif status == 'failed':
                    session.failed_rows = 1
                session.save()
            except IngestSession.DoesNotExist:
                logger.error(f"IngestSession with ID {upload_session_id} not found")
            except Exception as e:
                logger.error(f"Error updating IngestSession {upload_session_id}: {e}")

    logger.info(f"📊 DATA PROCESSING: Starting data processing for dataset '{dataset_name}' (mapping: {mapping_id})")
    
    try:
        # Phase 1: Load schema using SchemaService (handles cache validation and regeneration)
        phase_info = {"current_phase": "schema_verification", "execution_strategy": "data_only"}
        update_cache_with_phase_info("processing", "Loading/validating schemas...", 5, phase_info)
        
        from arkumu.importer.services.schema_service import SchemaService
        
        try:
            # SchemaService handles cache validation and regeneration automatically
            schema_service = SchemaService(mapping_id=mapping_id, base_uri=base_uri)
            # This will load from cache if valid, or regenerate if missing/invalid
            schema_service._ensure_schema_loaded()
            cached_blueprints = schema_service._processor.dataset_blueprints
            
            # SchemaService automatically validates cached resources and regenerates if needed
            
            logger.info(f"✅ Schema blueprints loaded for mapping {mapping_id} via SchemaService")
        except Exception as e:
            error_msg = f"Failed to load schema blueprints for mapping {mapping_id}: {str(e)}"
            logger.error(error_msg)
            update_cache_with_phase_info("failed", error_msg, 0, phase_info, error_type="SchemaLoadFailed")
            return {
                "status": "error",
                "dataset_name": dataset_name,
                "mapping_id": mapping_id,
                "error_message": error_msg,
                "error_type": "SchemaLoadFailed",
                "recovery_suggestion": "Check mapping configuration and database connectivity"
            }
        
        # Phase 2: Load mapping configuration
        phase_info = {"current_phase": "mapping_load", "execution_strategy": "data_only"}
        update_cache_with_phase_info("processing", "Loading mapping configuration...", 15, phase_info)
        
        from arkumu.metadata.models import Mapping
        from arkumu.importer.services.mapping_consumer.mapping_adapter import MappingAdapter
        from arkumu.importer.services.execution.mapping_aware_processor import MappingAwareProcessor
        from arkumu.importer.services.execution.statistics import ExecutionStatistics
        from arkumu.importer.services.mapping_consumer.config_translator import ProcessingStrategy
        
        try:
            mapping = Mapping.objects.get(id=mapping_id)
        except Mapping.DoesNotExist:
            error_msg = f"Mapping with ID '{mapping_id}' not found"
            logger.error(error_msg)
            update_cache_with_phase_info("failed", error_msg, 0, phase_info, error_type="MappingNotFound")
            return {"status": "error", "error_message": error_msg, "error_type": "MappingNotFound"}
        
        mapping_adapter = MappingAdapter()
        execution_config = mapping_adapter.translate_to_execution_config(mapping_id)
        
        # Verify the target dataset exists in the mapping (with consistent URI slugification)
        from arkumu.common.uri_utils import slugify_uri_part
        
        # Apply same slugification to both sides for consistent comparison
        slugified_target_name = slugify_uri_part(dataset_name)
        target_dataset_exists = any(
            slugify_uri_part(ds.dataset_name) == slugified_target_name 
            for ds in execution_config.datasets
        )
        
        if not target_dataset_exists:
            # Log available datasets for debugging
            available_datasets = [ds.dataset_name for ds in execution_config.datasets]
            error_msg = f"Dataset '{dataset_name}' (slugified: '{slugified_target_name}') not found in mapping configuration. Available: {available_datasets}"
            logger.error(error_msg)
            update_cache_with_phase_info("failed", error_msg, 0, phase_info, error_type="DatasetNotInMapping")
            return {"status": "error", "error_message": error_msg, "error_type": "DatasetNotInMapping"}
        
        # Phase 3: Download and parse CSV
        phase_info = {"current_phase": "data_preparation", "execution_strategy": "data_only"}
        update_cache_with_phase_info("processing", "Downloading and parsing CSV data...", 25, phase_info)
        
        from arkumu.storage.services.bucket_service import BucketService
        import csv
        import io
        
        bucket_service = BucketService()
        
        logger.info(f"📁 Attempting to load CSV data from S3: {s3_bucket_name}/{s3_object_key}")
        try:
            result = bucket_service.get_file_content(s3_bucket_name, s3_object_key)
            logger.info(f"📥 S3 get_file_content result: type={type(result)}, keys={result.keys() if isinstance(result, dict) else 'N/A'}")
            
            if isinstance(result, dict) and 'content' in result:
                content = result['content']
                if isinstance(content, bytes):
                    content = content.decode('utf-8')
                logger.info(f"✅ Successfully got file content, size: {len(content) if content else 0} bytes")
            else:
                logger.error(f"❌ Unexpected result format from get_file_content: {result}")
                raise Exception(f"Unexpected result format from get_file_content: {result}")
        except Exception as s3_error:
            error_msg = f"Failed to download CSV file '{s3_object_key}' from S3 bucket '{s3_bucket_name}'"
            logger.error(f"❌ S3 download failed: {s3_error}")
            logger.error(f"📊 S3 Error Details - Type: {type(s3_error).__name__}, Message: {str(s3_error)}")
            update_cache_with_phase_info("failed", error_msg, 0, phase_info, error_type="S3DownloadError")
            return {"status": "error", "error_message": error_msg, "error_type": "S3DownloadError"}
        
        # Parse CSV
        logger.info(f"📊 Starting CSV parsing for dataset '{dataset_name}', content preview: {content[:200] if content else 'EMPTY'}...")
        try:
            csv_reader = csv.DictReader(io.StringIO(content), delimiter=';')
            rows = list(csv_reader)
            
            logger.info(f"📋 CSV headers for '{dataset_name}': {csv_reader.fieldnames}")
            logger.info(f"📥 Loaded {len(rows)} rows for dataset '{dataset_name}'")
            
            if len(rows) > 0:
                logger.info(f"📊 Sample row data for '{dataset_name}': {dict(list(rows[0].items())[:3])}...")
            else:
                logger.warning(f"⚠️  Dataset '{dataset_name}' CSV file appears to be empty or has no data rows")
            
            csv_sources = {dataset_name: {
                'headers': csv_reader.fieldnames,
                'rows': rows,
                'row_count': len(rows)
            }}
        except Exception as csv_error:
            logger.error(f"❌ CSV parsing failed for dataset '{dataset_name}': {csv_error}")
            logger.error(f"📊 Content that failed to parse: {content[:500]}...")
            raise
        
        # Phase 4: Initialize processor with existing schemas
        phase_info = {"current_phase": "data_processing", "execution_strategy": "data_only"}
        update_cache_with_phase_info("processing", "Processing data with existing schemas...", 40, phase_info)
        
        # Initialize execution statistics
        execution_statistics = ExecutionStatistics()
        
        # Get session and organization for progress updates
        session = None
        channel_id = None
        organization = None
        if upload_session_id:
            try:
                session = IngestSession.objects.get(id=upload_session_id)
                organization = session.organization
                from arkumu.importer.utils.progress import create_channel_id
                channel_id = create_channel_id(session.pk)
            except IngestSession.DoesNotExist:
                logger.warning(f"IngestSession with ID {upload_session_id} not found")
        
        # Fallback: resolve organization from institution string if session not available
        if not organization:
            from arkumu.users.models import Organization
            try:
                organization = Organization.objects.get(code=institution)
            except Organization.DoesNotExist:
                logger.error(f"Organization with code '{institution}' not found")
                raise ValueError(f"Organization with code '{institution}' not found")
        
        # Initialize processor
        processor = MappingAwareProcessor(
            organization=organization,
            base_uri=base_uri,
            statistics=execution_statistics,
            ingest_session=session,
            channel_id=channel_id
        )
        
        # Load existing blueprints instead of creating them
        processor.dataset_blueprints = cached_blueprints
        logger.info(f"📋 Loaded {len(cached_blueprints)} existing schema blueprints")
        
        # Execute data processing only (schemas already exist)
        from datetime import datetime, timezone as dt_timezone
        start_time = datetime.now(dt_timezone.utc)
        
        # Process with streaming entity-centric strategy
        logger.info(f"🔄 DATA-ONLY HANDOFF TO PROCESSOR - About to pass csv_sources to MappingAwareProcessor")
        logger.info(f"📊 csv_sources structure: {list(csv_sources.keys()) if csv_sources else 'None'}")
        if csv_sources:
            for ds_name, ds_data in csv_sources.items():
                logger.info(f"📋 Dataset '{ds_name}': {ds_data.get('row_count', 0)} rows, headers: {ds_data.get('headers', [])}")
        logger.info(f"🎯 Target dataset for processing: '{dataset_name}'")
        
        metrics = processor.process_with_execution_config(
            execution_config=execution_config,
            csv_sources=csv_sources,
            strategy=ProcessingStrategy.STREAMING_ENTITY_CENTRIC
        )
        
        end_time = datetime.now(dt_timezone.utc)
        processing_time = (end_time - start_time).total_seconds()
        
        # Phase 5: Finalization
        phase_info = {"current_phase": "finalization", "execution_strategy": "data_only"}
        update_cache_with_phase_info("processing", "Finalizing data processing...", 85, phase_info)
        
        # Get detailed metrics
        detailed_metrics = metrics.to_dict()
        
        # Check if dataset was skipped (empty or no data)
        datasets_skipped = detailed_metrics.get('datasets_skipped', 0)
        if (not hasattr(metrics, 'rows_processed') or metrics.rows_processed <= 0) and datasets_skipped > 0:
            # Dataset was skipped (empty file or no rows)
            skip_message = f"Dataset '{dataset_name}' was skipped (contained no rows)"
            logger.info(f"📋 {skip_message}")
            
            phase_info = {"current_phase": "finalization", "execution_strategy": "data_only"}
            update_cache_with_phase_info("completed", skip_message, 100, phase_info, details=detailed_metrics)
            update_upload_session_status('completed', skip_message, 0, 0, detailed_metrics)
            
            # Update ImportTask status to 'skipped' in database
            if upload_session_id:
                from arkumu.importer.models import ImportTask
                try:
                    import_task = ImportTask.objects.get(
                        ingest_session_id=upload_session_id,
                        dataset_name=dataset_name,
                        file_path=s3_object_key
                    )
                    import_task.status = 'skipped'
                    import_task.completed_at = timezone.now()
                    import_task.rows_processed = 0
                    import_task.error_message = "Dataset contained no rows"
                    import_task.save()
                    logger.info(f"Updated ImportTask {import_task.id} status to 'skipped' for dataset '{dataset_name}'")
                except ImportTask.DoesNotExist:
                    logger.warning(f"ImportTask not found for skip update - dataset '{dataset_name}' in session {upload_session_id}")
            
            return {
                "status": "success",
                "dataset_name": dataset_name,
                "mapping_id": mapping_id,
                "s3_object_key": s3_object_key,
                "skipped": True,
                **detailed_metrics
            }
        elif not hasattr(metrics, 'rows_processed') or metrics.rows_processed <= 0:
            # No data processed and not marked as skipped - this is an error
            error_msg = f"No data was processed from '{dataset_name}' and dataset was not marked as skipped"
            logger.error(error_msg)
            update_cache_with_phase_info("failed", error_msg, 0, phase_info, error_type="NoDataProcessed")
            return {"status": "error", "error_message": error_msg, "error_type": "NoDataProcessed"}
        
        # Normal successful processing
        success_message = (
            f"Data processing for '{dataset_name}' completed successfully. "
            f"Processed: {metrics.rows_processed} rows in {processing_time:.2f}s. "
            f"Created: {metrics.resources_created} resources, {metrics.triples_created} triples."
        )
        
        logger.info(f"✅ {success_message}")
        
        phase_info = {"current_phase": "finalization", "execution_strategy": "data_only"}
        update_cache_with_phase_info("completed", success_message, 100, phase_info, details=detailed_metrics)
        update_upload_session_status('completed', success_message, 1, 0, detailed_metrics)
        
        # Update ImportTask status to 'completed' in database
        if upload_session_id:
            from arkumu.importer.models import ImportTask
            try:
                import_task = ImportTask.objects.get(
                    ingest_session_id=upload_session_id,
                    dataset_name=dataset_name,
                    file_path=s3_object_key
                )
                import_task.status = 'completed'
                import_task.completed_at = timezone.now()
                import_task.rows_processed = metrics.rows_processed
                import_task.save()
                logger.info(f"Updated ImportTask {import_task.id} status to 'completed' for dataset '{dataset_name}'")
            except ImportTask.DoesNotExist:
                logger.warning(f"ImportTask not found for completion update - dataset '{dataset_name}' in session {upload_session_id}")
        
        return {
            "status": "success",
            "dataset_name": dataset_name,
            "mapping_id": mapping_id,
            "s3_object_key": s3_object_key,
            **detailed_metrics
        }
        
    except Exception as e:
        error_msg = f"Data processing failed for '{dataset_name}': {str(e)}"
        logger.error(error_msg, exc_info=True)
        
        phase_info = {"current_phase": "error", "execution_strategy": "data_only"}
        update_cache_with_phase_info("failed", error_msg, 0, phase_info, error_type=type(e).__name__)
        update_upload_session_status('failed', error_msg)
        
        # Update ImportTask status to 'failed' in database
        if upload_session_id:
            from arkumu.importer.models import ImportTask
            try:
                import_task = ImportTask.objects.get(
                    ingest_session_id=upload_session_id,
                    dataset_name=dataset_name,
                    file_path=s3_object_key
                )
                import_task.status = 'failed'
                import_task.error_message = error_msg[:1024]  # Truncate to fit field
                import_task.save()
                logger.info(f"Updated ImportTask {import_task.id} status to 'failed' for dataset '{dataset_name}'")
            except ImportTask.DoesNotExist:
                logger.warning(f"ImportTask not found for failure update - dataset '{dataset_name}' in session {upload_session_id}")
        
        return {
            "status": "error",
            "dataset_name": dataset_name,
            "mapping_id": mapping_id,
            "error_message": error_msg,
            "error_type": type(e).__name__
        }


@db_task(retries=1, retry_delay=60)
def run_csv_directory_import_workflow(
    s3_bucket_name: str,
    s3_folder_prefix: str,
    dataset_name: str,
    institution: str,
    base_uri: str = "http://arkumu.org/data",
    delimiter: str = ';',
    has_quoted_fields: bool = True,
    link_row_cells: bool = True,
    link_to_first_column: bool = False,
    use_smart_updater: bool = False,
    use_polars: bool = False,
    update_strategy: UpdateStrategy = UpdateStrategy.SKIP_EXISTING,
    relationship_config_json: Optional[Dict] = None,
    file_columns: Optional[Dict[str, List[str]]] = None,
    timestamp_column: Optional[str] = None,
    task_id_for_cache: Optional[str] = None,
    upload_session_id: Optional[UUID] = None
) -> Dict[str, Any]:
    """
    Huey task to import all CSV files from an S3 folder using ImportWorkflowService.import_csv_directory().
    The task downloads all CSV files from the S3 folder to a local temporary directory before processing.
    It updates its status in Django's cache, updates the corresponding IngestSession,
    and cleans up the temporary files.

    Args:
        s3_bucket_name: Name of the S3 bucket where the CSV files are located.
        s3_folder_prefix: The S3 folder prefix (path) containing the CSV files.
        dataset_name: Base name to assign to the datasets being imported.
        institution: Identifier for the institution owning the data.
        base_uri: Base URI for generating resource URIs.
        delimiter: Character used as a delimiter in the CSV files.
        has_quoted_fields: Boolean indicating if fields in CSV are quoted.
        link_row_cells: Whether to create links between cells of the same row.
        link_to_first_column: Specific linking strategy for row links.
        use_smart_updater: Whether to use smart bulk updater for processing.
        use_polars: Whether to use Polars-optimized version for better performance.
        update_strategy: The strategy to use for handling existing data.
        relationship_config_json: JSON configuration for relationship handling between files.
        file_columns: Dict mapping dataset names to file column lists.
        timestamp_column: Column name for timestamp-based updates.
        task_id_for_cache: Explicit task ID for caching.
        upload_session_id: ID of the IngestSession to update.

    Returns:
        A dictionary containing the status of the import and aggregate statistics.
    """
    # Use task_id_for_cache if provided, otherwise fall back to upload_session_id
    actual_task_id = task_id_for_cache if task_id_for_cache else (str(upload_session_id) if upload_session_id else str(uuid.uuid4()))
    
    # Only use Huey's task ID if no custom ID was provided
    if not actual_task_id and hasattr(run_csv_directory_import_workflow, 'request') and run_csv_directory_import_workflow.request.id:
        actual_task_id = run_csv_directory_import_workflow.request.id
    
    if not actual_task_id:
        logger.warning(f"Task ID for caching not available for CSV directory import: {dataset_name}, S3 folder: {s3_bucket_name}/{s3_folder_prefix}. Status polling may not work.")
    
    cache_key = f"task_state_{actual_task_id}" if actual_task_id else None

    def update_cache(status: str, message: str, progress: int, details: Optional[Dict] = None, error_type: Optional[str] = None):
        if cache_key:
            payload = {"status": status, "message": message, "progress": progress}
            if details:
                payload["details"] = details
            if error_type:
                payload["error_type"] = error_type
            cache.set(cache_key, payload, timeout=3600)
            logger.info(f"Task {actual_task_id or 'UnknownID'}: Cache updated - Key: {cache_key}, Status: {status}, Message: {message[:50]}...")
        else:
            logger.warning(f"Task {actual_task_id or 'UnknownID'}: Cannot update cache - cache_key is None")
    
    def update_cache_with_phase_info(status: str, message: str, progress: int, 
                                   phase_info: Optional[Dict] = None, 
                                   details: Optional[Dict] = None, 
                                   error_type: Optional[str] = None):
        """Enhanced cache update function with phase information support for directory imports."""
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
                    "execution_strategy": phase_info.get("execution_strategy", "directory")
                }
            
            if details:
                payload["details"] = details
            if error_type:
                payload["error_type"] = error_type
                
            cache.set(cache_key, payload, timeout=3600)
            
            phase_msg = f" (Phase {phase_info.get('current_phase_index', 0) + 1}/{phase_info.get('total_phases', 1)}: {phase_info.get('current_phase', 'unknown')})" if phase_info else ""
            logger.info(f"Task {actual_task_id or 'UnknownID'}: Cache updated - Key: {cache_key}, Status: {status}, Message: {message[:50]}...{phase_msg}")
        else:
            logger.warning(f"Task {actual_task_id or 'UnknownID'}: Cannot update cache - cache_key is None")

    # Update IngestSession helper
    def update_upload_session_status(status: str, message: Optional[str] = None, files_processed: int = 0, errors_count: int = 0):
        if upload_session_id:
            try:
                session = IngestSession.objects.get(id=upload_session_id)
                session.status = status
                session.completed_at = timezone.now()
                if message:
                    session.error_message = message[:1024]
                if status == 'completed':
                    session.successful_rows = files_processed # Track number of files processed
                    session.failed_rows = errors_count
                elif status == 'failed':
                    session.failed_rows = 1
                session.save()
            except IngestSession.DoesNotExist:
                logger.error(f"Task {actual_task_id or 'UnknownID'}: IngestSession with ID {upload_session_id} not found for update.")
            except Exception as e_us:
                logger.error(f"Task {actual_task_id or 'UnknownID'}: Error updating IngestSession {upload_session_id}: {e_us}", exc_info=True)

    # Initialize phase tracking for directory import
    directory_phases = [
        "initialization",
        "discovery",
        "download",
        "processing",
        "finalization"
    ]
    
    def get_directory_phase_info(phase_name: str, phase_progress: int = 0) -> Dict:
        """Get phase information for directory import progress tracking."""
        try:
            phase_index = directory_phases.index(phase_name)
        except ValueError:
            phase_index = 0
        
        return {
            "current_phase": phase_name,
            "current_phase_index": phase_index,
            "total_phases": len(directory_phases),
            "phase_progress": phase_progress,
            "phase_description": get_directory_phase_description(phase_name),
            "execution_strategy": "directory"
        }
    
    def get_directory_phase_description(phase_name: str) -> str:
        """Get user-friendly description for each directory import phase."""
        descriptions = {
            "initialization": "Initializing directory import",
            "discovery": "Discovering CSV files",
            "download": "Downloading files",
            "processing": "Processing CSV files",
            "finalization": "Finalizing directory import"
        }
        return descriptions.get(phase_name, "Processing")
    
    # Phase 1: Initialization
    phase_info = get_directory_phase_info("initialization", 100)
    update_cache_with_phase_info("processing", f"Starting directory import for {dataset_name} from S3 folder: {s3_bucket_name}/{s3_folder_prefix}...", 5, phase_info)

    logger.info(
        f"Task {actual_task_id or 'UnknownID'}: Starting CSV directory import workflow for dataset '{dataset_name}' "
        f"from S3 folder '{s3_bucket_name}/{s3_folder_prefix}' for institution '{institution}'. "
        f"Smart updater: {use_smart_updater}, Strategy: {update_strategy.name if use_smart_updater else 'N/A'}. "
        f"IngestSession ID: {upload_session_id}. Cache key: {cache_key}"
    )
    
    temp_directory_path = None
    final_aggregate_stats = {}

    try:
        bucket_service = BucketService()

        # Create a temporary directory for downloading all CSV files
        temp_directory_path = tempfile.mkdtemp(prefix='arkumu_csv_directory_import_')
        logger.info(f"Task {actual_task_id or 'UnknownID'}: Created temporary directory: {temp_directory_path}")

        # Phase 2: Discovery
        phase_info = get_directory_phase_info("discovery", 25)
        update_cache_with_phase_info("processing", "Discovering CSV files in S3 folder...", 10, phase_info)

        # List all objects in the S3 folder with CSV extension
        s3_client = bucket_service.base_s3_service.s3_client
        
        # Ensure folder prefix ends with / if it's not empty
        if s3_folder_prefix and not s3_folder_prefix.endswith('/'):
            s3_folder_prefix += '/'
        
        # List objects in the S3 folder
        response = s3_client.list_objects_v2(
            Bucket=s3_bucket_name,
            Prefix=s3_folder_prefix
        )
        
        if 'Contents' not in response:
            raise ValueError(f"No files found in S3 folder {s3_bucket_name}/{s3_folder_prefix}")
        
        # Filter for CSV files only
        csv_objects = [
            obj for obj in response['Contents']
            if obj['Key'].lower().endswith('.csv') and obj['Size'] > 0
        ]
        
        if not csv_objects:
            raise ValueError(f"No CSV files found in S3 folder {s3_bucket_name}/{s3_folder_prefix}")
        
        logger.info(f"Task {actual_task_id or 'UnknownID'}: Found {len(csv_objects)} CSV files in S3 folder")
        for obj in csv_objects:
            logger.info(f"  - {obj['Key']} ({obj['Size']} bytes)")

        # Phase 2: Discovery - Complete
        phase_info = get_directory_phase_info("discovery", 100)
        update_cache_with_phase_info("processing", f"Found {len(csv_objects)} CSV files", 15, phase_info)

        # Phase 3: Download
        phase_info = get_directory_phase_info("download", 0)
        update_cache_with_phase_info("processing", f"Downloading {len(csv_objects)} CSV files from S3...", 20, phase_info)

        # Download all CSV files to the temporary directory
        downloaded_files = []
        for i, obj in enumerate(csv_objects):
            s3_object_key = obj['Key']
            filename = os.path.basename(s3_object_key)
            local_file_path = os.path.join(temp_directory_path, filename)
            
            logger.info(f"Task {actual_task_id or 'UnknownID'}: Downloading file {i+1}/{len(csv_objects)}: {s3_object_key}")
            
            try:
                s3_client.download_file(s3_bucket_name, s3_object_key, local_file_path)
                downloaded_files.append(local_file_path)
                logger.info(f"Task {actual_task_id or 'UnknownID'}: Successfully downloaded {filename}")
            except Exception as download_error:
                logger.error(f"Task {actual_task_id or 'UnknownID'}: Failed to download {s3_object_key}: {download_error}")
                raise download_error
            
            # Update progress during download
            file_progress = int(100 * (i + 1) / len(csv_objects))
            overall_progress = 20 + (30 * (i + 1) / len(csv_objects))
            phase_info = get_directory_phase_info("download", file_progress)
            update_cache_with_phase_info("processing", f"Downloaded {i+1}/{len(csv_objects)} files...", int(overall_progress), phase_info)

        logger.info(f"Task {actual_task_id or 'UnknownID'}: Successfully downloaded all {len(downloaded_files)} CSV files to {temp_directory_path}")

        # Phase 3: Download - Complete
        phase_info = get_directory_phase_info("download", 100)
        update_cache_with_phase_info("processing", f"Download completed", 45, phase_info)

        # Phase 4: Processing
        phase_info = get_directory_phase_info("processing", 0)
        update_cache_with_phase_info("processing", f"Processing {len(downloaded_files)} CSV files...", 50, phase_info)

        # Save relationship config to a temporary file if provided
        relationship_config_path = None
        if relationship_config_json:
            import json
            relationship_config_path = os.path.join(temp_directory_path, 'relationship_config.json')
            with open(relationship_config_path, 'w') as f:
                json.dump(relationship_config_json, f)
            logger.info(f"Task {actual_task_id or 'UnknownID'}: Saved relationship config to {relationship_config_path}")

        # Call the directory import service
        logger.info(f"Task {actual_task_id or 'UnknownID'}: Starting ImportWorkflowService.import_csv_directory() on {temp_directory_path}")
        
        # Start processing with initial progress
        import threading
        import time
        
        # Progress tracking for long-running import
        processing_complete = False
        def update_processing_progress():
            """Background thread to update progress during long directory processing"""
            progress_start = 55  # Start after download phase
            progress_end = 85    # End before finalization
            elapsed_time = 0
            estimated_total_time = len(downloaded_files) * 30  # Estimate 30 seconds per file
            
            while not processing_complete and elapsed_time < estimated_total_time * 2:  # Max 2x estimated time
                time.sleep(10)  # Update every 10 seconds
                elapsed_time += 10
                
                if not processing_complete:
                    # Calculate progress based on time elapsed
                    time_progress = min(elapsed_time / estimated_total_time, 0.9)  # Cap at 90%
                    current_progress = int(progress_start + (progress_end - progress_start) * time_progress)
                    
                    # Update with phase information
                    phase_info = get_directory_phase_info("processing", int(time_progress * 100))
                    update_cache_with_phase_info(
                        "processing", 
                        f"Processing {len(downloaded_files)} CSV files... ({elapsed_time//60}m {elapsed_time%60}s elapsed)",
                        current_progress,
                        phase_info,
                        details={"csv_files_found": len(csv_objects), "csv_files_downloaded": len(downloaded_files)}
                    )
        
        # Start progress thread
        progress_thread = threading.Thread(target=update_processing_progress, daemon=True)
        progress_thread.start()
        
        try:
            # Get organization (this is a simplified version - in production you'd get it from the session)
            from arkumu.metadata.models import Organization
            organization = Organization.objects.get(code=institution)
            
            # ELIMINATE bridge_service.import_csv_directory - use NEW system for each file
            logger.info(f"Task {actual_task_id or 'UnknownID'}: Using NEW system for directory import (processing {len(downloaded_files)} files individually)")
            
            aggregate_stats = {
                "files_processed": 0,
                "resources_created": 0,
                "triples_created": 0,
                "row_links_created": 0,
                "files_uploaded": 0,
                "upload_errors": 0,
                "errors": 0
            }
            
            # Process each file individually using the NEW mapping-aware system
            for i, file_path in enumerate(downloaded_files):
                try:
                    filename = os.path.basename(file_path)
                    logger.info(f"Task {actual_task_id or 'UnknownID'}: Processing file {i+1}/{len(downloaded_files)}: {filename}")
                    
                    # Upload file back to S3 temporarily for the NEW system to process
                    temp_s3_key = f"temp_directory_import/{upload_session_id}/{filename}"
                    bucket_service.base_s3_service.s3_client.upload_file(file_path, s3_bucket_name, temp_s3_key)
                    
                    # Call NEW system for this individual file
                    result = run_mapping_aware_import_workflow(
                        s3_bucket_name=s3_bucket_name,
                        s3_object_key=temp_s3_key,
                        dataset_name=f"{dataset_name}_{filename.replace('.csv', '')}",
                        institution=institution,
                        mapping_id="auto-generated",  # Auto-generate mapping for directory imports
                        base_uri=base_uri,
                        upload_session_id=upload_session_id,
                        csv_sources=None,
                        update_progress=None,
                        task_context=None
                    )
                    
                    # Aggregate results
                    if result.get("status") == "success":
                        aggregate_stats["files_processed"] += 1
                        aggregate_stats["resources_created"] += result.get("resources_created", 0)
                        aggregate_stats["triples_created"] += result.get("triples_created", 0)
                    else:
                        aggregate_stats["errors"] += 1
                        
                    # Clean up temp S3 file
                    try:
                        bucket_service.base_s3_service.s3_client.delete_object(Bucket=s3_bucket_name, Key=temp_s3_key)
                    except Exception as cleanup_error:
                        logger.warning(f"Failed to cleanup temp S3 file {temp_s3_key}: {cleanup_error}")
                    
                    # Update progress
                    file_progress = int(100 * (i + 1) / len(downloaded_files))
                    overall_progress = 50 + (35 * (i + 1) / len(downloaded_files))
                    phase_info = get_directory_phase_info("processing", file_progress)
                    update_cache_with_phase_info("processing", f"Processed {i+1}/{len(downloaded_files)} files with NEW system...", int(overall_progress), phase_info)
                    
                except Exception as file_error:
                    logger.error(f"Task {actual_task_id or 'UnknownID'}: Error processing file {filename}: {file_error}")
                    aggregate_stats["errors"] += 1
        finally:
            # Stop the progress thread
            processing_complete = True
        
        # Phase 4: Processing - Complete
        phase_info = get_directory_phase_info("processing", 100)
        update_cache_with_phase_info("processing", f"Processing completed", 85, phase_info)

        # Phase 5: Finalization
        phase_info = get_directory_phase_info("finalization", 50)
        update_cache_with_phase_info("processing", f"Finalizing directory import for {dataset_name}...", 90, phase_info)

        # Prepare final statistics
        final_aggregate_stats = {
            "files_processed": aggregate_stats.get("files_processed", 0),
            "resources_created": aggregate_stats.get("resources_created", 0),
            "triples_created": aggregate_stats.get("triples_created", 0),
            "row_links_created": aggregate_stats.get("row_links_created", 0),
            "files_uploaded": aggregate_stats.get("files_uploaded", 0),
            "upload_errors": aggregate_stats.get("upload_errors", 0),
            "errors": aggregate_stats.get("errors", 0),
            "csv_files_found": len(csv_objects),
            "csv_files_downloaded": len(downloaded_files)
        }
        
        success_message = (
            f"Directory '{dataset_name}' (from S3 folder {s3_folder_prefix}) imported successfully. "
            f"Processed: {final_aggregate_stats['files_processed']} files. "
            f"Created: {final_aggregate_stats['resources_created']} resources, {final_aggregate_stats['triples_created']} triples. "
            f"Errors: {final_aggregate_stats['errors']}."
        )
        
        # Phase 5: Finalization - Complete
        phase_info = get_directory_phase_info("finalization", 100)
        update_cache_with_phase_info("completed", success_message, 100, phase_info, details=final_aggregate_stats)
        logger.info(f"Task {actual_task_id or 'UnknownID'}: Updated cache with 'completed' status. Cache key: {cache_key}")
        
        update_upload_session_status(
            'completed', 
            success_message, 
            final_aggregate_stats['files_processed'], 
            final_aggregate_stats['errors']
        )
        
        logger.info(
            f"Task {actual_task_id or 'UnknownID'}: CSV directory import workflow for dataset '{dataset_name}' "
            f"(from S3 folder {s3_folder_prefix}) completed successfully. "
            f"Files processed: {final_aggregate_stats['files_processed']}, "
            f"Resources created: {final_aggregate_stats['resources_created']}, "
            f"Triples created: {final_aggregate_stats['triples_created']}, "
            f"Errors: {final_aggregate_stats['errors']}"
        )
        
        return {
            "status": "success",
            "dataset_name": dataset_name,
            "s3_folder_prefix": s3_folder_prefix,
            **final_aggregate_stats
        }
        
    except Exception as e:
        error_message = f"Error importing directory '{dataset_name}' from S3 folder {s3_bucket_name}/{s3_folder_prefix}: {str(e)}"
        logger.error(
            f"Task {actual_task_id or 'UnknownID'}: Error during CSV directory import workflow for dataset '{dataset_name}' "
            f"from S3 folder '{s3_bucket_name}/{s3_folder_prefix}': {e}",
            exc_info=True
        )
        # Use generic error phase info if no specific phase is available
        phase_info = get_directory_phase_info("initialization", 0)
        update_cache_with_phase_info("failed", error_message, 0, phase_info, error_type=type(e).__name__)
        update_upload_session_status('failed', error_message)
        return {
            "status": "error",
            "dataset_name": dataset_name,
            "s3_folder_prefix": s3_folder_prefix,
            "error_message": str(e),
            "error_type": type(e).__name__
        }
    finally:
        # Clean up the temporary directory and all downloaded files
        if temp_directory_path and os.path.exists(temp_directory_path):
            try:
                import shutil
                shutil.rmtree(temp_directory_path)
                logger.info(f"Task {actual_task_id or 'UnknownID'}: Successfully deleted temporary directory {temp_directory_path}")
            except OSError as e_cleanup:
                logger.error(f"Task {actual_task_id or 'UnknownID'}: Error deleting temporary directory {temp_directory_path}: {e_cleanup}")
        elif temp_directory_path:
            logger.warning(f"Task {actual_task_id or 'UnknownID'}: Temporary directory {temp_directory_path} not found for deletion.")



