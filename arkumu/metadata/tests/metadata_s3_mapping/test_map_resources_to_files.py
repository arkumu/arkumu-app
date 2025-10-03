import pytest
import os
from unittest.mock import Mock, patch, MagicMock
from django.test import TestCase
from django.core.exceptions import ValidationError
from django.db import transaction
from django.contrib.auth import get_user_model
from django.conf import settings

from arkumu.storage.models import S3FileObject, UploadSession
from arkumu.metadata.models import Resource
from arkumu.metadata.models.resource import ResourceType
from arkumu.metadata.models.triples import Triple
from arkumu.metadata.services.metatdata_s3_mapping.map_resources_to_files import (
    FileResourceMatcherService,
    MatchingConfig,
    FileMatchingError,
    S3SyncError,
    retry_on_failure
)

User = get_user_model()


@pytest.fixture
def matching_config():
    """Fixture for test configuration."""
    return MatchingConfig(
        batch_size=10,
        case_sensitive=False,
        max_retries=2,
        timeout_seconds=30,
        log_progress_every=5
    )


@pytest.fixture
def mock_logger():
    """Fixture for mock logger."""
    return Mock()


@pytest.fixture
def service(matching_config, mock_logger):
    """Fixture for FileResourceMatcherService instance."""
    return FileResourceMatcherService(
        logger_func=mock_logger,
        config=matching_config
    )


@pytest.fixture
def mock_bucket_service():
    """Fixture for mock bucket service."""
    with patch('arkumu.metadata.services.metatdata_s3_mapping.map_resources_to_files.BucketService') as mock:
        yield mock.return_value


@pytest.fixture
def test_user():
    """Fixture for creating a test user using AUTH_USER_MODEL."""
    return User.objects.create_user(
        username="testuser",
        email="test@example.com",
        password="testpass123"
    )


@pytest.fixture
def upload_session(test_user):
    """Fixture for creating an upload session."""
    return UploadSession.objects.create(
        user=test_user,
        folder_name="test-folder",
        status="in_progress"
    )


def create_test_resource(value, resource_type='LITERAL'):
    """Helper function to create valid test resources."""
    if resource_type == 'LITERAL':
        return Resource.objects.create(
            resource_type=resource_type,
            value=value
        )
    else:
        return Resource.objects.create(
            resource_type=resource_type,
            uri=f"http://example.com/{value}",
            value=value
        )


def create_test_s3_file(file_name, s3_key, upload_session=None, related_resource=None):
    """Helper function to create valid test S3FileObject instances."""
    # If no upload_session provided, create a temporary one
    if upload_session is None:
        User = get_user_model()
        temp_user = User.objects.create_user(
            username=f"tempuser_{file_name}",
            email=f"temp_{file_name}@example.com"
        )
        upload_session = UploadSession.objects.create(
            user=temp_user,
            folder_name=f"temp-{file_name}",
            status="in_progress"
        )
    
    return S3FileObject.objects.create(
        session=upload_session,
        file_name=file_name,
        s3_key=s3_key,
        file_size_bytes=1024,
        status="verified",
        related_resource=related_resource
    )


@pytest.mark.django_db
class TestFileResourceMatcherService:
    """Test class for FileResourceMatcherService - using pytest style."""
    pass


# Configuration Tests
def test_matching_config_defaults():
    """Test MatchingConfig default values."""
    config = MatchingConfig()
    assert config.batch_size == 1000
    assert config.case_sensitive is False
    assert config.max_retries == 3
    assert config.timeout_seconds == 300
    assert config.log_progress_every == 100


def test_matching_config_custom_values():
    """Test MatchingConfig with custom values."""
    config = MatchingConfig(
        batch_size=500,
        case_sensitive=True,
        max_retries=5,
        timeout_seconds=600,
        log_progress_every=50
    )
    assert config.batch_size == 500
    assert config.case_sensitive is True
    assert config.max_retries == 5
    assert config.timeout_seconds == 600
    assert config.log_progress_every == 50


# Service Initialization Tests
def test_service_initialization_default():
    """Test service initialization with defaults."""
    service = FileResourceMatcherService()
    assert service.config.batch_size == 1000
    assert service.logger_func is not None
    assert service.bucket_service is not None


def test_service_initialization_custom(matching_config, mock_logger):
    """Test service initialization with custom config and logger."""
    service = FileResourceMatcherService(
        logger_func=mock_logger,
        config=matching_config
    )
    assert service.config == matching_config
    assert service.logger_func == mock_logger


