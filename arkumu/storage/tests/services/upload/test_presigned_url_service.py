"""
Tests for PresignedURLService - direct browser-to-S3 uploads.
"""
import pytest
import boto3
from moto import mock_aws
import os
from unittest.mock import patch

from arkumu.storage.services.upload.presigned_url_service import PresignedURLService

# Import test constants
from .test_constants import (
    TEST_BUCKET_NAME, 
    TEST_INGEST_BUCKET, 
    TEST_PRODUCTION_BUCKET,
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
        
        # Create test buckets
        s3.create_bucket(Bucket=TEST_BUCKET_NAME)
        s3.create_bucket(Bucket=TEST_INGEST_BUCKET)
        s3.create_bucket(Bucket=TEST_PRODUCTION_BUCKET)
        
        yield s3


@pytest.fixture
def aws_credentials():
    """Mock AWS credentials for testing"""
    os.environ['AWS_ACCESS_KEY_ID'] = 'testing'
    os.environ['AWS_SECRET_ACCESS_KEY'] = 'testing'
    os.environ['AWS_SECURITY_TOKEN'] = 'testing'
    os.environ['AWS_SESSION_TOKEN'] = 'testing'
    os.environ['AWS_DEFAULT_REGION'] = 'us-east-1'


@pytest.fixture
def presigned_url_service(mock_s3, aws_credentials):
    """Create a PresignedURLService instance with mock settings"""
    env_vars = {
        'S3_INGEST_BUCKET': TEST_INGEST_BUCKET,
        'S3_PRODUCTION_BUCKET': TEST_PRODUCTION_BUCKET,
        'AWS_ACCESS_KEY_ID': 'testing',
        'AWS_SECRET_ACCESS_KEY': 'testing',
        'AWS_DEFAULT_REGION': 'us-east-1'
    }
    # Remove AWS_S3_ENDPOINT_URL if it exists to use default
    if 'AWS_S3_ENDPOINT_URL' in os.environ:
        env_vars['AWS_S3_ENDPOINT_URL'] = ''
    
    with patch.dict(os.environ, env_vars):
        service = PresignedURLService()
        yield service


@pytest.mark.django_db
def test_presigned_url_service_initialization(presigned_url_service):
    """Test that PresignedURLService initializes correctly"""
    assert presigned_url_service is not None
    assert presigned_url_service.base_service is not None
    assert presigned_url_service.s3_client is not None


@pytest.mark.django_db
def test_generate_upload_url(presigned_url_service):
    """Test generation of single presigned upload URL"""
    result = presigned_url_service.generate_upload_url(
        key="test-folder/test.txt",
        content_type="text/plain",
        expiry=3600
    )
    
    assert result['success'] is True
    assert 'url' in result
    assert 'fields' in result
    assert result['key'] == "test-folder/test.txt"
    assert 'bucket' in result
    assert 'expires_at' in result


@pytest.mark.django_db
def test_generate_upload_url_with_metadata(presigned_url_service):
    """Test presigned URL generation with metadata"""
    metadata = {
        'user_id': '123',
        'organization': 'test-org'
    }
    
    result = presigned_url_service.generate_upload_url(
        key="metadata-test/test.txt",
        content_type="text/plain",
        metadata=metadata,
        max_file_size=1024 * 1024  # 1MB
    )
    
    assert result['success'] is True
    assert result['max_file_size'] == 1024 * 1024
    assert 'fields' in result
    # Check that metadata fields are in the form fields
    fields = result['fields']
    assert 'x-amz-meta-user_id' in fields
    assert 'x-amz-meta-organization' in fields


@pytest.mark.django_db
def test_batch_generate_upload_urls(presigned_url_service):
    """Test generation of batch presigned upload URLs"""
    files = [
        {"key": "batch-test/test1.txt", "content_type": "text/plain"},
        {"key": "batch-test/test2.jpg", "content_type": "image/jpeg"},
        {"key": "batch-test/test3.pdf", "content_type": "application/pdf"}
    ]
    
    result = presigned_url_service.batch_generate_upload_urls(
        files=files,
        expiry=1800
    )
    
    assert result['success'] is True
    assert 'results' in result
    assert len(result['results']) == 3
    assert result['total'] == 3
    assert result['successful'] == 3
    
    for i, upload_url in enumerate(result['results']):
        assert upload_url['success'] is True
        assert upload_url['key'] == files[i]['key']
        assert 'url' in upload_url
        assert 'fields' in upload_url


@pytest.mark.django_db
def test_initiate_and_generate_multipart_urls(presigned_url_service):
    """Test multipart upload URL generation"""
    # This test requires the multipart service, so we'll test the URL generation part
    key = "large-file/multipart-test.bin"
    upload_id = "test-upload-id-12345"
    part_numbers = [1, 2, 3, 4, 5]
    
    result = presigned_url_service.generate_multipart_urls(
        key=key,
        upload_id=upload_id,
        parts=part_numbers,
        expiry=3600
    )
    
    assert result['success'] is True
    assert result['upload_id'] == upload_id
    assert result['key'] == key
    assert 'presigned_urls' in result
    assert len(result['presigned_urls']) == 5
    
    # Check each part URL
    for i, part_url in enumerate(result['presigned_urls']):
        assert part_url['part_number'] == part_numbers[i]
        assert 'presigned_url' in part_url
        assert isinstance(part_url['presigned_url'], str)


@pytest.mark.django_db
def test_generate_download_url(presigned_url_service):
    """Test generation of download URL"""
    result = presigned_url_service.generate_download_url(
        key="download-test/file.txt",
        expiry=1800,
        response_content_disposition='attachment; filename="downloaded_file.txt"'
    )
    
    assert result['success'] is True
    assert 'url' in result
    assert result['key'] == "download-test/file.txt"
    assert 'expires_at' in result


@pytest.mark.django_db
def test_generate_upload_url_error_handling(presigned_url_service):
    """Test error handling in URL generation"""
    # Test with invalid parameters or simulate an error condition
    # This might be tricky with moto, but we can test the structure
    
    result = presigned_url_service.generate_upload_url(
        key="",  # Empty key might cause issues
        content_type="text/plain"
    )
    
    # The result should still have proper structure even if it fails
    assert isinstance(result, dict)
    assert 'success' in result


@pytest.mark.django_db
def test_batch_generate_partial_failures(presigned_url_service):
    """Test batch generation with some invalid requests"""
    files = [
        {"key": "valid/test1.txt", "content_type": "text/plain"},
        {"key": "", "content_type": "text/plain"},  # Invalid empty key
        {"key": "valid/test3.pdf", "content_type": "application/pdf"}
    ]
    
    result = presigned_url_service.batch_generate_upload_urls(files=files)
    
    assert isinstance(result, dict)
    assert 'success' in result
    assert 'results' in result
    assert 'errors' in result
    assert 'total' in result
    assert result['total'] == 3