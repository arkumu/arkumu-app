import logging
import json
import tempfile
import os
from typing import Dict, Any, List
from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.contrib.auth.decorators import login_required
from django.utils.decorators import method_decorator
from django.views import View
from arkumu.users.mixins import GeneralLoginRequiredMixin, general_login_required

from arkumu.storage.services.upload_service import UploadService
from arkumu.storage.services.bucket_service import BucketService

logger = logging.getLogger(__name__)

class RawStreamUploadView(GeneralLoginRequiredMixin, View):
    """
    Handle raw multipart stream upload without Django's file parsing.
    This bypasses the DATA_UPLOAD_MAX_NUMBER_FILES limit by streaming directly.
    """
    
    @method_decorator(csrf_exempt)  # We'll handle CSRF manually if needed
    def dispatch(self, request, *args, **kwargs):
        return super().dispatch(request, *args, **kwargs)
    
    def post(self, request):
        """
        Process raw multipart stream upload.
        """
        try:
            logger.info(f"📊 UPLOAD TYPE: Raw stream upload endpoint (bypasses Django limits)")
            logger.info(f"Processing raw stream upload for user: {request.user.username}")
            
            # Check authentication
            if not request.user.is_authenticated:
                return JsonResponse({'error': 'Authentication required'}, status=401)
            
            # Get content type and boundary
            content_type = request.META.get('CONTENT_TYPE', '')
            if not content_type.startswith('multipart/form-data'):
                return JsonResponse({'error': 'Multipart form data required'}, status=400)
            
            # Extract boundary
            boundary = None
            for part in content_type.split(';'):
                if part.strip().startswith('boundary='):
                    boundary = part.split('=', 1)[1].strip()
                    break
            
            if not boundary:
                return JsonResponse({'error': 'No boundary found in content type'}, status=400)
            
            # Process the raw stream
            result = self._process_raw_stream(request, boundary)
            return JsonResponse(result)
            
        except Exception as e:
            logger.exception(f"Error in raw stream upload: {str(e)}")
            return JsonResponse({'error': str(e)}, status=500)
    
    def _process_raw_stream(self, request, boundary: str) -> Dict[str, Any]:
        """
        Process the raw multipart stream and extract files.
        """
        boundary_bytes = boundary.encode('utf-8')
        boundary_pattern = b'--' + boundary_bytes
        end_boundary_pattern = b'--' + boundary_bytes + b'--'
        
        # Configuration from request headers or defaults
        folder_name = None
        organization = None
        files_processed = []
        
        # Read the stream in chunks
        buffer = b''
        current_part = None
        current_file = None
        files_count = 0
        
        try:
            upload_service = UploadService()
            bucket_service = BucketService()
            
            # Read stream in chunks
            for chunk in request:
                buffer += chunk
                
                # Process complete parts
                while boundary_pattern in buffer:
                    # Find boundary
                    boundary_pos = buffer.find(boundary_pattern)
                    
                    if current_part is not None:
                        # We have data for the current part
                        part_data = buffer[:boundary_pos]
                        
                        if current_part['type'] == 'field':
                            # Handle form field
                            field_value = part_data.decode('utf-8').strip()
                            if current_part['name'] == 'folder_name':
                                folder_name = field_value
                            elif current_part['name'] == 'organization':
                                organization = field_value
                        
                        elif current_part['type'] == 'file':
                            # Handle file data
                            if current_file is not None:
                                # Write file data and upload
                                current_file['temp_file'].write(part_data)
                                current_file['temp_file'].close()
                                
                                # Upload to S3
                                file_result = self._upload_temp_file(
                                    current_file, 
                                    upload_service, 
                                    bucket_service,
                                    folder_name, 
                                    organization
                                )
                                files_processed.append(file_result)
                                files_count += 1
                                
                                # Clean up
                                try:
                                    os.unlink(current_file['temp_path'])
                                except:
                                    pass
                                
                                current_file = None
                    
                    # Move past the boundary
                    buffer = buffer[boundary_pos + len(boundary_pattern):]
                    
                    # Check for end boundary
                    if buffer.startswith(b'--'):
                        # End of stream
                        break
                    
                    # Parse next part headers
                    if b'\r\n\r\n' in buffer:
                        header_end = buffer.find(b'\r\n\r\n')
                        headers = buffer[:header_end].decode('utf-8')
                        buffer = buffer[header_end + 4:]
                        
                        current_part = self._parse_part_headers(headers)
                        
                        if current_part['type'] == 'file':
                            # Create temporary file
                            temp_file = tempfile.NamedTemporaryFile(delete=False)
                            current_file = {
                                'name': current_part['filename'],
                                'content_type': current_part.get('content_type', 'application/octet-stream'),
                                'temp_file': temp_file,
                                'temp_path': temp_file.name
                            }
                    else:
                        # Need more data for headers
                        break
            
            # Process any remaining data
            if current_file is not None and buffer:
                current_file['temp_file'].write(buffer)
                current_file['temp_file'].close()
                
                file_result = self._upload_temp_file(
                    current_file, 
                    upload_service, 
                    bucket_service,
                    folder_name, 
                    organization
                )
                files_processed.append(file_result)
                files_count += 1
                
                try:
                    os.unlink(current_file['temp_path'])
                except:
                    pass
            
            success_count = sum(1 for f in files_processed if f.get('success', False))
            error_count = files_count - success_count
            
            return {
                'success': error_count == 0,
                'total_files': files_count,
                'success_count': success_count,
                'error_count': error_count,
                'results': files_processed,
                'folder_name': folder_name,
                'organization': organization
            }
            
        except Exception as e:
            logger.exception(f"Error processing raw stream: {str(e)}")
            return {
                'success': False,
                'error': str(e),
                'files_processed': len(files_processed)
            }
    
    def _parse_part_headers(self, headers: str) -> Dict[str, Any]:
        """
        Parse multipart part headers.
        """
        lines = headers.split('\r\n')
        content_disposition = None
        content_type = 'application/octet-stream'
        
        for line in lines:
            if line.startswith('Content-Disposition:'):
                content_disposition = line
            elif line.startswith('Content-Type:'):
                content_type = line.split(':', 1)[1].strip()
        
        if not content_disposition:
            return {'type': 'unknown'}
        
        # Parse Content-Disposition
        parts = content_disposition.split(';')
        disposition_type = parts[0].split(':', 1)[1].strip()
        
        name = None
        filename = None
        
        for part in parts[1:]:
            part = part.strip()
            if part.startswith('name='):
                name = part.split('=', 1)[1].strip('"')
            elif part.startswith('filename='):
                filename = part.split('=', 1)[1].strip('"')
        
        if filename:
            return {
                'type': 'file',
                'name': name,
                'filename': filename,
                'content_type': content_type
            }
        else:
            return {
                'type': 'field',
                'name': name
            }
    
    def _upload_temp_file(self, file_info: Dict, upload_service: UploadService, 
                         bucket_service: BucketService, folder_name: str, 
                         organization: str) -> Dict[str, Any]:
        """
        Upload a temporary file to S3.
        """
        try:
            # Determine target bucket
            if organization:
                target_bucket = bucket_service.get_organization_bucket(organization)
            else:
                target_bucket = upload_service.base_s3_service.ingest_bucket
            
            # Upload using file path
            with open(file_info['temp_path'], 'rb') as f:
                result = upload_service.upload_file_stream(
                    file_obj=f,
                    file_name=file_info['name'],
                    content_type=file_info['content_type'],
                    path_prefix=folder_name
                )
            
            return result
            
        except Exception as e:
            logger.error(f"Error uploading temp file {file_info['name']}: {str(e)}")
            return {
                'success': False,
                'error': str(e),
                'file_name': file_info['name']
            }


# Function-based view wrapper for URL routing
@require_http_methods(["POST"])
@general_login_required
def raw_stream_upload(request):
    """
    Function-based wrapper for the raw stream upload view.
    """
    view = RawStreamUploadView()
    return view.post(request) 