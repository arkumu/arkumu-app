import pytest
import json
import time
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime
import redis

from arkumu.storage.services.redis_resumable_storage import RedisResumableStorage


@pytest.fixture
def mock_redis_client():
    """Create a mock Redis client."""
    client = Mock()
    client.setex = Mock(return_value=True)
    client.get = Mock(return_value=None)
    client.delete = Mock(return_value=1)
    client.expire = Mock(return_value=True)
    client.scan_iter = Mock(return_value=[])
    return client


@pytest.fixture
def storage_service(mock_redis_client):
    """Create a RedisResumableStorage instance with mocked Redis client."""
    with patch('arkumu.storage.services.redis_resumable_storage.redis.from_url', return_value=mock_redis_client):
        service = RedisResumableStorage()
        service.client = mock_redis_client
        return service


class TestRedisResumableStorage:
    """Test cases for RedisResumableStorage service."""
    
    def test_init(self):
        """Test service initialization."""
        with patch('arkumu.storage.services.redis_resumable_storage.redis.from_url') as mock_from_url:
            service = RedisResumableStorage()
            mock_from_url.assert_called_once_with('redis://redis:6379/0')
            assert service.chunk_ttl == 3600
            assert service.session_ttl == 86400
            assert service.chunk_prefix == "resumable_chunk"
            assert service.session_prefix == "resumable_session"
    
    def test_create_upload_session(self, storage_service, mock_redis_client):
        """Test creating a new upload session."""
        upload_id = "test-upload-123"
        filename = "test-file.pdf"
        file_size = 1024 * 1024 * 10  # 10MB
        mime_type = "application/pdf"
        metadata = {"user_id": 1, "organization": "test-org"}
        
        result = storage_service.create_upload_session(
            upload_id=upload_id,
            filename=filename,
            file_size=file_size,
            mime_type=mime_type,
            metadata=metadata
        )
        
        # Verify result
        assert result['upload_id'] == upload_id
        assert result['filename'] == filename
        assert result['file_size'] == file_size
        assert result['mime_type'] == mime_type
        assert result['metadata'] == metadata
        assert result['status'] == 'uploading'
        assert result['uploaded_chunks'] == []
        assert result['uploaded_bytes'] == 0
        
        # Verify Redis call
        mock_redis_client.setex.assert_called_once()
        call_args = mock_redis_client.setex.call_args
        assert call_args[0][0] == f"resumable_session:{upload_id}"
        assert call_args[0][1] == 86400  # session TTL
        
    def test_get_upload_info(self, storage_service, mock_redis_client):
        """Test retrieving upload session information."""
        upload_id = "test-upload-123"
        session_data = {
            'upload_id': upload_id,
            'filename': 'test.pdf',
            'status': 'uploading'
        }
        mock_redis_client.get.return_value = json.dumps(session_data).encode()
        
        result = storage_service.get_upload_info(upload_id)
        
        assert result == session_data
        mock_redis_client.get.assert_called_once_with(f"resumable_session:{upload_id}")
    
    def test_get_upload_info_not_found(self, storage_service, mock_redis_client):
        """Test retrieving non-existent upload session."""
        mock_redis_client.get.return_value = None
        
        result = storage_service.get_upload_info("non-existent")
        
        assert result is None
    
    def test_update_upload_session(self, storage_service, mock_redis_client):
        """Test updating upload session."""
        upload_id = "test-upload-123"
        session_data = {
            'upload_id': upload_id,
            'filename': 'test.pdf',
            'status': 'uploading',
            'uploaded_bytes': 0
        }
        mock_redis_client.get.return_value = json.dumps(session_data).encode()
        
        updates = {'uploaded_bytes': 1024, 'status': 'paused'}
        result = storage_service.update_upload_session(upload_id, updates)
        
        assert result is True
        
        # Verify the updated data was saved
        saved_call = mock_redis_client.setex.call_args
        saved_data = json.loads(saved_call[0][2])
        assert saved_data['uploaded_bytes'] == 1024
        assert saved_data['status'] == 'paused'
        assert 'updated_at' in saved_data
    
    def test_store_chunk(self, storage_service, mock_redis_client):
        """Test storing a chunk."""
        upload_id = "test-upload-123"
        chunk_index = 0
        chunk_data = b"test chunk data"
        
        # Mock session data
        session_data = {
            'upload_id': upload_id,
            'uploaded_chunks': [],
            'uploaded_bytes': 0
        }
        mock_redis_client.get.return_value = json.dumps(session_data).encode()
        
        result = storage_service.store_chunk(upload_id, chunk_index, chunk_data)
        
        assert result is True
        
        # Verify chunk was stored
        chunk_call = mock_redis_client.setex.call_args_list[0]
        assert chunk_call[0][0] == f"resumable_chunk:{upload_id}:{chunk_index}"
        assert chunk_call[0][1] == 3600  # chunk TTL
        assert chunk_call[0][2] == chunk_data
    
    def test_get_chunk(self, storage_service, mock_redis_client):
        """Test retrieving a chunk."""
        upload_id = "test-upload-123"
        chunk_index = 0
        chunk_data = b"test chunk data"
        mock_redis_client.get.return_value = chunk_data
        
        result = storage_service.get_chunk(upload_id, chunk_index)
        
        assert result == chunk_data
        mock_redis_client.get.assert_called_with(f"resumable_chunk:{upload_id}:{chunk_index}")
    
    def test_get_uploaded_chunks(self, storage_service, mock_redis_client):
        """Test getting list of uploaded chunks."""
        upload_id = "test-upload-123"
        session_data = {
            'upload_id': upload_id,
            'uploaded_chunks': [0, 1, 2, 3]
        }
        mock_redis_client.get.return_value = json.dumps(session_data).encode()
        
        result = storage_service.get_uploaded_chunks(upload_id)
        
        assert result == [0, 1, 2, 3]
    
    def test_delete_chunk(self, storage_service, mock_redis_client):
        """Test deleting a specific chunk."""
        upload_id = "test-upload-123"
        chunk_index = 0
        
        result = storage_service.delete_chunk(upload_id, chunk_index)
        
        assert result is True
        mock_redis_client.delete.assert_called_once_with(f"resumable_chunk:{upload_id}:{chunk_index}")
    
    def test_delete_all_chunks(self, storage_service, mock_redis_client):
        """Test deleting all chunks for an upload."""
        upload_id = "test-upload-123"
        chunk_keys = [
            f"resumable_chunk:{upload_id}:0",
            f"resumable_chunk:{upload_id}:1",
            f"resumable_chunk:{upload_id}:2"
        ]
        mock_redis_client.scan_iter.return_value = chunk_keys
        mock_redis_client.delete.return_value = 3
        
        result = storage_service.delete_all_chunks(upload_id)
        
        assert result == 3
        mock_redis_client.delete.assert_called_once_with(*chunk_keys)
    
    @patch('arkumu.storage.services.redis_resumable_storage.settings')
    @patch('arkumu.storage.services.redis_resumable_storage.os.makedirs')
    @patch('arkumu.storage.services.redis_resumable_storage.open', create=True)
    @patch('arkumu.storage.services.redis_resumable_storage.os.unlink')
    def test_assemble_file(self, mock_unlink, mock_open, mock_makedirs, mock_settings, storage_service, mock_redis_client):
        """Test assembling chunks into a complete file."""
        # Mock settings
        mock_settings.FILE_UPLOAD_TEMP_DIR = '/tmp'
        
        upload_id = "test-upload-123"
        session_data = {
            'upload_id': upload_id,
            'uploaded_chunks': [0, 1, 2]
        }
        mock_redis_client.get.side_effect = [
            json.dumps(session_data).encode(),  # Session data
            b"chunk0",  # Chunk 0
            b"chunk1",  # Chunk 1
            b"chunk2"   # Chunk 2
        ]
        
        # Mock file operations
        mock_file = MagicMock()
        mock_open.return_value.__enter__.return_value = mock_file
        
        result = storage_service.assemble_file(upload_id)
        
        assert result == f"/tmp/assembled_{upload_id}"
        mock_makedirs.assert_called_once_with('/tmp', exist_ok=True)
        
        # Verify chunks were written in order
        assert mock_file.write.call_count == 3
        mock_file.write.assert_any_call(b"chunk0")
        mock_file.write.assert_any_call(b"chunk1")
        mock_file.write.assert_any_call(b"chunk2")
    
    @patch('arkumu.storage.services.redis_resumable_storage.settings')
    @patch('arkumu.storage.services.redis_resumable_storage.os.makedirs')
    @patch('arkumu.storage.services.redis_resumable_storage.open', create=True)
    @patch('arkumu.storage.services.redis_resumable_storage.os.unlink')
    @patch('arkumu.storage.services.redis_resumable_storage.os.path.exists')
    def test_assemble_file_missing_chunk(self, mock_exists, mock_unlink, mock_open, mock_makedirs, 
                                        mock_settings, storage_service, mock_redis_client):
        """Test assembling file with missing chunk."""
        # Mock settings
        mock_settings.FILE_UPLOAD_TEMP_DIR = '/tmp'
        
        upload_id = "test-upload-123"
        session_data = {
            'upload_id': upload_id,
            'uploaded_chunks': [0, 1, 2]
        }
        mock_redis_client.get.side_effect = [
            json.dumps(session_data).encode(),  # Session data
            b"chunk0",  # Chunk 0
            None,       # Chunk 1 missing
            b"chunk2"   # Chunk 2
        ]
        mock_exists.return_value = True
        
        # Mock file operations
        mock_file = MagicMock()
        mock_open.return_value.__enter__.return_value = mock_file
        
        result = storage_service.assemble_file(upload_id)
        
        assert result is None
        mock_unlink.assert_called_once()  # Cleanup on failure
    
    def test_complete_upload(self, storage_service, mock_redis_client):
        """Test completing an upload."""
        upload_id = "test-upload-123"
        session_data = {'upload_id': upload_id, 'status': 'uploading'}
        mock_redis_client.get.return_value = json.dumps(session_data).encode()
        mock_redis_client.scan_iter.return_value = [f"resumable_chunk:{upload_id}:0"]
        
        result = storage_service.complete_upload(upload_id)
        
        assert result is True
        # Verify status was updated
        saved_call = mock_redis_client.setex.call_args
        saved_data = json.loads(saved_call[0][2])
        assert saved_data['status'] == 'completed'
    
    def test_cancel_upload(self, storage_service, mock_redis_client):
        """Test cancelling an upload."""
        upload_id = "test-upload-123"
        mock_redis_client.scan_iter.return_value = [f"resumable_chunk:{upload_id}:0"]
        mock_redis_client.delete.return_value = 1
        
        result = storage_service.cancel_upload(upload_id)
        
        assert result is True
        # Verify session was deleted
        assert any(f"resumable_session:{upload_id}" in str(call) for call in mock_redis_client.delete.call_args_list)
    
    def test_get_active_uploads(self, storage_service, mock_redis_client):
        """Test getting active uploads."""
        session_keys = ["resumable_session:upload1", "resumable_session:upload2"]
        session_data1 = {
            'upload_id': 'upload1',
            'status': 'uploading',
            'metadata': {'user_id': 1}
        }
        session_data2 = {
            'upload_id': 'upload2',
            'status': 'completed',  # Not active
            'metadata': {'user_id': 1}
        }
        
        mock_redis_client.scan_iter.return_value = session_keys
        mock_redis_client.get.side_effect = [
            json.dumps(session_data1).encode(),
            json.dumps(session_data2).encode()
        ]
        
        result = storage_service.get_active_uploads(user_id=1)
        
        assert len(result) == 1
        assert result[0]['upload_id'] == 'upload1'
    
    def test_extend_ttl(self, storage_service, mock_redis_client):
        """Test extending TTL for upload session and chunks."""
        upload_id = "test-upload-123"
        chunk_keys = [f"resumable_chunk:{upload_id}:0", f"resumable_chunk:{upload_id}:1"]
        
        mock_redis_client.expire.return_value = True
        mock_redis_client.scan_iter.return_value = chunk_keys
        
        result = storage_service.extend_ttl(upload_id, 3600)
        
        assert result is True
        # Verify session TTL was extended
        session_call = mock_redis_client.expire.call_args_list[0]
        assert session_call[0][0] == f"resumable_session:{upload_id}"
        assert session_call[0][1] == 86400 + 3600  # original + additional
    
    def test_get_upload_progress(self, storage_service, mock_redis_client):
        """Test getting upload progress."""
        upload_id = "test-upload-123"
        session_data = {
            'upload_id': upload_id,
            'filename': 'test.pdf',
            'status': 'uploading',
            'uploaded_chunks': [0, 1, 2],
            'total_chunks': 5,
            'uploaded_bytes': 15728640,  # 15MB
            'file_size': 26214400,  # 25MB
            'created_at': '2024-01-01T00:00:00',
            'updated_at': '2024-01-01T00:01:00'
        }
        mock_redis_client.get.return_value = json.dumps(session_data).encode()
        
        result = storage_service.get_upload_progress(upload_id)
        
        assert result['upload_id'] == upload_id
        assert result['filename'] == 'test.pdf'
        assert result['status'] == 'uploading'
        assert result['uploaded_chunks'] == 3
        assert result['total_chunks'] == 5
        assert result['uploaded_bytes'] == 15728640
        assert result['file_size'] == 26214400
        assert result['progress_percentage'] == 60.0
    
    def test_get_upload_progress_not_found(self, storage_service, mock_redis_client):
        """Test getting progress for non-existent upload."""
        mock_redis_client.get.return_value = None
        
        result = storage_service.get_upload_progress("non-existent")
        
        assert result == {'error': 'Upload not found'}


@pytest.mark.django_db
class TestRedisResumableStorageIntegration:
    """Integration tests with real Redis (if available)."""
    
    @pytest.mark.skipif(not hasattr(pytest, 'redis_available'), reason="Redis not available")
    def test_full_upload_lifecycle(self):
        """Test complete upload lifecycle with real Redis."""
        storage = RedisResumableStorage()
        upload_id = f"test-{int(time.time())}"
        
        # Create session
        session = storage.create_upload_session(
            upload_id=upload_id,
            filename="test.pdf",
            file_size=1024 * 1024,
            metadata={'user_id': 1}
        )
        assert session['upload_id'] == upload_id
        
        # Store chunks
        for i in range(3):
            chunk_data = f"chunk{i}".encode()
            assert storage.store_chunk(upload_id, i, chunk_data) is True
        
        # Verify chunks
        assert len(storage.get_uploaded_chunks(upload_id)) == 3
        
        # Complete upload
        assert storage.complete_upload(upload_id) is True
        
        # Verify chunks are cleaned up
        assert storage.get_chunk(upload_id, 0) is None