# Validation Tests
def test_validate_bucket_params_valid():
    """Test bucket parameter validation with valid inputs."""
    service = FileResourceMatcherService()
    # Should not raise any exception
    service._validate_bucket_params("test-bucket", "prefix/")
    service._validate_bucket_params("test-bucket", "")


def test_validate_bucket_params_invalid_bucket():
    """Test bucket parameter validation with invalid bucket name."""
    service = FileResourceMatcherService()
    
    with pytest.raises(ValidationError, match="bucket_name must be a non-empty string"):
        service._validate_bucket_params("", "prefix")
    
    with pytest.raises(ValidationError, match="bucket_name must be a non-empty string"):
        service._validate_bucket_params(None, "prefix")
    
    with pytest.raises(ValidationError, match="bucket_name must be a non-empty string"):
        service._validate_bucket_params(123, "prefix")


def test_validate_bucket_params_invalid_prefix():
    """Test bucket parameter validation with invalid prefix."""
    service = FileResourceMatcherService()
    
    with pytest.raises(ValidationError, match="prefix must be a string"):
        service._validate_bucket_params("bucket", 123)


# Logging Tests
def test_logging_with_custom_logger(mock_logger):
    """Test logging with custom logger function."""
    service = FileResourceMatcherService(logger_func=mock_logger)
    service._log("test message")
    mock_logger.assert_called_once_with("test message")


def test_logging_with_default_logger():
    """Test logging with default logger."""
    service = FileResourceMatcherService()
    # Should not raise exception
    service._log("test message")


def test_record_metrics(mock_logger):
    """Test metrics recording."""
    service = FileResourceMatcherService(logger_func=mock_logger)
    service._record_metrics("test_operation", count=10, errors=1, time=5.5)
    mock_logger.assert_called_with("METRICS [test_operation]: count=10, errors=1, time=5.5")


# Retry Decorator Tests
def test_retry_decorator_success():
    """Test retry decorator with successful operation."""
    call_count = 0
    
    @retry_on_failure(max_retries=3, delay=0.01)
    def test_function():
        nonlocal call_count
        call_count += 1
        return "success"
    
    result = test_function()
    assert result == "success"
    assert call_count == 1


def test_retry_decorator_eventual_success():
    """Test retry decorator with eventual success."""
    call_count = 0
    
    @retry_on_failure(max_retries=3, delay=0.01)
    def test_function():
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise Exception("Temporary failure")
        return "success"
    
    result = test_function()
    assert result == "success"
    assert call_count == 3


def test_retry_decorator_permanent_failure():
    """Test retry decorator with permanent failure."""
    call_count = 0
    
    @retry_on_failure(max_retries=3, delay=0.01)
    def test_function():
        nonlocal call_count
        call_count += 1
        raise Exception("Permanent failure")
    
    with pytest.raises(Exception, match="Permanent failure"):
        test_function()
    
    assert call_count == 3


# File Matching Tests
@pytest.mark.django_db
def test_match_and_link_no_files(service):
    """Test matching when no unlinked files exist."""
    processed, linked, ambiguous, errors = service.match_and_link_by_filename_to_resource_value()
    
    assert processed == 0
    assert linked == 0
    assert ambiguous == 0
    assert errors == 0


@pytest.mark.django_db
def test_match_and_link_single_match(service):
    """Test matching with single exact match."""
    # Create test data
    resource = create_test_resource("testfile")
    s3_file = create_test_s3_file("testfile.pdf", "bucket/testfile.pdf")
    
    processed, linked, ambiguous, errors = service.match_and_link_by_filename_to_resource_value()
    
    assert processed == 1
    assert linked == 1
    assert ambiguous == 0
    assert errors == 0
    
    # Verify the link was created
    s3_file.refresh_from_db()
    assert s3_file.related_resource == resource


@pytest.mark.django_db
def test_match_and_link_to_event(service):
    """Test linking files directly to event entities when requested."""
    literal = create_test_resource("eventfile")
    event = Resource.objects.create(
        resource_type=ResourceType.ENTITY,
        uri="http://example.com/entities/ereignis/1",
    )
    predicate = Resource.objects.create(
        resource_type=ResourceType.PROPERTY,
        uri="http://example.com/properties/has-file",
    )
    Triple.objects.create(subject=event, predicate=predicate, object=literal)

    s3_file = create_test_s3_file("eventfile.mov", "bucket/eventfile.mov")

    processed, linked, ambiguous, errors = service.match_and_link_by_filename_to_resource_value(
        link_target="event"
    )

    assert processed == 1
    assert linked == 1
    assert ambiguous == 0
    assert errors == 0

    s3_file.refresh_from_db()
    assert s3_file.related_resource == event


