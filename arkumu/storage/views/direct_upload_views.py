import logging
import json
import os
from django.shortcuts import render
from django.contrib import messages
from django.views.decorators.http import require_http_methods
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, HttpResponse
from django.urls import reverse
from arkumu.storage.services.upload_service import UploadService
from django.views.decorators.csrf import csrf_exempt
import requests
from arkumu.users.mixins import general_login_required

logger = logging.getLogger(__name__)



@general_login_required
def direct_upload(request):
    """Handle direct S3 uploads from the browser."""
    # If GET request, just show the form
    if request.method != 'POST':
        # Check if we have session data from process_upload
        folder_name = request.session.get('upload_folder_name')
        files_metadata_json = request.session.get('upload_files_metadata')
        
        logger.info(f"GET request to direct_upload view for user: {request.user.username}")
        
        if folder_name and files_metadata_json:
            try:
                # Parse the files metadata from session
                files_metadata = json.loads(files_metadata_json)
                logger.info(f"Found session data for folder: {folder_name} with {len(files_metadata)} files")
                
                # Generate presigned URLs
                upload_service = UploadService()
                logger.info(f"Upload service configuration: is_minio={upload_service.is_minio}, endpoint_url={upload_service.endpoint_url}")
                
                result = upload_service.generate_batch_presigned_posts(
                    files_metadata=files_metadata,
                    path_prefix=folder_name,
                    expiration=3600,
                    use_multipart=False  # Explicitly use single-part uploads
                )
                
                # Clear the session data to prevent reuse
                del request.session['upload_folder_name']
                del request.session['upload_files_metadata']
                
                if result["success"]:
                    logger.info(f"Successfully generated {len(result['presigned_posts'])} presigned URLs")
                    # Log the first URL for debugging
                    if result["presigned_posts"]:
                        first_url = result["presigned_posts"][0].get("presigned_post", {}).get("url", "")
                        logger.info(f"Sample presigned URL: {first_url}")
                    
                    # Log the fields for the first presigned post
                    first_fields = result["presigned_posts"][0].get("presigned_post", {}).get("fields", {})
                    logger.info(f"Sample presigned fields: {json.dumps(first_fields)}")
                    
                    # Transform the presigned_posts to a client-friendly format
                    client_friendly_posts = []
                    for post in result["presigned_posts"]:
                        # Check if this post has the required structure
                        if not post.get('presigned_post'):
                            logger.warning(f"Missing presigned_post in data for {post.get('file_name')}")
                            continue
                        
                        # Extract the presigned_post data and merge with the post properties
                        presigned_post = post['presigned_post']
                        client_post = {
                            'file_name': post.get('file_name', ''),
                            's3_key': post.get('s3_key', ''),
                            'file_type': post.get('file_type', ''),
                            'url': presigned_post.get('url', ''),
                            'fields': presigned_post.get('fields', {}),
                        }
                        client_friendly_posts.append(client_post)
                    
                    logger.info(f"Transformed {len(client_friendly_posts)} posts to client-friendly format")
                    if client_friendly_posts:
                        logger.debug(f"Sample transformed post: {json.dumps(client_friendly_posts[0])}")
                    
                    # Return the presigned URLs to the upload_stage.html template
                    return render(request, "upload/upload_stage.html", {
                        "presigned_posts": client_friendly_posts,
                        "presigned_posts_json": json.dumps(client_friendly_posts)
                    })
                else:
                    error_msg = result.get('error', 'Unknown error')
                    logger.error(f"Failed to generate presigned URLs: {error_msg}")
                    return render(request, "upload/upload_status.html", {
                        "success": False, 
                        "message": f"Failed to generate presigned URLs: {error_msg}"
                    })
            except Exception as e:
                logger.exception(f"Error processing session data: {str(e)}")
                return render(request, "upload/upload_status.html", {
                    "success": False, 
                    "message": f"Error: {str(e)}"
                })
        
        # No session data, show the form
        logger.info("No session data found, showing upload form")
        return render(request, "upload/upload_form.html")
    
    # Handle direct POST requests (not from process_upload)
    logger.info(f"POST request to direct_upload view for user: {request.user.username}")
    
    # Get form data
    folder_name = request.POST.get('folder_name')
    file_paths_json = request.POST.get('file_paths_json')
    file_names_json = request.POST.get('file_names_json')
    
    logger.info(f"Upload request for folder: {folder_name}")
    
    # Validate required fields
    if not folder_name or not file_paths_json:
        logger.warning("Missing folder name or file paths in POST request")
        return render(request, "upload/upload_status.html", {
            "success": False, "message": "Missing folder name or file paths"
        })
    
    try:
        # Parse file information
        file_paths = json.loads(file_paths_json)
        file_names = json.loads(file_names_json)
        
        logger.info(f"Processing {len(file_names)} files for upload")
        
        # Prepare file metadata for presigned URL generation
        files_metadata = []
        for i, file_name in enumerate(file_names):
            if i < len(file_paths):
                # Extract file extension for basic MIME type guess
                content_type = guess_content_type(file_name)
                
                # Create relative path from full path
                path = os.path.dirname(file_paths[i])
                # Remove the first folder (which is the root folder name) to avoid duplication
                path_parts = path.split('/')
                if len(path_parts) > 1:
                    path = '/'.join(path_parts[1:])
                
                files_metadata.append({
                    "file_name": file_name,
                    "file_type": content_type,
                    "file_path": file_paths[i],
                    "path": path
                })
                
                logger.debug(f"File {i+1}: {file_name}, type: {content_type}, path: {path}")
        
        # Generate presigned URLs
        upload_service = UploadService()
        logger.info(f"Upload service configuration: is_minio={upload_service.is_minio}, endpoint_url={upload_service.endpoint_url}")
        
        result = upload_service.generate_batch_presigned_posts(
            files_metadata=files_metadata,
            path_prefix=folder_name,
            expiration=3600,
            use_multipart=False  # Explicitly use single-part uploads
        )
        
        if result["success"]:
            logger.info(f"Successfully generated {len(result['presigned_posts'])} presigned URLs")
            # Log the first URL for debugging
            if result["presigned_posts"]:
                first_url = result["presigned_posts"][0].get("presigned_post", {}).get("url", "")
                logger.info(f"Sample presigned URL: {first_url}")
                
                # Log the fields for the first presigned post
                first_fields = result["presigned_posts"][0].get("presigned_post", {}).get("fields", {})
                logger.info(f"Sample presigned fields: {json.dumps(first_fields)}")
            
            # Transform the presigned_posts to a client-friendly format
            client_friendly_posts = []
            for post in result["presigned_posts"]:
                # Check if this post has the required structure
                if not post.get('presigned_post'):
                    logger.warning(f"Missing presigned_post in data for {post.get('file_name')}")
                    continue
                
                # Extract the presigned_post data and merge with the post properties
                presigned_post = post['presigned_post']
                client_post = {
                    'file_name': post.get('file_name', ''),
                    's3_key': post.get('s3_key', ''),
                    'file_type': post.get('file_type', ''),
                    'url': presigned_post.get('url', ''),
                    'fields': presigned_post.get('fields', {}),
                }
                client_friendly_posts.append(client_post)
            
            logger.info(f"Transformed {len(client_friendly_posts)} posts to client-friendly format")
            if client_friendly_posts:
                logger.debug(f"Sample transformed post: {json.dumps(client_friendly_posts[0])}")
            
            # Return the presigned URLs to the upload_stage.html template
            return render(request, "upload/upload_stage.html", {
                "presigned_posts": client_friendly_posts,
                "presigned_posts_json": json.dumps(client_friendly_posts)
            })
        else:
            error_msg = result.get('error', 'Unknown error')
            logger.error(f"Failed to generate presigned URLs: {error_msg}")
            return render(request, "upload/upload_status.html", {
                "success": False, 
                "message": f"Failed to generate presigned URLs: {error_msg}"
            })
            
    except json.JSONDecodeError:
        logger.exception("Invalid JSON format in file paths or names")
        return render(request, "upload/upload_status.html", {
            "success": False, 
            "message": "Invalid file paths format"
        })
    except Exception as e:
        logger.exception(f"Unexpected error in direct_upload: {str(e)}")
        return render(request, "upload/upload_status.html", {
            "success": False, 
            "message": f"Error: {str(e)}"
        })



