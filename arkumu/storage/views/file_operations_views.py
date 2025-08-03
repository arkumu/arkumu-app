import logging
import os
import mimetypes
import tempfile
import csv
import io
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, HttpResponse
from django.urls import reverse

from arkumu.storage.services.bucket_service import BucketService

# Import UploadSession model and get_user_model
from arkumu.storage.models import UploadSession
from django.contrib.auth import get_user_model

# Django cache
from django.core.cache import cache
from arkumu.users.mixins import general_login_required

logger = logging.getLogger(__name__)



@general_login_required
def organization_dashboard(request):
    """
    Display a dashboard of all organizations and their buckets.
    """
    try:
        # Single bucket service instance - this is now optimized with singleton pattern
        bucket_service = BucketService()
        
        # Get available organizations (includes both existing and predefined)
        available_organizations = bucket_service.get_available_organizations()
        
        # Check if user wants detailed file counts (optional for performance)
        include_counts = request.GET.get('include_counts', 'false').lower() == 'true'
        
        # Prepare data for the template
        org_data = []
        for org_info in available_organizations:
            org_name = org_info.get('slug')
            org_display_name = org_info.get('name', org_name)
            org_description = org_info.get('description', '')
            exists = org_info.get('exists', False)
            
            org_entry = {
                "slug": org_name,
                "name": org_display_name,
                "description": org_description,
                "exists": exists,
                "bucket": bucket_service.get_organization_bucket(org_name) if exists else None,
                "file_count": 0,
                "folder_count": 0,
                "status": "active" if exists else "available"
            }
            
            # Only get file counts if requested and bucket exists (for performance)
            if include_counts and exists:
                try:
                    bucket_name = bucket_service.get_organization_bucket(org_name)
                    root_items = bucket_service.get_root_level_items(bucket_name)
                    org_entry["file_count"] = sum(1 for item in root_items.get('children', []) 
                                                  if item.get('type') == 'file')
                    org_entry["folder_count"] = sum(1 for item in root_items.get('children', []) 
                                                    if item.get('type') == 'folder')
                except Exception as e:
                    logger.warning(f"Error getting counts for org {org_name}: {str(e)}")
                    # Continue without counts instead of failing
                    org_entry["file_count"] = 0
                    org_entry["folder_count"] = 0
            
            org_data.append(org_entry)
        
        # Sort organizations: existing ones first, then by name
        org_data.sort(key=lambda x: (not x["exists"], x["name"]))
        
        return render(request, "dashboard/organization_dashboard.html", {
            "organizations": org_data,
            "total_orgs": len(org_data),
            "include_counts": include_counts,
            "existing_orgs": len([org for org in org_data if org["exists"]]),
            "available_orgs": len([org for org in org_data if not org["exists"]])
        })
        
    except Exception as e:
        error_message = f"Error loading organization dashboard: {str(e)}"
        logger.exception(error_message)
        messages.error(request, error_message)
        return redirect("home")