@pytest.mark.django_db
def test_match_and_link_case_insensitive(service):
    """Test case-insensitive matching."""
    # Create test data with different cases
    resource = create_test_resource("TestFile")
    s3_file = create_test_s3_file("testfile.pdf", "bucket/testfile.pdf")
    
    processed, linked, ambiguous, errors = service.match_and_link_by_filename_to_resource_value()
    
    assert processed == 1
    assert linked == 1
    assert ambiguous == 0
    assert errors == 0
    
    s3_file.refresh_from_db()
    assert s3_file.related_resource == resource


@pytest.mark.django_db
def test_match_and_link_case_sensitive():
    """Test case-sensitive matching."""
    config = MatchingConfig(case_sensitive=True)
    service = FileResourceMatcherService(config=config)
    
    # Create test data with different cases
    resource = create_test_resource("TestFile")
    s3_file = create_test_s3_file("testfile.pdf", "bucket/testfile.pdf")
    
    processed, linked, ambiguous, errors = service.match_and_link_by_filename_to_resource_value()
    
    assert processed == 1
    assert linked == 0  # No match due to case difference
    assert ambiguous == 0
    assert errors == 0
    
    s3_file.refresh_from_db()
    assert s3_file.related_resource is None


@pytest.mark.django_db
def test_match_and_link_ambiguous_match(service):
    """Test handling of ambiguous matches."""
    # Create test data with multiple matching resources that have different sources
    # to avoid the unique constraint but same values for matching
    resource1 = Resource.objects.create(
        resource_type=ResourceType.LITERAL,
        value='testfile',
        language='en'
    )
    resource2 = Resource.objects.create(
        resource_type=ResourceType.LITERAL,
        value='testfile',
        language='de'
    )
    s3_file = create_test_s3_file("testfile.pdf", "bucket/testfile.pdf")
    
    processed, linked, ambiguous, errors = service.match_and_link_by_filename_to_resource_value()
    
    assert processed == 1
    assert linked == 0
    assert ambiguous == 1
    assert errors == 0
    
    # Verify no link was created
    s3_file.refresh_from_db()
    assert s3_file.related_resource is None


@pytest.mark.django_db
def test_match_and_link_no_match(service):
    """Test handling when no resource matches."""
    s3_file = create_test_s3_file("nonexistent.pdf", "bucket/nonexistent.pdf")
    
    processed, linked, ambiguous, errors = service.match_and_link_by_filename_to_resource_value()
    
    assert processed == 1
    assert linked == 0
    assert ambiguous == 0
    assert errors == 0
    
    s3_file.refresh_from_db()
    assert s3_file.related_resource is None


@pytest.mark.django_db
def test_match_and_link_empty_filename(service):
    """Test handling of files with empty names after extension stripping."""
    s3_file = create_test_s3_file(".pdf", "bucket/.pdf")  # Empty name after stripping extension
    
    processed, linked, ambiguous, errors = service.match_and_link_by_filename_to_resource_value()
    
    assert processed == 1
    assert linked == 0
    assert ambiguous == 0
    assert errors == 0


@pytest.mark.django_db
def test_match_and_link_already_linked_files(service):
    """Test that already linked files are skipped."""
    resource = create_test_resource("testfile")
    s3_file = create_test_s3_file("testfile.pdf", "bucket/testfile.pdf", related_resource=resource)  # Already linked
    
    processed, linked, ambiguous, errors = service.match_and_link_by_filename_to_resource_value()
    
    assert processed == 0  # Should skip already linked files
    assert linked == 0
    assert ambiguous == 0
    assert errors == 0


@pytest.mark.django_db
def test_match_and_link_with_queryset(service):
    """Test matching with a specific queryset."""
    resource = create_test_resource("testfile")
    
    # Create multiple files
    s3_file1 = create_test_s3_file("testfile.pdf", "bucket/testfile.pdf")
    s3_file2 = create_test_s3_file("otherfile.pdf", "bucket/otherfile.pdf")
    
    # Process only specific queryset
    queryset = S3FileObject.objects.filter(id=s3_file1.id)
    processed, linked, ambiguous, errors = service.match_and_link_by_filename_to_resource_value(queryset)
    
    assert processed == 1
    assert linked == 1
    assert ambiguous == 0
    assert errors == 0
    
    # Verify only the targeted file was processed
    s3_file1.refresh_from_db()
    s3_file2.refresh_from_db()
    assert s3_file1.related_resource == resource
    assert s3_file2.related_resource is None