@require_http_methods(["POST"])
@general_login_required
def process_upload(request):
    """Process folder uploads using presigned URLs."""
    try:
        # Get form data
        folder_name = request.POST.get('folder_name')
        file_paths_json = request.POST.get('file_paths_json')
        file_names_json = request.POST.get('file_names_json')
        
        # Log request details
        logger.info(f"Processing upload request for folder: {folder_name} by user: {request.user.username}")
        logger.info(f"Request contains {len(request.POST)} POST parameters")
        
        # Validate required fields
        if not folder_name:
            error_message = "Folder name is required"
            logger.warning(error_message)
            messages.error(request, error_message)
            return render(request, "upload/upload_status.html", {
                "success": False, "message": error_message
            })
        
        if not file_paths_json or not file_names_json:
            error_message = "No files metadata provided"
            logger.warning(error_message)
            messages.error(request, error_message)
            return render(request, "upload/upload_status.html", {
                "success": False, "message": error_message
            })
        
        # Parse file information
        file_paths = json.loads(file_paths_json)
        file_names = json.loads(file_names_json)
        
        logger.info(f"Parsed {len(file_names)} files from request")
        
        if not file_paths or not file_names:
            error_message = "Empty file selection"
            logger.warning(error_message)
            messages.error(request, error_message)
            return render(request, "upload/upload_status.html", {
                "success": False, "message": error_message
            })
        
        logger.info(f"Preparing presigned URLs for {len(file_names)} files")
        
        # Prepare file metadata
        files_metadata = []
        for i, file_name in enumerate(file_names):
            if i < len(file_paths):
                _, ext = os.path.splitext(file_name)
                file_type = get_mime_type(ext)
                
                path = os.path.dirname(file_paths[i])
                path_parts = path.split('/')
                if len(path_parts) > 1:
                    path = '/'.join(path_parts[1:])
                
                files_metadata.append({
                    "file_name": file_name,
                    "file_type": file_type,
                    "path": path
                })
                
                logger.debug(f"File {i+1}: {file_name}, type: {file_type}, path: {path}")
        
        # Generate presigned URLs directly
        upload_service = UploadService()
        logger.info(f"Upload service configuration: is_minio={upload_service.is_minio}, endpoint_url={upload_service.endpoint_url}")
        
        result = upload_service.generate_batch_presigned_posts(
            files_metadata=files_metadata,
            path_prefix=folder_name,
            expiration=3600,
            use_multipart=False  # Explicitly use single-part uploads
        )
        
        if result["success"]:
            logger.info(f"Successfully generated {len(result['presigned_posts'])} presigned URLs")
            # Log the first URL for debugging
            if result["presigned_posts"]:
                first_url = result["presigned_posts"][0].get("presigned_post", {}).get("url", "")
                logger.info(f"Sample presigned URL: {first_url}")
                
                # Log the fields for the first presigned post
                first_fields = result["presigned_posts"][0].get("presigned_post", {}).get("fields", {})
                logger.info(f"Sample presigned fields: {json.dumps(first_fields)}")
            
            # Transform the presigned_posts to a client-friendly format
            client_friendly_posts = []
            for post in result["presigned_posts"]:
                # Check if this post has the required structure
                if not post.get('presigned_post'):
                    logger.warning(f"Missing presigned_post in data for {post.get('file_name')}")
                    continue
                
                # Extract the presigned_post data and merge with the post properties
                presigned_post = post['presigned_post']
                client_post = {
                    'file_name': post.get('file_name', ''),
                    's3_key': post.get('s3_key', ''),
                    'file_type': post.get('file_type', ''),
                    'url': presigned_post.get('url', ''),
                    'fields': presigned_post.get('fields', {}),
                }
                client_friendly_posts.append(client_post)
            
            logger.info(f"Transformed {len(client_friendly_posts)} posts to client-friendly format")
            if client_friendly_posts:
                logger.debug(f"Sample transformed post: {json.dumps(client_friendly_posts[0])}")
            
            # Return the upload stage template directly
            return render(request, "upload/upload_stage.html", {
                "presigned_posts": client_friendly_posts,
                "presigned_posts_json": json.dumps(client_friendly_posts)
            })
        else:
            error_msg = result.get('error', 'Unknown error')
            logger.error(f"Failed to generate presigned URLs: {error_msg}")
            return render(request, "upload/upload_status.html", {
                "success": False, 
                "message": f"Failed to generate presigned URLs: {error_msg}"
            })
            
    except Exception as e:
        # Handle errors
        logger.exception(f"Unexpected error in process_upload: {str(e)}")
        return render(request, "upload/upload_status.html", {
            "success": False, 
            "message": f"Error: {str(e)}"
        })


