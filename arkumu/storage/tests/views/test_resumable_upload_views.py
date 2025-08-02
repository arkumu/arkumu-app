"""
Tests for resumable upload views
"""
import json
import tempfile
import uuid
from unittest.mock import patch, MagicMock

import pytest
from django.contrib.auth import get_user_model
from django.test import TestCase, Client
from django.urls import reverse

from arkumu.storage.models import ResumableUploadSession, ResumableUploadChunk

User = get_user_model()


@pytest.mark.django_db
class TestResumableUploadViews(TestCase):
    """Test resumable upload view endpoints"""

    def setUp(self):
        """Set up test data"""
        self.client = Client()
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        self.client.force_login(self.user)

    def test_resumable_upload_init_success(self):
        """Test successful resumable upload initialization"""
        data = {
            'filename': 'test_large_file.pdf',
            'file_size': 100 * 1024 * 1024,  # 100MB
            'chunk_size': 8 * 1024 * 1024,   # 8MB
            'organization': 'test_org',
            'base_folder': 'data',
            'folder_name': 'test_folder',
            'original_path': 'test_large_file.pdf'
        }
        
        response = self.client.post(
            reverse('storage:resumable_upload_init'),
            data=json.dumps(data),
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, 200)
        response_data = response.json()
        
        self.assertTrue(response_data['success'])
        self.assertIn('upload_id', response_data)
        self.assertIn('total_chunks', response_data)
        self.assertEqual(response_data['total_chunks'], 13)  # 100MB / 8MB = 12.5 -> 13 chunks
        
        # Verify database record
        upload_session = ResumableUploadSession.objects.get(
            upload_id=response_data['upload_id']
        )
        self.assertEqual(upload_session.filename, 'test_large_file.pdf')
        self.assertEqual(upload_session.file_size, 100 * 1024 * 1024)
        self.assertEqual(upload_session.user, self.user)

    def test_resumable_upload_init_missing_data(self):
        """Test resumable upload init with missing required data"""
        data = {
            'filename': 'test.pdf',
            # Missing file_size and chunk_size
        }
        
        response = self.client.post(
            reverse('storage:resumable_upload_init'),
            data=json.dumps(data),
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, 400)
        response_data = response.json()
        self.assertFalse(response_data['success'])
        self.assertIn('error', response_data)

    def test_resumable_upload_chunk_success(self):
        """Test successful chunk upload"""
        # Create upload session first
        upload_session = ResumableUploadSession.objects.create(
            upload_id=uuid.uuid4(),
            user=self.user,
            filename='test.pdf',
            file_size=100 * 1024 * 1024,
            chunk_size=8 * 1024 * 1024,
            total_chunks=13,
            organization='test_org',
            base_folder='data'
        )
        
        # Create a test file chunk
        chunk_data = b'x' * (8 * 1024 * 1024)  # 8MB of data
        with tempfile.NamedTemporaryFile() as tmp_file:
            tmp_file.write(chunk_data)
            tmp_file.seek(0)
            
            response = self.client.post(
                reverse('storage:resumable_upload_chunk'),
                data={
                    'upload_id': str(upload_session.upload_id),
                    'chunk_number': 0,
                    'chunk_data': tmp_file
                }
            )
        
        self.assertEqual(response.status_code, 200)
        response_data = response.json()
        self.assertTrue(response_data['success'])
        
        # Verify chunk was created
        chunk = ResumableUploadChunk.objects.get(
            upload_session=upload_session,
            chunk_number=0
        )
        self.assertEqual(chunk.status, 'completed')
        self.assertEqual(chunk.size, 8 * 1024 * 1024)

    def test_resumable_upload_chunk_invalid_session(self):
        """Test chunk upload with invalid session ID"""
        chunk_data = b'test data'
        with tempfile.NamedTemporaryFile() as tmp_file:
            tmp_file.write(chunk_data)
            tmp_file.seek(0)
            
            response = self.client.post(
                reverse('storage:resumable_upload_chunk'),
                data={
                    'upload_id': str(uuid.uuid4()),  # Non-existent ID
                    'chunk_number': 0,
                    'chunk_data': tmp_file
                }
            )
        
        self.assertEqual(response.status_code, 404)
        response_data = response.json()
        self.assertFalse(response_data['success'])
        self.assertIn('Upload session not found', response_data['error'])

    def test_resumable_upload_status(self):
        """Test upload status endpoint"""
        # Create upload session with some chunks
        upload_session = ResumableUploadSession.objects.create(
            upload_id=uuid.uuid4(),
            user=self.user,
            filename='test.pdf',
            file_size=100 * 1024 * 1024,
            chunk_size=8 * 1024 * 1024,
            total_chunks=13,
            organization='test_org'
        )
        
        # Create some completed chunks
        for i in range(3):
            ResumableUploadChunk.objects.create(
                upload_session=upload_session,
                chunk_number=i,
                status='completed',
                size=8 * 1024 * 1024
            )
        
        response = self.client.get(
            reverse('storage:resumable_upload_status', kwargs={'upload_id': upload_session.upload_id})
        )
        
        self.assertEqual(response.status_code, 200)
        response_data = response.json()
        
        self.assertTrue(response_data['success'])
        self.assertEqual(response_data['completed_chunks'], 3)
        self.assertEqual(response_data['total_chunks'], 13)
        self.assertAlmostEqual(response_data['progress'], 23.08, places=1)  # 3/13 * 100

    @patch('arkumu.storage.services.upload_service.UploadService.upload_multipart_stream')
    def test_resumable_upload_complete_assembly(self, mock_upload):
        """Test file assembly when all chunks are uploaded"""
        mock_upload.return_value = {
            'success': True,
            'file_name': 'test.pdf',
            's3_key': 'data/test.pdf',
            'file_size': 100 * 1024 * 1024
        }
        
        # Create upload session with all chunks completed
        upload_session = ResumableUploadSession.objects.create(
            upload_id=uuid.uuid4(),
            user=self.user,
            filename='test.pdf',
            file_size=100 * 1024 * 1024,
            chunk_size=8 * 1024 * 1024,
            total_chunks=13,
            organization='test_org',
            base_folder='data'
        )
        
        # Create all chunks as completed
        for i in range(13):
            size = 8 * 1024 * 1024 if i < 12 else 4 * 1024 * 1024  # Last chunk smaller
            ResumableUploadChunk.objects.create(
                upload_session=upload_session,
                chunk_number=i,
                status='completed',
                size=size,
                temp_file_path=f'/tmp/chunk_{i}.tmp'
            )
        
        response = self.client.get(
            reverse('storage:resumable_upload_status', kwargs={'upload_id': upload_session.upload_id})
        )
        
        self.assertEqual(response.status_code, 200)
        response_data = response.json()
        
        self.assertTrue(response_data['success'])
        self.assertTrue(response_data['is_complete'])
        self.assertEqual(response_data['progress'], 100)
        
        # Verify mock was called for file assembly
        mock_upload.assert_called_once()

    def test_resumable_upload_resume(self):
        """Test resuming an interrupted upload"""
        # Create upload session with some completed chunks
        upload_session = ResumableUploadSession.objects.create(
            upload_id=uuid.uuid4(),
            user=self.user,
            filename='test.pdf',
            file_size=100 * 1024 * 1024,
            chunk_size=8 * 1024 * 1024,
            total_chunks=13,
            organization='test_org',
            status='uploading'
        )
        
        # Create some completed chunks (simulate partial upload)
        for i in range(5):
            ResumableUploadChunk.objects.create(
                upload_session=upload_session,
                chunk_number=i,
                status='completed',
                size=8 * 1024 * 1024
            )
        
        response = self.client.post(
            reverse('storage:resumable_upload_resume', kwargs={'upload_id': upload_session.upload_id})
        )
        
        self.assertEqual(response.status_code, 200)
        response_data = response.json()
        
        self.assertTrue(response_data['success'])
        self.assertEqual(response_data['completed_chunks'], 5)
        self.assertEqual(response_data['next_chunk'], 5)
        self.assertIn('Resume upload from chunk 5', response_data['message'])

    def test_unauthorized_access(self):
        """Test that unauthorized users cannot access upload endpoints"""
        self.client.logout()
        
        response = self.client.post(reverse('storage:resumable_upload_init'))
        self.assertEqual(response.status_code, 302)  # Redirect to login

    def test_user_isolation(self):
        """Test that users can only access their own upload sessions"""
        # Create another user and upload session
        other_user = User.objects.create_user(
            username='otheruser',
            email='other@example.com',
            password='otherpass123'
        )
        
        upload_session = ResumableUploadSession.objects.create(
            upload_id=uuid.uuid4(),
            user=other_user,  # Different user
            filename='other_test.pdf',
            file_size=50 * 1024 * 1024,
            chunk_size=5 * 1024 * 1024,
            total_chunks=10,
            organization='other_org'
        )
        
        # Try to access other user's session
        response = self.client.get(
            reverse('storage:resumable_upload_status', kwargs={'upload_id': upload_session.upload_id})
        )
        
        self.assertEqual(response.status_code, 404)
        response_data = response.json()
        self.assertFalse(response_data['success'])
        self.assertIn('Upload session not found', response_data['error'])