@general_login_required
def organization_contents(request, organization=None):
    """
    Display the contents of an organization's bucket.
    Returns partial template for HTMX requests.
    """
    try:
        # Check if this is the browse URL (always get from query parameter)
        is_browse_url = request.resolver_match.url_name == 'organization_contents_browse'
        
        if is_browse_url:
            # For browse URL, always get organization from query parameter
            organization = request.GET.get('organization') or request.POST.get('organization')
        elif not organization:
            # For regular URL, get from URL parameter or form parameter
            organization = request.GET.get('organization') or request.POST.get('organization')
        
        if not organization:
            if request.headers.get('HX-Request') == 'true':
                return render(request, "dashboard/organization_files_empty.html")
            return redirect("storage:organization_dashboard")
        
        bucket_service = BucketService()
        
        # Ensure the organization bucket exists first
        bucket_result = bucket_service.ensure_organization_bucket_exists(organization)
        if not bucket_result.get('success', False):
            error_message = f"Failed to create/access bucket for {organization}: {bucket_result.get('error', 'Unknown error')}"
            if request.headers.get('HX-Request') == 'true':
                return render(request, "dashboard/organization_files_error.html", {
                    "error": error_message,
                    "organization": organization
                })
            messages.error(request, error_message)
            return redirect("storage:organization_dashboard")
        
        # Get the bucket for this organization
        bucket_name = bucket_service.get_organization_bucket(organization)
        
        # Get optional prefix from query params
        prefix = request.GET.get('prefix', '')
        
        # Get contents of the bucket with the given prefix
        contents = bucket_service.list_bucket_contents(bucket_name, prefix)
        
        # Check if HTMX request for partial content
        is_htmx_request = request.headers.get('HX-Request') == 'true'
        
        # Debug logging
        logger.info(f"Organization: {organization}")
        logger.info(f"Is browse URL: {is_browse_url}")
        
        if is_htmx_request or is_browse_url:
            # Return partial template for HTMX
            logger.info("Returning partial template for HTMX or browse URL")
            
            # If we have a prefix (navigating into subfolders), use the organization folder contents template
            # to avoid duplicating the header. Otherwise, use the full organization files template.
            if prefix:
                # Transform contents to match the organization_folder_contents_partial.html expected format
                structure = {
                    "children": contents
                }
                return render(request, "dashboard/organization_folder_contents_partial.html", {
                    "structure": structure,
                    "organization": organization,
                    "bucket_type": f"org-{organization}"
                })
            else:
                # Initial load - show full template with header
                return render(request, "dashboard/organization_files_partial.html", {
                    "organization": organization,
                    "bucket_name": bucket_name,
                    "contents": contents,
                    "prefix": prefix
                })
        
        # Prepare breadcrumbs for navigation
        breadcrumbs = []
        if prefix:
            parts = prefix.strip('/').split('/')
            current_path = ''
            for i, part in enumerate(parts):
                current_path += part + '/'
                breadcrumbs.append({
                    'name': part,
                    'path': current_path,
                    'is_last': i == len(parts) - 1
                })
        
        return render(request, "dashboard/organization_contents.html", {
            "organization": organization,
            "bucket_name": bucket_name,
            "contents": contents,
            "prefix": prefix,
            "breadcrumbs": breadcrumbs
        })
        
    except Exception as e:
        error_message = f"Error loading organization contents: {str(e)}"
        logger.exception(error_message)
        
        # Check if HTMX request
        is_htmx_request = request.headers.get('HX-Request') == 'true'
        
        if is_htmx_request:
            return render(request, "dashboard/organization_files_error.html", {
                "error": error_message,
                "organization": organization
            })
        
        messages.error(request, error_message)
        return redirect("storage:organization_dashboard")




@general_login_required
def file_content(request, bucket_type, file_path):
    """
    Retrieve and display the content of a file from a bucket.
    
    This view serves the content of a file directly to the browser.
    For binary files (images, etc.), it streams the content with the
    appropriate content type. For text files, it renders the content
    in a readable format.
    """
    try:
        bucket_service = BucketService()
        
        # Determine which bucket to use
        bucket_name = bucket_service.base_s3_service.ingest_bucket
        if bucket_type == "production":
            bucket_name = bucket_service.base_s3_service.production_bucket
        elif bucket_type.startswith("org-"):
            # Handle organization-specific buckets
            org_name = bucket_type[4:]  # Remove 'org-' prefix
            bucket_name = bucket_service.get_organization_bucket(org_name)
        
        # Get file content and metadata
        result = bucket_service.get_file_content(bucket_name, file_path)
        
        if result.get("success", False):
            content_type = result.get("content_type", "application/octet-stream")
            content = result.get("content")
            
            # Return the file content with the appropriate content type
            response = HttpResponse(content, content_type=content_type)
            
            # Add content disposition header for download if requested
            if request.GET.get("download") == "true":
                filename = file_path.split("/")[-1]
                response["Content-Disposition"] = f'attachment; filename="{filename}"'
                
            return response
        else:
            error_message = f"Failed to retrieve file: {result.get('error', 'Unknown error')}"
            logger.error(error_message)
            return HttpResponse(error_message, status=404)
            
    except Exception as e:
        error_message = f"Error retrieving file content: {str(e)}"
        logger.exception(error_message)
        return HttpResponse(error_message, status=500)



