"""
State-of-the-art Task Management System for Arkumu Import Tasks

This module provides comprehensive task lifecycle management including:
- Graceful task cancellation with proper cleanup
- Real-time task monitoring and control
- Resource cleanup and rollback mechanisms
- Task state persistence and recovery
- WebSocket integration for real-time updates
"""

import logging
import threading
import time
import uuid
import signal
import atexit
from datetime import datetime, timezone
from typing import Dict, Optional, Any, List, Callable
from dataclasses import dataclass, field
from enum import Enum
from contextlib import contextmanager

from django.core.cache import cache
from django.db import transaction
from django.utils import timezone as django_timezone
from django.conf import settings

from huey import RedisHuey
from huey.exceptions import CancelExecution
from huey.signals import SIGNAL_INTERRUPTED, SIGNAL_ERROR, SIGNAL_EXECUTING
import redis

from arkumu.importer.models import IngestSession


logger = logging.getLogger(__name__)


def clear_huey_queue_on_shutdown():
    """
    Clear Huey task queue on container shutdown to prevent stale tasks.
    
    This function should be called when the container stops to ensure
    no orphaned tasks remain in the Redis queue.
    """
    from django.conf import settings
    
    try:
        # Get Redis connection from Huey settings
        huey_settings = getattr(settings, 'HUEY', {})
        
        # Try to get Redis URL from connection settings
        connection_settings = huey_settings.get('connection', {})
        redis_url = connection_settings.get('url')
        
        if not redis_url:
            # Fallback to individual settings
            redis_host = huey_settings.get('host', 'localhost')
            redis_port = huey_settings.get('port', 6379)
            redis_db = huey_settings.get('db', 0)
            redis_password = huey_settings.get('password', None)
            
            redis_client = redis.Redis(
                host=redis_host,
                port=redis_port,
                db=redis_db,
                password=redis_password,
                decode_responses=True
            )
        else:
            redis_client = redis.from_url(redis_url, decode_responses=True)
        
        # Test connection
        redis_client.ping()
        
        # Get all keys related to Huey
        patterns = [
            'huey:*',
            '*huey*',
            'arkumu:*',
            'queue:*',
            'results:*',
            'schedule:*',
            'locks:*',
            'task_state_*',  # Clear task state cache
            'task_cancel_*',  # Clear task cancellation flags
            'import_progress_*'  # Clear import progress cache
        ]
        
        huey_keys = []
        for pattern in patterns:
            keys = redis_client.keys(pattern)
            huey_keys.extend(keys)
        
        # Remove duplicates
        huey_keys = list(set(huey_keys))
        
        if huey_keys:
            deleted_count = redis_client.delete(*huey_keys)
            logger.info(f"Container shutdown: Cleared {deleted_count} Huey-related keys from Redis")
        
        # Clear common queue names
        queue_names = ['huey', 'arkumu', 'default']
        for queue_name in queue_names:
            redis_client.delete(queue_name)
            redis_client.delete(f"{queue_name}:queue")
            redis_client.delete(f"{queue_name}:results")
            redis_client.delete(f"{queue_name}:schedule")
        
        logger.info("Container shutdown: Huey queue cleared successfully")
        return True
        
    except Exception as e:
        logger.error(f"Container shutdown: Failed to clear Huey queue: {e}")
        return False


class TaskState(Enum):
    """Enhanced task states for comprehensive lifecycle management"""
    PENDING = "pending"
    RUNNING = "running"
    CANCELLING = "cancelling"
    CANCELLED = "cancelled"
    COMPLETED = "completed"
    FAILED = "failed"
    INTERRUPTED = "interrupted"


class CancellationReason(Enum):
    """Reasons for task cancellation"""
    USER_REQUESTED = "user_requested"
    TIMEOUT = "timeout"
    RESOURCE_EXHAUSTED = "resource_exhausted"
    SYSTEM_SHUTDOWN = "system_shutdown"
    ERROR_THRESHOLD = "error_threshold"


@dataclass
class TaskContext:
    """Comprehensive task context with cancellation support"""
    task_id: str
    session_id: Optional[str] = None
    user_id: Optional[str] = None
    state: TaskState = TaskState.PENDING
    cancellation_requested: bool = False
    cancellation_reason: Optional[CancellationReason] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    progress: int = 0
    phase: str = "initialization"
    error_message: Optional[str] = None
    cleanup_callbacks: List[Callable] = field(default_factory=list)
    rollback_callbacks: List[Callable] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self):
        if self.start_time is None:
            self.start_time = datetime.now(timezone.utc)


