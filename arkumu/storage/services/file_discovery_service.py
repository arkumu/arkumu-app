import os
import logging
import json
from pathlib import Path
from typing import List, Dict, Union, Optional, Set, Any
from botocore.exceptions import ClientError
import urllib3.exceptions

from django.conf import settings
from .base_storage_service import BaseStorageService

logger = logging.getLogger(__name__)

class FileDiscoveryService(BaseStorageService):
    """
    Service for discovering files in directory structures.
    
    This service handles finding files based on patterns and crawling directory
    structures to identify resources.
    """
    
    _instance = None
    
    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super(FileDiscoveryService, cls).__new__(cls)
        return cls._instance
    
    def __init__(self, skip_bucket_check=False):
        if hasattr(self, 'initialized'):
            return
        super().__init__(skip_bucket_check=skip_bucket_check)
        
        # Load path structure configuration from settings
        self.path_structure = self._load_path_structure()
        
        logger.info("FileDiscoveryService initialized with configured path patterns")
        self.initialized = True
    
    def _safe_head_object(self, bucket_name: str, s3_key: str) -> Dict[str, Any]:
        """
        Safely perform head_object call with fallback for MinIO header parsing issues.
        
        Args:
            bucket_name: S3 bucket name
            s3_key: S3 object key
            
        Returns:
            Dictionary with object metadata or None if failed
        """
        try:
            return self.s3_client.head_object(
                Bucket=bucket_name,
                Key=s3_key
            )
        except urllib3.exceptions.HeaderParsingError as e:
            logger.warning(f"MinIO header parsing error for {s3_key}: {e}")
            # For empty files, MinIO sometimes has header parsing issues
            # Try to get object info via list_objects_v2 as fallback
            try:
                response = self.s3_client.list_objects_v2(
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
                        'ContentType': 'application/octet-stream',
                        'Metadata': {}
                    }
                else:
                    logger.error(f"Object {s3_key} not found in fallback list_objects_v2")
                    return None
            except ClientError as fallback_e:
                logger.error(f"Fallback list_objects_v2 also failed for {s3_key}: {fallback_e}")
                return None
        except ClientError as e:
            # Let ClientError bubble up as it's expected for 404s, etc.
            raise e
    
    def _load_path_structure(self) -> Dict[str, Any]:
        """
        Load path structure configuration from settings.
        
        This method loads individual path pattern settings from Django settings and
        constructs derived paths to avoid duplication.
        
        Returns:
            Dictionary containing path structure configuration
        """
        path_structure = {}
        
        # Get base path patterns directly from settings with no defaults
        collection_path_pattern = getattr(settings, 'COLLECTION_PATH_PATTERN')
        path_structure['collection_path_pattern'] = collection_path_pattern
        
        bundle_path_pattern = getattr(settings, 'BUNDLE_PATH_PATTERN')
        path_structure['bundle_path_pattern'] = bundle_path_pattern
        
        # Resource path pattern - can be derived from bundle path or set explicitly
        resource_path_pattern = getattr(settings, 'RESOURCE_PATH_PATTERN', None)
        if resource_path_pattern is None:
            # Default derived from bundle path
            resource_path_pattern = bundle_path_pattern + '/v1/content/Resources/{resource_filename}'
        path_structure['resource_path_pattern'] = resource_path_pattern
        
        # XML file paths - can be derived from base patterns or set explicitly
        collection_xml_path = getattr(settings, 'COLLECTION_XML_PATH', None)
        if collection_xml_path is None:
            # Default derived from collection path
            collection_xml_path = collection_path_pattern + '/v1/content/{collection_id}.xml'
        path_structure['collection_xml_path'] = collection_xml_path
        
        bundle_xml_path = getattr(settings, 'BUNDLE_XML_PATH', None)
        if bundle_xml_path is None:
            # Default derived from bundle path
            bundle_xml_path = bundle_path_pattern + '/v1/content/{bundle_id}.xml'
        path_structure['bundle_xml_path'] = bundle_xml_path
        
        # Log the loaded configuration
        logger.info(f"Loaded path patterns: collection={collection_path_pattern}, bundle={bundle_path_pattern}")
        logger.info(f"Derived paths: collection_xml={collection_xml_path}, bundle_xml={bundle_xml_path}")
        
        return path_structure
    
    def get_collection_path_pattern(self) -> str:
        """Get the configured collection path pattern"""
        return self.path_structure.get('collection_path_pattern')
    
    def get_bundle_path_pattern(self) -> str:
        """Get the configured bundle path pattern"""
        return self.path_structure.get('bundle_path_pattern')
    
    def get_resource_path_pattern(self) -> str:
        """Get the configured resource path pattern"""
        return self.path_structure.get('resource_path_pattern')
    
    def get_collection_xml_path(self) -> str:
        """Get the configured collection XML path pattern"""
        return self.path_structure.get('collection_xml_path')
    
    def get_bundle_xml_path(self) -> str:
        """Get the configured bundle XML path pattern"""
        return self.path_structure.get('bundle_xml_path')
    
    def form_collection_path(self, collection_id: Union[str, int]) -> str:
        """
        Form an S3 path for a collection based on the configured pattern.
        
        Args:
            collection_id: Collection ID to use in the path
            
        Returns:
            Formatted S3 path for the collection
        """
        pattern = self.get_collection_path_pattern()
        return pattern.format(collection_id=collection_id)
    
    def form_bundle_path(self, collection_id: Union[str, int], bundle_id: Union[str, int]) -> str:
        """
        Form an S3 path for a bundle based on the configured pattern.
        
        Args:
            collection_id: Collection ID to use in the path
            bundle_id: Bundle ID to use in the path
            
        Returns:
            Formatted S3 path for the bundle
        """
        pattern = self.get_bundle_path_pattern()
        return pattern.format(collection_id=collection_id, bundle_id=bundle_id)
    
    def form_resource_path(self, collection_id: Union[str, int], bundle_id: Union[str, int], 
                          resource_filename: str) -> str:
        """
        Form an S3 path for a resource based on the configured pattern.
        
        Args:
            collection_id: Collection ID to use in the path
            bundle_id: Bundle ID to use in the path
            resource_filename: Filename of the resource
            
        Returns:
            Formatted S3 path for the resource
        """
        pattern = self.get_resource_path_pattern()
        return pattern.format(
            collection_id=collection_id,
            bundle_id=bundle_id,
            resource_filename=resource_filename
        )
    
    def form_collection_xml_path(self, collection_id: Union[str, int]) -> str:
        """
        Form the path to a collection's XML file based on the configured pattern.
        
        Args:
            collection_id: Collection ID to use in the path
            
        Returns:
            Formatted path for the collection XML file
        """
        pattern = self.get_collection_xml_path()
        return pattern.format(collection_id=collection_id)
    
    def form_bundle_xml_path(self, collection_id: Union[str, int], bundle_id: Union[str, int]) -> str:
        """
        Form the path to a bundle's XML file based on the configured pattern.
        
        Args:
            collection_id: Collection ID to use in the path
            bundle_id: Bundle ID to use in the path
            
        Returns:
            Formatted path for the bundle XML file
        """
        pattern = self.get_bundle_xml_path()
        return pattern.format(collection_id=collection_id, bundle_id=bundle_id)

    def find_collections_s3(self, bucket: str = None, prefix: str = "") -> List[str]:
        """
        Find all collection directories in the specified S3 bucket.
        
        A collection is identified as a top-level directory that contains
        the expected folder structure with an XML file matching the collection name.
        
        Args:
            bucket: S3 bucket name (defaults to production bucket if None)
            prefix: Prefix to start searching from
            
        Returns:
            List of collection IDs found
        """
        # Default to production bucket if none provided
        if bucket is None:
            bucket = self.production_bucket
            
        collections = []
        
        try:
            # List all "directories" at the top level
            paginator = self.s3_client.get_paginator('list_objects_v2')
            response = paginator.paginate(Bucket=bucket, Prefix=prefix, Delimiter='/')
            
            for prefix_obj in response.search('CommonPrefixes'):
                dir_prefix = prefix_obj.get('Prefix')
                # Extract collection ID using string manipulation for S3 paths
                dir_name = dir_prefix.rstrip('/').rsplit('/', 1)[-1]
                
                # Check for the expected XML file using the configured path pattern
                collection_xml_key = self.form_collection_xml_path(dir_name)
                try:
                    result = self._safe_head_object(bucket, collection_xml_key)
                    if result:
                        collections.append(dir_name)
                        logger.debug(f"Found collection in S3: {dir_name}")
                    else:
                        logger.debug(f"Not a collection (no result): {dir_name}")
                except Exception as e:
                    logger.debug(f"Not a collection or error: {dir_name}, {str(e)}")
            
            logger.info(f"Found {len(collections)} collections in S3 bucket {bucket}")
            return collections
        except Exception as e:
            logger.error(f"Error finding collections in S3: {e}")
            return []

    def find_bundles_in_collection_s3(self, bucket: str = None, collection_id: str = None) -> List[str]:
        """
        Find all bundle directories within a collection directory in S3.
        
        Args:
            bucket: S3 bucket name (defaults to production bucket if None)
            collection_id: Collection ID to search in
            
        Returns:
            List of bundle IDs found
        """
        # Default to production bucket if none provided
        if bucket is None:
            bucket = self.production_bucket
            
        if collection_id is None:
            return []
            
        bundles = []
        collection_prefix = f"{collection_id}/"
        
        try:
            # List all "directories" within the collection
            paginator = self.s3_client.get_paginator('list_objects_v2')
            response = paginator.paginate(Bucket=bucket, Prefix=collection_prefix, Delimiter='/')
            
            for prefix_obj in response.search('CommonPrefixes'):
                dir_prefix = prefix_obj.get('Prefix')
                # Extract bundle ID using string manipulation for S3 paths
                bundle_id = dir_prefix.rstrip('/').rsplit('/', 1)[-1]
                
                # Skip if it's the same as the collection (inner folder with same name)
                if bundle_id == collection_id:
                    continue
                
                # Check for the expected XML file using the form_bundle_xml_path method
                bundle_xml_key = self.form_bundle_xml_path(collection_id, bundle_id)
                try:
                    result = self._safe_head_object(bucket, bundle_xml_key)
                    if result:
                        bundles.append(bundle_id)
                        logger.debug(f"Found bundle in S3: {bundle_id} in collection {collection_id}")
                    else:
                        logger.debug(f"Not a bundle (no result): {bundle_id}")
                except Exception as e:
                    logger.debug(f"Not a bundle or error: {bundle_id}, {str(e)}")
            
            logger.info(f"Found {len(bundles)} bundles in collection {collection_id} in S3 bucket {bucket}")
            return bundles
        except Exception as e:
            logger.error(f"Error finding bundles in collection in S3: {e}")
            return []

    def find_resources_in_bundle_s3(self, bucket: str = None, collection_id: str = None, bundle_id: str = None) -> List[str]:
        """
        Find all resources within a bundle directory in S3.
        
        Args:
            bucket: S3 bucket name (defaults to production bucket if None)
            collection_id: Collection ID containing the bundle
            bundle_id: Bundle ID to search in
            
        Returns:
            List of resource filenames found
        """
        # Default to production bucket if none provided
        if bucket is None:
            bucket = self.production_bucket
            
        if collection_id is None or bundle_id is None:
            return []
            
        resources = []
        
        # Construct the resources prefix directly from the pattern
        resource_pattern = self.get_resource_path_pattern()
        # Format the pattern up to the filename part
        try:
            prefix_pattern = resource_pattern.rsplit('{resource_filename}', 1)[0]
            resources_prefix = prefix_pattern.format(collection_id=collection_id, bundle_id=bundle_id)
        except KeyError: # Handle cases where format keys might be missing if pattern is unexpected
             logger.error(f"Could not format resource prefix from pattern: {resource_pattern}")
             return []
        
        try:
            # List all files in the resources directory
            paginator = self.s3_client.get_paginator('list_objects_v2')
            pages = paginator.paginate(Bucket=bucket, Prefix=resources_prefix)
            
            for page in pages:
                if 'Contents' in page:
                    for obj in page['Contents']:
                        key = obj['Key']
                        # Extract filename using string manipulation for S3 paths
                        filename = key.rsplit('/', 1)[-1]
                        if filename: # Avoid adding empty strings if key ends with /
                           # Ensure we only list direct children, not items in sub-prefixes
                           if key.startswith(resources_prefix) and '/' not in key[len(resources_prefix):]:
                               resources.append(filename)
                               logger.debug(f"Found resource in S3: {filename} in bundle {bundle_id}")
            
            logger.info(f"Found {len(resources)} resources in bundle {bundle_id} in S3 bucket {bucket}")
            return resources
        except Exception as e:
            logger.error(f"Error finding resources in bundle in S3: {e}")
            return []

    def find_collection_and_bundle_xmls_s3(self, bucket, prefix=""):
        """
        Find all collection and bundle XML files in the specified S3 bucket.
        Assumes collection and bundle directories are siblings under the prefix.
        Performs a two-pass scan: first identifies the collection, then searches
        among siblings for associated bundles.
        
        Args:
            bucket: S3 bucket name
            prefix: Prefix containing the collection and bundle sibling directories
            
        Returns:
            Dictionary with lists of collection and bundle XML paths
        """
        logger.info(f"Starting S3 XML discovery in bucket '{bucket}', prefix '{prefix}' for sibling structure.")
        result = {
            'potential_collection_xmls': [],
            'potential_bundle_xmls': []
        }
        
        found_collection_id = None
        found_collection_prefix = None
        potential_collection_xml_keys = [] # Store tuples of (id, key, prefix) temporarily

        paginator = self.s3_client.get_paginator('list_objects_v2')
        try:
            # --- Pass 1: Find the Collection ID and its XML ---
            collection_page_iterator = paginator.paginate(Bucket=bucket, Prefix=prefix, Delimiter='/')
            top_level_prefixes = list(collection_page_iterator.search('CommonPrefixes')) # Convert generator
            logger.debug(f"Found {len(top_level_prefixes)} potential top-level prefixes: {[p.get('Prefix') for p in top_level_prefixes if p]}")

            for prefix_obj in top_level_prefixes:
                if not prefix_obj: continue # Skip if None
                current_prefix = prefix_obj.get('Prefix')
                potential_id = current_prefix.rstrip('/').rsplit('/', 1)[-1]
                logger.debug(f"Checking prefix {current_prefix} as potential collection '{potential_id}'")

                try:
                    collection_xml_key = self.form_collection_xml_path(potential_id)
                    # Check if the formed key belongs to this prefix
                    if collection_xml_key.startswith(current_prefix):
                        logger.debug(f"Checking for collection XML at: {collection_xml_key}")
                        result = self._safe_head_object(bucket, collection_xml_key)
                        if result:
                            # Store potential collection info
                            potential_collection_xml_keys.append((potential_id, collection_xml_key, current_prefix))
                            logger.info(f"SUCCESS: Identified potential Collection via XML: {collection_xml_key}")
                        else:
                            logger.debug(f"Collection XML not found: {collection_xml_key}")
                    else:
                         logger.debug(f"Skipping collection check for {potential_id} as formed path {collection_xml_key} doesn't match prefix {current_prefix}")
                except ClientError as coll_e:
                    if coll_e.response.get('Error', {}).get('Code', 'Unknown') == '404':
                        logger.debug(f"Not a collection: Collection XML check failed (404) for {collection_xml_key}")
                    else:
                         error_code = coll_e.response.get('Error', {}).get('Code', 'Unknown')
                         logger.warning(f"WARN: Collection XML check failed unexpectedly for {collection_xml_key}. Error: {error_code}")
                except Exception as coll_e:
                     logger.error(f"ERROR: Unexpected error checking collection XML for {potential_id}: {coll_e}", exc_info=True)

            # Determine the primary collection ID to use for bundle association
            # Simple case: Assume the first one found is the one. 
            # TODO: Add logic here if multiple collections under one prefix are possible and need specific handling.
            if potential_collection_xml_keys:
                found_collection_id, collection_xml_to_add, found_collection_prefix = potential_collection_xml_keys[0]
                result['potential_collection_xmls'].append(collection_xml_to_add)
                logger.info(f"Using Collection ID '{found_collection_id}' from prefix '{found_collection_prefix}' for bundle search.")
            else:
                logger.warning(f"No collection XML found under prefix '{prefix}'. Cannot search for associated bundles.")
                return result # No collection, so no bundles to find this way

            # --- Pass 2: Find Bundles as Siblings ---
            if found_collection_id:
                logger.debug(f"Searching for bundles associated with collection '{found_collection_id}' among sibling prefixes.")
                for prefix_obj in top_level_prefixes:
                    if not prefix_obj: continue
                    current_prefix = prefix_obj.get('Prefix')

                    # Skip the prefix identified as the collection directory
                    if current_prefix == found_collection_prefix:
                        logger.debug(f"Skipping prefix {current_prefix} as it's the identified collection prefix.")
                        continue

                    potential_bundle_id = current_prefix.rstrip('/').rsplit('/', 1)[-1]
                    logger.debug(f"Checking prefix {current_prefix} as potential bundle '{potential_bundle_id}' for collection '{found_collection_id}'")

                    try:
                        # Use the FOUND collection ID here when forming the path
                        bundle_xml_key = self.form_bundle_xml_path(found_collection_id, potential_bundle_id)
                        # Check if the formed key belongs to this bundle prefix
                        if bundle_xml_key.startswith(current_prefix):
                             logger.debug(f"Checking for bundle XML at: {bundle_xml_key}")
                             head_result = self._safe_head_object(bucket, bundle_xml_key)
                             if head_result:
                                 result['potential_bundle_xmls'].append(bundle_xml_key)
                                 logger.info(f"SUCCESS: Identified Bundle via XML: {bundle_xml_key}")
                             else:
                                 logger.debug(f"Bundle XML not found: {bundle_xml_key}")
                        else:
                             logger.debug(f"Skipping bundle check for {potential_bundle_id} as formed path {bundle_xml_key} doesn't match prefix {current_prefix}")
                    except ClientError as bundle_e:
                        if bundle_e.response.get('Error', {}).get('Code', 'Unknown') == '404':
                            logger.debug(f"Not a bundle: Bundle XML check failed (404) for {bundle_xml_key}")
                        else:
                             error_code = bundle_e.response.get('Error', {}).get('Code', 'Unknown')
                             logger.warning(f"WARN: Bundle XML check failed unexpectedly for {bundle_xml_key}. Error: {error_code}")
                    except Exception as bundle_e:
                        logger.error(f"ERROR: Unexpected error checking bundle XML for {potential_bundle_id}: {bundle_e}", exc_info=True)
                # --- End Bundle Search ---
                
        except Exception as outer_e:
            logger.error(f"ERROR: Failed during S3 listing for prefix '{prefix}': {outer_e}", exc_info=True)

        logger.info(f"Finished S3 XML discovery. Found {len(result['potential_collection_xmls'])} collections, {len(result['potential_bundle_xmls'])} bundles.")
        return result

    def read_s3_object(self, bucket: str = None, key: str = None) -> Optional[bytes]:
        """
        Read the contents of an S3 object.
        
        Args:
            bucket: S3 bucket name (defaults to production bucket if None)
            key: S3 object key
            
        Returns:
            Object content as bytes, or None if the object doesn't exist
        """
        # Default to production bucket if none provided
        if bucket is None:
            bucket = self.production_bucket
            
        if key is None:
            return None
            
        try:
            response = self.s3_client.get_object(Bucket=bucket, Key=key)
            return response['Body'].read()
        except ClientError as e:
            if e.response['Error']['Code'] == 'NoSuchKey':
                logger.warning(f"S3 object {bucket}/{key} not found")
                return None
            else:
                logger.error(f"Error reading S3 object {bucket}/{key}: {e}")
                raise

    def get_resource(self, bucket: str = None, collection_id: str = None, 
                   bundle_id: str = None, resource_filename: str = None) -> Optional[bytes]:
        """
        Get a specific resource by its path components.
        
        Args:
            bucket: S3 bucket name (defaults to production bucket if None)
            collection_id: Collection ID containing the resource
            bundle_id: Bundle ID containing the resource
            resource_filename: Filename of the resource
            
        Returns:
            Resource content as bytes, or None if not found
        """
        # Default to production bucket if none provided
        if bucket is None:
            bucket = self.production_bucket
            
        if not all([collection_id, bundle_id, resource_filename]):
            logger.error("Missing required parameters for resource retrieval")
            return None
            
        # Form the resource path
        resource_path = self.form_resource_path(collection_id, bundle_id, resource_filename)
        
        # Get the resource content
        return self.read_s3_object(bucket, resource_path)

    def get_collection_xml(self, bucket: str = None, collection_id: str = None) -> Optional[bytes]:
        """
        Get a collection's XML file content.
        
        Args:
            bucket: S3 bucket name (defaults to production bucket if None)
            collection_id: Collection ID
            
        Returns:
            XML content as bytes, or None if not found
        """
        # Default to production bucket if none provided
        if bucket is None:
            bucket = self.production_bucket
            
        if not collection_id:
            logger.error("Missing collection_id for collection XML retrieval")
            return None
            
        # Form the collection XML path
        xml_path = self.form_collection_xml_path(collection_id)
        
        # Get the XML content
        return self.read_s3_object(bucket, xml_path)
        
    def get_bundle_xml(self, bucket: str = None, collection_id: str = None, bundle_id: str = None) -> Optional[bytes]:
        """
        Get a bundle's XML file content.
        
        Args:
            bucket: S3 bucket name (defaults to production bucket if None)
            collection_id: Collection ID containing the bundle
            bundle_id: Bundle ID
            
        Returns:
            XML content as bytes, or None if not found
        """
        # Default to production bucket if none provided
        if bucket is None:
            bucket = self.production_bucket
            
        if not all([collection_id, bundle_id]):
            logger.error("Missing required parameters for bundle XML retrieval")
            return None
            
        # Form the bundle XML path
        xml_path = self.form_bundle_xml_path(collection_id, bundle_id)
        
        # Get the XML content
        return self.read_s3_object(bucket, xml_path) 