import logging
import time
import os
import json
from typing import Dict, Any, List, Tuple, Set, Optional, IO, Union
from io import BytesIO
import concurrent.futures
from functools import partial

import boto3
from boto3.s3.transfer import TransferConfig
from botocore.exceptions import ClientError

from .base_storage_service import BaseStorageService

logger = logging.getLogger(__name__)

class UploadService:
    """
    Service for handling file uploads to S3/MinIO buckets via streaming.
    
    This service focuses on streaming file uploads directly from Django to S3,
    avoiding the need for presigned URLs which may not be supported by all S3-compatible
    services. Files are streamed chunk by chunk to avoid memory issues.
    
    This service is NOT a singleton. It uses BaseStorageService for S3 client operations.
    """
    
    def __init__(self):
        """
        Initialize the UploadService with reference to BaseStorageService.
        """
        logger.info("Initializing UploadService...")
        # Get the singleton instance of BaseStorageService for S3 operations
        self.base_s3_service = BaseStorageService()
        logger.info(f"UploadService initialized using BaseStorageService with endpoint: {self.base_s3_service.endpoint_url}")

    def _generate_file_key(self, file_name: str, path_prefix: Optional[str] = None) -> str:
        """
        Generate a clean S3 key (path) for a file.
        
        Args:
            file_name (str): The name of the file
            path_prefix (str, optional): Path prefix to prepend to the file name
            
        Returns:
            str: The generated S3 key
        """
        # Sanitize the file name to work with S3 (replace spaces with underscores)
        clean_file_name = file_name.replace(' ', '_')
        
        # Build the full S3 key (path)
        if path_prefix:
            # Ensure the path has no leading or trailing slashes
            clean_prefix = path_prefix.strip('/')
            if clean_prefix:
                return f"{clean_prefix}/{clean_file_name}"
        
        # Just return the clean file name if no prefix
        return clean_file_name

    def _upload_file_to_custom_key(self, file_obj, s3_key, bucket_name, content_type='application/octet-stream'):
        """
        Upload a file directly to a specific S3 key without path generation.
        
        Args:
            file_obj: File-like object (Django UploadedFile, etc.)
            s3_key: Complete S3 key (path) for the file
            bucket_name: Target S3 bucket
            content_type: MIME type of the file
            
        Returns:
            Dictionary with upload result
        """
        try:
            logger.debug(f"Uploading to custom key: {s3_key}")
            
            # Prepare upload arguments
            upload_args = {
                'ContentType': content_type,
            }
            
            # Upload the file using BaseStorageService's S3 client
            self.base_s3_service.s3_client.upload_fileobj(
                file_obj,
                bucket_name,
                s3_key,
                ExtraArgs=upload_args
            )
            
            # Verify upload and get file info
            try:
                head_response = self.base_s3_service.s3_client.head_object(
                    Bucket=bucket_name,
                    Key=s3_key
                )
                actual_file_size = head_response.get('ContentLength', 0)
                last_modified = head_response.get('LastModified', None)
                
                s3_url = f"s3://{bucket_name}/{s3_key}"
                
                logger.debug(f"✅ Successfully uploaded to {s3_key} ({self.base_s3_service._format_size(actual_file_size)})")
                
                return {
                    'success': True,
                    's3_key': s3_key,
                    's3_url': s3_url,
                    'bucket': bucket_name,
                    'file_size': actual_file_size,
                    'content_type': content_type,
                    'last_modified': last_modified.isoformat() if last_modified else None,
                }
            except Exception as verify_error:
                logger.warning(f"Upload succeeded but verification failed for {s3_key}: {verify_error}")
                return {
                    'success': True,
                    's3_key': s3_key,
                    's3_url': f"s3://{bucket_name}/{s3_key}",
                    'bucket': bucket_name,
                    'content_type': content_type,
                    'verification_warning': str(verify_error)
                }
                
        except Exception as e:
            logger.error(f"Error uploading to {s3_key}: {str(e)}")
            return {
                'success': False,
                'error': str(e),
                's3_key': s3_key
            }

    def upload_file_stream(self, file_obj: Union[IO, bytes], file_name: str, 
                          content_type: str = 'application/octet-stream',
                          path_prefix: Optional[str] = None, 
                          file_size: Optional[int] = None) -> Dict[str, Any]:
        """
        Upload a file from a file-like object or bytes directly to S3.
        
        Args:
            file_obj: File-like object (Django UploadedFile, BytesIO, etc.) or bytes
            file_name: The name of the file
            content_type: MIME type of the file
            path_prefix: Optional prefix for the S3 key
            file_size: Optional file size (if known)
            
        Returns:
            Dictionary with upload result
        """
        try:
            # Generate S3 key
            s3_key = self._generate_file_key(file_name, path_prefix)
            
            logger.info(f"Uploading file stream {file_name} to {s3_key}")
            
            # Handle bytes input
            if isinstance(file_obj, bytes):
                file_obj = BytesIO(file_obj)
                if file_size is None:
                    file_size = len(file_obj.getvalue())
            
            # Prepare upload arguments
            upload_args = {
                'ContentType': content_type,
            }
            
            # Upload the file using BaseStorageService's S3 client
            self.base_s3_service.s3_client.upload_fileobj(
                file_obj,
                self.base_s3_service.ingest_bucket,
                s3_key,
                ExtraArgs=upload_args
            )
            
            # Verify upload and get file info
            try:
                head_response = self.base_s3_service.s3_client.head_object(
                    Bucket=self.base_s3_service.ingest_bucket,
                    Key=s3_key
                )
                actual_file_size = head_response.get('ContentLength', 0)
                last_modified = head_response.get('LastModified', None)
                
                logger.info(f"Successfully uploaded {file_name} ({self.base_s3_service._format_size(actual_file_size)})")
                
                return {
                    'success': True,
                    'file_name': file_name,
                    's3_key': s3_key,
                    'bucket': self.base_s3_service.ingest_bucket,
                    'file_size': actual_file_size,
                    'file_size_formatted': self.base_s3_service._format_size(actual_file_size),
                    'content_type': content_type,
                    'last_modified': last_modified.isoformat() if last_modified else None,
                }
            except Exception as verify_error:
                logger.warning(f"Upload succeeded but verification failed for {s3_key}: {verify_error}")
                return {
                    'success': True,
                    'file_name': file_name,
                    's3_key': s3_key,
                    'bucket': self.base_s3_service.ingest_bucket,
                    'content_type': content_type,
                    'verification_warning': str(verify_error)
                }
                
        except Exception as e:
            logger.error(f"Error uploading file stream {file_name}: {str(e)}")
            return {
                'success': False,
                'error': str(e),
                'file_name': file_name
            }

    def upload_multipart_stream(self, file_obj: Union[IO, bytes], file_name: str,
                               content_type: str = 'application/octet-stream',
                               path_prefix: Optional[str] = None,
                               chunk_size: int = 5 * 1024 * 1024) -> Dict[str, Any]:
        """
        Upload a large file using multipart upload for better reliability and performance.
        
        Args:
            file_obj: File-like object or bytes
            file_name: The name of the file
            content_type: MIME type of the file
            path_prefix: Optional prefix for the S3 key
            chunk_size: Size of each part in bytes (minimum 5MB for S3)
            
        Returns:
            Dictionary with upload result
        """
        try:
            # Generate S3 key
            s3_key = self._generate_file_key(file_name, path_prefix)
            
            logger.info(f"Starting multipart upload for {file_name} to {s3_key}")
            
            # Handle bytes input
            if isinstance(file_obj, bytes):
                file_obj = BytesIO(file_obj)
            
            # Initialize multipart upload
            create_response = self.base_s3_service.s3_client.create_multipart_upload(
                Bucket=self.base_s3_service.ingest_bucket,
                Key=s3_key,
                ContentType=content_type
            )
            
            upload_id = create_response['UploadId']
            logger.info(f"Multipart upload initialized with ID: {upload_id}")
            
            # Upload parts
            parts = []
            part_number = 1
            total_size = 0
            
            try:
                while True:
                    # Read chunk
                    chunk = file_obj.read(chunk_size)
                    if not chunk:
                        break
                    
                    chunk_size_actual = len(chunk)
                    total_size += chunk_size_actual
                    
                    logger.debug(f"Uploading part {part_number} ({self.base_s3_service._format_size(chunk_size_actual)})")
                    
                    # Upload part
                    part_response = self.base_s3_service.s3_client.upload_part(
                        Bucket=self.base_s3_service.ingest_bucket,
                        Key=s3_key,
                        PartNumber=part_number,
                        UploadId=upload_id,
                        Body=chunk
                    )
                    
                    # Store part info
                    parts.append({
                        'PartNumber': part_number,
                        'ETag': part_response['ETag']
                    })
                    
                    part_number += 1
                
                # Complete multipart upload
                complete_response = self.base_s3_service.s3_client.complete_multipart_upload(
                    Bucket=self.base_s3_service.ingest_bucket,
                    Key=s3_key,
                    UploadId=upload_id,
                    MultipartUpload={'Parts': parts}
                )
                
                logger.info(f"Multipart upload completed for {file_name} ({self.base_s3_service._format_size(total_size)}, {len(parts)} parts)")
                
                # Verify upload
                try:
                    head_response = self.base_s3_service.s3_client.head_object(
                        Bucket=self.base_s3_service.ingest_bucket,
                        Key=s3_key
                    )
                    actual_file_size = head_response.get('ContentLength', 0)
                    last_modified = head_response.get('LastModified', None)
                    
                    return {
                        'success': True,
                        'file_name': file_name,
                        's3_key': s3_key,
                        'bucket': self.base_s3_service.ingest_bucket,
                        'file_size': actual_file_size,
                        'file_size_formatted': self.base_s3_service._format_size(actual_file_size),
                        'content_type': content_type,
                        'last_modified': last_modified.isoformat() if last_modified else None,
                        'part_count': len(parts)
                    }
                except Exception as verify_error:
                    logger.warning(f"Upload succeeded but verification failed for {s3_key}: {verify_error}")
                    return {
                        'success': True,
                        'file_name': file_name,
                        's3_key': s3_key,
                        'bucket': self.base_s3_service.ingest_bucket,
                        'file_size_approximation': total_size,
                        'file_size_formatted': self.base_s3_service._format_size(total_size),
                        'content_type': content_type,
                        'part_count': len(parts),
                        'verification_warning': str(verify_error)
                    }
                    
            except Exception as part_error:
                logger.error(f"Error during multipart upload for {file_name}: {str(part_error)}")
                
                # Abort the multipart upload to clean up
                try:
                    self.base_s3_service.s3_client.abort_multipart_upload(
                        Bucket=self.base_s3_service.ingest_bucket,
                        Key=s3_key,
                        UploadId=upload_id
                    )
                    logger.info(f"Aborted multipart upload for {file_name} with ID {upload_id}")
                except Exception as abort_error:
                    logger.error(f"Error aborting multipart upload: {str(abort_error)}")
                
                raise part_error
                
        except Exception as e:
            logger.error(f"Error in multipart upload for {file_name}: {str(e)}")
            return {
                'success': False,
                'error': str(e),
                'file_name': file_name
            }

    def upload_django_file(self, uploaded_file, path_prefix: Optional[str] = None, 
                          use_multipart: bool = True, 
                          multipart_threshold: int = 10 * 1024 * 1024) -> Dict[str, Any]:
        """
        Upload a Django uploaded file to S3.
        
        Args:
            uploaded_file: Django UploadedFile object
            path_prefix: Optional prefix for the S3 key
            use_multipart: Whether to use multipart upload for large files
            multipart_threshold: Size threshold for multipart upload
            
        Returns:
            Dictionary with upload result
        """
        # Get file details
        file_name = os.path.basename(uploaded_file.name)
        file_size = uploaded_file.size
        content_type = uploaded_file.content_type or 'application/octet-stream'
        
        logger.info(f"Uploading Django file: {file_name}, size: {self.base_s3_service._format_size(file_size)}, type: {content_type}")
        
        # Choose upload method based on file size
        if use_multipart and file_size > multipart_threshold:
            logger.info(f"Using multipart upload for {file_name} ({self.base_s3_service._format_size(file_size)} > {self.base_s3_service._format_size(multipart_threshold)})")
            return self.upload_multipart_stream(
                file_obj=uploaded_file,
                file_name=file_name,
                content_type=content_type,
                path_prefix=path_prefix
            )
        else:
            logger.info(f"Using single-part upload for {file_name} ({self.base_s3_service._format_size(file_size)})")
            return self.upload_file_stream(
                file_obj=uploaded_file,
                file_name=file_name,
                content_type=content_type,
                path_prefix=path_prefix,
                file_size=file_size
            )

    def upload_batch_django_files(self, uploaded_files: List, 
                                 path_prefix: Optional[str] = None,
                                 use_multipart: bool = True,
                                 multipart_threshold: int = 10 * 1024 * 1024) -> Dict[str, Any]:
        """
        Upload multiple Django uploaded files to S3.
        
        Args:
            uploaded_files: List of Django UploadedFile objects
            path_prefix: Optional prefix for the S3 key
            use_multipart: Whether to use multipart upload for large files
            multipart_threshold: Size threshold for multipart upload
            
        Returns:
            Dictionary with upload results
        """
        results = []
        success_count = 0
        error_count = 0
        total_size = 0
        
        logger.info(f"Starting batch upload of {len(uploaded_files)} files")
        
        for uploaded_file in uploaded_files:
            result = self.upload_django_file(
                uploaded_file=uploaded_file,
                path_prefix=path_prefix,
                use_multipart=use_multipart,
                multipart_threshold=multipart_threshold
            )
            
            results.append(result)
            
            if result.get('success', False):
                success_count += 1
                total_size += result.get('file_size', 0)
            else:
                error_count += 1
        
        logger.info(f"Batch upload complete: {success_count} successful, {error_count} failed, total size: {self.base_s3_service._format_size(total_size)}")
        
        return {
            'success': error_count == 0,
            'total_files': len(uploaded_files),
            'success_count': success_count,
            'error_count': error_count,
            'total_size': total_size,
            'total_size_formatted': self.base_s3_service._format_size(total_size),
            'results': results
        }

    def get_file_info(self, s3_key: str) -> Dict[str, Any]:
        """
        Get information about a file in S3.
        
        Args:
            s3_key: The S3 key of the file
            
        Returns:
            Dictionary with file information
        """
        try:
            # Get file metadata
            head_response = self.base_s3_service.s3_client.head_object(
                Bucket=self.base_s3_service.ingest_bucket,
                Key=s3_key
            )
            
            # Extract file details
            file_size = head_response.get('ContentLength', 0)
            last_modified = head_response.get('LastModified', None)
            content_type = head_response.get('ContentType', 'application/octet-stream')
            metadata = head_response.get('Metadata', {})
            
            logger.info(f"Retrieved file info for {s3_key}: {self.base_s3_service._format_size(file_size)}, {content_type}")
            
            return {
                'success': True,
                's3_key': s3_key,
                'file_name': os.path.basename(s3_key),
                'bucket': self.base_s3_service.ingest_bucket,
                'file_size': file_size,
                'file_size_formatted': self.base_s3_service._format_size(file_size),
                'content_type': content_type,
                'last_modified': last_modified.isoformat() if last_modified else None,
                'metadata': metadata
            }
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', '')
            if error_code == 'NoSuchKey':
                logger.warning(f"File not found: {s3_key}")
                return {
                    'success': False,
                    'error': 'File not found',
                    's3_key': s3_key
                }
            else:
                logger.error(f"Error getting file info for {s3_key}: {str(e)}")
                return {
                    'success': False,
                    'error': str(e),
                    's3_key': s3_key
                }
        except Exception as e:
            logger.error(f"Unexpected error getting file info for {s3_key}: {str(e)}")
            return {
                'success': False,
                'error': str(e),
                's3_key': s3_key
            }

    def upload_files_optimized(self, files: List[Dict[str, Any]], path_prefix: Optional[str] = None, 
                             max_workers: int = 10, multipart_threshold: int = 8 * 1024 * 1024,
                             max_concurrency: int = 10, multipart_chunksize: int = 8 * 1024 * 1024,
                             bucket_name: Optional[str] = None) -> Dict[str, Any]:
        """
        Upload multiple files using optimized threading and boto3 config.
        
        Args:
            files: List of dictionaries with file information (must include 'file_path' and 'file_name')
            path_prefix: Optional prefix for the S3 key
            max_workers: Maximum number of worker threads
            multipart_threshold: Size threshold for multipart upload
            max_concurrency: Maximum number of concurrent threads for a single multipart upload
            multipart_chunksize: Size of each part in a multipart upload
            bucket_name: Override the default ingest bucket
            
        Returns:
            Dictionary with upload results
        """
        logger.info(f"Starting optimized upload of {len(files)} files with max_workers={max_workers}")
        
        if not files:
            return {
                'success': True,
                'message': 'No files to upload',
                'total_files': 0,
                'success_count': 0,
                'error_count': 0,
                'total_size': 0,
                'total_size_formatted': '0 B',
                'results': []
            }
        
        # Use ingest bucket by default
        if not bucket_name:
            bucket_name = self.base_s3_service.ingest_bucket
        
        # Configure transfer settings
        transfer_config = TransferConfig(
            multipart_threshold=multipart_threshold,
            max_concurrency=max_concurrency,
            multipart_chunksize=multipart_chunksize,
            use_threads=True
        )
        
        # Define function for uploading a single file
        def upload_single_file(file_info):
            file_path = file_info.get('file_path')
            file_name = file_info.get('file_name') or os.path.basename(file_path)
            content_type = file_info.get('content_type') or 'application/octet-stream'
            file_folder = file_info.get('folder')
            
            # Determine final path prefix
            final_path_prefix = path_prefix
            if file_folder:
                if final_path_prefix:
                    final_path_prefix = f"{final_path_prefix}/{file_folder}"
                else:
                    final_path_prefix = file_folder
            
            # Generate S3 key
            s3_key = self._generate_file_key(file_name, final_path_prefix)
            
            logger.debug(f"Uploading file {file_name} to {s3_key}")
            
            try:
                # Get file size
                file_size = os.path.getsize(file_path)
                
                # Prepare upload arguments
                upload_args = {
                    'ContentType': content_type
                }
                
                # Add metadata if provided
                metadata = file_info.get('metadata')
                if metadata:
                    upload_args['Metadata'] = metadata
                
                # Add tags if provided
                tags = file_info.get('tags')
                if tags:
                    tag_string = '&'.join([f"{k}={v}" for k, v in tags.items()])
                    upload_args['Tagging'] = tag_string
                
                # Track start time for performance analysis
                start_time = time.time()
                
                # Upload the file using optimized settings
                self.base_s3_service.s3_client.upload_file(
                    file_path,
                    bucket_name,
                    s3_key,
                    ExtraArgs=upload_args,
                    Config=transfer_config
                )
                
                # Calculate upload speed
                end_time = time.time()
                duration = end_time - start_time
                upload_speed = file_size / duration if duration > 0 else 0
                upload_speed_formatted = f"{self.base_s3_service._format_size(upload_speed)}/s"
                
                logger.info(f"Successfully uploaded {file_name} ({self.base_s3_service._format_size(file_size)}) in {duration:.2f}s ({upload_speed_formatted})")
                
                return {
                    'success': True,
                    'file_name': file_name,
                    's3_key': s3_key,
                    'bucket': bucket_name,
                    'file_size': file_size,
                    'file_size_formatted': self.base_s3_service._format_size(file_size),
                    'content_type': content_type,
                    'duration': duration,
                    'upload_speed': upload_speed,
                    'upload_speed_formatted': upload_speed_formatted
                }
            except Exception as e:
                logger.error(f"Error uploading file {file_name}: {str(e)}")
                return {
                    'success': False,
                    'error': str(e),
                    'file_name': file_name,
                    's3_key': s3_key,
                    'bucket': bucket_name
                }
        
        # Use ThreadPoolExecutor for parallel uploads
        results = []
        success_count = 0
        error_count = 0
        total_size = 0
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Submit all uploads
            future_to_file = {executor.submit(upload_single_file, file_info): file_info for file_info in files}
            
            # Process results as they complete
            for future in concurrent.futures.as_completed(future_to_file):
                file_info = future_to_file[future]
                try:
                    result = future.result()
                    results.append(result)
                    
                    if result.get('success', False):
                        success_count += 1
                        total_size += result.get('file_size', 0)
                    else:
                        error_count += 1
                        
                    # Log progress periodically
                    if (success_count + error_count) % 10 == 0 or (success_count + error_count) == len(files):
                        logger.info(f"Progress: {success_count + error_count}/{len(files)} files processed, {success_count} successful, {error_count} failed")
                        
                except Exception as e:
                    logger.error(f"Exception processing result for {file_info.get('file_name')}: {str(e)}")
                    results.append({
                        'success': False,
                        'error': str(e),
                        'file_name': file_info.get('file_name') or file_info.get('file_path', 'unknown')
                    })
                    error_count += 1
        
        logger.info(f"Optimized batch upload complete: {success_count}/{len(files)} successful, {error_count} failed, total size: {self.base_s3_service._format_size(total_size)}")
        
        return {
            'success': error_count == 0,
            'total_files': len(files),
            'success_count': success_count,
            'error_count': error_count,
            'total_size': total_size,
            'total_size_formatted': self.base_s3_service._format_size(total_size),
            'results': results
        }

    def upload_batch_django_files_optimized(self, uploaded_files: List, 
                                 path_prefix: Optional[str] = None,
                                 max_workers: int = 10,
                                 multipart_threshold: int = 8 * 1024 * 1024,
                                 max_concurrency: int = 10,
                                 multipart_chunksize: int = 8 * 1024 * 1024,
                                 bucket_name: Optional[str] = None) -> Dict[str, Any]:
        """
        Upload multiple Django uploaded files to S3 using an optimized approach.
        
        This method saves each Django file to a temporary file and then uses
        upload_files_optimized for better performance with large batches.
        
        Args:
            uploaded_files: List of Django UploadedFile objects
            path_prefix: Optional prefix for the S3 key
            max_workers: Maximum number of worker threads
            multipart_threshold: Size threshold for multipart upload
            max_concurrency: Maximum number of concurrent threads for a single multipart upload
            multipart_chunksize: Size of each part in a multipart upload
            bucket_name: Override the default ingest bucket
            
        Returns:
            Dictionary with upload results
        """
        import tempfile
        import os
        
        logger.info(f"Starting optimized batch upload of {len(uploaded_files)} Django files")
        
        # Convert Django files to file paths
        temp_files = []
        files_to_upload = []
        
        try:
            for uploaded_file in uploaded_files:
                # Create a temporary file
                temp_file = tempfile.NamedTemporaryFile(delete=False)
                temp_files.append(temp_file.name)
                
                # Write Django file content to the temporary file
                for chunk in uploaded_file.chunks():
                    temp_file.write(chunk)
                temp_file.close()
                
                # Add file info to the upload list
                files_to_upload.append({
                    'file_path': temp_file.name,
                    'file_name': os.path.basename(uploaded_file.name),
                    'content_type': uploaded_file.content_type or 'application/octet-stream'
                })
            
            # Use the optimized upload method
            result = self.upload_files_optimized(
                files=files_to_upload,
                path_prefix=path_prefix,
                max_workers=max_workers,
                multipart_threshold=multipart_threshold,
                max_concurrency=max_concurrency,
                multipart_chunksize=multipart_chunksize,
                bucket_name=bucket_name
            )
            
            return result
            
        finally:
            # Clean up temporary files
            for temp_file in temp_files:
                try:
                    os.unlink(temp_file)
                except Exception as e:
                    logger.warning(f"Error cleaning up temporary file {temp_file}: {str(e)}")

    def upload_batch_django_files_with_structure(self, uploaded_files, base_path='', bucket_name=None, file_paths=None):
        """
        Upload Django files while preserving their folder structure.
        Uses provided file paths to maintain directory hierarchy.
        
        Args:
            uploaded_files: List of Django UploadedFile objects
            base_path: Base path to prepend to all files (e.g., 'data' or 'metadata')
            bucket_name: Target S3 bucket (optional, uses default if None)
            file_paths: List of relative paths for each file (optional)
            
        Returns:
            Dict with success status, results, and summary
        """
        if not uploaded_files:
            return {
                'success': False,
                'error': 'No files provided',
                'results': [],
                'failures': []
            }
        
        bucket_name = bucket_name or self.base_s3_service.ingest_bucket
        logger.info(f"Starting structured batch upload: {len(uploaded_files)} files to {bucket_name}")
        
        start_time = time.time()
        results = []
        failures = []
        
        try:
            for i, uploaded_file in enumerate(uploaded_files):
                try:
                    # Get the file's relative path for folder structure
                    if file_paths and i < len(file_paths):
                        # Use provided path from JavaScript (webkitRelativePath)
                        relative_path = file_paths[i]
                    else:
                        # Fallback to file name
                        relative_path = uploaded_file.name
                    
                    # If we have a base_path, prepend it
                    if base_path:
                        s3_key = f"{base_path.rstrip('/')}/{relative_path}"
                    else:
                        s3_key = relative_path
                    
                    # Clean up the S3 key (remove double slashes, etc.)
                    s3_key = '/'.join(filter(None, s3_key.split('/')))
                    
                    # Only log first few files to avoid spam
                    if i <= 2:
                        logger.info(f"📁 FOLDER UPLOAD DEBUG: {uploaded_file.name} -> S3 key: {s3_key}")
                    
                    # Upload the file directly using the existing upload methods
                    # Reset file position to beginning
                    if hasattr(uploaded_file, 'seek'):
                        uploaded_file.seek(0)
                    
                    # Use upload_file_stream method - we need to set the key manually
                    # Since upload_file_stream uses _generate_file_key, we need a custom approach
                    result = self._upload_file_to_custom_key(
                        file_obj=uploaded_file,
                        s3_key=s3_key,
                        bucket_name=bucket_name,
                        content_type=uploaded_file.content_type or 'application/octet-stream'
                    )
                    
                    if result.get('success', False):
                        results.append({
                            'file_name': uploaded_file.name,
                            'original_path': relative_path,
                            's3_key': s3_key,
                            's3_url': result.get('s3_url', ''),
                            'file_size': uploaded_file.size,
                            'content_type': uploaded_file.content_type or 'application/octet-stream'
                        })
                        logger.debug(f"✅ Successfully uploaded: {uploaded_file.name}")
                    else:
                        error_msg = result.get('error', 'Upload failed')
                        failures.append({
                            'file_name': uploaded_file.name,
                            'original_path': relative_path,
                            's3_key': s3_key,
                            'error': error_msg,
                            'file_size': uploaded_file.size,
                            'content_type': uploaded_file.content_type or 'application/octet-stream'
                        })
                        logger.error(f"❌ Failed to upload {uploaded_file.name}: {error_msg}")
                
                except Exception as e:
                    error_msg = f"Error processing file {uploaded_file.name}: {str(e)}"
                    logger.exception(error_msg)
                    failures.append({
                        'file_name': uploaded_file.name,
                        'original_path': file_paths[i] if file_paths and i < len(file_paths) else uploaded_file.name,
                        's3_key': '',
                        'error': error_msg,
                        'file_size': getattr(uploaded_file, 'size', 0),
                        'content_type': getattr(uploaded_file, 'content_type', 'application/octet-stream') or 'application/octet-stream'
                    })
        
        except Exception as e:
            logger.exception(f"Critical error in batch upload: {str(e)}")
            return {
                'success': False,
                'error': f"Batch upload failed: {str(e)}",
                'results': results,
                'failures': failures
            }
        
        # Calculate summary
        duration = time.time() - start_time
        total_files = len(uploaded_files)
        success_count = len(results)
        failure_count = len(failures)
        
        total_size = sum(f.get('file_size', 0) for f in results)
        
        logger.info(f"Structured batch upload completed: {success_count}/{total_files} files successful in {duration:.2f}s")
        
        return {
            'success': failure_count == 0,
            'results': results,
            'failures': failures,
            'summary': {
                'total_files': total_files,
                'successful_files': success_count,
                'failed_files': failure_count,
                'total_size': total_size,
                'duration_seconds': duration,
                'bucket': bucket_name,
                'base_path': base_path
            },
            'success_count': success_count,
            'error_count': failure_count,
            'total_size': total_size,
            'duration': f"{duration:.2f}s"
        } 