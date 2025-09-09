"""
Huey Task for Import Processing with Cache-Based Progress Updates

This module contains the Huey task for running import jobs asynchronously
with real-time progress updates via cache-based storage for HTMX polling.
"""

import logging
from huey.contrib.djhuey import task
from arkumu.importer.utils.progress import publish_progress
from arkumu.importer.models import IngestSession

logger = logging.getLogger(__name__)


@task()
def run_import(session_pk: int):
    """
    Run import job asynchronously with cache-based progress updates.
    
    Args:
        session_pk: Primary key of the IngestSession to process
        
    Raises:
        Exception: Re-raises any exceptions for Huey retry mechanism
    """
    try:
        session = IngestSession.objects.get(pk=session_pk)
        
        logger.info(f"Starting import for session {session_pk}")
        
        # Update status and initial progress
        session.mark_started()
        publish_progress(f"task_state_{run_import.task_id}", {
            'status': 'started',
            'message': 'Import job started',
            'percentage': 0,
            'processed': 0,
            'total': 0
        })
        
        # Import the processor here to avoid circular imports
        from arkumu.importer.services.execution.mapping_aware_processor import MappingAwareProcessor
        from arkumu.importer.services.execution.statistics import ExecutionStatistics
        from arkumu.importer.services.mapping_consumer import ExecutionConfig
        from arkumu.importer.services.mapping_consumer.config_translator import ConfigTranslator
        
        # Create statistics tracker
        statistics = ExecutionStatistics()
        
        # Initialize processor with channel_id and session for progress updates
        from arkumu.importer.utils.progress import create_channel_id
        channel_id = create_channel_id(session_pk)
        
        processor = MappingAwareProcessor(
            institution=session.organization.code,
            base_uri=session.base_uri,
            statistics=statistics,
            channel_id=channel_id,
            session=session
        )
        
        # Translate mapping configuration
        if session.mapping:
            config_translator = ConfigTranslator()
            execution_config = config_translator.translate_mapping_config(
                session.mapping.mapping_config
            )
            
            # If no valid execution config, skip processing
            if not execution_config or not execution_config.datasets:
                logger.warning(f"No valid execution config for session {session_pk}")
                session.mark_completed({'message': 'No valid configuration'})
                publish_progress(f"task_state_{run_import.task_id}", {
                    'status': 'completed',
                    'message': 'No valid configuration found',
                    'percentage': 100,
                    'processed': 0,
                    'total': 0
                }, event='complete')
                return
            
            # Create mock CSV sources for testing
            # In production, this would load actual CSV data
            csv_sources = {}
            total_rows = 0
            for dataset in execution_config.datasets:
                mock_rows = [
                    {'id': '1', 'name': 'Test 1', 'value': 'Value 1'},
                    {'id': '2', 'name': 'Test 2', 'value': 'Value 2'},
                ]
                csv_sources[dataset.dataset_name] = {
                    'headers': ['id', 'name', 'value'],
                    'rows': mock_rows
                }
                total_rows += len(mock_rows)
            
            # Update progress with total count
            publish_progress(f"task_state_{run_import.task_id}", {
                'status': 'processing',
                'message': 'Processing data...',
                'percentage': 25,
                'processed': 0,
                'total': total_rows
            })
            
            # Run processor with streaming entity-centric strategy (supports FK resolution)
            from arkumu.importer.services.mapping_consumer import ProcessingStrategy
            metrics = processor.process_with_execution_config(
                execution_config, 
                csv_sources, 
                ProcessingStrategy.STREAMING_ENTITY_CENTRIC
            )
            
            # Update session with results
            session.ingestion_stats = {
                'rows_processed': metrics.rows_processed,
                'resources_created': metrics.resources_created,
                'triples_created': metrics.triples_created,
                'errors': metrics.errors
            }
        
        # Success notification
        session.mark_completed(session.ingestion_stats)
        
        publish_progress(f"task_state_{run_import.task_id}", {
            'status': 'completed',
            'message': 'Import completed successfully',
            'percentage': 100,
            'processed': session.ingestion_stats.get('rows_processed', 0),
            'total': session.ingestion_stats.get('rows_processed', 0)
        }, event='complete')
        
        logger.info(f"Import completed successfully for session {session_pk}")
        
    except IngestSession.DoesNotExist as exc:
        logger.error(f"Import failed for session {session_pk}: {exc}")
        # Can't update session or send progress since it doesn't exist
        raise  # Re-raise for Huey retry mechanism
        
    except Exception as exc:
        logger.error(f"Import failed for session {session_pk}: {exc}")
        
        # Error handling - session is guaranteed to exist here
        session.mark_failed(str(exc))
        
        publish_progress(f"task_state_{run_import.task_id}", {
            'status': 'failed',
            'message': f'Import failed: {str(exc)}',
            'percentage': session.get_progress_percentage()
        }, event='error')
        
        raise  # Re-raise for Huey retry mechanism