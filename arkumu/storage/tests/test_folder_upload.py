import json
import pytest
from unittest.mock import Mock, patch, MagicMock
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.test import Client
from arkumu.users.models import User


@pytest.mark.django_db
class TestFolderUpload:
    """Test folder upload functionality with path preservation."""
    
    def setup_method(self):
        """Set up test data."""
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        self.client = Client()
        self.client.force_login(self.user)
        self.upload_url = reverse('storage:streaming_upload_api')
    
    @patch('arkumu.storage.views.streaming_upload_views.UploadSession')
    @patch('arkumu.storage.views.streaming_upload_views.UploadService')
    @patch('arkumu.storage.views.streaming_upload_views.BucketService')
    def test_folder_upload_preserves_structure(self, mock_bucket_service, mock_upload_service, mock_upload_session):
        """Test that folder uploads preserve the directory structure."""
        # Mock the services
        mock_upload_instance = Mock()
        mock_upload_service.return_value = mock_upload_instance
        
        # Mock the base_s3_service.ingest_bucket attribute
        mock_upload_instance.base_s3_service = Mock()
        mock_upload_instance.base_s3_service.ingest_bucket = 'test-bucket'
        
        # Mock bucket service
        mock_bucket_instance = Mock()
        mock_bucket_service.return_value = mock_bucket_instance
        mock_bucket_instance.ensure_organization_bucket_exists.return_value = {
            'success': True,
            'bucket_name': 'test-org-bucket'
        }
        mock_bucket_instance.get_organization_bucket.return_value = 'test-org-bucket'
        
        # Mock UploadSession
        mock_session_instance = Mock()
        mock_session_instance.id = 'test-session-id'
        mock_session_instance.status = 'completed'
        mock_upload_session.create_from_import.return_value = mock_session_instance
        
        # Mock the upload method to return a mutable dict (not a Mock)
        mock_result = {
            'success': True,
            'results': [
                {
                    'file_name': 'test_file_1.txt',
                    's3_key': 'data/my_folder/test_file_1.txt',
                    'file_size': 14,
                    'content_type': 'text/plain',
                    's3_url': 'http://example.com/data/my_folder/test_file_1.txt'
                },
                {
                    'file_name': 'test_file_2.txt',
                    's3_key': 'data/my_folder/test_file_2.txt',
                    'file_size': 14,
                    'content_type': 'text/plain',
                    's3_url': 'http://example.com/data/my_folder/test_file_2.txt'
                },
                {
                    'file_name': 'test_file_3.txt',
                    's3_key': 'data/my_folder/subfolder/test_file_3.txt',
                    'file_size': 14,
                    'content_type': 'text/plain',
                    's3_url': 'http://example.com/data/my_folder/subfolder/test_file_3.txt'
                }
            ],
            'failures': []
        }
        mock_upload_instance.upload_batch_django_files_with_structure.side_effect = lambda *args, **kwargs: mock_result.copy()
        
        # Create test files
        files = [
            SimpleUploadedFile("test_file_1.txt", b"Test content 1", content_type="text/plain"),
            SimpleUploadedFile("test_file_2.txt", b"Test content 2", content_type="text/plain"),
            SimpleUploadedFile("test_file_3.txt", b"Test content 3", content_type="text/plain")
        ]
        
        # Simulate file paths that would come from webkitRelativePath
        file_paths = [
            "test_file_1.txt",
            "test_file_2.txt",
            "subfolder/test_file_3.txt"
        ]
        
        # Prepare the upload data
        data = {
            'organization': 'test-org',
            'folder_name': 'data/my_folder',
            'preserve_folder_structure': 'true',
            'file_paths': json.dumps(file_paths),
            'files': files
        }
        
        # Make the upload request
        response = self.client.post(self.upload_url, data=data)
        
        # Check response
        assert response.status_code == 200
        response_data = response.json()
        assert response_data['success'] is True
        
        # Verify the upload method was called with correct parameters
        mock_upload_instance.upload_batch_django_files_with_structure.assert_called_once()
        call_args = mock_upload_instance.upload_batch_django_files_with_structure.call_args
        
        # Check that the base_path includes the folder name
        assert call_args.kwargs['base_path'] == 'data/my_folder'
        assert call_args.kwargs['file_paths'] == file_paths
        
        # Verify the response contains correct S3 keys
        results = response_data.get('results', [])
        assert len(results) == 3
        
        s3_keys = [r['s3_key'] for r in results]
        assert 'data/my_folder/test_file_1.txt' in s3_keys
        assert 'data/my_folder/test_file_2.txt' in s3_keys
        assert 'data/my_folder/subfolder/test_file_3.txt' in s3_keys
    
    @patch('arkumu.storage.views.streaming_upload_views.UploadService')
    @patch('arkumu.storage.views.streaming_upload_views.BucketService')
    def test_folder_upload_without_structure_preservation(self, mock_bucket_service, mock_upload_service):
        """Test folder upload without preserving structure (flat upload)."""
        # Mock the services
        mock_upload_instance = Mock()
        mock_upload_service.return_value = mock_upload_instance
        mock_upload_instance.base_s3_service = Mock()
        mock_upload_instance.base_s3_service.ingest_bucket = 'test-bucket'
        
        mock_bucket_instance = Mock()
        mock_bucket_service.return_value = mock_bucket_instance
        mock_bucket_instance.ensure_organization_bucket_exists.return_value = {
            'success': True,
            'bucket_name': 'test-org-bucket'
        }
        mock_bucket_instance.get_organization_bucket.return_value = 'test-org-bucket'
        
        # Mock the upload method for flat upload
        mock_upload_instance.upload_batch_django_files_optimized.return_value = {
            'success': True,
            'results': [
                {
                    'file_name': 'test_file_1.txt',
                    's3_key': 'data/flat_folder/test_file_1.txt',
                    'file_size': 14,
                    'content_type': 'text/plain'
                },
                {
                    'file_name': 'test_file_2.txt',
                    's3_key': 'data/flat_folder/test_file_2.txt',
                    'file_size': 14,
                    'content_type': 'text/plain'
                }
            ],
            'failures': []
        }
        
        files = [
            SimpleUploadedFile("test_file_1.txt", b"Test content 1", content_type="text/plain"),
            SimpleUploadedFile("test_file_2.txt", b"Test content 2", content_type="text/plain")
        ]
        
        data = {
            'organization': 'test-org',
            'folder_name': 'data/flat_folder',
            'files': files
        }
        
        response = self.client.post(self.upload_url, data=data)
        
        assert response.status_code == 200
        response_data = response.json()
        assert response_data['success'] is True
        
        # Verify files are uploaded to flat structure
        results = response_data.get('results', [])
        s3_keys = [r['s3_key'] for r in results]
        assert 'data/flat_folder/test_file_1.txt' in s3_keys
        assert 'data/flat_folder/test_file_2.txt' in s3_keys