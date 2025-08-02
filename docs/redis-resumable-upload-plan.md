# Redis-Based Resumable Upload Plan

## Overview
Replace filesystem-based chunk storage with Redis in-memory storage for better performance, automatic cleanup, and simplified architecture.

## Current Issues with Filesystem Approach
- Docker container isolation problems (Huey can't access Django's /tmp)
- Manual cleanup required
- Disk I/O overhead
- Potential disk space issues with large files

## Proposed Redis Solution

### 1. Chunk Storage
```python
# Store chunks in Redis with TTL
redis_key = f"resumable_chunk:{upload_id}:{chunk_number}"
redis.setex(redis_key, 3600, chunk_data)  # 1 hour expiration
```

### 2. Assembly Process
```python
# Read chunks from Redis during assembly
for chunk_num in range(total_chunks):
    chunk_data = redis.get(f"resumable_chunk:{upload_id}:{chunk_num}")
    if chunk_data:
        final_file.write(chunk_data)
    else:
        raise ChunkMissingError(f"Chunk {chunk_num} not found")
```

### 3. Memory Management
- **5MB chunks × 20 concurrent uploads = 100MB Redis memory**
- Automatic cleanup with TTL (no manual file deletion)
- Configure Redis maxmemory policy for safety

## Implementation Steps

### Phase 1: Update Chunk Upload Endpoint
- [ ] Modify `resumable_upload_chunk` view to store in Redis
- [ ] Remove filesystem temp file creation
- [ ] Update chunk model to track Redis keys instead of file paths

### Phase 2: Update Assembly Process  
- [ ] Modify `_assemble_file` function to read from Redis
- [ ] Remove filesystem directory cleanup
- [ ] Add error handling for missing chunks

### Phase 3: Model Updates
- [ ] Remove `temp_file_path` from ResumableUploadChunk model
- [ ] Remove `temp_storage_path` from ResumableUploadSession model
- [ ] Add Redis key tracking if needed

### Phase 4: Configuration & Testing
- [ ] Add Redis connection configuration
- [ ] Set appropriate TTL values (1-24 hours)
- [ ] Test with parallel uploads
- [ ] Test chunk expiration scenarios

## Benefits
✅ **Performance**: Memory-based storage much faster than disk  
✅ **Cleanup**: Automatic expiration, no manual file deletion  
✅ **Scalability**: No disk space concerns  
✅ **Reliability**: No container isolation issues  
✅ **Simplicity**: Fewer moving parts, cleaner code  

## Considerations
⚠️ **Memory Usage**: Monitor Redis memory consumption  
⚠️ **TTL Tuning**: Balance between safety and memory usage  
⚠️ **Error Handling**: Handle Redis connection failures gracefully  
⚠️ **Large Files**: Consider size limits or hybrid approach  

Ready to implement?