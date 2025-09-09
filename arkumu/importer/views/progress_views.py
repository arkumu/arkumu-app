from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden
from arkumu.importer.models import IngestSession
from arkumu.importer.services.progress_cache import ProgressCacheService
import logging

logger = logging.getLogger(__name__)


@login_required
def import_progress_view(request, session_pk):
    """
    Get import progress for HTMX polling.
    
    Args:
        session_pk: IngestSession primary key
    """
    try:
        # Get the session and check ownership
        session = IngestSession.objects.get(pk=session_pk)
        
        if session.user != request.user:
            return HttpResponseForbidden("Unauthorized")
        
        from django.core.cache import cache
        from arkumu.importer.models import ImportTask
        
        # Check if this session has multiple import tasks
        import_tasks = ImportTask.objects.filter(ingest_session=session).order_by('created_at')
        
        logger.info(f"Progress view - Session {session_pk} has {import_tasks.count()} ImportTask records")
        
        if import_tasks.exists():
            # Multi-dataset import - show individual progress for each dataset
            tasks_with_progress = []
            completed_count = 0
            processing_count = 0
            failed_count = 0
            
            for task in import_tasks:
                cache_key = f"task_state_{task.task_id}"
                progress_data = cache.get(cache_key)
                
                
                if not progress_data:
                    progress_data = {
                        'status': 'pending',
                        'message': 'Waiting to start...',
                        'percentage': 0
                    }
                
                # Update counts
                if progress_data.get('status') == 'completed':
                    completed_count += 1
                elif progress_data.get('status') == 'processing':
                    processing_count += 1
                elif progress_data.get('status') == 'failed':
                    failed_count += 1
                elif progress_data.get('status') == 'cancelled':
                    failed_count += 1  # Count cancelled as failed for display
                
                tasks_with_progress.append({
                    'task_id': task.task_id,
                    'dataset_name': task.dataset_name,
                    'file_path': task.file_path,
                    'progress_data': progress_data
                })
            
            # Continue polling if any tasks are still processing
            all_done = all(
                t['progress_data'].get('status') in ['completed', 'failed'] 
                for t in tasks_with_progress
            )
            
            return render(request, 'importer/partials/multi_dataset_progress.html', {
                'session': session,
                'import_tasks': tasks_with_progress,
                'completed_count': completed_count,
                'processing_count': processing_count,
                'failed_count': failed_count,
                'should_poll': not all_done
            })
        
        else:
            # Single dataset import (legacy) or no tasks yet
            task_id = session.task_id if session.task_id else str(session.pk)
            cache_key = f"task_state_{task_id}"
            progress_data = cache.get(cache_key)
            
            logger.info(f"Progress view for session {session_pk}, task_id: {task_id}, cache_key: {cache_key}")
            logger.info(f"Progress data from cache: {progress_data}")
            
            if not progress_data:
                progress_data = {
                    'status': 'pending',
                    'message': 'Waiting to start...',
                    'percentage': 0,
                    'event_type': 'progress'
                }
            
            # Determine if polling should continue
            should_poll = progress_data.get('status') not in ['completed', 'failed']
            
            logger.info(f"Status: {progress_data.get('status')}, Should poll: {should_poll}, Cancel button should show: {progress_data.get('status') in ['processing', 'pending']}")
            
            return render(request, 'importer/partials/progress_display_polling.html', {
                'session': session,
                'progress_data': progress_data,
                'should_poll': should_poll
            })
        
    except IngestSession.DoesNotExist:
        return HttpResponseForbidden("Session not found")
    except Exception as e:
        logger.error(f"Error getting progress for session {session_pk}: {e}")
        return HttpResponseForbidden("Error retrieving progress")