@general_login_required
def delete_object(request, bucket_type, object_type, object_path):
    """
    Delete a file or folder from a bucket.
    
    This operation permanently deletes the specified object from the bucket.
    If the object is a folder, all contents will also be deleted.
    
    Args:
        bucket_type: "ingest", "production", or "org-{organization_name}"
        object_type: "file" or "folder"
        object_path: The path to the object within the bucket
    """
    if request.method not in ["POST", "DELETE"]:
        return JsonResponse({"success": False, "error": "Method not allowed"})
    
    try:
        bucket_service = BucketService()
        
        # Determine which bucket to use
        bucket_name = bucket_service.base_s3_service.ingest_bucket
        if bucket_type == "production":
            bucket_name = bucket_service.base_s3_service.production_bucket
        elif bucket_type.startswith("org-"):
            # Handle organization-specific buckets
            org_name = bucket_type[4:]  # Remove 'org-' prefix
            bucket_name = bucket_service.get_organization_bucket(org_name)
        
        # Delete the object based on its type
        if object_type == "folder":
            result = bucket_service.delete_folder(bucket_name, object_path)
        else:  # file
            result = bucket_service.delete_file(bucket_name, object_path)
        
        if result.get("success", False):
            success_message = f"Successfully deleted {object_type} '{object_path}'"
            logger.info(success_message)
            logger.info(f"🔥 DELETE_DEBUG: Processing successful deletion, HTMX={request.headers.get('HX-Request')}, bucket_type={bucket_type}")
            
            # Clean up database records for deleted files
            from arkumu.storage.models import S3FileObject
            deleted_count = 0
            
            if bucket_type.startswith('org-'):
                organization = bucket_type.replace('org-', '')
                
                if object_type == "folder":
                    # Delete all S3FileObject records with s3_key starting with the folder path
                    folder_prefix = object_path if object_path.endswith('/') else object_path + '/'
                    deleted_objects = S3FileObject.objects.filter(
                        session__s3_bucket=organization,
                        s3_key__startswith=folder_prefix
                    )
                    deleted_count = deleted_objects.count()
                    deleted_objects.delete()
                    logger.info(f"🗑️ Deleted {deleted_count} S3FileObject records for folder {folder_prefix}")
                else:
                    # Delete specific S3FileObject record for the file
                    deleted_objects = S3FileObject.objects.filter(
                        session__s3_bucket=organization,
                        s3_key=object_path
                    )
                    deleted_count = deleted_objects.count()
                    deleted_objects.delete()
                    logger.info(f"🗑️ Deleted {deleted_count} S3FileObject record for file {object_path}")
            
            if deleted_count > 0:
                success_message += f" (cleaned up {deleted_count} database records)"
            
            # Invalidate directory listing cache after deletion
            from django.core.cache import cache
            if bucket_type.startswith('org-'):
                organization = bucket_type.replace('org-', '')
                # Clear cache for parent directories
                cache_keys_to_delete = [
                    f"bucket_contents_{organization}_",  # Root directory
                ]
                
                # Clear parent directories of deleted item
                if '/' in object_path:
                    parent_path = '/'.join(object_path.split('/')[:-1])
                    cache_keys_to_delete.append(f"bucket_contents_{organization}_{parent_path.replace('/', '_')}_")
                
                # Delete the cache entries
                for cache_key in cache_keys_to_delete:
                    cache.delete(cache_key)
                    logger.info(f"🗑️ Deleted cache key after deletion: {cache_key}")
                
                logger.info(f"🗑️ Cache invalidation completed for deletion of {object_path} (org: {organization})")
            
            if request.headers.get('HX-Request') == 'true':
                # For HTMX DELETE requests, return empty response so HTMX removes the element
                if request.method == "DELETE":
                    logger.info(f"🔥 DELETE_DEBUG: Returning empty response for DELETE request")
                    return HttpResponse("")
                
                # For HTMX POST requests, return a toast notification AND refresh file browser
                from django.template.loader import render_to_string
                from arkumu.metadata.views.csv_mapping.mixins.template_helpers import CSVMappingTemplateHelperMixin
                
                # Get organization from bucket_type for file browser refresh
                if bucket_type.startswith("org-"):
                    logger.info(f"🔥 DELETE_DEBUG: Organization bucket deletion path")
                    org_name = bucket_type[4:]  # Remove 'org-' prefix
                    
                    # Refresh file browser content after deletion - force fresh
                    contents = bucket_service.list_bucket_contents(bucket_name, '', force_fresh=True)
                    
                    # Add file counts for data and metadata folders - force fresh after operation
                    for item in contents:
                        if item['type'] == 'folder' and item['name'] in ['data', 'metadata']:
                            item['file_count'] = bucket_service.count_files_in_folder(bucket_name, item['path'], force_fresh=True)
                    
                    file_browser_html = render_to_string(
                        'dashboard/organization_files_partial.html',
                        {
                            'organization': org_name,
                            'bucket_name': bucket_name,
                            'contents': contents,
                            'selected_org_slug': org_name,
                            'prefix': ''
                        },
                        request=request
                    )
                    
                    # Main toast notification
                    toast_html = render_to_string(
                        "partials/toast_notification.html",
                        {
                            "message": success_message,
                            "type": "success"
                        },
                        request=request
                    )
                    
                    # Use template helper mixin for clean OOB response
                    helper = CSVMappingTemplateHelperMixin()
                    oob_updates = {
                        'toast-container': toast_html,  # Add toast to container via OOB
                        'file-browser-content': file_browser_html
                    }
                    
                    # Return empty main content with OOB updates
                    response_html = helper.build_oob_response("", oob_updates)
                    logger.info(f"🔥 DELETE_DEBUG: Returning OOB response with toast and file browser update")
                    return HttpResponse(response_html)
                else:
                    # For non-organization buckets, return toast via OOB to container
                    toast_html = render_to_string(
                        "partials/toast_notification.html",
                        {
                            "message": success_message,
                            "type": "success"
                        },
                        request=request
                    )
                    
                    helper = CSVMappingTemplateHelperMixin()
                    oob_updates = {
                        'toast-container': toast_html
                    }
                    
                    response_html = helper.build_oob_response("", oob_updates)
                    return HttpResponse(response_html)
            
            # Only add Django messages for non-HTMX requests
            messages.success(request, success_message)
            return JsonResponse({"success": True, "message": success_message})
        else:
            error_message = f"Failed to delete {object_type}: {result.get('error', 'Unknown error')}"
            logger.error(error_message)
            
            if request.headers.get('HX-Request') == 'true':
                return render(request, "partials/toast_notification.html", {
                    "message": error_message,
                    "type": "error"
                })
                
            # Only add Django messages for non-HTMX requests
            messages.error(request, error_message)
            return JsonResponse({"success": False, "error": error_message})
            
    except Exception as e:
        error_message = f"Error deleting {object_type}: {str(e)}"
        logger.exception(error_message)
        
        if request.headers.get('HX-Request') == 'true':
            return HttpResponse(error_message, status=500)
            
        # Only add Django messages for non-HTMX requests
        messages.error(request, error_message)
        return JsonResponse({"success": False, "error": error_message})



