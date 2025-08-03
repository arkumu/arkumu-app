"""
Simple multipart upload view - no unnecessary complexity
"""
import logging

from django.conf import settings
from django.shortcuts import render
from django.http import JsonResponse, HttpResponse
from django.core.cache import cache
from django.template.loader import render_to_string
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.viewsets import ViewSet
from rest_framework.permissions import AllowAny

from arkumu.storage.services.upload_service import UploadService
from arkumu.storage.services.bucket_service import BucketService
from arkumu.users.models import Organization
from arkumu.users.mixins import GeneralLoginRequiredMixin
from arkumu.metadata.views.csv_mapping.mixins.template_helpers import CSVMappingTemplateHelperMixin

logger = logging.getLogger(__name__)


class SimpleMultipartUploadHelper(CSVMappingTemplateHelperMixin):
    """Helper class to use template mixin methods for OOB updates"""
    pass


def clear_bucket_cache(bucket_name: str, folder_path: str = None):
    """Clear bucket cache for the uploaded files to refresh the UI."""
    # Clear root bucket cache
    root_cache_key = f"bucket_contents_{bucket_name}_"
    cache.delete(root_cache_key)
    logger.info(f"🗑️ CACHE CLEARED: Root bucket cache for {bucket_name}: {root_cache_key}")
    
    # Clear folder-specific cache if folder_path provided
    if folder_path:
        folder_cache_key = f"bucket_contents_{bucket_name}_{folder_path.replace('/', '_')}_"
        cache.delete(folder_cache_key)
        logger.info(f"🗑️ CACHE CLEARED: Folder cache for {bucket_name}/{folder_path}: {folder_cache_key}")
    
    # Also clear any parent directory caches
    if folder_path and '/' in folder_path:
        parent_paths = []
        path_parts = folder_path.split('/')
        for i in range(len(path_parts)):
            parent_path = '/'.join(path_parts[:i+1])
            if parent_path and parent_path != folder_path:
                parent_paths.append(parent_path)
        
        for parent_path in parent_paths:
            parent_cache_key = f"bucket_contents_{bucket_name}_{parent_path.replace('/', '_')}_"
            cache.delete(parent_cache_key)
            logger.info(f"🗑️ CACHE CLEARED: Parent path cache for {bucket_name}/{parent_path}: {parent_cache_key}")


def simple_multipart_form(request):
    """Render the simple upload form"""
    organizations = Organization.objects.all()
    return render(request, 'upload/simple_multipart.html', {
        'organizations': organizations
    })