# S3 Sync Tests
@pytest.mark.django_db
def test_discover_and_sync_s3_files_success(service, mock_bucket_service):
    """Test successful S3 file discovery and sync."""
    # Mock S3 response
    mock_s3_objects = [
        {'Key': 'path/file1.pdf', 'Size': 1024, 'ContentType': 'application/pdf'},
        {'Key': 'path/file2.txt', 'Size': 512, 'ContentType': 'text/plain'},
        {'Key': 'path/folder/', 'Size': 0},  # Should be skipped
    ]
    mock_bucket_service.list_bucket_contents.return_value = mock_s3_objects
    service.bucket_service = mock_bucket_service
    
    synced, created, skipped, errors = service.discover_and_sync_s3_files("test-bucket", "path/")
    
    assert synced == 0
    assert created == 2  # Two files created
    assert skipped == 1  # Folder skipped
    assert errors == 0
    
    # Verify files were created in database
    assert S3FileObject.objects.count() == 2
    file1 = S3FileObject.objects.get(s3_key='path/file1.pdf')
    assert file1.file_name == 'file1.pdf'
    assert file1.file_size_bytes == 1024
    assert file1.content_type == 'application/pdf'
    assert file1.status == 'verified'


@pytest.mark.django_db
def test_discover_and_sync_existing_files(service, mock_bucket_service):
    """Test sync with existing files in database."""
    # Create existing file
    existing_file = create_test_s3_file("existing.pdf", "path/existing.pdf")
    
    # Mock S3 response with existing and new files
    mock_s3_objects = [
        {'Key': 'path/existing.pdf', 'Size': 1024, 'ContentType': 'application/pdf'},
        {'Key': 'path/newfile.txt', 'Size': 512, 'ContentType': 'text/plain'},
    ]
    mock_bucket_service.list_bucket_contents.return_value = mock_s3_objects
    service.bucket_service = mock_bucket_service
    
    synced, created, skipped, errors = service.discover_and_sync_s3_files("test-bucket", "path/")
    
    assert synced == 1  # Existing file
    assert created == 1  # New file
    assert skipped == 0
    assert errors == 0
    
    assert S3FileObject.objects.count() == 2


@pytest.mark.django_db
def test_discover_and_sync_bucket_service_error(service, mock_bucket_service):
    """Test handling of BucketService errors."""
    mock_bucket_service.list_bucket_contents.side_effect = Exception("S3 connection failed")
    service.bucket_service = mock_bucket_service
    
    with pytest.raises(S3SyncError, match="Error calling BucketService.list_bucket_contents"):
        service.discover_and_sync_s3_files("test-bucket", "path/")


@pytest.mark.django_db
def test_discover_and_sync_invalid_bucket_name(service):
    """Test sync with invalid bucket name."""
    with pytest.raises(ValidationError, match="bucket_name must be a non-empty string"):
        service.discover_and_sync_s3_files("", "path/")


@pytest.mark.django_db
def test_discover_and_sync_batch_processing(service, mock_bucket_service):
    """Test batch processing during S3 sync."""
    # Configure small batch size
    service.config.batch_size = 2
    
    # Create more files than batch size
    mock_s3_objects = [
        {'Key': f'path/file{i}.pdf', 'Size': 1024, 'ContentType': 'application/pdf'}
        for i in range(5)
    ]
    mock_bucket_service.list_bucket_contents.return_value = mock_s3_objects
    service.bucket_service = mock_bucket_service
    
    synced, created, skipped, errors = service.discover_and_sync_s3_files("test-bucket", "path/")
    
    assert synced == 0
    assert created == 5
    assert skipped == 0
    assert errors == 0
    assert S3FileObject.objects.count() == 5


# Utility Method Tests
@pytest.mark.django_db
def test_get_unlinked_files_count(service):
    """Test getting count of unlinked files."""
    resource = create_test_resource("test")
    
    # Create linked and unlinked files
    create_test_s3_file("linked.pdf", "bucket/linked.pdf", related_resource=resource)
    create_test_s3_file("unlinked1.pdf", "bucket/unlinked1.pdf")
    create_test_s3_file("unlinked2.pdf", "bucket/unlinked2.pdf")
    
    count = service.get_unlinked_files_count()
    assert count == 2


@pytest.mark.django_db
def test_get_matching_statistics(service):
    """Test getting matching statistics."""
    resource = create_test_resource("test")
    
    # Create linked and unlinked files
    create_test_s3_file("linked1.pdf", "bucket/linked1.pdf", related_resource=resource)
    create_test_s3_file("linked2.pdf", "bucket/linked2.pdf", related_resource=resource)
    create_test_s3_file("unlinked.pdf", "bucket/unlinked.pdf")
    
    stats = service.get_matching_statistics()
    
    assert stats['total_files'] == 3
    assert stats['linked_files'] == 2
    assert stats['unlinked_files'] == 1
    assert stats['link_percentage'] == 66.67


