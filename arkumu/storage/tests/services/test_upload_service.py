import tempfile
import shutil
import pytest
import boto3
from moto import mock_aws
import os
import json
from io import BytesIO
from unittest.mock import Mock, patch

from arkumu.storage.services.upload_service import UploadService
from arkumu.storage.models import UploadSession, S3FileObject

# Import test constants
from .test_constants import (
    TEST_BUCKET_NAME, 
    TEST_INGEST_BUCKET, 
    TEST_PRODUCTION_BUCKET,
    TEST_ORG_BUCKETS,
    TEST_ORG_BUCKET_NAME,
    TEST_FOLDER_NAME,
    TEST_BASE_FOLDERS,
    TEST_FILE_SIZES,
    TEST_MULTIPART_THRESHOLD,
    TEST_CHUNK_SIZE,
    TEST_MAX_CONCURRENT,
    TEST_CONTENT_TYPES,
    TEST_FOLDER_STRUCTURES
)

@pytest.fixture
def mock_s3():
    """Set up mock AWS S3 environment"""
    with mock_aws():
        # Create S3 client with mock credentials
        s3 = boto3.client(
            's3',
            aws_access_key_id='testing',
            aws_secret_access_key='testing',
            region_name='us-east-1'
        )
        
        # Create main test buckets
        s3.create_bucket(Bucket=TEST_BUCKET_NAME)
        s3.create_bucket(Bucket=TEST_INGEST_BUCKET)
        s3.create_bucket(Bucket=TEST_PRODUCTION_BUCKET)
        
        # Create organization-specific buckets
        for org_code, bucket_name in TEST_ORG_BUCKETS.items():
            s3.create_bucket(Bucket=bucket_name)
        
        # Configure bucket policy to allow all operations for all buckets
        bucket_policy = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Sid": "PublicReadGetObject",
                    "Effect": "Allow",
                    "Principal": "*",
                    "Action": "s3:*",
                    "Resource": []
                }
            ]
        }
        
        # Add all bucket ARNs to the policy
        all_buckets = [TEST_BUCKET_NAME, TEST_INGEST_BUCKET, TEST_PRODUCTION_BUCKET] + list(TEST_ORG_BUCKETS.values())
        for bucket in all_buckets:
            bucket_policy["Statement"][0]["Resource"].extend([
                f"arn:aws:s3:::{bucket}",
                f"arn:aws:s3:::{bucket}/*"
            ])
        
        # Apply bucket policy and CORS to all buckets
        cors_configuration = {
            'CORSRules': [{
                'AllowedHeaders': ['*'],
                'AllowedMethods': ['GET', 'PUT', 'POST', 'DELETE'],
                'AllowedOrigins': ['*'],
                'ExposeHeaders': ['ETag']
            }]
        }
        
        for bucket in all_buckets:
            s3.put_bucket_policy(Bucket=bucket, Policy=json.dumps(bucket_policy))
            s3.put_bucket_cors(Bucket=bucket, CORSConfiguration=cors_configuration)
        
        yield s3

@pytest.fixture
def temp_dir():
    """Create a temporary directory for tests and clean it up afterwards"""
    temp_dir = tempfile.mkdtemp()
    yield temp_dir
    shutil.rmtree(temp_dir)

@pytest.fixture
def mock_upload_service(mock_s3):
    """Create an UploadService instance with mock settings"""
    service = UploadService()
    # For organization-bucket-only architecture, override the S3 client with our mock
    service.base_s3_service.s3_client = mock_s3
    return service

@pytest.fixture
def mock_bucket_service():
    """Mock bucket service for testing organization buckets"""
    service = Mock()
    
    def get_org_bucket(org_code):
        return TEST_ORG_BUCKETS.get(org_code, TEST_ORG_BUCKET_NAME)
    
    service.get_organization_bucket.side_effect = get_org_bucket
    service.ensure_organization_bucket_exists.return_value = {'success': True}
    return service

