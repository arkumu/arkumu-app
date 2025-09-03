"""
Upload utility functions for S3 operations.
Extracted from upload_service.py for better code organization.
"""
import logging
import os
import urllib3.exceptions
from typing import Dict, Any, Optional, List

from botocore.exceptions import ClientError

from ..base_storage_service import BaseStorageService

logger = logging.getLogger(__name__)


def generate_file_key(file_name: str, path_prefix: Optional[str] = None) -> str:
    """
    Generate consistent S3 key (path) for a file with sanitization.
    Always replaces spaces with underscores for consistency.
    
    Args:
        file_name: The name of the file
        path_prefix: Path prefix to prepend to the file name
        
    Returns:
        The sanitized S3 key with underscores instead of spaces
    """
    # Sanitize filename - replace spaces with underscores
    clean_file_name = file_name.replace(' ', '_')
    
    # Build the full S3 key (path) with sanitization
    if path_prefix:
        # Ensure the path has no leading or trailing slashes and strip whitespace
        clean_prefix = path_prefix.strip().strip('/')
        # Sanitize the path prefix - replace spaces with underscores
        clean_prefix = clean_prefix.replace(' ', '_')
        if clean_prefix:
            return f"{clean_prefix}/{clean_file_name}"
    
    # Just return the sanitized file name if no prefix
    return clean_file_name


def safe_head_object(bucket_name: str, s3_key: str) -> Optional[Dict[str, Any]]:
    """
    Safely perform head_object call with fallback for MinIO header parsing issues.
    
    Args:
        bucket_name: S3 bucket name
        s3_key: S3 object key
        
    Returns:
        Dictionary with object metadata or None if failed
    """
    base_service = BaseStorageService()
    s3_client = base_service.s3_client
    
    try:
        return s3_client.head_object(
            Bucket=bucket_name,
            Key=s3_key
        )
    except ClientError as e:
        # Let NoSuchKey and 404 errors bubble up to the caller for proper handling
        error_code = e.response.get('Error', {}).get('Code', '')
        status_code = e.response.get('ResponseMetadata', {}).get('HTTPStatusCode', '')
        if error_code == 'NoSuchKey' or status_code == 404:
            raise  # Re-raise the ClientError to let get_file_info handle it
        else:
            logger.error(f"ClientError in head_object for {s3_key}: {e}")
            return None
    except urllib3.exceptions.HeaderParsingError as e:
        logger.warning(f"MinIO header parsing error for {s3_key}: {e}")
        # For empty files, MinIO sometimes has header parsing issues
        # Try to get object info via list_objects_v2 as fallback
        try:
            response = s3_client.list_objects_v2(
                Bucket=bucket_name,
                Prefix=s3_key,
                MaxKeys=1
            )
            objects = response.get('Contents', [])
            if objects and objects[0]['Key'] == s3_key:
                obj = objects[0]
                return {
                    'ContentLength': obj.get('Size', 0),
                    'LastModified': obj.get('LastModified'),
                    'ETag': obj.get('ETag', ''),
                    'ContentType': 'application/octet-stream'  # Default fallback
                }
            else:
                logger.error(f"Object {s3_key} not found in fallback list_objects_v2")
                return None
        except Exception as fallback_error:
            logger.error(f"Fallback method also failed for {s3_key}: {fallback_error}")
            return None
    except Exception as e:
        logger.error(f"Unexpected error in head_object for {s3_key}: {e}")
        return None


def get_file_info(s3_key: str, bucket_name: Optional[str] = None) -> Dict[str, Any]:
    """
    Get information about a file in S3.
    
    Args:
        s3_key: The S3 key of the file
        bucket_name: Bucket name (uses default if None)
        
    Returns:
        Dictionary with file information
    """
    base_service = BaseStorageService()
    bucket_name = bucket_name or base_service.ingest_bucket
    
    try:
        # Get file metadata using safe head_object
        head_response = safe_head_object(bucket_name, s3_key)
        
        if head_response:
            # Extract file details
            file_size = head_response.get('ContentLength', 0)
            last_modified = head_response.get('LastModified', None)
            content_type = head_response.get('ContentType', 'application/octet-stream')
            metadata = head_response.get('Metadata', {})
            
            logger.info(f"Retrieved file info for {s3_key}: {base_service._format_size(file_size)}, {content_type}")
            
            return {
                'success': True,
                's3_key': s3_key,
                'file_name': os.path.basename(s3_key),
                'bucket': bucket_name,
                'file_size': file_size,
                'file_size_formatted': base_service._format_size(file_size),
                'content_type': content_type,
                'last_modified': last_modified.isoformat() if last_modified else None,
                'metadata': metadata
            }
        else:
            logger.error(f"Could not get file info for {s3_key} due to header parsing error")
            return {
                'success': False,
                'error': 'Could not retrieve file info due to header parsing error',
                's3_key': s3_key
            }
    except ClientError as e:
        error_code = e.response.get('Error', {}).get('Code', '')
        status_code = e.response.get('ResponseMetadata', {}).get('HTTPStatusCode', '')
        if error_code == 'NoSuchKey' or status_code == 404:
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


def validate_s3_key(s3_key: str) -> Dict[str, Any]:
    """
    Validate an S3 key for common issues.
    
    Args:
        s3_key: The S3 key to validate
        
    Returns:
        Dict with validation result
    """
    errors = []
    warnings = []
    
    # Check length
    if len(s3_key) > 1024:
        errors.append("S3 key exceeds maximum length of 1024 characters")
    
    # Check for invalid characters
    invalid_chars = ['\\', '{', '^', '}', '%', '`', ']', '"', '>', '[', '~', '<', '#', '|']
    for char in invalid_chars:
        if char in s3_key:
            errors.append(f"S3 key contains invalid character: {char}")
            break
    
    # Check for leading slash
    if s3_key.startswith('/'):
        warnings.append("S3 key starts with '/' which may cause issues")
    
    # Check for double slashes
    if '//' in s3_key:
        warnings.append("S3 key contains double slashes")
    
    # Check for spaces (common issue)
    if ' ' in s3_key:
        warnings.append("S3 key contains spaces - consider using underscores")
    
    return {
        'valid': len(errors) == 0,
        'errors': errors,
        'warnings': warnings
    }


def normalize_s3_key(s3_key: str) -> str:
    """
    Normalize an S3 key by fixing common issues.
    
    Args:
        s3_key: The S3 key to normalize
        
    Returns:
        Normalized S3 key
    """
    # Remove leading slash
    if s3_key.startswith('/'):
        s3_key = s3_key[1:]
    
    # Replace spaces with underscores
    s3_key = s3_key.replace(' ', '_')
    
    # Fix double slashes
    while '//' in s3_key:
        s3_key = s3_key.replace('//', '/')
    
    # Remove trailing slash
    s3_key = s3_key.rstrip('/')
    
    return s3_key


def build_s3_url(bucket_name: str, s3_key: str, endpoint_url: Optional[str] = None) -> str:
    """
    Build a complete S3 URL from bucket and key.
    
    Args:
        bucket_name: S3 bucket name
        s3_key: S3 object key
        endpoint_url: Optional custom endpoint URL
        
    Returns:
        Complete S3 URL
    """
    if endpoint_url:
        # Custom endpoint (e.g., MinIO)
        return f"{endpoint_url.rstrip('/')}/{bucket_name}/{s3_key}"
    else:
        # Standard S3
        return f"https://{bucket_name}.s3.amazonaws.com/{s3_key}"