@general_login_required
def csv_preview(request, bucket_type, file_path):
    """
    Preview CSV file content from S3 bucket.
    
    Fetches the CSV file from S3, parses it, and returns an HTML table
    showing the first 100 rows for preview purposes.
    """
    try:
        bucket_service = BucketService()
        
        # Determine which bucket to use (same logic as file_content)
        bucket_name = bucket_service.base_s3_service.ingest_bucket
        if bucket_type == "production":
            bucket_name = bucket_service.base_s3_service.production_bucket
        elif bucket_type.startswith("org-"):
            # Handle organization-specific buckets
            org_name = bucket_type[4:]  # Remove 'org-' prefix
            bucket_name = bucket_service.get_organization_bucket(org_name)
        
        # Get file content
        result = bucket_service.get_file_content(bucket_name, file_path)
        
        if not result.get("success", False):
            error_message = f"Failed to retrieve CSV file: {result.get('error', 'Unknown error')}"
            logger.error(error_message)
            return render(request, "dashboard/csv_preview_error.html", {
                "error": error_message,
                "file_path": file_path
            })
        
        content = result.get("content")
        if not content:
            return render(request, "dashboard/csv_preview_error.html", {
                "error": "File is empty",
                "file_path": file_path
            })
        
        # Decode content if it's bytes
        if isinstance(content, bytes):
            try:
                content = content.decode('utf-8')
            except UnicodeDecodeError:
                try:
                    content = content.decode('latin-1')
                except UnicodeDecodeError:
                    return render(request, "dashboard/csv_preview_error.html", {
                        "error": "Unable to decode file content. File may not be a valid text file.",
                        "file_path": file_path
                    })
        
        # Parse CSV content
        try:
            # Auto-detect delimiter using csv.Sniffer
            sample = content[:1024]  # Use first 1KB for delimiter detection
            sniffer = csv.Sniffer()
            delimiter = ','  # Default delimiter
            
            try:
                dialect = sniffer.sniff(sample, delimiters=',;\t|')
                delimiter = dialect.delimiter
                logger.info(f"Auto-detected CSV delimiter: '{delimiter}'")
            except csv.Error:
                # If auto-detection fails, try common delimiters manually
                common_delimiters = [',', ';', '\t', '|']
                max_columns = 0
                best_delimiter = ','
                
                for test_delimiter in common_delimiters:
                    try:
                        test_reader = csv.reader(io.StringIO(sample), delimiter=test_delimiter)
                        first_row = next(test_reader)
                        if len(first_row) > max_columns:
                            max_columns = len(first_row)
                            best_delimiter = test_delimiter
                    except:
                        continue
                
                delimiter = best_delimiter
                logger.info(f"Fallback delimiter detection: '{delimiter}' (produces {max_columns} columns)")
            
            # Parse CSV with detected delimiter
            csv_reader = csv.reader(io.StringIO(content), delimiter=delimiter)
            rows = []
            headers = None
            row_count = 0
            max_preview_rows = 100  # Limit preview to first 100 rows
            
            for i, row in enumerate(csv_reader):
                if i == 0:
                    # First row - treat as headers if it looks like headers
                    headers = row
                    # Add first row to rows for display (template will handle skipping)
                    rows.append(row)
                    logger.info(f"CSV headers detected: {headers[:5]}...")  # Log first 5 headers
                elif i < max_preview_rows:
                    rows.append(row)
                
                row_count = i + 1
                
                # Stop reading after max_preview_rows for performance
                if i >= max_preview_rows:
                    break
            
            # Ensure we have headers
            if not headers and rows:
                # If no headers were set but we have rows, use the first row as headers
                headers = rows[0] if rows else []
                logger.info(f"Using first row as headers: {headers[:5]}...")
            
            logger.info(f"Final headers count: {len(headers) if headers else 0}")
            logger.info(f"Total rows: {len(rows)}, Column count: {len(headers) if headers else 0}")
            
            # Get total row count (approximate if we stopped at max_preview_rows)
            total_rows = row_count
            if row_count >= max_preview_rows:
                # Try to count total rows more efficiently
                try:
                    total_rows = content.count('\n')
                    if not content.endswith('\n'):
                        total_rows += 1
                except:
                    total_rows = f"{max_preview_rows}+"
            
            # Calculate file stats
            file_size_bytes = len(content.encode('utf-8'))
            file_size_mb = file_size_bytes / (1024 * 1024)
            
            filename = file_path.split('/')[-1]
            
            # Determine delimiter name for display
            delimiter_names = {
                ',': 'Comma',
                ';': 'Semicolon', 
                '\t': 'Tab',
                '|': 'Pipe'
            }
            delimiter_display = delimiter_names.get(delimiter, f"'{delimiter}'")
            
            return render(request, "dashboard/csv_preview_modal.html", {
                "filename": filename,
                "file_path": file_path,
                "headers": headers,
                "rows": rows,
                "total_rows": total_rows,
                "displayed_rows": len(rows),
                "max_preview_rows": max_preview_rows,
                "file_size_bytes": file_size_bytes,
                "file_size_mb": round(file_size_mb, 2),
                "column_count": len(headers) if headers else 0,
                "truncated": row_count >= max_preview_rows,
                "delimiter": delimiter,
                "delimiter_display": delimiter_display
            })
            
        except csv.Error as e:
            return render(request, "dashboard/csv_preview_error.html", {
                "error": f"CSV parsing error: {str(e)}",
                "file_path": file_path
            })
        except Exception as e:
            logger.exception(f"Error parsing CSV file {file_path}")
            return render(request, "dashboard/csv_preview_error.html", {
                "error": f"Unexpected error while parsing CSV: {str(e)}",
                "file_path": file_path
            })
            
    except Exception as e:
        error_message = f"Error loading CSV preview: {str(e)}"
        logger.exception(error_message)
        return render(request, "dashboard/csv_preview_error.html", {
            "error": error_message,
            "file_path": file_path
        }) 


