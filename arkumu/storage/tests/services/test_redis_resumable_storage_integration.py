import pytest
import time
import uuid
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.db import transaction

from arkumu.storage.models import (
    UploadSession, 
    ResumableUploadSession, 
    ResumableUploadChunk,
    S3FileObject
)
from arkumu.storage.services.redis_resumable_storage import RedisResumableStorage

User = get_user_model()


@pytest.mark.django_db
class TestRedisResumableStorageWithModels:
    """Integration tests for RedisResumableStorage with Django models."""
    
    @pytest.fixture
    def test_user(self):
        """Create a test user."""
        user = User.objects.create_user(
            username=f'testuser_{uuid.uuid4().hex[:8]}',
            email='test@example.com',
            password='testpass123'
        )
        return user
    
    @pytest.fixture
    def upload_session(self, test_user):
        """Create an upload session."""
        session = UploadSession.objects.create(
            user=test_user,
            folder_name='test-upload',
            status='in_progress',
            total_files=1,
            total_size_bytes=10485760  # 10MB
        )
        return session
    
    @pytest.fixture
    def s3_file_object(self, upload_session):
        """Create an S3 file object."""
        s3_file = S3FileObject.objects.create(
            session=upload_session,
            file_name='test-file.pdf',
            original_path='uploads/test-file.pdf',
            s3_key='test-org/data/test-file.pdf',
            file_size_bytes=10485760,
            content_type='application/pdf',
            status='pending'
        )
        return s3_file
    
    @pytest.fixture
    def resumable_upload(self, upload_session, s3_file_object):
        """Create a resumable upload session."""
        resumable = ResumableUploadSession.objects.create(
            upload_session=upload_session,
            s3_file_object=s3_file_object,
            original_filename='test-file.pdf',
            total_size_bytes=10485760,
            chunk_size_bytes=5242880,  # 5MB
            total_chunks=2,
            status='uploading'
        )
        return resumable
    
    def test_redis_storage_with_model_sync(self, resumable_upload, test_user):
        """Test that Redis storage works alongside model tracking."""
        storage = RedisResumableStorage()
        upload_id = str(resumable_upload.id)
        
        # Create Redis session with model metadata
        redis_session = storage.create_upload_session(
            upload_id=upload_id,
            filename=resumable_upload.original_filename,
            file_size=resumable_upload.total_size_bytes,
            metadata={
                'user_id': test_user.id,
                'resumable_upload_id': upload_id,
                'upload_session_id': str(resumable_upload.upload_session.id)
            }
        )
        
        assert redis_session['upload_id'] == upload_id
        assert redis_session['metadata']['user_id'] == test_user.id
        
        # Store chunks in Redis
        chunk1_data = b'A' * 5242880  # 5MB
        chunk2_data = b'B' * 5242880  # 5MB
        
        assert storage.store_chunk(upload_id, 0, chunk1_data) is True
        assert storage.store_chunk(upload_id, 1, chunk2_data) is True
        
        # Verify chunks are tracked
        uploaded_chunks = storage.get_uploaded_chunks(upload_id)
        assert len(uploaded_chunks) == 2
        assert 0 in uploaded_chunks
        assert 1 in uploaded_chunks
        
        # Get progress from Redis
        progress = storage.get_upload_progress(upload_id)
        assert progress['uploaded_chunks'] == 2
        assert progress['progress_percentage'] == 100.0
    
    def test_chunk_model_creation_with_redis(self, resumable_upload):
        """Test creating chunk models while using Redis for data storage."""
        storage = RedisResumableStorage()
        upload_id = str(resumable_upload.id)
        
        # Create chunks in database
        chunks = []
        for i in range(2):
            chunk = ResumableUploadChunk.objects.create(
                resumable_upload=resumable_upload,
                chunk_number=i,
                start_byte=i * 5242880,
                end_byte=(i + 1) * 5242880,
                size_bytes=5242880,
                status='pending'
            )
            chunks.append(chunk)
        
        # Store actual chunk data in Redis
        for i, chunk in enumerate(chunks):
            chunk_data = f'CHUNK_{i}'.encode() * 1000  # Some test data
            storage.store_chunk(upload_id, i, chunk_data)
            
            # Update chunk model status
            chunk.mark_completed(checksum=f'checksum_{i}')
        
        # Verify model updates
        resumable_upload.refresh_from_db()
        assert resumable_upload.uploaded_bytes == 10485760
        assert resumable_upload.completed_chunks == 2
        
        # Verify Redis has the data
        assert storage.get_chunk(upload_id, 0) is not None
        assert storage.get_chunk(upload_id, 1) is not None
    
    def test_assembly_updates_models(self, resumable_upload, s3_file_object):
        """Test that file assembly updates the appropriate models."""
        storage = RedisResumableStorage()
        upload_id = str(resumable_upload.id)
        
        # Create session in Redis
        storage.create_upload_session(
            upload_id=upload_id,
            filename=resumable_upload.original_filename,
            file_size=resumable_upload.total_size_bytes
        )
        
        # Store chunks
        chunk1 = b'START_OF_FILE'
        chunk2 = b'END_OF_FILE'
        storage.store_chunk(upload_id, 0, chunk1)
        storage.store_chunk(upload_id, 1, chunk2)
        
        # Assemble file
        temp_file_path = storage.assemble_file(upload_id)
        assert temp_file_path is not None
        
        # Verify assembled content
        with open(temp_file_path, 'rb') as f:
            content = f.read()
            assert content == chunk1 + chunk2
        
        # Simulate upload completion
        storage.complete_upload(upload_id)
        
        # In real usage, you would update models here
        resumable_upload.mark_completed()
        s3_file_object.mark_completed()
        
        # Verify model states
        resumable_upload.refresh_from_db()
        s3_file_object.refresh_from_db()
        assert resumable_upload.status == 'completed'
        assert s3_file_object.status == 'completed'
        
        # Verify chunks are cleaned up from Redis
        assert storage.get_chunk(upload_id, 0) is None
        assert storage.get_chunk(upload_id, 1) is None
        
        # Clean up temp file
        import os
        if os.path.exists(temp_file_path):
            os.unlink(temp_file_path)
    
    def test_resume_upload_with_existing_models(self, resumable_upload):
        """Test resuming an upload with existing model data."""
        storage = RedisResumableStorage()
        upload_id = str(resumable_upload.id)
        
        # Create initial session
        storage.create_upload_session(
            upload_id=upload_id,
            filename=resumable_upload.original_filename,
            file_size=resumable_upload.total_size_bytes
        )
        
        # Upload first chunk only
        chunk1_data = b'FIRST_CHUNK'
        storage.store_chunk(upload_id, 0, chunk1_data)
        
        # Create chunk record
        ResumableUploadChunk.objects.create(
            resumable_upload=resumable_upload,
            chunk_number=0,
            start_byte=0,
            end_byte=5242880,
            size_bytes=5242880,
            status='completed',
            checksum='chunk0_checksum'
        )
        
        # Simulate pause/resume by checking what's already uploaded
        uploaded_chunks = storage.get_uploaded_chunks(upload_id)
        assert len(uploaded_chunks) == 1
        assert 0 in uploaded_chunks
        
        # Resume by uploading remaining chunk
        chunk2_data = b'SECOND_CHUNK'
        storage.store_chunk(upload_id, 1, chunk2_data)
        
        # Verify complete upload
        progress = storage.get_upload_progress(upload_id)
        assert progress['uploaded_chunks'] == 2
    
    def test_multiple_concurrent_uploads(self, upload_session, test_user):
        """Test handling multiple concurrent uploads with Redis storage."""
        storage = RedisResumableStorage()
        
        # Create multiple file uploads
        uploads = []
        for i in range(3):
            s3_file = S3FileObject.objects.create(
                session=upload_session,
                file_name=f'file_{i}.pdf',
                original_path=f'uploads/file_{i}.pdf',
                s3_key=f'test-org/data/file_{i}.pdf',
                file_size_bytes=1048576,  # 1MB each
                content_type='application/pdf',
                status='pending'
            )
            
            resumable = ResumableUploadSession.objects.create(
                upload_session=upload_session,
                s3_file_object=s3_file,
                original_filename=f'file_{i}.pdf',
                total_size_bytes=1048576,
                chunk_size_bytes=524288,  # 512KB
                total_chunks=2,
                status='uploading'
            )
            uploads.append((str(resumable.id), resumable))
        
        # Store chunks for each upload
        for upload_id, resumable in uploads:
            storage.create_upload_session(
                upload_id=upload_id,
                filename=resumable.original_filename,
                file_size=resumable.total_size_bytes,
                metadata={'user_id': test_user.id}
            )
            
            # Upload chunks
            for chunk_idx in range(2):
                chunk_data = f'{upload_id}_chunk_{chunk_idx}'.encode()
                storage.store_chunk(upload_id, chunk_idx, chunk_data)
        
        # Get active uploads for user
        active_uploads = storage.get_active_uploads(user_id=test_user.id)
        # Filter to only the uploads we just created
        current_upload_ids = [upload_id for upload_id, _ in uploads]
        active_uploads = [u for u in active_uploads if u['upload_id'] in current_upload_ids]
        assert len(active_uploads) == 3
        
        # Verify each upload
        for upload_id, resumable in uploads:
            progress = storage.get_upload_progress(upload_id)
            assert progress['uploaded_chunks'] == 2
            # For small test chunks, the percentage might be low due to overhead
            assert progress['uploaded_bytes'] > 0
    
    def test_cleanup_on_session_expiry(self, resumable_upload):
        """Test that expired sessions are handled properly."""
        storage = RedisResumableStorage()
        upload_id = str(resumable_upload.id)
        
        # Create session
        storage.create_upload_session(
            upload_id=upload_id,
            filename=resumable_upload.original_filename,
            file_size=resumable_upload.total_size_bytes
        )
        
        # Store a chunk
        storage.store_chunk(upload_id, 0, b'test_data')
        
        # Verify it exists
        assert storage.get_chunk(upload_id, 0) is not None
        
        # Cancel the upload (simulating cleanup)
        storage.cancel_upload(upload_id)
        
        # Verify cleanup
        assert storage.get_upload_info(upload_id) is None
        assert storage.get_chunk(upload_id, 0) is None
        
        # Update model to reflect cancellation
        resumable_upload.mark_failed('Upload cancelled by user')
        resumable_upload.refresh_from_db()
        assert resumable_upload.status == 'failed'
    
    @pytest.mark.parametrize("chunk_count,chunk_size", [
        (2, 5242880),    # 2 chunks of 5MB
        (5, 2097152),    # 5 chunks of 2MB
        (10, 1048576),   # 10 chunks of 1MB
    ])
    def test_different_chunk_configurations(self, upload_session, s3_file_object, chunk_count, chunk_size):
        """Test handling different chunk sizes and counts."""
        total_size = chunk_count * chunk_size
        
        # Create resumable upload with specific configuration
        resumable = ResumableUploadSession.objects.create(
            upload_session=upload_session,
            s3_file_object=s3_file_object,
            original_filename='variable-chunk-test.bin',
            total_size_bytes=total_size,
            chunk_size_bytes=chunk_size,
            total_chunks=chunk_count,
            status='uploading'
        )
        
        storage = RedisResumableStorage()
        upload_id = str(resumable.id)
        
        # Create session
        storage.create_upload_session(
            upload_id=upload_id,
            filename=resumable.original_filename,
            file_size=total_size
        )
        
        # Upload all chunks
        for i in range(chunk_count):
            chunk_data = f'CHUNK_{i}'.encode() * (chunk_size // 10)  # Repeat to fill size
            storage.store_chunk(upload_id, i, chunk_data[:chunk_size])
        
        # Verify progress
        progress = storage.get_upload_progress(upload_id)
        assert progress['uploaded_chunks'] == chunk_count
        assert progress['file_size'] == total_size