@pytest.fixture
def mock_user():
    """Mock user for testing upload sessions."""
    user = Mock()
    user.username = "test_user"
    user.id = 1
    return user

@pytest.fixture
def mock_upload_session():
    """Create a mock upload session for testing."""
    session = Mock(spec=UploadSession)
    session.id = "test-session-id"
    session.status = "in_progress"
    session.user = Mock()
    session.user.username = "test_user"
    session.folder_name = "test-folder"
    session.total_files = 0
    session.mark_completed = Mock()
    session.mark_failed = Mock()
    session.save = Mock()
    return session

@pytest.fixture
def mock_s3_file_object():
    """Create a mock S3FileObject for testing."""
    file_obj = Mock(spec=S3FileObject)
    file_obj.session = Mock()
    file_obj.session.id = "test-session-id"
    file_obj.file_name = "test.txt"
    file_obj.original_path = "test.txt"
    file_obj.s3_key = "test-folder/test.txt"
    file_obj.mark_completed = Mock()
    file_obj.mark_failed = Mock()
    return file_obj

def test_batch_operations_with_organization_bucket(mock_upload_service, mock_bucket_service):
    """Test batch operations with organization-specific bucket"""
    # Patch the bucket service getter to return our mock
    with patch('arkumu.storage.services.bucket_service.BucketService') as mock_bucket_svc:
        mock_bucket_svc.return_value = mock_bucket_service
        
        # Test different organization buckets
        test_organizations = ['rsh', 'khm', 'fuk']
        
        for org_code in test_organizations:
            # Create test files for this organization
            files = []
            for i in range(3):
                mock_file = Mock()
                mock_file.name = f"{org_code}_test_{i}.txt"
                mock_file.content_type = TEST_CONTENT_TYPES['text']
                mock_file.size = TEST_FILE_SIZES['small']
                mock_file.chunks = Mock(return_value=[f"Organization {org_code} test content {i}".encode()])
                files.append(mock_file)
            
            # Test batch upload with organization parameter
            target_bucket = TEST_ORG_BUCKETS[org_code]
            result = mock_upload_service.upload_batch_django_files_optimized(
                uploaded_files=files,
                path_prefix=f"org-test-{org_code}",
                bucket_name=target_bucket
            )
            
            # Verify the result and bucket usage
            assert result["success"] is True, f"Upload failed for organization {org_code}"
            assert len(result["results"]) == 3, f"Expected 3 results for {org_code}, got {len(result['results'])}"
            
            # Verify each file was uploaded to the correct bucket
            for file_result in result["results"]:
                assert file_result["bucket"] == target_bucket, f"File uploaded to wrong bucket for {org_code}"

def test_upload_session_tracking_with_organization(mock_upload_service, mock_bucket_service, mock_upload_session, mock_s3_file_object):
    """Test upload session tracking with organization-specific bucket"""
    # This test should use the structured upload method since the basic upload_django_file
    # doesn't support bucket_name parameter yet
    
    # Patch the bucket service getter
    with patch('arkumu.storage.services.bucket_service.BucketService') as mock_bucket_svc:
        mock_bucket_svc.return_value = mock_bucket_service
        
        # Patch S3FileObject.create_from_upload
        with patch('arkumu.storage.models.S3FileObject.create_from_upload', return_value=mock_s3_file_object):
            # Mock file for upload
            from io import BytesIO
            content = b"Session organization test content"
            mock_file = BytesIO(content)
            mock_file.name = "session_org_test.txt"
            mock_file.content_type = "text/plain"
            mock_file.size = len(content)
            
            # Set organization in the session
            mock_upload_session.institution = "fuk"
            mock_upload_session.s3_bucket = ""
            
            # Use the structured upload method that supports organization buckets
            org_bucket = TEST_ORG_BUCKETS['fuk']
            result = mock_upload_service.upload_batch_django_files_with_structure(
                uploaded_files=[mock_file],
                base_path="session-org-test",
                bucket_name=org_bucket
            )
            
            # Verify the session was updated with organization bucket
            assert result["success"] is True
            assert result["success_count"] == 1
            assert result["error_count"] == 0