def file_viewer(request, bucket_type, file_path):
    """
    Generic file viewer that can handle multiple file types.
    Routes to appropriate viewer based on file extension.
    """
    import os
    import mimetypes
    from django.http import HttpResponse
    
    try:
        bucket_service = BucketService()
        
        # Determine which bucket to use (same logic as csv_preview)
        bucket_name = bucket_service.base_s3_service.ingest_bucket
        if bucket_type == "production":
            bucket_name = bucket_service.base_s3_service.production_bucket
        elif bucket_type.startswith("org-"):
            # Handle organization-specific buckets
            org_name = bucket_type[4:]  # Remove 'org-' prefix
            bucket_name = bucket_service.get_organization_bucket(org_name)
        
        # Get file info from S3 metadata and key
        filename = file_path.split('/')[-1]  # Get filename from path
        file_ext = '.' + file_path.split('.')[-1].lower() if '.' in file_path else ''
        
        # Get actual content type from S3 metadata
        try:
            head_response = bucket_service.base_s3_service.s3_client.head_object(
                Bucket=bucket_name,
                Key=file_path
            )
            mime_type = head_response.get('ContentType', 'application/octet-stream')
        except Exception as e:
            logger.warning(f"Could not get S3 metadata for {file_path}: {e}")
            # Fallback to guessing from filename
            mime_type, _ = mimetypes.guess_type(filename)
        
        # Handle CSV files using existing CSV viewer
        if file_ext in ['.csv'] or mime_type in ['text/csv']:
            return csv_preview(request, bucket_type, file_path)
        
        # Handle images (check both extension and MIME type)
        elif (file_ext in ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.svg'] or 
              mime_type.startswith('image/')):
            return _handle_image_file(request, bucket_service, bucket_name, file_path, filename, mime_type)
        
        # Handle PDFs (check both extension and MIME type) - DISABLED
        # elif file_ext in ['.pdf'] or mime_type == 'application/pdf':
        #     return _handle_pdf_file(request, bucket_service, bucket_name, file_path, filename, bucket_type)
        
        # Handle videos (check both extension and MIME type)
        elif (file_ext in ['.mp4', '.webm', '.ogg', '.avi', '.mov'] or 
              mime_type.startswith('video/')):
            return _handle_video_file(request, bucket_service, bucket_name, file_path, filename, mime_type, bucket_type)
        
        # Handle audio files (check both extension and MIME type)
        elif (file_ext in ['.mp3', '.wav', '.ogg', '.flac', '.m4a'] or 
              mime_type.startswith('audio/')):
            return _handle_audio_file(request, bucket_service, bucket_name, file_path, filename, mime_type, bucket_type)
        
        # Handle text files (check both extension and MIME type)
        elif (file_ext in ['.txt', '.json', '.xml', '.html', '.css', '.js', '.py', '.java', '.c', '.cpp', '.md'] or 
              mime_type.startswith('text/')):
            return _handle_text_file(request, bucket_service, bucket_name, file_path, filename, file_ext)
        
        # Unsupported file type
        else:
            return render(request, "dashboard/file_viewer_error.html", {
                "error": f"File type '{file_ext}' is not supported for preview",
                "file_path": file_path,
                "filename": filename
            })
            
    except Exception as e:
        logger.exception(f"Error in file viewer for {file_path}")
        return render(request, "dashboard/file_viewer_error.html", {
            "error": f"Error loading file preview: {str(e)}",
            "file_path": file_path,
            "filename": os.path.basename(file_path)
        })


