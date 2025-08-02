import logging
import redis
import json
import os
import tempfile
from datetime import datetime, timezone
from typing import Dict, Optional, List, Any
from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)


class RedisResumableStorage:
    """
    Service class for managing resumable uploads using Redis as the storage backend.
    Provides methods for storing chunks, tracking upload sessions, and assembling files.
    """
    
    def __init__(self):
        """Initialize Redis connection."""
        self.redis_url = getattr(settings, 'REDIS_URL', 'redis://redis:6379/0')
        self.client = redis.from_url(self.redis_url)
        self.chunk_ttl = 3600  # 1 hour TTL for chunks
        self.session_ttl = 86400  # 24 hour TTL for sessions
        self.chunk_prefix = "resumable_chunk"
        self.session_prefix = "resumable_session"
        
    def create_upload_session(self, upload_id: str, filename: str, file_size: int, 
                            mime_type: str = 'application/octet-stream', 
                            metadata: Optional[Dict] = None) -> Dict[str, Any]:
        """Create a new upload session."""
        session_key = f"{self.session_prefix}:{upload_id}"
        
        session_data = {
            'upload_id': upload_id,
            'filename': filename,
            'file_size': file_size,
            'mime_type': mime_type,
            'metadata': metadata or {},
            'status': 'uploading',
            'created_at': datetime.now(timezone.utc).isoformat(),
            'updated_at': datetime.now(timezone.utc).isoformat(),
            'uploaded_chunks': [],
            'uploaded_bytes': 0,
            'total_chunks': 0
        }
        
        # Store session data in Redis
        self.client.setex(
            session_key,
            self.session_ttl,
            json.dumps(session_data)
        )
        
        logger.info(f"Created upload session: {upload_id}")
        return session_data
    
    def get_upload_info(self, upload_id: str) -> Optional[Dict[str, Any]]:
        """Get upload session information."""
        session_key = f"{self.session_prefix}:{upload_id}"
        session_data = self.client.get(session_key)
        
        if session_data:
            return json.loads(session_data)
        return None
    
    def update_upload_session(self, upload_id: str, updates: Dict[str, Any]) -> bool:
        """Update upload session information."""
        session_info = self.get_upload_info(upload_id)
        if not session_info:
            return False
        
        # Update fields
        session_info.update(updates)
        session_info['updated_at'] = datetime.now(timezone.utc).isoformat()
        
        # Save back to Redis
        session_key = f"{self.session_prefix}:{upload_id}"
        self.client.setex(
            session_key,
            self.session_ttl,
            json.dumps(session_info)
        )
        
        return True
    
    def store_chunk(self, upload_id: str, chunk_index: int, chunk_data: bytes) -> bool:
        """Store a chunk in Redis."""
        chunk_key = f"{self.chunk_prefix}:{upload_id}:{chunk_index}"
        
        try:
            # Store chunk with TTL
            self.client.setex(chunk_key, self.chunk_ttl, chunk_data)
            
            # Update session with chunk info
            session_info = self.get_upload_info(upload_id)
            if session_info:
                uploaded_chunks = set(session_info.get('uploaded_chunks', []))
                uploaded_chunks.add(chunk_index)
                
                self.update_upload_session(upload_id, {
                    'uploaded_chunks': list(uploaded_chunks),
                    'uploaded_bytes': session_info.get('uploaded_bytes', 0) + len(chunk_data)
                })
            
            logger.info(f"Stored chunk {chunk_index} for upload {upload_id} (size: {len(chunk_data)} bytes)")
            return True
            
        except Exception as e:
            logger.error(f"Failed to store chunk {chunk_index} for upload {upload_id}: {str(e)}")
            return False
    
    def get_chunk(self, upload_id: str, chunk_index: int) -> Optional[bytes]:
        """Retrieve a chunk from Redis."""
        chunk_key = f"{self.chunk_prefix}:{upload_id}:{chunk_index}"
        return self.client.get(chunk_key)
    
    def get_uploaded_chunks(self, upload_id: str) -> List[int]:
        """Get list of uploaded chunk indices."""
        session_info = self.get_upload_info(upload_id)
        if session_info:
            return session_info.get('uploaded_chunks', [])
        return []
    
    def delete_chunk(self, upload_id: str, chunk_index: int) -> bool:
        """Delete a specific chunk."""
        chunk_key = f"{self.chunk_prefix}:{upload_id}:{chunk_index}"
        return bool(self.client.delete(chunk_key))
    
    def delete_all_chunks(self, upload_id: str) -> int:
        """Delete all chunks for an upload."""
        pattern = f"{self.chunk_prefix}:{upload_id}:*"
        keys = list(self.client.scan_iter(match=pattern))
        
        if keys:
            return self.client.delete(*keys)
        return 0
    
    def assemble_file(self, upload_id: str) -> Optional[str]:
        """Assemble all chunks into a complete file."""
        session_info = self.get_upload_info(upload_id)
        if not session_info:
            logger.error(f"Upload session not found: {upload_id}")
            return None
        
        uploaded_chunks = sorted(session_info.get('uploaded_chunks', []))
        if not uploaded_chunks:
            logger.error(f"No chunks found for upload: {upload_id}")
            return None
        
        # Create temp file for assembly
        temp_dir = getattr(settings, 'FILE_UPLOAD_TEMP_DIR', None) or '/tmp'
        os.makedirs(temp_dir, exist_ok=True)
        
        temp_file_path = os.path.join(temp_dir, f"assembled_{upload_id}")
        
        try:
            with open(temp_file_path, 'wb') as output_file:
                for chunk_index in uploaded_chunks:
                    chunk_data = self.get_chunk(upload_id, chunk_index)
                    if chunk_data:
                        output_file.write(chunk_data)
                        logger.info(f"Assembled chunk {chunk_index} for upload {upload_id}")
                    else:
                        logger.error(f"Missing chunk {chunk_index} for upload {upload_id}")
                        os.unlink(temp_file_path)
                        return None
            
            logger.info(f"Successfully assembled file for upload {upload_id}")
            return temp_file_path
            
        except Exception as e:
            logger.error(f"Failed to assemble file for upload {upload_id}: {str(e)}")
            if os.path.exists(temp_file_path):
                os.unlink(temp_file_path)
            return None
    
    def complete_upload(self, upload_id: str) -> bool:
        """Mark upload as complete and clean up chunks."""
        # Update session status
        self.update_upload_session(upload_id, {'status': 'completed'})
        
        # Delete all chunks
        deleted_count = self.delete_all_chunks(upload_id)
        logger.info(f"Completed upload {upload_id}, deleted {deleted_count} chunks")
        
        return True
    
    def cancel_upload(self, upload_id: str) -> bool:
        """Cancel an upload and clean up all data."""
        # Delete all chunks
        deleted_chunks = self.delete_all_chunks(upload_id)
        
        # Delete session
        session_key = f"{self.session_prefix}:{upload_id}"
        deleted_session = self.client.delete(session_key)
        
        logger.info(f"Cancelled upload {upload_id}, deleted {deleted_chunks} chunks")
        return bool(deleted_session)
    
    def get_active_uploads(self, user_id: Optional[int] = None) -> List[Dict[str, Any]]:
        """Get all active upload sessions, optionally filtered by user."""
        pattern = f"{self.session_prefix}:*"
        sessions = []
        
        for key in self.client.scan_iter(match=pattern):
            session_data = self.client.get(key)
            if session_data:
                session_info = json.loads(session_data)
                
                # Filter by user if specified
                if user_id is not None:
                    metadata = session_info.get('metadata', {})
                    if metadata.get('user_id') != user_id:
                        continue
                
                # Only include active uploads
                if session_info.get('status') in ['uploading', 'paused']:
                    sessions.append(session_info)
        
        return sessions
    
    def extend_ttl(self, upload_id: str, additional_seconds: int = 3600) -> bool:
        """Extend TTL for upload session and all its chunks."""
        session_key = f"{self.session_prefix}:{upload_id}"
        
        # Extend session TTL
        if self.client.expire(session_key, self.session_ttl + additional_seconds):
            # Extend chunk TTLs
            pattern = f"{self.chunk_prefix}:{upload_id}:*"
            for key in self.client.scan_iter(match=pattern):
                self.client.expire(key, self.chunk_ttl + additional_seconds)
            
            logger.info(f"Extended TTL for upload {upload_id} by {additional_seconds} seconds")
            return True
        
        return False
    
    def get_upload_progress(self, upload_id: str) -> Dict[str, Any]:
        """Get detailed upload progress information."""
        session_info = self.get_upload_info(upload_id)
        if not session_info:
            return {'error': 'Upload not found'}
        
        uploaded_chunks = len(session_info.get('uploaded_chunks', []))
        total_chunks = session_info.get('total_chunks', 0)
        uploaded_bytes = session_info.get('uploaded_bytes', 0)
        file_size = session_info.get('file_size', 0)
        
        progress_percentage = 0
        if file_size > 0:
            progress_percentage = (uploaded_bytes / file_size) * 100
        
        return {
            'upload_id': upload_id,
            'filename': session_info.get('filename'),
            'status': session_info.get('status'),
            'uploaded_chunks': uploaded_chunks,
            'total_chunks': total_chunks,
            'uploaded_bytes': uploaded_bytes,
            'file_size': file_size,
            'progress_percentage': round(progress_percentage, 2),
            'created_at': session_info.get('created_at'),
            'updated_at': session_info.get('updated_at')
        }