def get_mime_type(ext):
    """Helper function to guess MIME type from file extension."""
    ext = ext.lower()
    mime_types = {
        '.jpg': 'image/jpeg',
        '.jpeg': 'image/jpeg',
        '.png': 'image/png',
        '.gif': 'image/gif',
        '.pdf': 'application/pdf',
        '.txt': 'text/plain',
        '.html': 'text/html',
        '.xml': 'application/xml',
        '.json': 'application/json',
        '.wav': 'audio/wav',
        '.mp3': 'audio/mpeg',
        '.mp4': 'video/mp4',
        '.eaf': 'application/xml',  # For ELAN files
    }
    return mime_types.get(ext, 'application/octet-stream')


def guess_content_type(filename):
    """Helper function to guess content type from filename extension."""
    import mimetypes
    content_type, _ = mimetypes.guess_type(filename)
    return content_type or 'application/octet-stream'


def format_file_size(size_bytes):
    """Format file size in bytes to a human-readable format."""
    if size_bytes == 0:
        return "0B"
    
    size_name = ("B", "KB", "MB", "GB", "TB", "PB", "EB", "ZB", "YB")
    i = 0
    while size_bytes >= 1024 and i < len(size_name) - 1:
        size_bytes /= 1024
        i += 1
    
    return f"{size_bytes:.2f} {size_name[i]}"