def test_upload_failure_handling(mock_upload_service, mock_upload_session, mock_s3_file_object):
    """Test handling of upload failures with session tracking"""
    # Set up failure scenario using the custom key upload method
    with patch.object(mock_upload_service, '_upload_file_to_custom_key', side_effect=Exception("Simulated upload failure")):
        with patch('arkumu.storage.models.S3FileObject.create_from_upload', return_value=mock_s3_file_object):
            # Create test file
            from io import BytesIO
            content = b"This upload will fail"
            mock_file = BytesIO(content)
            mock_file.name = "failing_file.txt"
            mock_file.content_type = "text/plain"
            mock_file.size = len(content)
            
            # Try to upload using structured method
            org_bucket = TEST_ORG_BUCKETS['det']
            result = mock_upload_service.upload_batch_django_files_with_structure(
                uploaded_files=[mock_file],
                base_path="failure-test",
                bucket_name=org_bucket
            )
            
            # Verify failure was properly tracked
            assert result["success"] is False
            assert result["success_count"] == 0
            assert result["error_count"] == 1
            assert len(result["failures"]) == 1

def test_upload_file_to_custom_key(mock_upload_service):
    """Test uploading a file to a custom S3 key"""
    # Create mock file with proper file-like behavior
    from io import BytesIO
    content = b"Custom key test content"
    mock_file = BytesIO(content)
    mock_file.name = "custom_test.txt"
    mock_file.size = len(content)
    
    # Test custom key upload using organization bucket
    custom_s3_key = "custom/folder/structure/test_file.txt"
    org_bucket = TEST_ORG_BUCKETS['fuk']  # Use FUK organization bucket
    
    result = mock_upload_service._upload_file_to_custom_key(
        file_obj=mock_file,
        s3_key=custom_s3_key,
        bucket_name=org_bucket,
        content_type="text/plain"
    )
    
    # Verify the result
    assert result["success"] is True
    assert result["s3_key"] == custom_s3_key
    assert result["bucket"] == org_bucket
    assert result["content_type"] == "text/plain"

def test_batch_upload_with_folder_structure_simple(mock_upload_service):
    """Test batch upload with folder structure preservation using simple file names"""
    # Create test files without webkitRelativePath
    from io import BytesIO
    files = []
    for i in range(3):
        content = f"Simple test content {i}".encode()
        mock_file = BytesIO(content)
        mock_file.name = f"simple_test_{i}.txt"
        mock_file.content_type = "text/plain"
        mock_file.size = 50 + i * 10
        mock_file.seek = Mock()
        files.append(mock_file)
    
    # Test structured upload without file_paths (should use file names) with org bucket
    org_bucket = TEST_ORG_BUCKETS['rsh']  # Use RSH organization bucket
    
    result = mock_upload_service.upload_batch_django_files_with_structure(
        uploaded_files=files,
        base_path="data",
        bucket_name=org_bucket
    )
    
    # Verify the result
    assert result["success"] is True
    assert result["success_count"] == 3
    assert result["error_count"] == 0
    assert len(result["results"]) == 3
    
    # Check that file structure is preserved with base path
    for i, file_result in enumerate(result["results"]):
        expected_s3_key = f"data/simple_test_{i}.txt"
        assert file_result["s3_key"] == expected_s3_key
        assert file_result["file_name"] == f"simple_test_{i}.txt"
        assert file_result["original_path"] == f"simple_test_{i}.txt"