class SimpleMultipartUploadViewSet(GeneralLoginRequiredMixin, CSVMappingTemplateHelperMixin, ViewSet):
    """Simple multipart upload for large files"""
    
    def render_file_browser_content(self, organization, request):
        """Render updated file browser content for the organization"""
        try:
            bucket_service = BucketService()
            bucket_name = organization.lower()
            
            # Get the file structure for the organization - force fresh after upload
            contents = bucket_service.list_bucket_contents(bucket_name, prefix='', force_fresh=True)
            
            # Add file counts for data and metadata folders - force fresh after upload
            for item in contents:
                if item['type'] == 'folder' and item['name'] in ['data', 'metadata']:
                    item['file_count'] = bucket_service.count_files_in_folder(bucket_name, item['path'], force_fresh=True)
            
            from django.middleware.csrf import get_token
            context = {
                'organization': organization,
                'contents': contents,  # Template expects 'contents' not 'items'
                'bucket_name': bucket_name,
                'csrf_token': get_token(request)
            }
            
            return render_to_string(
                'dashboard/organization_files_partial.html',
                context,
                request=request
            )
        except Exception as e:
            logger.error(f"Error rendering file browser content: {str(e)}")
            return f'''
            <div class="alert alert-info">
                <span>Files updated. Please refresh to see changes.</span>
            </div>
            '''
    
    @action(detail=False, methods=['post'])
    def upload(self, request):
        """Stream file upload with parallel processing"""
        print("🚀🚀🚀 DJANGO VIEW TRIGGERED! 🚀🚀🚀")
        print(f"Request method: {request.method}")
        print(f"POST data: {dict(request.POST)}")
        print(f"FILES: {list(request.FILES.keys())}")
        
        logger.info(f"🚀 UPLOAD_START: Request method={request.method}")
        logger.info(f"📝 UPLOAD_DATA: POST data={dict(request.POST)}")
        logger.info(f"📁 UPLOAD_FILES: FILES keys={list(request.FILES.keys())}")
        logger.info(f"🔑 UPLOAD_HEADERS: Content-Type={request.content_type}")
        
        # Handle both 'file' (singular) and 'files' (plural) field names
        # For multiple files, getlist returns a list; for single file, get returns the file
        files_list = request.FILES.getlist('files') or request.FILES.getlist('file')
        
        # Handle both FormData and JSON requests
        organization = request.POST.get('organization') or request.data.get('organization', 'DEFAULT')
        folder_path = request.POST.get('folder_path') or request.POST.get('base_folder') or request.data.get('folder_path', 'data')
        
        logger.info(f"📦 UPLOAD_PARAMS: files_count={len(files_list)}, org={organization}, folder={folder_path}")
        
        if not files_list:
            logger.error("❌ UPLOAD_ERROR: No files provided in request")
            html = '''
            <div class="alert alert-error">
                <svg xmlns="http://www.w3.org/2000/svg" class="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 14l2-2m0 0l2-2m-2 2l-2-2m2 2l2 2m7-2a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
                <span>No files provided</span>
            </div>
            '''
            return HttpResponse(html, status=400)
        
        # Initialize upload service
        logger.info(f"🔧 UPLOAD_SERVICE: Initializing upload service")
        upload_service = UploadService()
        
        # Determine target bucket - use organization as bucket name
        bucket_name = organization.lower()
        logger.info(f"🪣 UPLOAD_TARGET: Using bucket_name={bucket_name}")
        
        # Process ALL files the same way - let the upload service handle size decisions
        results = []
        success_count = 0
        
        for file_obj in files_list:
            s3_key = f"{folder_path}/{file_obj.name}"
            logger.info(f"📁 UPLOADING: {file_obj.name} → {s3_key} ({file_obj.size / (1024*1024):.2f} MB)")
            
            # Use the same method for ALL files - it handles encryption and multipart automatically
            result = upload_service._upload_file_to_custom_key(
                file_obj=file_obj,
                s3_key=s3_key,
                bucket_name=bucket_name,
                content_type=file_obj.content_type or 'application/octet-stream'
            )
            
            results.append(result)
            if result.get('success'):
                success_count += 1
            else:
                logger.error(f"❌ FAILED: {file_obj.name} - {result.get('error', 'Unknown error')}")
        
        # Clear cache after uploads
        clear_bucket_cache(bucket_name, folder_path)
        
        # Return success/error response
        total_files = len(files_list)
        if success_count == total_files:
            logger.info(f"✅ ALL SUCCESS: {success_count}/{total_files} files uploaded to {bucket_name}")
            
            # Main success message
            main_html = f'''
            <div class="alert alert-success">
                <svg xmlns="http://www.w3.org/2000/svg" class="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
                <span>Successfully uploaded {success_count}/{total_files} files to {bucket_name}!</span>
            </div>
            '''
            
            # Create OOB update for file browser content
            file_browser_html = self.render_file_browser_content(organization, request)
            oob_updates = {
                'file-browser-content': file_browser_html
            }
            
            # Return response with OOB updates
            return HttpResponse(self.build_oob_response(main_html, oob_updates))
        else:
            failed_count = total_files - success_count
            logger.error(f"❌ PARTIAL FAILURE: {success_count}/{total_files} succeeded, {failed_count} failed")
            html = f'''
            <div class="alert alert-warning">
                <svg xmlns="http://www.w3.org/2000/svg" class="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4c-.77-.833-1.732-.833-2.5 0L4.268 16.5c-.77.833.192 2.5 1.732 2.5z" />
                </svg>
                <span>Uploaded {success_count}/{total_files} files. {failed_count} failed.</span>
            </div>
            '''
            return HttpResponse(html, status=207)  # 207 Multi-Status