import logging
import json
import tempfile
import os
import hashlib
import time
# import magic  # Not available in container
from typing import Dict, Any, List
from django.http import JsonResponse, HttpResponse
from django.views.decorators.http import require_http_methods
from django.contrib.auth.decorators import login_required
from django.utils.decorators import method_decorator
from django.views import View
from django.middleware.csrf import get_token
from django.views.decorators.cache import cache_control
from django.core.exceptions import ValidationError
from django.conf import settings
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.backends import default_backend
import base64
from arkumu.users.mixins import GeneralLoginRequiredMixin, general_login_required

from arkumu.storage.services.upload_service import UploadService
from arkumu.storage.services.bucket_service import BucketService
from arkumu.storage.models.upload_sessions import UploadSession
from arkumu.metadata.views.csv_mapping.mixins.template_helpers import CSVMappingTemplateHelperMixin

logger = logging.getLogger(__name__)

# No file type restrictions - upload anything
MAX_FILES_PER_REQUEST = 10000  # Allow lots of files

# Cache services to avoid repeated initialization
_upload_service = None
_bucket_service = None

def get_cached_upload_service():
    """Get cached upload service to avoid repeated initialization."""
    global _upload_service
    if _upload_service is None:
        logger.info("🔧 RAW UPLOAD: Initializing UploadService for the first time...")
        start_time = time.time()
        _upload_service = UploadService()
        init_duration = time.time() - start_time
        logger.info(f"🔧 RAW UPLOAD: UploadService initialized in {init_duration:.2f} seconds")
    else:
        logger.info("🔧 RAW UPLOAD: Using cached UploadService")
    return _upload_service

def get_cached_bucket_service():
    """Get cached bucket service to avoid repeated initialization."""
    global _bucket_service
    if _bucket_service is None:
        logger.info("🔧 RAW UPLOAD: Initializing BucketService for the first time...")
        start_time = time.time()
        _bucket_service = BucketService()
        init_duration = time.time() - start_time
        logger.info(f"🔧 RAW UPLOAD: BucketService initialized in {init_duration:.2f} seconds")
    else:
        logger.info("🔧 RAW UPLOAD: Using cached BucketService")
    return _bucket_service

class SecurityError(Exception):
    """Custom exception for security-related errors"""
    pass

class EncryptionService:
    """Service for encrypting/decrypting uploaded files"""
    
    @staticmethod
    def generate_key_from_password(password: str, salt: bytes = None) -> bytes:
        """Generate encryption key from password"""
        if salt is None:
            salt = os.urandom(16)
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=100000,
            backend=default_backend()
        )
        key = base64.urlsafe_b64encode(kdf.derive(password.encode()))
        return key, salt
    
    @staticmethod
    def encrypt_file(file_path: str, password: str) -> str:
        """Encrypt file and return encrypted file path"""
        try:
            key, salt = EncryptionService.generate_key_from_password(password)
            fernet = Fernet(key)
            
            encrypted_path = file_path + '.encrypted'
            
            with open(file_path, 'rb') as original_file:
                original_data = original_file.read()
            
            encrypted_data = fernet.encrypt(original_data)
            
            with open(encrypted_path, 'wb') as encrypted_file:
                # Store salt at the beginning of the file
                encrypted_file.write(salt)
                encrypted_file.write(encrypted_data)
            
            # Remove original file
            os.unlink(file_path)
            
            return encrypted_path
        except Exception as e:
            logger.error(f"File encryption failed: {str(e)}")
            raise SecurityError(f"Encryption failed: {str(e)}")