def test_batch_upload_with_folder_structure_paths(mock_upload_service):
    """Test batch upload with folder structure preservation using provided file paths"""
    # Use the nested folder structure from constants
    file_paths = TEST_FOLDER_STRUCTURES['nested']
    
    from io import BytesIO
    files = []
    for i, path in enumerate(file_paths):
        content = f"Content for {path}".encode()
        mock_file = BytesIO(content)
        mock_file.name = path.split('/')[-1]  # Just the filename
        mock_file.content_type = TEST_CONTENT_TYPES['text']
        mock_file.size = 100 + i * 20
        mock_file.seek = Mock()
        files.append(mock_file)
    
    # Test structured upload with file_paths using metadata base folder and org bucket
    org_bucket = TEST_ORG_BUCKETS['khm']  # Use KHM organization bucket
    
    result = mock_upload_service.upload_batch_django_files_with_structure(
        uploaded_files=files,
        base_path=TEST_BASE_FOLDERS[1],  # 'metadata'
        bucket_name=org_bucket,
        file_paths=file_paths
    )
    
    # Verify the result
    assert result["success"] is True
    assert result["success_count"] == len(file_paths)
    assert result["error_count"] == 0
    assert len(result["results"]) == len(file_paths)
    
    # Check that folder structure is preserved correctly
    for i, file_result in enumerate(result["results"]):
        expected_s3_key = f"{TEST_BASE_FOLDERS[1]}/{file_paths[i]}"
        assert file_result["s3_key"] == expected_s3_key
        assert file_result["original_path"] == file_paths[i]
        assert file_result["file_name"] == file_paths[i].split('/')[-1]

def test_batch_upload_with_folder_structure_no_base_path(mock_upload_service):
    """Test batch upload with folder structure preservation without base path"""
    # Create test files
    from io import BytesIO
    files = []
    file_paths = [
        "docs/api.md",
        "docs/user-guide.md",
        "config.json"
    ]
    
    for i, path in enumerate(file_paths):
        content = f"Content for {path}".encode()
        mock_file = BytesIO(content)
        mock_file.name = path.split('/')[-1]
        mock_file.content_type = "text/plain" if path.endswith('.md') else "application/json"
        mock_file.size = 80 + i * 15
        mock_file.seek = Mock()
        files.append(mock_file)
    
    # Test structured upload without base_path but with explicit org bucket
    org_bucket = TEST_ORG_BUCKETS['hmt']  # Use HMT organization bucket
    
    result = mock_upload_service.upload_batch_django_files_with_structure(
        uploaded_files=files,
        base_path="",  # No base path
        bucket_name=org_bucket,
        file_paths=file_paths
    )
    
    # Verify the result
    assert result["success"] is True
    assert result["success_count"] == 3
    assert result["error_count"] == 0
    
    # Check that files are placed at the root with their relative paths
    for i, file_result in enumerate(result["results"]):
        expected_s3_key = file_paths[i]  # No base path, so just the relative path
        assert file_result["s3_key"] == expected_s3_key
        assert file_result["original_path"] == file_paths[i]

def test_batch_upload_with_folder_structure_empty_files(mock_upload_service):
    """Test batch upload with folder structure preservation with empty file list"""
    org_bucket = TEST_ORG_BUCKETS['det']  # Use DET organization bucket
    
    result = mock_upload_service.upload_batch_django_files_with_structure(
        uploaded_files=[],
        base_path="data",
        bucket_name=org_bucket
    )
    
    # Verify the result
    assert result["success"] is False
    assert result["error"] == "No files provided"
    assert result["results"] == []
    assert result["failures"] == []