def _handle_image_file(request, bucket_service, bucket_name, file_path, filename, mime_type):
    """Handle image file viewing"""
    try:
        # Get file content as binary
        result = bucket_service.get_file_content(bucket_name, file_path)
        
        if not result.get("success", False):
            raise Exception(result.get('error', 'Unknown error'))
        
        content = result.get("content")
        if not content:
            raise Exception("File is empty")
        
        # Convert to base64 for display
        import base64
        if isinstance(content, str):
            content = content.encode('utf-8')
        
        base64_content = base64.b64encode(content).decode('utf-8')
        
        return render(request, "dashboard/file_viewer_modal.html", {
            "viewer_type": "image",
            "filename": filename,
            "file_path": file_path,
            "mime_type": mime_type or "image/jpeg",
            "content": base64_content,
            "file_size": len(content)
        })
        
    except Exception as e:
        return render(request, "dashboard/file_viewer_error.html", {
            "error": f"Error loading image: {str(e)}",
            "file_path": file_path,
            "filename": filename
        })


def _handle_pdf_file(request, bucket_service, bucket_name, file_path, filename, bucket_type):
    """Handle PDF file viewing"""
    try:
        # Use the bucket_type passed from the caller
        stream_url = f"/storage/stream/{bucket_type}/{file_path}"
        
        return render(request, "dashboard/file_viewer_modal.html", {
            "viewer_type": "pdf",
            "filename": filename,
            "file_path": file_path,
            "stream_url": stream_url
        })
        
    except Exception as e:
        return render(request, "dashboard/file_viewer_error.html", {
            "error": f"Error loading PDF: {str(e)}",
            "file_path": file_path,
            "filename": filename
        })


