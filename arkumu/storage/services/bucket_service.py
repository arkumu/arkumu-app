import logging
import os
import time
import threading
from typing import Any, Dict, List
import tempfile
from pathlib import Path

from botocore.exceptions import ClientError
from django.conf import settings
import boto3

from .base_storage_service import BaseStorageService
from .upload_service import UploadService

# Import metadata models for direct access
from arkumu.metadata.models.resource import Resource
from arkumu.metadata.models.triples import Triple

logger = logging.getLogger(__name__)

# List of predefined organizations (can be moved to settings if dynamic)
PREDEFINED_ORGANIZATIONS = [
    "rsh",
    "khm", 
    "fuk",
    "hmt",
    "det",
]

class BucketService:
    """
    Service for managing organization-specific S3 buckets.
    This service is now a singleton to prevent redundant initializations and S3 API calls.
    """
    _instance = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        # Singleton pattern like BaseStorageService
        if not cls._instance:
            with cls._lock:
                if not cls._instance:
                    logger.info("-----> BucketService.__new__: Creating new singleton instance")
                    cls._instance = super().__new__(cls)
                else:
                    logger.info("-----> BucketService.__new__: Instance already existed (another thread created it)")
        else:
            logger.info("-----> BucketService.__new__: Instance already existed")
        return cls._instance

    def __init__(self):
        # Check if this instance has already been initialized
        if hasattr(self, '_bucket_initialized_flag') and self._bucket_initialized_flag:
            logger.info("-----> BucketService.__init__: Already initialized. Skipping setup.")
            return
            
        logger.info("-----> BucketService.__init__ ENTERED")
        # Get the singleton instance of BaseStorageService
        self.base_s3_service = BaseStorageService()
        
        # Initialize cache for bucket existence and directory listings
        from django.core.cache import cache
        self.cache = cache
        
        # Mark as initialized
        self._bucket_initialized_flag = True
        # an instance flag like self._initialized could be used here.
        # For now, assume most of its state comes from BaseStorageService or is per-method.

        # Initialize UploadService here if it's a direct dependency, passing the base_s3_service instance
        # or letting UploadService get it itself. For now, let's assume UploadService gets it.
        # self.upload_service = UploadService() # Example if needed
        
        # Removed the old complex initialization logic that duplicated BaseStorageService concerns.
        logger.info("-----> BucketService.__init__ COMPLETED. Using BaseStorageService for S3 operations.")

    def _get_organization_bucket_name(self, organization_id: str) -> str:
        return organization_id

    def get_organization_bucket(self, organization_id: str) -> str:
        """Public method to get organization bucket name."""
        return self._get_organization_bucket_name(organization_id)

    def get_predefined_organizations(self) -> List[str]:
        """Get the list of predefined organization IDs."""
        return PREDEFINED_ORGANIZATIONS.copy()

    def get_predefined_organizations_data(self) -> List[Dict[str, str]]:
        """Get predefined organizations with additional data like names."""
        org_names = {
            "rsh": "Robert Schumann Hochschule Düsseldorf",
            "khm": "Kunsthochschule für Medien Köln",
            "fuk": "Folkwang Universität der Künste",
            "hmt": "Hochschule für Musik und Tanz Köln",
            "det": "Hochschule für Musik Detmold",
        }
        
        return [
            {
                "id": org_id,
                "slug": org_id,  # For backwards compatibility
                "name": org_names.get(org_id, f"Organization {org_id.capitalize()}")
            }
            for org_id in PREDEFINED_ORGANIZATIONS
        ]

    def ensure_organization_bucket_exists(self, organization_id: str, check_only: bool = False, auto_create: bool = True) -> Dict[str, Any]:
        """
        Ensures an organization-specific bucket exists. 
        Now uses BaseStorageService's ensure_bucket_exists for creation if not check_only.
        If check_only is True, it only checks existence using head_bucket and does not create.
        Uses Redis caching to avoid redundant S3 API calls.
        """
        bucket_name = self._get_organization_bucket_name(organization_id)
        cache_key = f"bucket_exists_{bucket_name}"
        
        # Check cache first (30 minute TTL for bucket existence)
        cached_result = self.cache.get(cache_key)
        if cached_result and check_only:
            logger.info(f"✅ Organization bucket '{bucket_name}' existence cached (skipping S3 call)")
            return {"success": True, "bucket_name": bucket_name, "status": "exists"}
        
        logger.info(f"Ensuring organization bucket: {bucket_name}, check_only={check_only}")
        
        try:
            self.base_s3_service.s3_client.head_bucket(Bucket=bucket_name)
            logger.info(f"✅ Organization bucket '{bucket_name}' already exists.")
            
            # Cache the positive result for 30 minutes
            self.cache.set(cache_key, True, timeout=1800)
            
            return {"success": True, "bucket_name": bucket_name, "status": "exists"}
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', 'Unknown')
            if error_code == '404' or error_code == 'NoSuchBucket':
                logger.info(f"Organization bucket '{bucket_name}' does not exist.")
                if check_only:
                    return {"success": False, "bucket_name": bucket_name, "status": "does_not_exist", "error": "Bucket not found and check_only is True"}
                
                if not auto_create:
                    logger.info(f"Auto-creation disabled for bucket '{bucket_name}'")
                    return {"success": False, "bucket_name": bucket_name, "status": "does_not_exist", "error": "Bucket not found and auto_create is False"}
                
                # Attempt to create using BaseStorageService's method
                logger.info(f"🔄 Auto-creating organization bucket '{bucket_name}' via BaseStorageService...")
                if self.base_s3_service.ensure_bucket_exists(bucket_name):
                    logger.info(f"✅ Organization bucket '{bucket_name}' created successfully.")
                    return {"success": True, "bucket_name": bucket_name, "status": "created"}
                else:
                    logger.error(f"❌ Failed to create organization bucket '{bucket_name}' via BaseStorageService.")
                    return {"success": False, "bucket_name": bucket_name, "status": "creation_failed", "error": "Failed to create bucket"}
            else:
                logger.error(f"❌ Error checking organization bucket '{bucket_name}': {e.response.get('Error', {})}")
                return {"success": False, "bucket_name": bucket_name, "status": "error", "error": str(e.response.get('Error', {}))}

    def get_available_organizations(self, include_counts: bool = False) -> List[Dict[str, Any]]:
        """
        List available organizations by checking their predefined buckets.
        Uses the check_only=True variant of ensure_organization_bucket_exists.
        Optionally includes item counts (can be slow).
        """
        logger.info(f"Getting available organizations. Include counts: {include_counts}")
        
        # Map organization IDs to proper names
        org_names = {
            "rsh": "Robert Schumann Hochschule Düsseldorf",
            "khm": "Kunsthochschule für Medien Köln",
            "fuk": "Folkwang Universität der Künste",
            "hmt": "Hochschule für Musik und Tanz Köln",
            "det": "Hochschule für Musik Detmold",
        }
        
        organizations_data = []
        for org_id in PREDEFINED_ORGANIZATIONS:
            bucket_name = self._get_organization_bucket_name(org_id)
            org_info = {
                "id": org_id,
                "bucket_name": bucket_name,
                "status": "unknown",
                "name": org_names.get(org_id, f"Organization {org_id.capitalize()}"),
                "file_count": 0, # Initialize counts
                "folder_count": 0,
                "total_size_formatted": "0 B"
            }
            
            # Try to ensure bucket exists with auto-creation enabled for better UX
            check_result = self.ensure_organization_bucket_exists(org_id, check_only=False, auto_create=True)
            
            if check_result["success"]: 
                status = check_result.get("status")
                if status == "exists":
                    org_info["status"] = "active"
                elif status == "created":
                    org_info["status"] = "active_auto_created"
                    logger.info(f"✅ Auto-created bucket for organization '{org_id}'")
                else:
                    org_info["status"] = "active"
                
                if include_counts:
                    logger.info(f"Fetching counts for organization '{org_id}' bucket '{bucket_name}'...")
                    items_data = self.get_root_level_items(org_id, bucket_name)
                    org_info.update(items_data) # file_count, folder_count, total_size_formatted
            elif check_result.get("status") == "does_not_exist":
                org_info["status"] = "inactive_bucket_not_found"
            elif check_result.get("status") == "creation_failed":
                org_info["status"] = "error_bucket_creation_failed"
                org_info["error_details"] = check_result.get("error", "Failed to create bucket")
            else: # error or other issues
                org_info["status"] = "error_checking_bucket"
                org_info["error_details"] = check_result.get("error", "Unknown error")

            organizations_data.append(org_info)
        
        logger.info(f"Found {len(organizations_data)} organizations data.")
        return organizations_data

    def get_root_level_items(self, organization_id: str, bucket_name: str = None) -> Dict[str, Any]:
        """
        Get root level items (files and folders) for an organization's bucket.
        Uses BaseStorageService.s3_client for listing objects.
        Auto-creates bucket if it doesn't exist.
        """
        if not bucket_name:
            bucket_name = self._get_organization_bucket_name(organization_id)
        
        logger.info(f"Fetching root level items for bucket: {bucket_name}")
        
        # Ensure bucket exists, auto-create if needed
        bucket_result = self.ensure_organization_bucket_exists(organization_id, check_only=False, auto_create=True)
        if not bucket_result["success"]:
            logger.error(f"Failed to ensure bucket '{bucket_name}' exists: {bucket_result.get('error', 'Unknown error')}")
            return {
                "files": [], 
                "folders": [], 
                "file_count": 0, 
                "folder_count": 0, 
                "total_size": 0,
                "total_size_formatted": "0 B",
                "error": f"Bucket '{bucket_name}' unavailable: {bucket_result.get('error', 'Unknown error')}"
            }
        root_items = {"files": [], "folders": [], "file_count": 0, "folder_count": 0, "total_size": 0}
        
        try:
            logger.info(f"Creating S3 paginator for bucket: {bucket_name}")
            paginator = self.base_s3_service.s3_client.get_paginator('list_objects_v2')
            logger.info(f"Starting pagination for bucket: {bucket_name}")
            page_count = 0
            try:
                for page in paginator.paginate(Bucket=bucket_name, Delimiter='/', PaginationConfig={'MaxItems': 100}):
                    page_count += 1
                    logger.info(f"Processing page {page_count} for bucket: {bucket_name}")
                    # Add folders (CommonPrefixes)
                    for prefix in page.get('CommonPrefixes', []):
                        folder_name = prefix.get('Prefix')
                        root_items["folders"].append({"name": folder_name, "path": folder_name})
                        root_items["folder_count"] += 1
                    
                    # Add files (Contents)
                    for obj in page.get('Contents', []):
                        if not obj['Key'].endswith('/'): # Ensure it's not a folder object
                            file_size = obj.get('Size', 0)
                            root_items["files"].append({
                                "name": os.path.basename(obj['Key']),
                                "path": obj['Key'],
                                "size": file_size,
                                "size_formatted": self.base_s3_service._format_size(file_size),
                                "last_modified": obj.get('LastModified')
                            })
                            root_items["file_count"] += 1
                            root_items["total_size"] += file_size
            except Exception as pagination_error:
                logger.error(f"Pagination error for bucket {bucket_name}: {pagination_error}")
                root_items["error"] = f"Pagination failed: {str(pagination_error)}"
                return root_items
            
            root_items["total_size_formatted"] = self.base_s3_service._format_size(root_items["total_size"])
            logger.info(f"Found {root_items['file_count']} files and {root_items['folder_count']} folders in {bucket_name}.")

        except ClientError as e:
            logger.error(f"Error listing root items for bucket {bucket_name}: {e.response.get('Error', {})}")
            # Return empty/zeroed data but log the error
            root_items["error"] = str(e.response.get('Error', {}))
        
        return root_items
    
    # Add other BucketService specific methods here, using self.base_s3_service for S3 ops.
    # For example, methods to manage files within an organization's bucket, etc.

    def delete_organization_bucket_and_contents(self, organization_id: str) -> Dict[str, Any]:
        """Deletes all objects within an organization's bucket and then the bucket itself."""
        bucket_name = self._get_organization_bucket_name(organization_id)
        logger.info(f"Attempting to delete all contents and bucket for organization: {organization_id}, bucket: {bucket_name}")

        # First, delete all objects in the bucket using BaseStorageService
        # The delete_object method in BaseStorageService can handle directory deletion.
        # We list all objects and delete them. A more robust way would be to use list_objects_v2 and DeleteObjects.
        # For simplicity, let's assume BaseStorageService might need a more direct "empty_bucket" or we iterate here.
        
        # Iteratively delete objects (safer for services without direct batch delete)
        try:
            logger.info(f"Listing all objects in bucket {bucket_name} for deletion...")
            paginator = self.base_s3_service.s3_client.get_paginator('list_objects_v2')
            objects_to_delete = []
            for page in paginator.paginate(Bucket=bucket_name):
                if 'Contents' in page:
                    for obj in page['Contents']:
                        objects_to_delete.append({'Key': obj['Key']})
            
            if objects_to_delete:
                logger.info(f"Found {len(objects_to_delete)} objects to delete from {bucket_name}.")
                # S3 DeleteObjects can handle up to 1000 keys at a time
                for i in range(0, len(objects_to_delete), 1000):
                    chunk = objects_to_delete[i:i + 1000]
                    delete_payload = {'Objects': chunk}
                    response = self.base_s3_service.s3_client.delete_objects(
                        Bucket=bucket_name,
                        Delete=delete_payload
                    )
                    deleted_count = len(response.get('Deleted', []))
                    logger.info(f"Batch delete: {deleted_count} objects deleted from {bucket_name}.")
                    errors = response.get('Errors', [])
                    if errors:
                        logger.error(f"Errors during batch delete from {bucket_name}: {errors}")
                        return {"success": False, "error": f"Errors deleting objects: {errors}"}
            else:
                logger.info(f"Bucket {bucket_name} is already empty.")

            # After emptying, delete the bucket itself
            logger.info(f"Attempting to delete bucket: {bucket_name}")
            self.base_s3_service.s3_client.delete_bucket(Bucket=bucket_name)
            logger.info(f"✅ Successfully deleted bucket {bucket_name}.")
            return {"success": True, "message": f"Bucket {bucket_name} and all its contents deleted."}

        except ClientError as e:
            logger.error(f"Error during deletion of bucket {bucket_name} or its contents: {e.response.get('Error', {})}")
            return {"success": False, "error": str(e.response.get('Error', {}))}
        except Exception as e:
            logger.error(f"Unexpected error during deletion of bucket {bucket_name}: {str(e)}")
            return {"success": False, "error": str(e)}

    def list_bucket_contents(self, bucket_name: str, prefix: str = "", skip_bucket_check: bool = True) -> List[Dict[str, Any]]:
        """List contents of a bucket with optional prefix. Uses Redis caching to avoid redundant S3 API calls."""
        cache_key = f"bucket_contents_{bucket_name}_{prefix.replace('/', '_')}"
        
        # Check cache first (5 minute TTL for directory listings)
        cached_contents = self.cache.get(cache_key)
        if cached_contents is not None:
            logger.info(f"📋 Found {len(cached_contents)} cached items for {bucket_name} prefix '{prefix}' (skipping S3 call)")
            return cached_contents
        
        # Skip bucket existence check for read operations (performance optimization)
        if not skip_bucket_check:
            bucket_exists = self.cache.get(f"bucket_exists_{bucket_name}")
            if not bucket_exists:
                logger.info(f"Verifying bucket {bucket_name} exists before listing")
                # This will cache the result if successful
                result = self.ensure_organization_bucket_exists(bucket_name.replace('arkumu-', ''), check_only=True)
                if not result["success"]:
                    return []
        
        start_time = time.time()
        logger.info(f"⏱️ S3 LIST START: Listing contents for bucket: {bucket_name}, prefix: {prefix} at {start_time}")
        logger.info(f"🔑 Using cache key: {cache_key}")
        contents = []
        
        try:
            paginator = self.base_s3_service.s3_client.get_paginator('list_objects_v2')
            logger.info(f"⏱️ S3 PAGINATOR: Created paginator at {time.time()}")
            for page in paginator.paginate(Bucket=bucket_name, Prefix=prefix, Delimiter='/'):
                # Add folders (CommonPrefixes)
                for prefix_info in page.get('CommonPrefixes', []):
                    folder_name = prefix_info.get('Prefix')
                    contents.append({
                        "name": os.path.basename(folder_name.rstrip('/')),
                        "path": folder_name,
                        "type": "folder",
                        "size": 0,
                        "size_formatted": "0 B",
                        "last_modified": None
                    })
                
                # Add files (Contents)
                for obj in page.get('Contents', []):
                    if not obj['Key'].endswith('/') and obj['Key'] != prefix:  # Ensure it's not a folder object or the prefix itself
                        file_size = obj.get('Size', 0)
                        contents.append({
                            "name": os.path.basename(obj['Key']),
                            "path": obj['Key'],
                            "type": "file",
                            "size": file_size,
                            "size_formatted": self.base_s3_service._format_size(file_size),
                            "last_modified": obj.get('LastModified')
                        })
            
            end_time = time.time()
            logger.info(f"⏱️ S3 LIST COMPLETE: Found {len(contents)} items in {bucket_name} with prefix '{prefix}' at {end_time}")
            if contents:
                logger.info(f"📁 Items found: {[item.get('name', 'unnamed') + ' (' + item.get('type', 'unknown') + ')' for item in contents[:5]]}")  # Show first 5 items
            
            # Cache the results for 5 minutes (300 seconds)
            logger.info(f"⏱️ CACHE SET: Caching {len(contents)} items with key {cache_key}")
            self.cache.set(cache_key, contents, timeout=300)
            
            return contents

        except ClientError as e:
            logger.error(f"Error listing contents for bucket {bucket_name}: {e.response.get('Error', {})}")
            return []

    def get_file_content(self, bucket_name: str, file_path: str) -> Dict[str, Any]:
        """Get file content using BaseStorageService."""
        return self.base_s3_service.get_file_content(bucket_name, file_path)

    def delete_folder(self, bucket_name: str, folder_path: str) -> Dict[str, Any]:
        """Delete a folder and all its contents."""
        # Ensure folder path ends with /
        if not folder_path.endswith('/'):
            folder_path += '/'
        
        return self.base_s3_service.delete_object(bucket_name, folder_path, is_directory=True)

    def delete_file(self, bucket_name: str, file_path: str) -> Dict[str, Any]:
        """Delete a single file."""
        return self.base_s3_service.delete_object(bucket_name, file_path, is_directory=False)