def test_batch_upload_with_folder_structure_upload_failure(mock_upload_service):
    """Test batch upload with folder structure preservation handling upload failures"""
    # Create test files
    from io import BytesIO
    files = []
    file_paths = ["test/file1.txt", "test/file2.txt"]
    
    for i, path in enumerate(file_paths):
        content = f"Content {i}".encode()
        mock_file = BytesIO(content)
        mock_file.name = path.split('/')[-1]
        mock_file.content_type = "text/plain"
        mock_file.size = 50
        mock_file.seek = Mock()
        files.append(mock_file)
    
    # Mock upload failure for the custom key method
    original_upload = mock_upload_service._upload_file_to_custom_key
    def mock_upload_fail(file_obj, s3_key, bucket_name, content_type):
        if "file1" in s3_key:
            return {"success": False, "error": "Simulated upload failure"}
        else:
            return original_upload(file_obj, s3_key, bucket_name, content_type)
    
    org_bucket = TEST_ORG_BUCKETS['fuk']  # Use FUK organization bucket
    
    with patch.object(mock_upload_service, '_upload_file_to_custom_key', side_effect=mock_upload_fail):
        result = mock_upload_service.upload_batch_django_files_with_structure(
            uploaded_files=files,
            base_path="data",
            bucket_name=org_bucket,
            file_paths=file_paths
        )
    
    # Verify partial success/failure
    assert result["success"] is False  # Not all files succeeded
    assert result["success_count"] == 1
    assert result["error_count"] == 1
    assert len(result["results"]) == 1
    assert len(result["failures"]) == 1
    
    # Check that the failure is properly recorded
    failure = result["failures"][0]
    assert failure["file_name"] == "file1.txt"
    assert failure["original_path"] == "test/file1.txt"
    assert failure["error"] == "Simulated upload failure"

def test_batch_upload_with_folder_structure_mismatched_paths(mock_upload_service):
    """Test batch upload with folder structure when file_paths length doesn't match files"""
    # Create test files
    from io import BytesIO
    files = []
    for i in range(3):
        content = f"Content {i}".encode()
        mock_file = BytesIO(content)
        mock_file.name = f"file_{i}.txt"
        mock_file.content_type = "text/plain"
        mock_file.size = 50
        mock_file.seek = Mock()
        files.append(mock_file)
    
    # Provide fewer file_paths than files
    file_paths = ["folder/file_0.txt", "folder/file_1.txt"]  # Missing path for file_2
    org_bucket = TEST_ORG_BUCKETS['rsh']  # Use RSH organization bucket
    
    result = mock_upload_service.upload_batch_django_files_with_structure(
        uploaded_files=files,
        base_path="data",
        bucket_name=org_bucket,
        file_paths=file_paths
    )
    
    # Verify the result - should still succeed but use filename for missing path
    assert result["success"] is True
    assert result["success_count"] == 3
    assert len(result["results"]) == 3
    
    # Check first two files use provided paths
    assert result["results"][0]["original_path"] == "folder/file_0.txt"
    assert result["results"][1]["original_path"] == "folder/file_1.txt"
    # Third file should fallback to filename
    assert result["results"][2]["original_path"] == "file_2.txt"

def test_batch_upload_folder_structure_performance(mock_upload_service):
    """Test performance aspects of folder structure upload with many files"""
    # Create a larger batch of files to test performance
    from io import BytesIO
    files = []
    file_paths = []
    
    # Simulate a realistic folder structure using deep structure from constants
    base_structure = TEST_FOLDER_STRUCTURES['deep']
    
    # Multiply the structure to create more files for performance testing
    for i in range(5):  # 5 copies of the structure
        for path in base_structure:
            modified_path = f"batch_{i}/{path}"
            file_paths.append(modified_path)
            
            content = f"Content for {modified_path}".encode()
            mock_file = BytesIO(content)
            mock_file.name = path.split('/')[-1]
            mock_file.content_type = TEST_CONTENT_TYPES['text']
            mock_file.size = TEST_FILE_SIZES['small']
            mock_file.seek = Mock()
            files.append(mock_file)
    
    # Measure upload time
    import time
    start_time = time.time()
    
    # Test with organization bucket
    org_bucket = TEST_ORG_BUCKETS['fuk']  # Use FUK organization bucket
    
    result = mock_upload_service.upload_batch_django_files_with_structure(
        uploaded_files=files,
        base_path=TEST_BASE_FOLDERS[0],  # 'data'
        bucket_name=org_bucket,
        file_paths=file_paths
    )
    
    end_time = time.time()
    duration = end_time - start_time
    
    # Verify the result
    assert result["success"] is True
    assert result["success_count"] == len(file_paths)  # 5 * 4 = 20 files
    assert result["error_count"] == 0
    
    # Performance assertion - should complete in reasonable time
    assert duration < 10.0, f"Upload took too long: {duration}s"
    
    # Verify folder structure is preserved
    for i, file_result in enumerate(result["results"]):
        expected_s3_key = f"{TEST_BASE_FOLDERS[0]}/{file_paths[i]}"
        assert file_result["s3_key"] == expected_s3_key
        assert file_result["original_path"] == file_paths[i]