class TaskManager:
    """
    State-of-the-art task manager with comprehensive lifecycle management
    """
    
    def __init__(self, huey_instance: RedisHuey, enable_monitoring: bool = True):
        self.huey = huey_instance
        self.active_tasks: Dict[str, TaskContext] = {}
        self.lock = threading.RLock()
        self._monitoring_enabled = enable_monitoring
        self._monitoring_thread = None
        self._redis_client = None
        self._setup_redis_client()
        self._setup_signal_handlers()
        self._setup_shutdown_handlers()
        if enable_monitoring:
            self._setup_monitoring_thread()
    
    def _setup_redis_client(self):
        """Setup Redis client for task-specific cleanup"""
        try:
            # Get Redis connection from Huey settings
            huey_settings = getattr(settings, 'HUEY', {})
            connection_settings = huey_settings.get('connection', {})
            redis_url = connection_settings.get('url')
            
            if redis_url:
                self._redis_client = redis.from_url(redis_url, decode_responses=True)
            else:
                # Fallback to individual settings
                redis_host = huey_settings.get('host', 'localhost')
                redis_port = huey_settings.get('port', 6379)
                redis_db = huey_settings.get('db', 0)
                redis_password = huey_settings.get('password', None)
                
                self._redis_client = redis.Redis(
                    host=redis_host,
                    port=redis_port,
                    db=redis_db,
                    password=redis_password,
                    decode_responses=True
                )
            
            # Test connection
            self._redis_client.ping()
            logger.info("Redis client initialized for task cleanup")
            
        except Exception as e:
            logger.error(f"Failed to initialize Redis client for task cleanup: {e}")
            self._redis_client = None
    
    def _setup_signal_handlers(self):
        """Setup Huey signal handlers for graceful task management"""
        
        @self.huey.signal(SIGNAL_EXECUTING)
        def on_task_executing(signal, task, *args, **kwargs):
            """Handle task execution start"""
            task_id = getattr(task, 'id', str(uuid.uuid4()))
            with self.lock:
                if task_id in self.active_tasks:
                    context = self.active_tasks[task_id]
                    context.state = TaskState.RUNNING
                    context.start_time = datetime.now(timezone.utc)
                    self._persist_task_state(context)
                    logger.info(f"Task {task_id} started execution")
        
        @self.huey.signal(SIGNAL_INTERRUPTED)
        def on_task_interrupted(signal, task, *args, **kwargs):
            """Handle task interruption with cleanup"""
            task_id = getattr(task, 'id', str(uuid.uuid4()))
            with self.lock:
                if task_id in self.active_tasks:
                    context = self.active_tasks[task_id]
                    context.state = TaskState.INTERRUPTED
                    context.cancellation_reason = CancellationReason.SYSTEM_SHUTDOWN
                    self._execute_cleanup_callbacks(context)
                    self._persist_task_state(context)
                    logger.warning(f"Task {task_id} was interrupted")
        
        @self.huey.signal(SIGNAL_ERROR)
        def on_task_error(signal, task, exc=None, *args, **kwargs):
            """Handle task errors with proper cleanup"""
            task_id = getattr(task, 'id', str(uuid.uuid4()))
            with self.lock:
                if task_id in self.active_tasks:
                    context = self.active_tasks[task_id]
                    context.state = TaskState.FAILED
                    context.error_message = str(exc) if exc else "Unknown error"
                    self._execute_cleanup_callbacks(context)
                    self._persist_task_state(context)
                    logger.error(f"Task {task_id} failed: {context.error_message}")
    
    def _setup_monitoring_thread(self):
        """Setup background monitoring thread for active tasks"""
        def monitor_tasks():
            while self._monitoring_enabled:
                try:
                    with self.lock:
                        for task_id, context in list(self.active_tasks.items()):
                            # Check for cancellation requests
                            if self._check_cancellation_request(task_id):
                                self._process_cancellation(context)
                            
                            # Check for timeout
                            if self._check_timeout(context):
                                self._process_timeout(context)
                            
                            # Update real-time status
                            self._update_realtime_status(context)
                    
                    time.sleep(1)  # Check every second
                except Exception as e:
                    logger.error(f"Error in task monitoring thread: {e}")
                    time.sleep(5)  # Wait longer on error
        
        self._monitoring_thread = threading.Thread(target=monitor_tasks, daemon=True)
        self._monitoring_thread.start()
    
    def stop_monitoring(self):
        """Stop the monitoring thread"""
        self._monitoring_enabled = False
        if self._monitoring_thread:
            self._monitoring_thread.join(timeout=2)
    
    def register_task(self, task_id: str, session_id: Optional[str] = None, 
                     user_id: Optional[str] = None, metadata: Optional[Dict] = None) -> TaskContext:
        """Register a new task with the manager"""
        with self.lock:
            context = TaskContext(
                task_id=task_id,
                session_id=session_id,
                user_id=user_id,
                metadata=metadata or {}
            )
            self.active_tasks[task_id] = context
            self._persist_task_state(context)
            logger.info(f"Registered task {task_id}")
            return context
    
    def update_task_progress(self, task_id: str, progress: int, phase: str, 
                           message: Optional[str] = None, details: Optional[Dict] = None):
        """Update task progress with real-time broadcasting"""
        with self.lock:
            if task_id not in self.active_tasks:
                logger.warning(f"Task {task_id} not found in active tasks")
                return
            
            context = self.active_tasks[task_id]
            context.progress = progress
            context.phase = phase
            
            if details:
                context.metadata.update(details)
            
            # Persist state
            self._persist_task_state(context)
            
            # Broadcast real-time update
            self._broadcast_progress_update(context, message, details)
            
            # Check for cancellation during progress update
            if context.cancellation_requested:
                raise CancelExecution(f"Task {task_id} cancelled: {context.cancellation_reason}")
    
    def request_cancellation(self, task_id: str, reason: CancellationReason = CancellationReason.USER_REQUESTED):
        """Request task cancellation with proper cleanup"""
        with self.lock:
            if task_id not in self.active_tasks:
                logger.warning(f"Task {task_id} not found for cancellation")
                return False
            
            context = self.active_tasks[task_id]
            context.cancellation_requested = True
            context.cancellation_reason = reason
            context.state = TaskState.CANCELLING
            
            # Set cancellation flag in cache for immediate pickup
            cache.set(f"task_cancel_{task_id}", True, timeout=3600)
            
            # Persist state
            self._persist_task_state(context)
            
            # Broadcast cancellation status
            self._broadcast_cancellation_update(context)
            
            logger.info(f"Cancellation requested for task {task_id}: {reason}")
            return True
    
    def complete_task(self, task_id: str, success: bool = True, 
                     error_message: Optional[str] = None, result: Optional[Dict] = None):
        """Mark task as completed with proper cleanup"""
        with self.lock:
            if task_id not in self.active_tasks:
                logger.warning(f"Task {task_id} not found for completion")
                return
            
            context = self.active_tasks[task_id]
            context.state = TaskState.COMPLETED if success else TaskState.FAILED
            context.end_time = datetime.now(timezone.utc)
            context.progress = 100 if success else context.progress
            
            if error_message:
                context.error_message = error_message
            
            if result:
                context.metadata.update(result)
            
            # Execute cleanup callbacks
            self._execute_cleanup_callbacks(context)
            
            # Persist final state
            self._persist_task_state(context)
            
            # Broadcast completion
            self._broadcast_completion_update(context)
            
            # Clean up active task after a delay
            threading.Timer(300, self._cleanup_completed_task, args=[task_id]).start()
            
            logger.info(f"Task {task_id} completed: {context.state}")
    
    def add_cleanup_callback(self, task_id: str, callback: Callable):
        """Add a cleanup callback for a task"""
        with self.lock:
            if task_id in self.active_tasks:
                self.active_tasks[task_id].cleanup_callbacks.append(callback)
    
    def add_rollback_callback(self, task_id: str, callback: Callable):
        """Add a rollback callback for a task"""
        with self.lock:
            if task_id in self.active_tasks:
                self.active_tasks[task_id].rollback_callbacks.append(callback)
    
    def _check_cancellation_request(self, task_id: str) -> bool:
        """Check if cancellation was requested for a task"""
        return cache.get(f"task_cancel_{task_id}", False)
    
    def _check_timeout(self, context: TaskContext) -> bool:
        """Check if task has exceeded timeout"""
        if not context.start_time:
            return False
        
        timeout_minutes = context.metadata.get('timeout_minutes', 60)  # Default 1 hour
        elapsed = datetime.now(timezone.utc) - context.start_time
        return elapsed.total_seconds() > (timeout_minutes * 60)
    
    def _process_cancellation(self, context: TaskContext):
        """Process task cancellation"""
        if context.state == TaskState.CANCELLED:
            return  # Already cancelled
        
        if context.state != TaskState.CANCELLING:
            context.state = TaskState.CANCELLING
            logger.info(f"Processing cancellation for task {context.task_id}")
        
        # Execute rollback callbacks first
        self._execute_rollback_callbacks(context)
        
        # Then cleanup callbacks
        self._execute_cleanup_callbacks(context)
        
        # Mark as cancelled
        context.state = TaskState.CANCELLED
        context.end_time = datetime.now(timezone.utc)
        
        # Persist and broadcast
        self._persist_task_state(context)
        self._broadcast_cancellation_update(context)
    
    def _process_timeout(self, context: TaskContext):
        """Process task timeout"""
        logger.warning(f"Task {context.task_id} timed out")
        context.cancellation_requested = True
        context.cancellation_reason = CancellationReason.TIMEOUT
        self._process_cancellation(context)
    
    def _execute_cleanup_callbacks(self, context: TaskContext):
        """Execute cleanup callbacks for a task"""
        for callback in context.cleanup_callbacks:
            try:
                callback()
            except Exception as e:
                logger.error(f"Error executing cleanup callback for task {context.task_id}: {e}")
        
        # Always execute Redis cleanup for cancelled tasks
        if context.state in [TaskState.CANCELLED, TaskState.FAILED]:
            self._cleanup_redis_for_task(context.task_id)
    
    def _execute_rollback_callbacks(self, context: TaskContext):
        """Execute rollback callbacks for a task"""
        for callback in context.rollback_callbacks:
            try:
                callback()
            except Exception as e:
                logger.error(f"Error executing rollback callback for task {context.task_id}: {e}")
    
    def _setup_shutdown_handlers(self):
        """Setup signal handlers for graceful shutdown with queue cleanup"""
        def shutdown_handler(signum, frame):
            logger.info(f"Received shutdown signal {signum}, cleaning up...")
            self._graceful_shutdown()
            
        def emergency_shutdown():
            """Emergency shutdown handler for atexit"""
            logger.info("Process exiting, performing emergency cleanup...")
            self._graceful_shutdown()
        
        # Only register signal handlers if we're in the main thread
        try:
            # Check if we're in the main thread
            if threading.current_thread() is threading.main_thread():
                signal.signal(signal.SIGTERM, shutdown_handler)
                signal.signal(signal.SIGINT, shutdown_handler)
                logger.info("TaskManager: Signal handlers registered for graceful shutdown")
            else:
                logger.info("TaskManager: Skipping signal handlers (not in main thread)")
        except Exception as e:
            logger.warning(f"TaskManager: Could not register signal handlers: {e}")
        
        # Always register atexit handler as fallback (works in any thread)
        try:
            atexit.register(emergency_shutdown)
            logger.info("TaskManager: Atexit handler registered for emergency cleanup")
        except Exception as e:
            logger.warning(f"TaskManager: Could not register atexit handler: {e}")
    
    def _graceful_shutdown(self):
        """Perform graceful shutdown with queue cleanup"""
        logger.info("TaskManager: Starting graceful shutdown...")
        
        # Stop monitoring
        self.stop_monitoring()
        
        # Cancel all active tasks
        with self.lock:
            for task_id, context in self.active_tasks.items():
                logger.info(f"Cancelling active task {task_id} due to shutdown")
                context.cancellation_requested = True
                context.cancellation_reason = CancellationReason.SYSTEM_SHUTDOWN
                context.state = TaskState.CANCELLED
                self._execute_cleanup_callbacks(context)
        
        # Clear the entire Huey queue
        logger.info("TaskManager: Clearing Huey queue on shutdown...")
        clear_huey_queue_on_shutdown()
        
        logger.info("TaskManager: Graceful shutdown completed")
    
    def _cleanup_redis_for_task(self, task_id: str):
        """Clean up Redis entries for a specific task"""
        if not self._redis_client:
            logger.warning(f"Redis client not available for task cleanup: {task_id}")
            return
        
        try:
            # Find all Redis keys related to this specific task
            task_patterns = [
                f"*{task_id}*",  # Any key containing the task ID
                f"arkumu:task:{task_id}*",  # Arkumu-specific task keys
                f"huey:task:{task_id}*",  # Huey-specific task keys
                f"*task_state_{task_id}*",  # Task state cache keys
                f"*task_cancel_{task_id}*",  # Task cancellation cache keys
            ]
            
            keys_to_delete = []
            for pattern in task_patterns:
                keys = self._redis_client.keys(pattern)
                keys_to_delete.extend(keys)
            
            # Remove duplicates
            keys_to_delete = list(set(keys_to_delete))
            
            if keys_to_delete:
                deleted_count = self._redis_client.delete(*keys_to_delete)
                logger.info(f"Cleaned up {deleted_count} Redis keys for task {task_id}: {keys_to_delete}")
            else:
                logger.info(f"No Redis keys found for task {task_id}")
                
            # Also clean up from Huey's internal queue structures
            self._cleanup_huey_queue_for_task(task_id)
            
        except Exception as e:
            logger.error(f"Error cleaning up Redis for task {task_id}: {e}")
    
    def _cleanup_huey_queue_for_task(self, task_id: str):
        """Clean up Huey queue entries for a specific task"""
        if not self._redis_client:
            return
        
        try:
            # Common Huey queue names
            queue_names = ['arkumu', 'huey', 'default']
            
            for queue_name in queue_names:
                # Check various queue structures
                queue_keys = [
                    queue_name,
                    f"{queue_name}:queue",
                    f"{queue_name}:tasks",
                    f"{queue_name}:pending",
                    f"{queue_name}:results"
                ]
                
                for queue_key in queue_keys:
                    try:
                        # For list-based queues, we need to scan and remove specific items
                        if self._redis_client.exists(queue_key):
                            queue_type = self._redis_client.type(queue_key)
                            
                            if queue_type == 'list':
                                # Scan list for items containing task_id
                                list_length = self._redis_client.llen(queue_key)
                                for i in range(list_length):
                                    try:
                                        item = self._redis_client.lindex(queue_key, i)
                                        if item and task_id in str(item):
                                            # Remove this item from the list
                                            self._redis_client.lrem(queue_key, 0, item)
                                            logger.info(f"Removed task {task_id} from queue {queue_key}")
                                    except Exception:
                                        continue
                            
                            elif queue_type == 'hash':
                                # For hash-based structures, remove keys containing task_id
                                hash_keys = self._redis_client.hkeys(queue_key)
                                for hash_key in hash_keys:
                                    if task_id in str(hash_key):
                                        self._redis_client.hdel(queue_key, hash_key)
                                        logger.info(f"Removed task {task_id} from hash {queue_key}")
                    
                    except Exception as e:
                        logger.debug(f"Error scanning queue {queue_key}: {e}")
                        continue
            
            logger.info(f"Completed Huey queue cleanup for task {task_id}")
            
        except Exception as e:
            logger.error(f"Error cleaning up Huey queues for task {task_id}: {e}")
    
    def _persist_task_state(self, context: TaskContext):
        """Persist task state to cache and database"""
        # Cache for real-time access
        cache_key = f"task_state_{context.task_id}"
        cache_data = {
            "task_id": context.task_id,
            "state": context.state.value,
            "progress": context.progress,
            "phase": context.phase,
            "cancellation_requested": context.cancellation_requested,
            "cancellation_reason": context.cancellation_reason.value if context.cancellation_reason else None,
            "start_time": context.start_time.isoformat() if context.start_time else None,
            "end_time": context.end_time.isoformat() if context.end_time else None,
            "error_message": context.error_message,
            "metadata": context.metadata,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        cache.set(cache_key, cache_data, timeout=3600)
        
        # Update database session if available
        if context.session_id:
            try:
                with transaction.atomic():
                    session = IngestSession.objects.get(id=context.session_id)
                    session.status = self._map_task_state_to_session_status(context.state)
                    
                    if context.error_message:
                        session.error_message = context.error_message[:1024]
                    
                    if context.state in [TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELLED]:
                        session.completed_at = django_timezone.now()
                    
                    session.save()
            except Exception as e:
                logger.error(f"Error updating session {context.session_id}: {e}")
    
    def _broadcast_progress_update(self, context: TaskContext, message: Optional[str], details: Optional[Dict]):
        """Broadcast progress update via WebSocket"""
        # This will be implemented with WebSocket integration
        pass
    
    def _broadcast_cancellation_update(self, context: TaskContext):
        """Broadcast cancellation update via WebSocket"""
        # This will be implemented with WebSocket integration
        pass
    
    def _broadcast_completion_update(self, context: TaskContext):
        """Broadcast completion update via WebSocket"""
        # This will be implemented with WebSocket integration
        pass
    
    def _update_realtime_status(self, context: TaskContext):
        """Update real-time status indicators"""
        # This will be implemented with WebSocket integration
        pass
    
    def _map_task_state_to_session_status(self, state: TaskState) -> str:
        """Map task state to session status"""
        mapping = {
            TaskState.PENDING: 'pending',
            TaskState.RUNNING: 'processing',
            TaskState.CANCELLING: 'cancelling',
            TaskState.CANCELLED: 'cancelled',
            TaskState.COMPLETED: 'completed',
            TaskState.FAILED: 'failed',
            TaskState.INTERRUPTED: 'failed'
        }
        return mapping.get(state, 'unknown')
    
    def _cleanup_completed_task(self, task_id: str):
        """Clean up completed task after delay"""
        with self.lock:
            if task_id in self.active_tasks:
                del self.active_tasks[task_id]
                cache.delete(f"task_state_{task_id}")
                cache.delete(f"task_cancel_{task_id}")
                logger.info(f"Cleaned up completed task {task_id}")
    
    @contextmanager
    def task_context(self, task_id: str, session_id: Optional[str] = None, 
                    user_id: Optional[str] = None, metadata: Optional[Dict] = None):
        """Context manager for task execution with automatic cleanup"""
        context = self.register_task(task_id, session_id, user_id, metadata)
        try:
            yield context
            self.complete_task(task_id, success=True)
        except CancelExecution:
            self.complete_task(task_id, success=False, error_message="Task was cancelled")
            raise
        except Exception as e:
            self.complete_task(task_id, success=False, error_message=str(e))
            raise


# Global task manager instance
task_manager = None


def get_task_manager() -> TaskManager:
    """Get the global task manager instance"""
    global task_manager
    if task_manager is None:
        from config.settings.base import HUEY
        from huey.contrib.djhuey import HUEY as huey_instance
        task_manager = TaskManager(huey_instance)
        # Clear any stale tasks from previous runs (only in main thread)
        if threading.current_thread() is threading.main_thread():
            clear_huey_queue_on_startup()
    return task_manager


def clear_huey_queue_on_startup():
    """
    Clear stale tasks from previous container runs on startup.
    
    This ensures a clean state when the container starts up,
    preventing stale tasks from interfering with new operations.
    """
    try:
        logger.info("Startup: Clearing stale Huey tasks from previous runs...")
        success = clear_huey_queue_on_shutdown()
        if success:
            logger.info("Startup: Successfully cleared stale Huey tasks")
        else:
            logger.warning("Startup: Failed to clear stale Huey tasks")
    except Exception as e:
        logger.error(f"Startup: Error clearing stale Huey tasks: {e}")


class ProgressUpdater:
    """Serializable progress updater for cancellable tasks"""
    
    def __init__(self, task_id: str):
        self.task_id = task_id
    
    def __call__(self, progress: int, phase: str, message: str = None, details: Dict = None):
        manager = get_task_manager()
        manager.update_task_progress(self.task_id, progress, phase, message, details)


def cancellable_task(task_id_param: str = 'upload_session_id', 
                    session_id_param: str = 'upload_session_id'):
    """
    Decorator for making tasks cancellable with proper lifecycle management
    """
    def decorator(func):
        def wrapper(*args, **kwargs):
            # Extract task and session IDs from parameters
            task_id = kwargs.get(task_id_param)
            session_id = kwargs.get(session_id_param)
            
            if not task_id:
                # Generate task ID if not provided
                task_id = str(uuid.uuid4())
                kwargs[task_id_param] = task_id
            
            manager = get_task_manager()
            
            # Use task context manager for automatic lifecycle management
            with manager.task_context(task_id, session_id) as context:
                # Add serializable progress update helper to kwargs
                kwargs['update_progress'] = ProgressUpdater(task_id)
                kwargs['task_context'] = context
                
                # Execute the original function
                # In test/immediate mode, djhuey tasks can be executed synchronously via call_local
                try:
                    huey_settings = getattr(settings, 'HUEY', {})
                    immediate = bool(huey_settings.get('immediate'))
                except Exception:
                    immediate = False

                if immediate and hasattr(func, 'call_local'):
                    return func.call_local(*args, **kwargs)
                return func(*args, **kwargs)
        
        return wrapper
    return decorator