def _handle_video_file(request, bucket_service, bucket_name, file_path, filename, mime_type, bucket_type):
    """Handle video file viewing"""
    try:
        # Use the bucket_type passed from the caller
        stream_url = f"/storage/stream/{bucket_type}/{file_path}"
        
        return render(request, "dashboard/file_viewer_modal.html", {
            "viewer_type": "video",
            "filename": filename,
            "file_path": file_path,
            "mime_type": mime_type or "video/mp4",
            "stream_url": stream_url
        })
        
    except Exception as e:
        return render(request, "dashboard/file_viewer_error.html", {
            "error": f"Error loading video: {str(e)}",
            "file_path": file_path,
            "filename": filename
        })


def _handle_audio_file(request, bucket_service, bucket_name, file_path, filename, mime_type, bucket_type):
    """Handle audio file viewing"""
    try:
        # Use the bucket_type passed from the caller
        stream_url = f"/storage/stream/{bucket_type}/{file_path}"
        
        return render(request, "dashboard/file_viewer_modal.html", {
            "viewer_type": "audio",
            "filename": filename,
            "file_path": file_path,
            "mime_type": mime_type or "audio/mpeg",
            "stream_url": stream_url
        })
        
    except Exception as e:
        return render(request, "dashboard/file_viewer_error.html", {
            "error": f"Error loading audio: {str(e)}",
            "file_path": file_path,
            "filename": filename
        })


