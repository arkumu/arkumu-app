"""
Test constants for upload service tests.

This module re-exports constants from the parent services test_constants module
to maintain compatibility with the upload service test files.
"""

from ..test_constants import (
    # Bucket names
    TEST_BUCKET_NAME,
    TEST_INGEST_BUCKET, 
    TEST_PRODUCTION_BUCKET,
    TEST_ORG_BUCKETS,
    TEST_ORG_BUCKET_NAME,
    
    # File constants
    TEST_FILE_SIZES,
    TEST_CONTENT_TYPES,
    
    # Folder constants
    TEST_FOLDER_NAME,
    TEST_BASE_FOLDERS,
    TEST_FOLDER_STRUCTURES,
    
    # Upload configuration
    TEST_MULTIPART_THRESHOLD,
    TEST_CHUNK_SIZE,
    TEST_MAX_CONCURRENT,
)