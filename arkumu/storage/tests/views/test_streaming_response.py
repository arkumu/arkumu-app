"""Test streaming response with proxy bypass headers"""
import pytest
from django.test import RequestFactory
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from unittest.mock import patch, MagicMock

from arkumu.storage.views.streaming_upload_views import streaming_upload_form

User = get_user_model()


@pytest.mark.django_db
class TestStreamingResponse:
    """Test that streaming responses bypass proxy buffering"""
    
    @pytest.fixture
    def user(self):
        """Create test user"""
        return User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
    
    @pytest.fixture
    def request_factory(self):
        """Django request factory"""
        return RequestFactory()
    
    @pytest.fixture
    def mock_upload_service(self):
        """Mock upload service to avoid S3 calls"""
        with patch('arkumu.storage.views.streaming_upload_views.UploadService') as mock:
            service = MagicMock()
            mock.return_value = service
            
            # Mock successful upload
            service.upload_files_to_s3.return_value = {
                'success': True,
                'results': [
                    {
                        'file_name': 'test.jpg',
                        's3_key': 'data/test.jpg',
                        'file_size': 1024,
                        'content_type': 'image/jpeg',
                        's3_url': 'https://s3.example.com/bucket/data/test.jpg'
                    }
                ],
                'failures': [],
                'duration': 0.5,
                'total_size': 1024
            }
            yield service
    
    def test_streaming_response_headers(self, user, request_factory, mock_upload_service):
        """Test that successful upload returns StreamingHttpResponse with proxy bypass headers"""
        # Create test file
        test_file = SimpleUploadedFile(
            "test.jpg",
            b"fake image content",
            content_type="image/jpeg"
        )
        
        # Create POST request
        request = request_factory.post(
            '/storage/upload/streaming/',
            data={
                'organization': 'test-org',
                'folder_name': 'data',
                'files': test_file
            },
            format='multipart'
        )
        request.user = user
        request.META['HTTP_HX_REQUEST'] = 'true'  # HTMX request header
        
        # Call view
        response = streaming_upload_form(request)
        
        # Assertions
        assert response.status_code == 200
        assert response['X-Accel-Buffering'] == 'no'
        assert response['Cache-Control'] == 'no-cache, no-transform'
        assert response.streaming is True
        
        # Check content is generated properly
        content = b''.join(response.streaming_content).decode('utf-8')
        assert '✅ Uploaded 1 files' in content
        assert 'Refresh File Browser' in content
        assert 'hx-get="/storage/organizations/test-org/"' in content
    
    def test_non_htmx_request_returns_json(self, user, request_factory, mock_upload_service):
        """Test that non-HTMX requests still return JSON"""
        # Create test file
        test_file = SimpleUploadedFile(
            "test.jpg",
            b"fake image content",
            content_type="image/jpeg"
        )
        
        # Create POST request without HTMX header
        request = request_factory.post(
            '/storage/upload/streaming/',
            data={
                'organization': 'test-org',
                'folder_name': 'data',
                'files': test_file
            },
            format='multipart'
        )
        request.user = user
        # No HX-Request header
        
        # Call view
        response = streaming_upload_form(request)
        
        # Assertions
        assert response.status_code == 200
        assert response['Content-Type'] == 'application/json'
        assert not hasattr(response, 'streaming')
    
    def test_error_response_not_streaming(self, user, request_factory):
        """Test that error responses are not streamed"""
        # Create request without required fields
        request = request_factory.post(
            '/storage/upload/streaming/',
            data={},  # Missing required fields
            format='multipart'
        )
        request.user = user
        request.META['HTTP_HX_REQUEST'] = 'true'
        
        # Call view
        response = streaming_upload_form(request)
        
        # Assertions
        assert response.status_code == 400
        # Error responses should not be streaming
        assert not hasattr(response, 'streaming') or response.streaming is False