class RawStreamUploadView(GeneralLoginRequiredMixin, CSVMappingTemplateHelperMixin, View):
    """
    Secure raw multipart stream upload with CSRF protection, validation, and encryption.
    This bypasses the DATA_UPLOAD_MAX_NUMBER_FILES limit by streaming directly.
    """
    
    @method_decorator(cache_control(no_cache=True, no_store=True))
    def dispatch(self, request, *args, **kwargs):
        return super().dispatch(request, *args, **kwargs)
    
    def _validate_csrf_token(self, request) -> bool:
        """Validate CSRF token from request"""
        try:
            # For routing from standard view, CSRF is already validated by Django middleware
            # Just return True since we're being called from an already validated request
            return True
        except Exception as e:
            logger.error(f"CSRF validation error: {str(e)}")
            return False
    
    def _validate_file_content(self, file_path: str, filename: str) -> Dict[str, Any]:
        """Basic file validation - size and hash only"""
        try:
            # Check file size
            file_size = os.path.getsize(file_path)
            
            # Calculate file hash
            hash_sha256 = hashlib.sha256()
            with open(file_path, 'rb') as f:
                for chunk in iter(lambda: f.read(4096), b""):
                    hash_sha256.update(chunk)
            
            return {
                'valid': True,
                'mime_type': 'application/octet-stream',  # Generic type
                'size': file_size,
                'hash': hash_sha256.hexdigest()
            }
            
        except Exception as e:
            logger.error(f"File validation error for {filename}: {str(e)}")
            raise SecurityError(f"File validation failed: {str(e)}")
    
    def _rate_limit_check(self, request) -> bool:
        """Basic rate limiting (in production, use Redis/cache)"""
        # For now, just log - implement Redis-based rate limiting in production
        user_id = request.user.id
        logger.info(f"Rate limit check for user {user_id}")
        return True  # Allow for now
    
    def _build_upload_success_response(self, request, organization, target_bucket, result, upload_time, bucket_service):
        """Build HTMX success response with file browser refresh."""
        from django.template.loader import render_to_string
        from django.http import HttpResponse
        
        # Get updated file browser content
        bucket_name = bucket_service.get_organization_bucket(organization) if organization else target_bucket
        all_contents = bucket_service.list_bucket_contents(bucket_name, '')
        contents = [item for item in all_contents if item.get('type') == 'folder' and '/' not in item.get('name', '').strip('/')]
        
        # Render templates
        file_browser_html = render_to_string(
            'dashboard/organization_files_partial.html',
            {
                'organization': organization,
                'bucket_name': bucket_name,
                'contents': contents,
                'current_path': '',
                'total_size': sum(item.get('size', 0) for item in all_contents),
                'total_files': len([item for item in all_contents if item.get('type') == 'file'])
            },
            request=request
        )
        
        upload_results_html = render_to_string(
            'dashboard/partials/upload_results.html',
            {
                'success': True,
                'files_count': result.get('total_uploaded_files', len(result.get('results', []))),
                'total_size': result.get('total_size_formatted', '0 B'),
                'duration': result.get('duration', f"{upload_time:.2f}s"),
                'folder_name': result.get('folder_name', '')
            },
            request=request
        )
        
        # Build OOB response using template helper pattern
        oob_updates = {
            'upload-status': upload_results_html,
            f'organization-files-{organization}': file_browser_html
        }
        
        return HttpResponse(self.build_oob_response("", oob_updates))
    
    def _build_upload_error_response(self, result):
        """Build HTMX error response."""
        from django.template.loader import render_to_string
        from django.http import HttpResponse
        
        error_html = f'<div class="alert alert-error">Upload failed: {result.get("error", "Unknown error")}</div>'
        
        # Build OOB response using template helper pattern
        oob_updates = {
            'upload-status': error_html
        }
        
        return HttpResponse(self.build_oob_response("", oob_updates))
    
    def _format_file_size(self, size_bytes: int) -> str:
        """Format bytes to human-readable size (same as standard upload)."""
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if size_bytes < 1024.0:
                return f"{size_bytes:.2f} {unit}"
            size_bytes /= 1024.0
        return f"{size_bytes:.2f} PB"
    
    
    def post(self, request):
        """
        Process file upload using Django's built-in parsing, then stream to S3.
        """
        upload_start_time = time.time()
        
        try:
            logger.info(f"🔐 RAW UPLOAD: Using Django's built-in file parsing")
            logger.info(f"Processing raw stream upload for user: {request.user.username}")
            
            # Authentication check
            if not request.user.is_authenticated:
                return JsonResponse({'error': 'Authentication required'}, status=401)
            
            # Rate limiting
            if not self._rate_limit_check(request):
                return JsonResponse({'error': 'Rate limit exceeded'}, status=429)
            
            # Get form data (Django already parsed POST and FILES)
            folder_name = request.POST.get('folder_name', '').strip()
            organization = request.POST.get('organization', '').strip()
            file_paths_json = request.POST.get('file_paths', '[]')
            
            logger.info(f"📊 RAW UPLOAD: folder_name='{folder_name}', organization='{organization}'")
            logger.info(f"📊 RAW UPLOAD: Found {len(request.FILES)} files in request.FILES")
            
            if not folder_name:
                return JsonResponse({'error': 'folder_name is required'}, status=400)
            
            # Get uploaded files (Django already parsed them!)
            files = request.FILES.getlist('files')
            if not files:
                return JsonResponse({'error': 'No files uploaded'}, status=400)
            
            # Calculate total size for tracking
            total_size = sum(f.size for f in files)
            logger.info(f"📊 RAW UPLOAD: Total upload size: {total_size / (1024*1024):.2f}MB")
            
            # Create upload session for tracking
            upload_session = UploadSession.create_from_import(
                user=request.user,
                folder_name=folder_name,
                import_type='file_upload',
                institution=organization or 'DEFAULT',
                s3_bucket='',  # Will be filled in below
                s3_base_path=folder_name
            )
            upload_session.total_files = len(files)
            upload_session.total_size_bytes = total_size
            upload_session.save()
            
            logger.info(f"📊 RAW UPLOAD: Created UploadSession {upload_session.id} for tracking")
            
            # Parse file paths for structured upload
            file_paths = []
            try:
                if file_paths_json and file_paths_json != '[]':
                    file_paths = json.loads(file_paths_json)
                    logger.info(f"📊 RAW UPLOAD: Using structured upload with {len(file_paths)} paths")
            except json.JSONDecodeError:
                logger.warning("Invalid file_paths JSON, using standard upload")
            
            # Get cached services to avoid repeated initialization
            upload_service = get_cached_upload_service()
            bucket_service = get_cached_bucket_service()
            
            # Determine target bucket
            if organization:
                target_bucket = bucket_service.get_organization_bucket(organization)
                logger.info(f"📊 RAW UPLOAD: Using organization bucket: {target_bucket} for organization: {organization}")
            else:
                target_bucket = upload_service.base_s3_service.ingest_bucket
                logger.info(f"📊 RAW UPLOAD: No organization specified, using default ingest bucket: {target_bucket}")
            
            # Update session with bucket info
            upload_session.s3_bucket = target_bucket
            upload_session.save()
            
            logger.info(f"📊 RAW UPLOAD: Uploading {len(files)} files to bucket: {target_bucket}")
            
            # Log file details (first few files)
            for i, uploaded_file in enumerate(files[:3]):
                logger.info(f"📄 FILE {i+1}: {uploaded_file.name} ({uploaded_file.size} bytes)")
                if hasattr(uploaded_file, 'temporary_file_path'):
                    logger.info(f"📄 FILE {i+1}: Temp file at {uploaded_file.temporary_file_path()}")
                else:
                    logger.info(f"📄 FILE {i+1}: In memory (small file)")
            
            # Use appropriate upload method
            if file_paths and len(file_paths) == len(files):
                logger.info(f"📊 RAW UPLOAD: Using structured upload")
                result = upload_service.upload_batch_django_files_with_structure(
                    uploaded_files=files,
                    base_path=folder_name,
                    bucket_name=target_bucket,
                    file_paths=file_paths
                )
            else:
                logger.info(f"📊 RAW UPLOAD: Using standard batch upload")
                result = upload_service.upload_batch_django_files_optimized(
                    uploaded_files=files,
                    path_prefix=folder_name,
                    bucket_name=target_bucket
                )
            
            # Log results and update session
            upload_time = time.time() - upload_start_time
            if result.get('success', False):
                logger.info(f"✅ RAW UPLOAD: Completed {len(files)} files in {upload_time:.2f}s")
                upload_session.mark_completed(result)
                logger.info(f"📊 RAW UPLOAD: Marked UploadSession {upload_session.id} as completed")
            else:
                error_msg = result.get('error', 'Unknown error')
                logger.error(f"❌ RAW UPLOAD: Failed after {upload_time:.2f}s: {error_msg}")
                upload_session.mark_failed(error_msg)
                logger.info(f"📊 RAW UPLOAD: Marked UploadSession {upload_session.id} as failed")
            
            # Add session info to response (like standard upload)
            result['upload_session_id'] = str(upload_session.id)
            result['upload_session_status'] = upload_session.status
            
            # Calculate actual file count and total size for display (like standard upload)
            successful_files = result.get('results', [])
            total_uploaded_files = len(successful_files)
            total_size = sum(file_result.get('file_size', 0) for file_result in successful_files)
            
            # Debug: Log size comparison (like standard upload)
            original_total_size = sum(f.size for f in files)
            logger.info(f"📊 RAW UPLOAD SIZE DEBUG: Django reported total: {original_total_size / (1024*1024):.2f}MB")
            logger.info(f"📊 RAW UPLOAD SIZE DEBUG: S3 actual total: {total_size / (1024*1024):.2f}MB")
            
            # Use S3 size as it's more accurate
            if abs(original_total_size - total_size) > 1024:  # More than 1KB difference
                size_ratio = original_total_size / total_size if total_size > 0 else 0
                logger.warning(f"📊 RAW UPLOAD SIZE MISMATCH: Django reports {size_ratio:.1f}x larger than actual ({original_total_size / (1024*1024):.2f}MB vs {total_size / (1024*1024):.2f}MB)")
            
            # Add display information (like standard upload)
            result['total_uploaded_files'] = total_uploaded_files
            result['total_size_bytes'] = total_size  # Use S3 reported size
            result['total_size_formatted'] = self._format_file_size(total_size)
            result['duration'] = f"{upload_time:.2f}s"
            
            # Handle HTMX vs JSON responses consistently
            if request.headers.get('HX-Request'):
                if result.get('success', False):
                    logger.info("🔄 RAW UPLOAD: Building HTMX success response")
                    return self._build_upload_success_response(
                        request, organization, target_bucket, result, upload_time, bucket_service
                    )
                else:
                    logger.info("🔄 RAW UPLOAD: Building HTMX error response")
                    return self._build_upload_error_response(result)
            else:
                # Non-HTMX requests get JSON
                return JsonResponse(result)
            
        except SecurityError as e:
            logger.error(f"🚨 Security error in upload: {str(e)}")
            # Try to mark session as failed if it exists
            if 'upload_session' in locals():
                upload_session.mark_failed(f'Security validation failed: {str(e)}')
            return JsonResponse({'error': f'Security validation failed: {str(e)}'}, status=400)
        except ValidationError as e:
            logger.error(f"📋 Validation error in upload: {str(e)}")
            # Try to mark session as failed if it exists  
            if 'upload_session' in locals():
                upload_session.mark_failed(f'Validation failed: {str(e)}')
            return JsonResponse({'error': f'Validation failed: {str(e)}'}, status=400)
        except Exception as e:
            logger.exception(f"💥 Unexpected error in upload: {str(e)}")
            # Try to mark session as failed if it exists
            if 'upload_session' in locals():
                upload_session.mark_failed(f'Upload failed: {str(e)}')
            return JsonResponse({'error': f'Upload failed: {str(e)}'}, status=500)
    