@require_http_methods(["POST"])
@general_login_required
def upload_complete(request):
    """Handle notification that all uploads are complete."""
    try:
        folder_name = request.POST.get('folder_name')
        uploaded_files_json = request.POST.get('uploaded_files')
        
        logger.info(f"Upload complete notification for folder: {folder_name} by user: {request.user.username}")
        
        if not folder_name or not uploaded_files_json:
            logger.warning("Missing folder name or uploaded files data in upload_complete request")
            return render(request, "upload/upload_status.html", {
                "success": False,
                "message": "Missing folder name or uploaded files data"
            })
        
        uploaded_files = json.loads(uploaded_files_json)
        logger.info(f"Processing {len(uploaded_files)} completed uploads")
        
        # Process the uploaded files
        upload_service = UploadService()
        logger.info(f"Upload service configuration: is_minio={upload_service.is_minio}, endpoint_url={upload_service.endpoint_url}")
        
        result = upload_service.process_uploaded_files(
            folder_name=folder_name,
            uploaded_files=uploaded_files
        )
        
        if result["success"]:
            logger.info(f"Successfully processed {len(result.get('processed_files', []))} files")
            if result.get("failed_files"):
                logger.warning(f"Failed to process {len(result.get('failed_files', []))} files")
        else:
            logger.error(f"Failed to process uploaded files: {result.get('error', 'Unknown error')}")
        
        return render(request, "upload/upload_status.html", {
            "success": result["success"],
            "processed_files": result.get("processed_files", []),
            "failed_files": result.get("failed_files", []),
            "message": "Upload complete!"
        })
        
    except Exception as e:
        logger.exception(f"Unexpected error in upload_complete: {str(e)}")
        return render(request, "upload/upload_status.html", {
            "success": False,
            "message": f"Error processing uploads: {str(e)}"
        })


# Add a debug view to test presigned URL generation