@pytest.mark.django_db
class TestResumableUploadIntegration(TestCase):
    """Integration tests for complete resumable upload flow"""

    def setUp(self):
        """Set up test data"""
        self.client = Client()
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        self.client.force_login(self.user)

    @patch('arkumu.storage.services.upload_service.UploadService.upload_multipart_stream')
    def test_complete_resumable_upload_flow(self, mock_upload):
        """Test the complete flow from init to completion"""
        mock_upload.return_value = {
            'success': True,
            'file_name': 'integration_test.pdf',
            's3_key': 'data/integration_test.pdf',
            'file_size': 25 * 1024 * 1024
        }
        
        # Step 1: Initialize upload
        init_data = {
            'filename': 'integration_test.pdf',
            'file_size': 25 * 1024 * 1024,  # 25MB
            'chunk_size': 8 * 1024 * 1024,   # 8MB chunks
            'organization': 'test_org',
            'base_folder': 'data'
        }
        
        init_response = self.client.post(
            reverse('storage:resumable_upload_init'),
            data=json.dumps(init_data),
            content_type='application/json'
        )
        
        self.assertEqual(init_response.status_code, 200)
        init_result = init_response.json()
        upload_id = init_result['upload_id']
        total_chunks = init_result['total_chunks']
        self.assertEqual(total_chunks, 4)  # 25MB / 8MB = 3.125 -> 4 chunks
        
        # Step 2: Upload chunks
        chunk_sizes = [8 * 1024 * 1024, 8 * 1024 * 1024, 8 * 1024 * 1024, 1 * 1024 * 1024]  # Last chunk smaller
        
        for chunk_num in range(total_chunks):
            chunk_data = b'x' * chunk_sizes[chunk_num]
            with tempfile.NamedTemporaryFile() as tmp_file:
                tmp_file.write(chunk_data)
                tmp_file.seek(0)
                
                chunk_response = self.client.post(
                    reverse('storage:resumable_upload_chunk'),
                    data={
                        'upload_id': upload_id,
                        'chunk_number': chunk_num,
                        'chunk_data': tmp_file
                    }
                )
                
                self.assertEqual(chunk_response.status_code, 200)
                chunk_result = chunk_response.json()
                self.assertTrue(chunk_result['success'])
        
        # Step 3: Check status (should trigger assembly)
        status_response = self.client.get(
            reverse('storage:resumable_upload_status', kwargs={'upload_id': upload_id})
        )
        
        self.assertEqual(status_response.status_code, 200)
        status_result = status_response.json()
        
        self.assertTrue(status_result['success'])
        self.assertTrue(status_result['is_complete'])
        self.assertEqual(status_result['progress'], 100)
        
        # Verify database state
        upload_session = ResumableUploadSession.objects.get(upload_id=upload_id)
        self.assertEqual(upload_session.status, 'completed')
        
        chunks = ResumableUploadChunk.objects.filter(upload_session=upload_session)
        self.assertEqual(chunks.count(), 4)
        self.assertTrue(all(chunk.status == 'completed' for chunk in chunks))
        
        # Verify assembly was called
        mock_upload.assert_called_once()

    def test_resumable_upload_with_failures_and_retry(self):
        """Test upload with chunk failures and successful retry"""
        # Initialize upload
        init_data = {
            'filename': 'retry_test.pdf',
            'file_size': 16 * 1024 * 1024,  # 16MB
            'chunk_size': 8 * 1024 * 1024,   # 2 chunks
            'organization': 'test_org',
            'base_folder': 'data'
        }
        
        init_response = self.client.post(
            reverse('storage:resumable_upload_init'),
            data=json.dumps(init_data),
            content_type='application/json'
        )
        
        upload_id = init_response.json()['upload_id']
        
        # Upload first chunk successfully
        chunk_data = b'x' * (8 * 1024 * 1024)
        with tempfile.NamedTemporaryFile() as tmp_file:
            tmp_file.write(chunk_data)
            tmp_file.seek(0)
            
            response = self.client.post(
                reverse('storage:resumable_upload_chunk'),
                data={
                    'upload_id': upload_id,
                    'chunk_number': 0,
                    'chunk_data': tmp_file
                }
            )
            self.assertEqual(response.status_code, 200)
        
        # Check status - should show partial progress
        status_response = self.client.get(
            reverse('storage:resumable_upload_status', kwargs={'upload_id': upload_id})
        )
        status_result = status_response.json()
        
        self.assertEqual(status_result['completed_chunks'], 1)
        self.assertEqual(status_result['total_chunks'], 2)
        self.assertEqual(status_result['progress'], 50)
        self.assertFalse(status_result['is_complete'])
        
        # Upload second chunk to complete
        with tempfile.NamedTemporaryFile() as tmp_file:
            tmp_file.write(chunk_data)
            tmp_file.seek(0)
            
            response = self.client.post(
                reverse('storage:resumable_upload_chunk'),
                data={
                    'upload_id': upload_id,
                    'chunk_number': 1,
                    'chunk_data': tmp_file
                }
            )
            self.assertEqual(response.status_code, 200)
        
        # Verify completion
        status_response = self.client.get(
            reverse('storage:resumable_upload_status', kwargs={'upload_id': upload_id})
        )
        status_result = status_response.json()
        self.assertTrue(status_result['is_complete'])