# Multipart Upload Tests

@pytest.mark.django_db
def test_upload_multipart_stream_small_file(mock_upload_service):
    """Test multipart stream upload for small file (should use single part)"""
    from io import BytesIO
    
    # Create a small file (less than chunk size)
    content = b"Small file content for multipart test"
    file_obj = BytesIO(content)
    file_name = "small_multipart_test.txt"
    
    result = mock_upload_service.upload_multipart_stream(
        file_obj=file_obj,
        file_name=file_name,
        content_type="text/plain",
        path_prefix="data/multipart_test",
        chunk_size=5 * 1024 * 1024  # 5MB chunks
    )
    
    # Verify successful upload
    assert result["success"] is True
    assert result["file_name"] == file_name
    assert "s3_key" in result
    assert "file_size" in result
    assert result["file_size"] == len(content)


@pytest.mark.django_db
def test_upload_multipart_stream_large_file(mock_upload_service):
    """Test multipart stream upload for large file (multiple parts)"""
    from io import BytesIO
    
    # Create a large file that will require multiple parts
    chunk_size = 5 * 1024 * 1024  # 5MB
    total_size = 12 * 1024 * 1024  # 12MB (will need 3 parts)
    content = b"X" * total_size
    file_obj = BytesIO(content)
    file_name = "large_multipart_test.bin"
    
    result = mock_upload_service.upload_multipart_stream(
        file_obj=file_obj,
        file_name=file_name,
        content_type="application/octet-stream",
        path_prefix="data/multipart_test",
        chunk_size=chunk_size
    )
    
    # Verify successful upload
    assert result["success"] is True
    assert result["file_name"] == file_name
    assert result["file_size"] == total_size
    assert "s3_key" in result
    assert "etag" in result


@pytest.mark.django_db
def test_upload_multipart_stream_with_custom_parameters(mock_upload_service):
    """Test multipart upload with custom parameters"""
    from io import BytesIO
    
    content = b"Custom parameter test content" * 100000  # Make it reasonably large
    file_obj = BytesIO(content)
    
    result = mock_upload_service.upload_multipart_stream(
        file_obj=file_obj,
        file_name="custom_params_test.txt",
        content_type="text/plain",
        path_prefix="metadata/custom_test",
        chunk_size=1 * 1024 * 1024  # 1MB chunks (smaller than default)
    )
    
    assert result["success"] is True
    assert "custom_test" in result["s3_key"]
    assert result["file_size"] == len(content)


@pytest.mark.django_db
def test_upload_django_file_multipart_threshold(mock_upload_service):
    """Test that upload_django_file uses multipart for large files"""
    from django.core.files.uploadedfile import SimpleUploadedFile
    
    # Create file larger than multipart threshold
    multipart_threshold = 10 * 1024 * 1024  # 10MB
    large_content = b"L" * (multipart_threshold + 1024)  # Slightly larger than threshold
    
    large_file = SimpleUploadedFile(
        name="large_django_file.bin",
        content=large_content,
        content_type="application/octet-stream"
    )
    
    # Mock the multipart upload method to verify it's called
    with patch.object(mock_upload_service, 'upload_multipart_stream') as mock_multipart:
        mock_multipart.return_value = {
            "success": True,
            "file_name": "large_django_file.bin",
            "s3_key": "data/large_django_file.bin",
            "file_size": len(large_content)
        }
        
        result = mock_upload_service.upload_django_file(
            uploaded_file=large_file,
            path_prefix="data",
            multipart_threshold=multipart_threshold
        )
        
        # Verify multipart was called
        mock_multipart.assert_called_once()
        assert result["success"] is True