@require_http_methods(["GET"])
@general_login_required
def debug_presigned_url(request):
    """Debug endpoint to test presigned URL generation."""
    logger.info(f"Debug presigned URL requested by user: {request.user.username}")
    
    upload_service = UploadService()
    
    # Log the service configuration
    logger.info(f"Upload service configuration:")
    logger.info(f"  is_minio: {upload_service.is_minio}")
    logger.info(f"  endpoint_url: {upload_service.endpoint_url}")
    logger.info(f"  ingest_bucket: {upload_service.ingest_bucket}")
    
    # Generate a presigned URL for a test file
    result = upload_service.generate_presigned_post(
        file_name="test.txt",
        file_type="text/plain",
        path_prefix="debug",
        use_multipart=False  # Explicitly use single-part uploads
    )
    
    # Log the result
    if result.get("success", False):
        presigned_post = result.get("presigned_post", {})
        logger.info(f"Generated presigned URL: {presigned_post.get('url')}")
        logger.info(f"Generated fields: {json.dumps(presigned_post.get('fields', {}))}")
    else:
        logger.error(f"Failed to generate presigned URL: {result.get('error')}")
    
    # Convert the presigned post to a JSON string for JavaScript
    presigned_post_json = json.dumps(result.get("presigned_post", {}))
    
    # Return a simple HTML page with the presigned URL info
    html_content = f"""
    <html>
    <head>
        <title>Debug Presigned URL</title>
        <style>
            body {{ font-family: Arial, sans-serif; max-width: 800px; margin: 0 auto; padding: 20px; }}
            pre {{ background: #f5f5f5; padding: 10px; overflow: auto; border-radius: 4px; }}
            button {{ padding: 8px 16px; background: #4CAF50; color: white; border: none; cursor: pointer; border-radius: 4px; }}
            input[type="file"] {{ margin-bottom: 10px; }}
            .result {{ margin-top: 20px; }}
        </style>
    </head>
    <body>
        <h1>Debug Presigned URL</h1>
        <h2>Configuration:</h2>
        <ul>
            <li>is_minio: {upload_service.is_minio}</li>
            <li>endpoint_url: {upload_service.endpoint_url}</li>
            <li>ingest_bucket: {upload_service.ingest_bucket}</li>
        </ul>
        
        <h2>Presigned URL Result:</h2>
        <pre>{json.dumps(result, indent=2)}</pre>
        
        <h2>Test Upload:</h2>
        <form id="uploadForm" enctype="multipart/form-data">
            <input type="file" id="fileInput">
            <button type="button" id="uploadButton">Upload</button>
        </form>
        
        <h2>Result:</h2>
        <pre id="uploadResult" class="result"></pre>
        
        <script>
            // Store the presigned post data from the server
            const presignedPost = {presigned_post_json};
            
            document.getElementById('uploadButton').addEventListener('click', async () => {{
                const fileInput = document.getElementById('fileInput');
                const resultElement = document.getElementById('uploadResult');
                
                if (!fileInput.files.length) {{
                    resultElement.textContent = 'Please select a file first';
                    return;
                }}
                
                const file = fileInput.files[0];
                resultElement.textContent = `Uploading ${{file.name}}...`;
                
                try {{
                    console.log("Using presigned post:", presignedPost);
                    
                    const formData = new FormData();
                    
                    // Add all the fields from the presigned post
                    Object.keys(presignedPost.fields).forEach(key => {{
                        formData.append(key, presignedPost.fields[key]);
                        console.log(`Added field: ${{key}} = ${{presignedPost.fields[key]}}`);
                    }});
                    
                    // Add the file as the last field
                    formData.append('file', file);
                    console.log("Added file to form data");
                    
                    console.log("Sending request to:", presignedPost.url);
                    
                    const response = await fetch(presignedPost.url, {{
                        method: 'POST',
                        body: formData
                    }});
                    
                    console.log("Response status:", response.status);
                    
                    if (response.ok) {{
                        resultElement.textContent = `Upload successful!`;
                    }} else {{
                        const responseText = await response.text();
                        console.error("Response text:", responseText);
                        resultElement.textContent = `Upload failed with status: ${{response.status}}\\nResponse: ${{responseText}}`;
                    }}
                }} catch (error) {{
                    console.error("Error:", error);
                    resultElement.textContent = `Error: ${{error.message}}`;
                }}
            }});
        </script>
    </body>
    </html>
    """
    
    return HttpResponse(html_content)



@require_http_methods(["POST"])
@general_login_required
def debug_upload_error(request):
    """
    Endpoint for logging client-side upload errors on the server.
    This allows client-side JavaScript errors to appear in server logs.
    """
    try:
        data = json.loads(request.body)
        error = data.get('error', 'No error details provided')
        file_name = data.get('file_name', 'unknown')
        s3_key = data.get('s3_key', 'unknown')
        
        logger.error(f"CLIENT-SIDE UPLOAD ERROR for {file_name} → {s3_key}:")
        logger.error(f"Error details: {error}")
        
        # Log additional request information that might be useful
        logger.error(f"Headers: {dict(request.headers)}")
        
        # Return a simple acknowledgment
        return JsonResponse({
            'success': True,
            'message': 'Error logged successfully'
        })
    except Exception as e:
        logger.exception(f"Error in debug_upload_error endpoint: {str(e)}")
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500) 