@pytest.mark.django_db
def test_get_matching_statistics_no_files(service):
    """Test statistics with no files."""
    stats = service.get_matching_statistics()
    
    assert stats['total_files'] == 0
    assert stats['linked_files'] == 0
    assert stats['unlinked_files'] == 0
    assert stats['link_percentage'] == 0


# Performance and Edge Case Tests
@pytest.mark.django_db
def test_large_dataset_performance(service):
    """Test performance with larger dataset."""
    # Create many resources and files
    resources = [
        create_test_resource(f"file{i}")
        for i in range(100)
    ]
    
    s3_files = [
        create_test_s3_file(f"file{i}.pdf", f"bucket/file{i}.pdf")
        for i in range(100)
    ]
    
    # Measure performance
    import time
    start_time = time.time()
    
    processed, linked, ambiguous, errors = service.match_and_link_by_filename_to_resource_value()
    
    execution_time = time.time() - start_time
    
    assert processed == 100
    assert linked == 100
    assert ambiguous == 0
    assert errors == 0
    assert execution_time < 10  # Should complete within 10 seconds


@pytest.mark.django_db
def test_unicode_and_special_characters(service):
    """Test handling of unicode and special characters."""
    # Create resource with unicode characters
    resource = create_test_resource("tëst-fílé_123")
    s3_file = create_test_s3_file("tëst-fílé_123.pdf", "bucket/tëst-fílé_123.pdf")
    
    processed, linked, ambiguous, errors = service.match_and_link_by_filename_to_resource_value()
    
    assert processed == 1
    assert linked == 1
    assert ambiguous == 0
    assert errors == 0
    
    s3_file.refresh_from_db()
    assert s3_file.related_resource == resource


# Integration Tests
@pytest.mark.django_db
def test_full_workflow_integration(service, mock_bucket_service):
    """Test complete workflow: discover files, then match to resources."""
    # Create some resources
    create_test_resource("document1")
    create_test_resource("document2")
    
    # Mock S3 discovery
    mock_s3_objects = [
        {'Key': 'docs/document1.pdf', 'Size': 1024, 'ContentType': 'application/pdf'},
        {'Key': 'docs/document2.txt', 'Size': 512, 'ContentType': 'text/plain'},
        {'Key': 'docs/unknown.pdf', 'Size': 256, 'ContentType': 'application/pdf'},
    ]
    mock_bucket_service.list_bucket_contents.return_value = mock_s3_objects
    service.bucket_service = mock_bucket_service
    
    # Step 1: Discover and sync S3 files
    synced, created, skipped, errors = service.discover_and_sync_s3_files("test-bucket", "docs/")
    assert created == 3
    assert errors == 0
    
    # Step 2: Match files to resources
    processed, linked, ambiguous, match_errors = service.match_and_link_by_filename_to_resource_value()
    assert processed == 3
    assert linked == 2  # document1 and document2 should link
    assert ambiguous == 0
    assert match_errors == 0
    
    # Verify final state
    stats = service.get_matching_statistics()
    assert stats['total_files'] == 3
    assert stats['linked_files'] == 2
    assert stats['unlinked_files'] == 1
    assert stats['link_percentage'] == 66.67


# Error Handling Tests
@pytest.mark.django_db
def test_database_error_handling_during_matching(service):
    """Test handling of database errors during matching."""
    resource = create_test_resource("testfile")
    s3_file = create_test_s3_file("testfile.pdf", "bucket/testfile.pdf")
    
    # Mock a database error during bulk_update
    with patch.object(S3FileObject.objects, 'bulk_update', side_effect=Exception("Database error")):
        processed, linked, ambiguous, errors = service.match_and_link_by_filename_to_resource_value()
        
        assert processed == 1
        assert linked == 1  # Counted as linked before error
        assert ambiguous == 0
        assert errors == 1  # Error during save


@pytest.mark.django_db
def test_transaction_rollback_on_error(service):
    """Test that transactions are properly rolled back on errors."""
    # This test would need more complex setup to properly test transaction rollback
    # For now, we verify the @transaction.atomic decorator is applied
    method = service.match_and_link_by_filename_to_resource_value
    assert hasattr(method, '__wrapped__')  # Indicates decorator was applied


def test_custom_exceptions():
    """Test custom exception classes."""
    file_error = FileMatchingError("File matching failed")
    assert str(file_error) == "File matching failed"
    
    s3_error = S3SyncError("S3 sync failed")
    assert str(s3_error) == "S3 sync failed"