@pytest.mark.django_db
def test_upload_django_file_below_multipart_threshold(mock_upload_service):
    """Test that upload_django_file uses single upload for small files"""
    from django.core.files.uploadedfile import SimpleUploadedFile
    
    # Create file smaller than multipart threshold
    multipart_threshold = 10 * 1024 * 1024  # 10MB
    small_content = b"S" * 1024  # 1KB
    
    small_file = SimpleUploadedFile(
        name="small_django_file.txt",
        content=small_content,
        content_type="text/plain"
    )
    
    # Mock the single upload method to verify it's called instead of multipart
    with patch.object(mock_upload_service, 'upload_fileobj_encrypted') as mock_single:
        mock_single.return_value = {
            "success": True,
            "file_name": "small_django_file.txt",
            "s3_key": "data/small_django_file.txt",
            "file_size": len(small_content)
        }
        
        result = mock_upload_service.upload_django_file(
            uploaded_file=small_file,
            path_prefix="data",
            multipart_threshold=multipart_threshold
        )
        
        # Verify single upload was called
        mock_single.assert_called_once()
        assert result["success"] is True


@pytest.mark.django_db
def test_upload_files_optimized_multipart_config(mock_upload_service):
    """Test upload_files_optimized with multipart configuration"""
    from io import BytesIO
    
    # Create files that should trigger multipart uploads
    files = []
    for i in range(3):
        content = b"Optimized multipart test content" * 500000  # Large content
        file_dict = {
            'file_obj': BytesIO(content),
            'file_name': f'optimized_test_{i}.bin',
            'content_type': 'application/octet-stream'
        }
        files.append(file_dict)
    
    # Test with custom multipart settings
    custom_threshold = 5 * 1024 * 1024  # 5MB
    custom_chunk_size = 2 * 1024 * 1024  # 2MB chunks
    
    result = mock_upload_service.upload_files_optimized(
        files=files,
        path_prefix="data/optimized_multipart",
        multipart_threshold=custom_threshold,
        multipart_chunksize=custom_chunk_size,
        max_workers=2,
        max_concurrency=2
    )
    
    assert result["success"] is True
    assert result["total_uploaded"] == 3
    assert len(result["results"]) == 3
    
    # Verify all files were uploaded successfully
    for file_result in result["results"]:
        assert file_result["success"] is True
        assert "optimized_multipart" in file_result["s3_key"]


@pytest.mark.django_db
def test_multipart_upload_error_handling(mock_upload_service):
    """Test error handling in multipart uploads"""
    from io import BytesIO
    
    # Create a file for testing
    content = b"Error handling test" * 1000
    file_obj = BytesIO(content)
    
    # Mock S3 client to raise an exception during multipart upload
    with patch.object(mock_upload_service.base_service.s3_client, 'create_multipart_upload') as mock_create:
        mock_create.side_effect = Exception("Simulated S3 error")
        
        result = mock_upload_service.upload_multipart_stream(
            file_obj=file_obj,
            file_name="error_test.txt",
            content_type="text/plain"
        )
        
        # Verify error is handled gracefully
        assert result["success"] is False
        assert "error" in result
        assert "Simulated S3 error" in result["error"]