def _handle_text_file(request, bucket_service, bucket_name, file_path, filename, file_ext):
    """Handle text file viewing"""
    try:
        result = bucket_service.get_file_content(bucket_name, file_path)
        
        if not result.get("success", False):
            raise Exception(result.get('error', 'Unknown error'))
        
        content = result.get("content")
        if not content:
            raise Exception("File is empty")
        
        # Decode content if it's bytes
        if isinstance(content, bytes):
            try:
                content = content.decode('utf-8')
            except UnicodeDecodeError:
                try:
                    content = content.decode('latin-1')
                except UnicodeDecodeError:
                    raise Exception("Unable to decode file content")
        
        # Limit content for preview (first 10KB)
        max_chars = 10000
        truncated = len(content) > max_chars
        if truncated:
            content = content[:max_chars]
        
        return render(request, "dashboard/file_viewer_modal.html", {
            "viewer_type": "text",
            "filename": filename,
            "file_path": file_path,
            "content": content,
            "file_extension": file_ext,
            "truncated": truncated,
            "total_chars": len(content)
        })
        
    except Exception as e:
        return render(request, "dashboard/file_viewer_error.html", {
            "error": f"Error loading text file: {str(e)}",
            "file_path": file_path,
            "filename": filename
        })


@general_login_required
def stream_file(request, bucket_type, file_path):
    """
    Stream file content with HTTP range request support.
    Essential for video streaming - enables seeking, progressive download, and efficient bandwidth usage.
    """
    try:
        bucket_service = BucketService()
        
        # Determine which bucket to use (same logic as other views)
        bucket_name = bucket_service.base_s3_service.ingest_bucket
        if bucket_type == "production":
            bucket_name = bucket_service.base_s3_service.production_bucket
        elif bucket_type.startswith("org-"):
            # Handle organization-specific buckets
            org_name = bucket_type[4:]  # Remove 'org-' prefix
            bucket_name = bucket_service.get_organization_bucket(org_name)
        
        # Get range header from request
        range_header = request.META.get('HTTP_RANGE')
        
        # Use the new streaming service with range support
        result = bucket_service.stream_file_with_range(bucket_name, file_path, range_header)
        
        if not result.get("success", False):
            error_message = result.get('error', 'Unknown error')
            logger.error(f"Streaming failed for {file_path}: {error_message}")
            return HttpResponse(error_message, status=404)
        
        # Create streaming response with appropriate headers
        content = result.get("content")
        content_type = result.get("content_type", "application/octet-stream")
        status_code = result.get("status_code", 200)
        
        response = HttpResponse(content, content_type=content_type, status=status_code)
        
        # Set essential headers for streaming and caching
        response["Accept-Ranges"] = result.get("accept_ranges", "bytes")
        response["Content-Length"] = str(len(content))
        
        # Add ETag and Last-Modified for caching
        if result.get("etag"):
            response["ETag"] = f'"{result["etag"]}"'
        if result.get("last_modified"):
            # Format as HTTP date
            from django.utils.http import http_date
            import calendar
            timestamp = calendar.timegm(result["last_modified"].timetuple())
            response["Last-Modified"] = http_date(timestamp)
        
        # Add cache headers for media files
        filename = os.path.basename(file_path)
        file_ext = os.path.splitext(filename)[1].lower()
        if file_ext in ['.mp4', '.webm', '.ogg', '.avi', '.mov', '.mp3', '.wav', '.flac', '.jpg', '.jpeg', '.png', '.gif']:
            # Cache media files for 1 hour
            response["Cache-Control"] = "public, max-age=3600"
        
        # Add range-specific headers for partial content
        if status_code == 206:
            response["Content-Range"] = result.get("content_range")
            response["Content-Length"] = str(result.get("partial_content_length", len(content)))
            logger.info(f"📹 Streaming partial content for {file_path}: {result.get('content_range')}")
        else:
            response["Content-Length"] = str(result.get("content_length", len(content)))
            logger.info(f"📹 Streaming full content for {file_path}: {len(content)} bytes")
        
        return response
        
    except Exception as e:
        error_message = f"Error streaming file: {str(e)}"
        logger.exception(error_message)
        return HttpResponse(error_message, status=500)