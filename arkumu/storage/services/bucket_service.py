import logging
import os
import time
import threading
from datetime import datetime
from typing import Any, Dict, List
import tempfile
from pathlib import Path
import csv
import io

from botocore.exceptions import ClientError
from django.conf import settings
import boto3

from .base_storage_service import BaseStorageService
from .upload_service import UploadService

# Import metadata models for direct access
from arkumu.metadata.models.resource import Resource
from arkumu.metadata.models.triples import Triple
from arkumu.storage.models import S3FileObject
from django.db.models import Q

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
            
            # Skip CORS check for Dell EMC (already configured via AWS CLI)
            if not check_only and self.base_s3_service.is_minio:
                logger.info(f"🔧 Checking CORS for existing bucket '{bucket_name}'...")
                cors_result = self.base_s3_service.ensure_cors_enabled(bucket_name)
                if cors_result.get("success"):
                    if cors_result.get("updated"):
                        logger.info(f"✅ CORS updated for bucket '{bucket_name}': {cors_result.get('message')}")
                    else:
                        logger.debug(f"✅ CORS already configured for bucket '{bucket_name}'")
                else:
                    logger.warning(f"⚠️ CORS check failed for bucket '{bucket_name}': {cors_result.get('error')}")
            
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
                    
                    # Only set up CORS for MinIO (Dell EMC CORS is managed via AWS CLI)
                    if self.base_s3_service.is_minio:
                        logger.info(f"🔧 Setting up CORS for organization bucket '{bucket_name}'...")
                        cors_result = self.base_s3_service.ensure_cors_enabled(bucket_name)
                        if cors_result.get("success"):
                            logger.info(f"✅ CORS configured for bucket '{bucket_name}': {cors_result.get('message')}")
                        else:
                            logger.warning(f"⚠️ CORS setup failed for bucket '{bucket_name}': {cors_result.get('error')}")
                    
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

    def _normalize_prefix_for_s3(self, prefix: str) -> str:
        """Normalize a folder prefix for S3 listing calls.
        - Remove leading '/'
        - Ensure trailing '/' if non-empty
        """
        if not prefix:
            return ""
        p = str(prefix).strip().lstrip('/')
        if p and not p.endswith('/'):
            p += '/'
        return p

    def _cache_key(self, base: str, bucket_name: str, prefix: str) -> str:
        """Build a consistent cache key for listings/counts.
        Always ends with a single underscore to match invalidation patterns.
        """
        norm = self._normalize_prefix_for_s3(prefix)
        slug = norm.rstrip('/').replace('/', '_')
        # Root listing -> trailing underscore after bucket name
        return f"{base}_{bucket_name}_{slug}_" if slug else f"{base}_{bucket_name}_"

    def list_bucket_contents(self, bucket_name: str, prefix: str = "", skip_bucket_check: bool = True, force_fresh: bool = False) -> List[Dict[str, Any]]:
        """List contents of a bucket with optional prefix. Uses Redis caching to avoid redundant S3 API calls."""
        cache_key = self._cache_key("bucket_contents", bucket_name, prefix)
        s3_prefix = self._normalize_prefix_for_s3(prefix)
        
        # Check cache first (5 minute TTL for directory listings) unless force_fresh is True
        if not force_fresh:
            cached_contents = self.cache.get(cache_key)
            if cached_contents is not None:
                logger.info(f"📋 Found {len(cached_contents)} cached items for {bucket_name} prefix '{s3_prefix}' (skipping S3 call)")
                return cached_contents
        else:
            logger.info(f"📋 Force fresh listing for {bucket_name} prefix '{s3_prefix}' (cache bypassed)")
        
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
        logger.info(f"⏱️ S3 LIST START: Listing contents for bucket: {bucket_name}, prefix: {s3_prefix} at {datetime.now().strftime('%H:%M:%S.%f')[:-3]}")
        logger.info(f"🔑 Using cache key: {cache_key}")
        contents = []
        
        try:
            paginator = self.base_s3_service.s3_client.get_paginator('list_objects_v2')
            logger.info(f"⏱️ S3 PAGINATOR: Created paginator at {datetime.now().strftime('%H:%M:%S.%f')[:-3]}")
            for page in paginator.paginate(Bucket=bucket_name, Prefix=s3_prefix, Delimiter='/'):
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
                    if not obj['Key'].endswith('/') and obj['Key'] != s3_prefix:  # Ensure it's not a folder object or the prefix itself
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
            logger.info(f"⏱️ S3 LIST COMPLETE: Found {len(contents)} items in {bucket_name} with prefix '{s3_prefix}' at {datetime.now().strftime('%H:%M:%S.%f')[:-3]}")
            if contents:
                logger.info(f"📁 Items found: {[item.get('name', 'unnamed') + ' (' + item.get('type', 'unknown') + ')' for item in contents[:5]]}")  # Show first 5 items
            
            # Sort contents naturally to preserve filesystem folder order (1, 2, 10, 11 instead of 1, 10, 11, 2)
            # Folders first, then files, both sorted naturally
            import re
            
            def natural_sort_key(item):
                """Natural sorting key that handles numbers in strings correctly."""
                name = item.get('name', '')
                # Split name into parts: text and numbers
                parts = re.split(r'(\d+)', name.lower())
                # Convert numeric parts to integers for proper sorting
                return [int(part) if part.isdigit() else part for part in parts]
            
            # Separate folders and files, then sort each group naturally
            folders = [item for item in contents if item.get('type') == 'folder']
            files = [item for item in contents if item.get('type') == 'file']
            
            folders.sort(key=natural_sort_key)
            files.sort(key=natural_sort_key)
            
            # Combine: folders first, then files (maintains filesystem convention)
            contents = folders + files
            
            # Cache the results for 5 minutes (300 seconds)
            logger.info(f"⏱️ CACHE SET: Caching {len(contents)} items with key {cache_key}")
            self.cache.set(cache_key, contents, timeout=300)
            
            return contents

        except ClientError as e:
            logger.error(f"Error listing contents for bucket {bucket_name}: {e.response.get('Error', {})}")
            return []

    def count_files_in_folder(self, bucket_name: str, folder_prefix: str, force_fresh: bool = False) -> int:
        """Count total number of files recursively in a folder."""
        cache_key = self._cache_key("file_count", bucket_name, folder_prefix)
        s3_prefix = self._normalize_prefix_for_s3(folder_prefix)
        
        # Check cache first (10 minute TTL for file counts) unless force_fresh is True
        if not force_fresh:
            cached_count = self.cache.get(cache_key)
            if cached_count is not None:
                logger.info(f"📊 Found cached file count for {folder_prefix}: {cached_count}")
                return cached_count
        else:
            logger.info(f"📊 Force fresh count for {s3_prefix} (cache bypassed)")
        
        try:
            paginator = self.base_s3_service.s3_client.get_paginator('list_objects_v2')
            file_count = 0
            
            for page in paginator.paginate(Bucket=bucket_name, Prefix=s3_prefix):
                for obj in page.get('Contents', []):
                    # Only count actual files, not folder markers
                    if not obj['Key'].endswith('/'):
                        file_count += 1
            
            # Cache the result for 10 minutes (600 seconds)
            self.cache.set(cache_key, file_count, timeout=600)
            logger.info(f"📊 Counted {file_count} files in {s3_prefix}")
            return file_count
            
        except ClientError as e:
            logger.error(f"Error counting files in {folder_prefix}: {e.response.get('Error', {})}")
            return 0

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

    def export_successful_imports_csv(self, organization_id: str) -> Dict[str, Any]:
        """
        Build a CSV export using S3FileObject records with S3 existence verification.
        This provides fast access to files with rich metadata and checksums.

        Columns:
        - file_name
        - folder_name (derived from S3 key path)
        - file_size_bytes
        - file_size_human
        - s3_key
        - checksum_sha256 (from DB or calculated on-demand)
        - upload_session
        - created_at
        - status

        Returns a dict with:
        - success: bool
        - filename: suggested filename
        - content: CSV bytes (utf-8)
        - count: number of rows exported
        - error: optional error message
        """
        try:
            from arkumu.storage.models.s3_file_objects import S3FileObject
            
            bucket_name = self.get_organization_bucket(organization_id)

            # Ensure bucket exists (check only)
            ensure = self.ensure_organization_bucket_exists(organization_id, check_only=True)
            if not ensure.get("success"):
                return {"success": False, "error": ensure.get("error", "Bucket not accessible")}

            logger.info(f"📊 DB EXPORT: Starting export for organization '{organization_id}' using S3FileObject records")

            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow([
                "file_name",
                "folder_name", 
                "file_size_bytes",
                "file_size_human",
                "s3_key",
                "checksum_sha256",
                "upload_session",
                "created_at",
                "status"
            ])

            count = 0
            total_size = 0
            verified_count = 0
            missing_count = 0
            
            # Query S3FileObject records for this organization
            # We need to find files that match the organization bucket
            logger.info(f"📋 DB QUERY: Getting S3FileObject records for organization '{organization_id}'")
            
            # Query files that are completed and have the organization bucket
            file_objects = S3FileObject.objects.filter(
                status__in=['completed', 'verified']
            ).select_related('session').order_by('created_at')
            
            # Filter by organization - we need to match against the session or infer from s3_key
            org_file_objects = []
            for file_obj in file_objects:
                # Check if file belongs to this organization
                if (hasattr(file_obj.session, 'organization') and 
                    file_obj.session.organization == organization_id):
                    org_file_objects.append(file_obj)
                elif file_obj.s3_key.startswith(f"{organization_id}/") or bucket_name in file_obj.s3_key:
                    org_file_objects.append(file_obj)
            
            logger.info(f"📋 FOUND: {len(org_file_objects)} S3FileObject records for organization '{organization_id}'")
            
            for file_obj in org_file_objects:
                # Verify file exists in S3
                exists = file_obj.exists_in_s3(self.base_s3_service)
                if not exists:
                    missing_count += 1
                    logger.warning(f"⚠️ File missing from S3: {file_obj.s3_key}")
                    continue
                    
                verified_count += 1
                
                # Extract file name and folder from S3 key
                file_name = file_obj.file_name or os.path.basename(file_obj.s3_key)
                folder_parts = file_obj.s3_key.split('/')
                folder_name = '/'.join(folder_parts[:-1]) if len(folder_parts) > 1 else ""
                
                # Use stored checksum or calculate on-demand
                checksum_algorithm, checksum_value = file_obj.get_checksum()
                if not checksum_value:
                    logger.info(
                        "📊 CHECKSUM: Calculating checksum for %s (%s)...",
                        file_name,
                        self.base_s3_service._format_size(file_obj.file_size_bytes),
                    )
                    checksum_value = file_obj.calculate_checksum(self.base_s3_service)
                    checksum_algorithm, checksum_value = file_obj.get_checksum()
                    if checksum_value:
                        logger.info(
                            "✅ CHECKSUM: %s for %s: %s...",
                            checksum_algorithm or 'sha256',
                            file_name,
                            checksum_value[:16],
                        )
                
                try:
                    # Write CSV row with database information
                    writer.writerow([
                        file_name,
                        folder_name,
                        file_obj.file_size_bytes,
                        self.base_s3_service._format_size(file_obj.file_size_bytes),
                        file_obj.s3_key,
                        checksum_value or "",
                        str(file_obj.session.id) if file_obj.session else "",
                        file_obj.created_at.strftime("%Y-%m-%d %H:%M:%S"),
                        file_obj.status
                    ])
                    count += 1
                    total_size += file_obj.file_size_bytes
                    
                    # Log progress every 10 files for better visibility
                    if count % 10 == 0:
                        logger.info(f"📊 PROGRESS: Processed {count}/{len(org_file_objects)} files, total size: {self.base_s3_service._format_size(total_size)}")

                except Exception as e:
                    logger.error(f"❌ Error processing file {file_obj.s3_key}: {e}")
                    continue

            csv_bytes = output.getvalue().encode("utf-8")
            output.close()

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"s3_export_{organization_id}_{timestamp}.csv"

            logger.info(f"✅ DB EXPORT: Export completed - {count} verified files out of {len(org_file_objects)} DB records")
            if missing_count > 0:
                logger.warning(f"⚠️ {missing_count} files found in DB but missing from S3")

            return {
                "success": True,
                "filename": filename,
                "content": csv_bytes,
                "count": count,
                "total_size": total_size,
            }

        except Exception as e:
            logger.exception("Failed to export S3 bucket scan CSV")
            return {"success": False, "error": str(e)}

    def _calculate_file_checksum(self, bucket_name: str, s3_key: str, *, algorithm: str = 'sha256', max_file_size: int = 50 * 1024 * 1024) -> str:
        """
        Calculate a checksum for a file in S3 by downloading and hashing it.
        
        Args:
            bucket_name: Name of the S3 bucket
            s3_key: S3 key of the file
            max_file_size: Maximum file size to process (default 50MB)
            
        Returns:
            str: Checksum in hexadecimal format, or empty string if calculation fails
        """
        try:
            import hashlib
            
            # Check file size first to avoid downloading huge files
            try:
                head_response = self.base_s3_service.s3_client.head_object(
                    Bucket=bucket_name,
                    Key=s3_key
                )
                file_size = head_response.get('ContentLength', 0)
                
                if file_size > max_file_size:
                    logger.warning(f"🚫 CHECKSUM: File {s3_key} too large ({self.base_s3_service._format_size(file_size)}), skipping checksum calculation")
                    return ""
                    
            except Exception as size_error:
                logger.debug(f"Could not determine file size for {s3_key}: {size_error}")
                return ""
            
            try:
                hasher = hashlib.new(algorithm)
            except ValueError:
                logger.error("Unsupported checksum algorithm %s", algorithm)
                return ""
            
            # Stream the file to avoid loading large files into memory
            try:
                response = self.base_s3_service.s3_client.get_object(
                    Bucket=bucket_name,
                    Key=s3_key
                )
                
                # Read in chunks to manage memory usage
                chunk_size = 8192  # 8KB chunks
                for chunk in iter(lambda: response['Body'].read(chunk_size), b''):
                    hasher.update(chunk)

                return hasher.hexdigest()
                
            except Exception as download_error:
                logger.debug(f"Failed to download file {s3_key} for checksum calculation: {download_error}")
                return ""
                
        except Exception as e:
            logger.debug(f"Failed to calculate checksum for {s3_key}: {e}")
            return ""

    def stream_file_with_range(self, bucket_name: str, file_path: str, range_header: str = None) -> Dict[str, Any]:
        """
        Stream file content with support for HTTP range requests.
        Essential for video streaming - enables seeking, progressive download, and efficient bandwidth usage.
        
        Args:
            bucket_name: Name of the S3 bucket
            file_path: Path to the file within the bucket
            range_header: HTTP Range header value (e.g., "bytes=0-1023")
            
        Returns:
            Dict containing:
                - success: bool
                - content: bytes (file content for the requested range)
                - content_type: str (MIME type)
                - content_length: int (total file size)
                - content_range: str (range info for response header)
                - status_code: int (206 for partial content, 200 for full content)
                - accept_ranges: str ("bytes")
        """
        try:
            # First, get file metadata to determine total size
            try:
                head_response = self.base_s3_service.s3_client.head_object(
                    Bucket=bucket_name,
                    Key=file_path
                )
                total_size = head_response['ContentLength']
                content_type = head_response.get('ContentType', 'application/octet-stream')
                last_modified = head_response.get('LastModified')
                etag = head_response.get('ETag', '').strip('"')
                
            except ClientError as e:
                logger.error(f"Error getting file metadata for {file_path}: {e}")
                return {
                    "success": False,
                    "error": f"File not found or inaccessible: {str(e)}"
                }
            
            # Parse range header if provided
            start_byte = 0
            end_byte = total_size - 1
            status_code = 200
            
            if range_header:
                try:
                    # Parse "bytes=start-end" format
                    range_match = range_header.replace('bytes=', '').strip()
                    if '-' in range_match:
                        parts = range_match.split('-', 1)
                        if parts[0]:  # start specified
                            start_byte = int(parts[0])
                        if parts[1]:  # end specified
                            end_byte = int(parts[1])
                        else:
                            # If no end specified, serve from start to end of file
                            end_byte = total_size - 1
                    
                    # Validate range
                    if start_byte >= total_size:
                        return {
                            "success": False,
                            "error": "Range start exceeds file size",
                            "status_code": 416  # Range Not Satisfiable
                        }
                    
                    # Ensure end doesn't exceed file size
                    end_byte = min(end_byte, total_size - 1)
                    status_code = 206  # Partial Content
                    
                    logger.info(f"📹 Range request for {file_path}: bytes {start_byte}-{end_byte}/{total_size}")
                    
                except (ValueError, IndexError) as e:
                    logger.warning(f"Invalid range header '{range_header}': {e}. Serving full file.")
                    range_header = None  # Fall back to full file
            
            # Build S3 get_object parameters
            get_params = {
                'Bucket': bucket_name,
                'Key': file_path
            }
            
            # Add range to S3 request if specified
            if range_header and status_code == 206:
                get_params['Range'] = f'bytes={start_byte}-{end_byte}'
            
            # Get the file content from S3
            try:
                response = self.base_s3_service.s3_client.get_object(**get_params)
                content = response['Body'].read()
                
                # Build response data
                result = {
                    "success": True,
                    "content": content,
                    "content_type": content_type,
                    "content_length": total_size,
                    "status_code": status_code,
                    "accept_ranges": "bytes",
                    "last_modified": last_modified,
                    "etag": etag
                }
                
                # Add range-specific headers for partial content
                if status_code == 206:
                    actual_content_length = len(content)
                    result["content_range"] = f"bytes {start_byte}-{start_byte + actual_content_length - 1}/{total_size}"
                    result["partial_content_length"] = actual_content_length
                    logger.info(f"📹 Served partial content: {actual_content_length} bytes ({start_byte}-{start_byte + actual_content_length - 1}/{total_size})")
                else:
                    logger.info(f"📹 Served full content: {total_size} bytes")
                
                return result
                
            except ClientError as e:
                logger.error(f"Error retrieving file content for {file_path}: {e}")
                return {
                    "success": False,
                    "error": f"Failed to retrieve file content: {str(e)}"
                }
                
        except Exception as e:
            logger.exception(f"Unexpected error in stream_file_with_range for {file_path}")
            return {
                "success": False,
                "error": f"Unexpected error: {str(e)}"
            }

    def get_bucket_total_size(self, bucket_name: str, force_fresh: bool = False) -> Dict[str, Any]:
        """
        Calculate the total size of all objects in a bucket.
        Uses Redis caching to avoid expensive S3 API calls (30 minute TTL).
        
        Args:
            bucket_name: Name of the S3 bucket
            force_fresh: If True, bypass cache and recalculate
            
        Returns:
            Dict containing:
                - success: bool
                - total_size: int (bytes)
                - total_size_formatted: str (human readable)
                - object_count: int (total number of objects)
                - error: str (if success is False)
        """
        cache_key = f"bucket_total_size_{bucket_name}"
        
        # Check cache first (30 minute TTL) unless force_fresh is True
        if not force_fresh:
            cached_result = self.cache.get(cache_key)
            if cached_result is not None:
                logger.info(f"📊 Found cached bucket size for {bucket_name}: {cached_result.get('total_size_formatted', '0 B')}")
                return cached_result
        else:
            logger.info(f"📊 Force fresh calculation for bucket {bucket_name} (cache bypassed)")
        
        start_time = time.time()
        logger.info(f"📊 BUCKET SIZE CALCULATION START: {bucket_name} at {datetime.now().strftime('%H:%M:%S.%f')[:-3]}")
        
        total_size = 0
        object_count = 0
        
        try:
            # Use paginator to handle large buckets efficiently
            paginator = self.base_s3_service.s3_client.get_paginator('list_objects_v2')
            
            for page_num, page in enumerate(paginator.paginate(Bucket=bucket_name), 1):
                page_objects = page.get('Contents', [])
                page_size = sum(obj.get('Size', 0) for obj in page_objects)
                page_count = len(page_objects)
                
                total_size += page_size
                object_count += page_count
                
                # Log progress for large buckets
                if page_num % 10 == 0:
                    logger.info(f"📊 Processed {page_num} pages, current total: {self.base_s3_service._format_size(total_size)}, objects: {object_count}")
            
            end_time = time.time()
            calculation_duration = end_time - start_time
            
            result = {
                "success": True,
                "total_size": total_size,
                "total_size_formatted": self.base_s3_service._format_size(total_size),
                "object_count": object_count,
                "calculation_duration": calculation_duration
            }
            
            # Cache the results for 30 minutes (1800 seconds)
            logger.info(f"📊 BUCKET SIZE COMPLETE: {bucket_name} = {result['total_size_formatted']} ({object_count} objects) in {calculation_duration:.3f}s")
            self.cache.set(cache_key, result, timeout=1800)
            
            return result
            
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', 'Unknown')
            logger.error(f"❌ Error calculating bucket size for {bucket_name}: {error_code}")
            return {
                "success": False,
                "error": f"S3 error: {error_code}",
                "total_size": 0,
                "total_size_formatted": "0 B",
                "object_count": 0
            }
        except Exception as e:
            logger.exception(f"❌ Unexpected error calculating bucket size for {bucket_name}")
            return {
                "success": False,
                "error": f"Unexpected error: {str(e)}",
                "total_size": 0,
                "total_size_formatted": "0 B", 
                "object_count": 0
            }

    def get_organization_bucket_size(self, organization_id: str, force_fresh: bool = False) -> Dict[str, Any]:
        """
        Calculate the total size of an organization's bucket.
        Convenience wrapper around get_bucket_total_size.
        
        Args:
            organization_id: Organization ID (e.g., 'fuk', 'khm', 'det', etc.)
            force_fresh: If True, bypass cache and recalculate
            
        Returns:
            Dict containing size information and organization details
        """
        bucket_name = self._get_organization_bucket_name(organization_id)
        logger.info(f"📊 Calculating size for organization '{organization_id}' bucket '{bucket_name}'")
        
        # Ensure bucket exists before calculating size
        bucket_result = self.ensure_organization_bucket_exists(organization_id, check_only=True)
        if not bucket_result["success"]:
            logger.error(f"Cannot calculate size - bucket '{bucket_name}' not accessible: {bucket_result.get('error', 'Unknown error')}")
            return {
                "success": False,
                "organization_id": organization_id,
                "bucket_name": bucket_name,
                "error": f"Bucket '{bucket_name}' not accessible: {bucket_result.get('error', 'Unknown error')}",
                "total_size": 0,
                "total_size_formatted": "0 B",
                "object_count": 0
            }
        
        # Get bucket size
        size_result = self.get_bucket_total_size(bucket_name, force_fresh)
        
        # Add organization context
        size_result.update({
            "organization_id": organization_id,
            "bucket_name": bucket_name
        })
        
        return size_result