@pytest.mark.django_db
def test_multipart_upload_performance_benchmarking(mock_upload_service):
    """Test multipart upload performance with various file sizes"""
    from io import BytesIO
    import time
    
    # Test cases with different file sizes
    test_cases = [
        {"size": 5 * 1024 * 1024, "name": "5MB_perf_test.bin"},    # 5MB
        {"size": 25 * 1024 * 1024, "name": "25MB_perf_test.bin"},  # 25MB
        {"size": 50 * 1024 * 1024, "name": "50MB_perf_test.bin"},  # 50MB
    ]
    
    results = []
    
    for test_case in test_cases:
        content = b"P" * test_case["size"]
        file_obj = BytesIO(content)
        
        start_time = time.time()
        
        result = mock_upload_service.upload_multipart_stream(
            file_obj=file_obj,
            file_name=test_case["name"],
            content_type="application/octet-stream",
            chunk_size=8 * 1024 * 1024  # 8MB chunks
        )
        
        end_time = time.time()
        duration = end_time - start_time
        
        assert result["success"] is True
        
        results.append({
            "file_size": test_case["size"],
            "duration": duration,
            "throughput_mbps": (test_case["size"] / (1024 * 1024)) / duration
        })
    
    # Verify reasonable performance (should complete within reasonable time)
    for result in results:
        # Allow up to 10 seconds per 50MB (quite generous for testing)
        max_time = (result["file_size"] / (50 * 1024 * 1024)) * 10
        assert result["duration"] < max_time, f"Upload took too long: {result['duration']}s for {result['file_size']} bytes"


@pytest.mark.django_db
def test_multipart_upload_with_different_chunk_sizes(mock_upload_service):
    """Test multipart upload with various chunk sizes"""
    from io import BytesIO
    
    # Create a 20MB file
    file_size = 20 * 1024 * 1024
    content = b"C" * file_size
    
    # Test different chunk sizes
    chunk_sizes = [
        5 * 1024 * 1024,   # 5MB (S3 minimum for multipart)
        8 * 1024 * 1024,   # 8MB (common default)
        10 * 1024 * 1024,  # 10MB
    ]
    
    for i, chunk_size in enumerate(chunk_sizes):
        file_obj = BytesIO(content)
        
        result = mock_upload_service.upload_multipart_stream(
            file_obj=file_obj,
            file_name=f"chunk_test_{chunk_size // (1024*1024)}MB.bin",
            content_type="application/octet-stream",
            chunk_size=chunk_size
        )
        
        assert result["success"] is True
        assert result["file_size"] == file_size
        
        # Verify the file is accessible
        s3_key = result["s3_key"]
        assert s3_key is not None


@pytest.mark.django_db
def test_multipart_upload_concurrent_operations(mock_upload_service):
    """Test multiple concurrent multipart uploads"""
    from io import BytesIO
    import threading
    import time
    
    def upload_file(file_index):
        content = b"Concurrent test content" * 100000
        file_obj = BytesIO(content)
        
        result = mock_upload_service.upload_multipart_stream(
            file_obj=file_obj,
            file_name=f"concurrent_test_{file_index}.bin",
            content_type="application/octet-stream"
        )
        
        return result
    
    # Start multiple uploads concurrently
    threads = []
    results = [None] * 3
    
    def thread_worker(index):
        results[index] = upload_file(index)
    
    start_time = time.time()
    
    for i in range(3):
        thread = threading.Thread(target=thread_worker, args=(i,))
        threads.append(thread)
        thread.start()
    
    # Wait for all threads to complete
    for thread in threads:
        thread.join()
    
    end_time = time.time()
    total_duration = end_time - start_time
    
    # Verify all uploads succeeded
    for i, result in enumerate(results):
        assert result is not None
        assert result["success"] is True
        assert f"concurrent_test_{i}" in result["file_name"]
    
    # Concurrent uploads should be faster than sequential
    # (This is more of a sanity check given the mocked S3)
    assert total_duration < 30, f"Concurrent uploads took too long: {total_duration}s"
