from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.views.decorators.http import require_POST
from django.db.models import Count
from django.utils import timezone

from arkumu.metadata.models.resource import Resource, ResourceType
from arkumu.metadata.models.triples import Triple
from typing import List
from types import SimpleNamespace
from collections import Counter

from arkumu.storage.models.upload_tracking import AsyncUploadSession, AsyncUploadFile
from arkumu.importer.models import IngestSession
from arkumu.users.mixins import general_login_required


def _format_size(bytes_total: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(bytes_total)
    for unit in units:
        if size < 1024 or unit == units[-1]:
            return f"{size:.1f} {unit}"
        size /= 1024


def _build_file_info(files) -> List[dict]:
    info = []
    for file_obj in files:
        info.append({
            'name': getattr(file_obj, 'filename', ''),
            'status': file_obj.status,
            'size': getattr(file_obj, 'file_size', 0),
            'content_type': getattr(file_obj, 'content_type', ''),
            'error_message': getattr(file_obj, 'error_message', ''),
        })
    return info


class UploadSessionDisplay:
    """Lightweight view model for async upload sessions."""

    def __init__(self, session: AsyncUploadSession, files: List[AsyncUploadFile]):
        self.id = session.id
        self.created_at = session.created_at
        self.completed_at = session.completed_at
        self.status = session.status
        self._status_display = session.get_status_display()
        self.user = session.user
        self.institution = session.organization or 'Not specified'
        self.organization = session.organization
        self.folder_name = session.base_folder or ''
        self._status_counts = Counter(f.status for f in files)
        file_count = len(files)
        self.total_files = session.total_files or file_count
        self.completed_files = self._status_counts.get('completed', 0)
        self.failed_files = self._status_counts.get('failed', 0)
        # Files that have reached S3 but not yet marked completed/failed
        self.uploaded_files = (
            self._status_counts.get('uploaded', 0)
            + self._status_counts.get('processing', 0)
        )
        # Files still pending client upload or mid-transfer
        self.pending_files = (
            self._status_counts.get('pending', 0)
            + self._status_counts.get('uploading', 0)
        )
        self.in_progress_files = self.uploaded_files + self.pending_files
        self.import_stats = _build_import_stats(session, files)

    def get_status_display(self):
        return self._status_display


def _build_import_stats(session: AsyncUploadSession, files: List[AsyncUploadFile]) -> SimpleNamespace:
    total_size = sum(f.file_size or 0 for f in files)
    start_time = session.started_at or session.created_at
    end_time = session.completed_at or timezone.now()
    duration_seconds = max((end_time - start_time).total_seconds(), 0)
    error_messages = [f.error_message for f in files if f.error_message]

    summary = SimpleNamespace(
        bucket=session.organization or '-',
        base_path=session.base_folder or '-',
    )

    return SimpleNamespace(
        duration_seconds=duration_seconds,
        total_size=total_size,
        total_size_formatted=_format_size(total_size),
        summary=summary,
        error_count=len([f for f in files if f.status == 'failed']),
        error=error_messages[0] if error_messages else None,
    )


def _build_upload_display(session: AsyncUploadSession, files: List[AsyncUploadFile] | None = None) -> UploadSessionDisplay:
    if files is None:
        files = list(session.files.all())
    return UploadSessionDisplay(session, files)


@general_login_required
def metadata_dashboard(request):
    """Main dashboard view for metadata visualization and analysis."""
    # Get basic statistics
    stats = {
        'total_resources': Resource.objects.count(),
        'total_triples': Triple.objects.count(),
        'iri_resources': Resource.objects.filter(resource_type=ResourceType.IRI).count(),
        'literal_resources': Resource.objects.filter(resource_type=ResourceType.LITERAL).count(),
        'class_resources': Resource.objects.filter(resource_type=ResourceType.CLASS).count(),
        'property_resources': Resource.objects.filter(resource_type=ResourceType.PROPERTY).count(),
        'uploads': AsyncUploadSession.objects.count(),
        'ingests': IngestSession.objects.count(),
    }
    
    # Get recent uploads
    recent_uploads = []
    for session in AsyncUploadSession.objects.select_related('user').prefetch_related('files').order_by('-created_at')[:5]:
        recent_uploads.append(_build_upload_display(session, list(session.files.all())))
    
    # Get recent ingests
    recent_ingests = IngestSession.objects.select_related('organization').order_by('-created_at')[:5]
    
    # Get institutions with resource counts
    institutions = Resource.objects.values('organization__name').annotate(
        count=Count('id')
    ).order_by('-count')[:10]
    
    # Get organizations with triple counts for selective deletion
    from arkumu.users.models import Organization
    organizations_with_data = []
    for org in Organization.objects.filter(is_active=True).order_by('name'):
        triple_count = Triple.objects.for_organization(org).count()
        resource_count = Resource.objects.for_organization(org).count()
        if triple_count > 0 or resource_count > 0:  # Only show orgs with data
            organizations_with_data.append({
                'id': org.id,
                'name': org.name,
                'code': org.code,
                'triple_count': triple_count,
                'resource_count': resource_count
            })
    
    return render(request, 'dashboard.html', {
        'stats': stats,
        'recent_uploads': recent_uploads,
        'recent_ingests': recent_ingests,
        'institutions': institutions,
        'organizations_with_data': organizations_with_data,
    })


@general_login_required
def all_upload_sessions(request):
    """Displays a list of all upload sessions with their files."""
    all_sessions = AsyncUploadSession.objects.select_related('user').prefetch_related('files').order_by('-created_at')

    enhanced_sessions = []
    for session in all_sessions:
        files = list(session.files.all())
        display = _build_upload_display(session, files)
        file_info = _build_file_info(files)
        enhanced_sessions.append({
            'session': display,
            'files': file_info,
            'file_count': len(file_info),
            'is_multi_file': len(file_info) > 1,
            'completed_files': sum(1 for f in file_info if f['status'] == 'completed'),
            'failed_files': sum(1 for f in file_info if f['status'] == 'failed'),
        })

    # Aggregate statistics
    total_stats = {
        'total_sessions': len(enhanced_sessions),
        'total_files': sum(item['file_count'] for item in enhanced_sessions),
        'completed_sessions': sum(1 for item in enhanced_sessions if item['session'].status == 'completed'),
        'failed_sessions': sum(1 for item in enhanced_sessions if item['session'].status == 'failed'),
        'in_progress_sessions': sum(1 for item in enhanced_sessions if item['session'].status in {'initialized', 'presigned_generated', 'uploading', 'processing'}),
    }
    
    return render(request, 'all_upload_sessions.html', {
        'enhanced_sessions': enhanced_sessions,
        'total_stats': total_stats
    })


@general_login_required
def all_ingest_sessions(request):
    """Displays a list of all ingest sessions with their datasets."""
    all_ingests = IngestSession.objects.select_related('organization').prefetch_related('import_tasks').all().order_by('-created_at')
    
    # Prepare enhanced session data
    enhanced_sessions = []
    for session in all_ingests:
        # Get associated import tasks (individual datasets)
        import_tasks = list(session.import_tasks.all())
        
        # Determine datasets for this session
        datasets = []
        if import_tasks:
            # Multi-dataset session - each ImportTask is a dataset
            for task in import_tasks:
                datasets.append({
                    'name': task.dataset_name,
                    'file_path': task.file_path,
                    'status': task.status,
                    'rows_processed': task.rows_processed,
                    'task_id': task.task_id,
                })
        elif session.file_paths:
            # Multi-file session from file_paths
            for file_path in session.file_paths:
                filename = file_path.split('/')[-1] if '/' in file_path else file_path
                datasets.append({
                    'name': filename,
                    'file_path': file_path,
                    'status': session.status,
                    'rows_processed': session.processed_rows if len(session.file_paths) == 1 else None,
                })
        else:
            # Single dataset session
            datasets.append({
                'name': session.dataset_name or session.file_name or 'Unknown Dataset',
                'file_path': session.s3_object_key,
                'status': session.status,
                'rows_processed': session.processed_rows,
            })
        
        enhanced_sessions.append({
            'session': session,
            'datasets': datasets,
            'dataset_count': len(datasets),
            'is_multi_dataset': len(datasets) > 1
        })
    
    # Calculate aggregate statistics
    total_stats = {
        'total_sessions': len(enhanced_sessions),
        'total_datasets': sum(item['dataset_count'] for item in enhanced_sessions),
        'completed_sessions': sum(1 for item in enhanced_sessions if item['session'].status == 'completed'),
        'failed_sessions': sum(1 for item in enhanced_sessions if item['session'].status == 'failed'),
        'processing_sessions': sum(1 for item in enhanced_sessions if item['session'].status == 'processing'),
        'total_rows_processed': 0,
        'total_resources_created': 0,
        'total_triples_created': 0,
        'sessions_with_stats': 0,
    }
    
    # Sum up ingestion stats
    for item in enhanced_sessions:
        session = item['session']
        if session.ingestion_stats:
            total_stats['sessions_with_stats'] += 1
            total_stats['total_rows_processed'] += session.ingestion_stats.get('rows_processed', 0)
            total_stats['total_resources_created'] += session.ingestion_stats.get('resources_created', 0)
            total_stats['total_triples_created'] += session.ingestion_stats.get('triples_created', 0)
    
    return render(request, 'all_ingest_sessions.html', {
        'enhanced_sessions': enhanced_sessions,
        'total_stats': total_stats
    })


@general_login_required
def ingest_session_stats(request, session_id):
    """HTMX endpoint to show detailed stats for a specific ingest session."""
    try:
        session = IngestSession.objects.get(pk=session_id)
        return render(request, 'importer/partials/stats_modal_content.html', {
            'session': session,
            'show_expanded': True
        })
    except IngestSession.DoesNotExist:
        return render(request, 'partials/error_message.html', {
            'error': 'Ingest session not found'
        })


@general_login_required
def upload_session_stats(request, session_id):
    """HTMX endpoint to show detailed stats for a specific upload session."""
    try:
        session = AsyncUploadSession.objects.prefetch_related('files').get(pk=session_id)

        file_info = _build_file_info(session.files.all())
        completed_files = sum(1 for f in file_info if f['status'] == 'completed')
        failed_files = sum(1 for f in file_info if f['status'] == 'failed')

        return render(request, 'partials/upload_stats_modal_content.html', {
            'session': _build_upload_display(session),
            'files': file_info,
            'file_count': len(file_info),
            'completed_files': completed_files,
            'failed_files': failed_files,
        })
    except AsyncUploadSession.DoesNotExist:
        return render(request, 'partials/error_message.html', {
            'error': 'Upload session not found'
        })


@general_login_required
@require_POST
def trigger_cache_refresh(request):
    """Enqueue Huey jobs that rebuild project and schema caches."""
    if not request.user.is_staff:
        messages.error(request, 'Only staff members can trigger cache refreshes.')
        return redirect('metadata:metadata_dashboard')

    from arkumu.cache.tasks import (
        warm_cross_institutional_projects_cache,
        warm_schema_cache,
        warm_card_schema_cache,
    )

    warm_cross_institutional_projects_cache.schedule(delay=0)
    warm_schema_cache.schedule(delay=0)
    warm_card_schema_cache.schedule(delay=0)

    messages.success(
        request,
        'Cache warm-up tasks enqueued. Huey will rebuild snapshots and schema data shortly.',
    )
    return redirect('metadata:metadata_dashboard')
