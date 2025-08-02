/**
 * ResumableUpload - Handle large file uploads with resumable chunks
 * 
 * This class handles individual large files by splitting them into chunks
 * and uploading them sequentially. It provides progress tracking and
 * resume capability for interrupted uploads.
 */
console.log('Loading resumable-upload.js at', new Date().toISOString());

// Prevent redeclaration by wrapping in an IIFE
(function() {
    // Only define classes if they don't exist
    if (typeof window.ResumableUpload !== 'undefined') {
        console.log('ResumableUpload already defined, skipping redefinition');
        return;
    }

// Global logger for consistent logging
const logger = {
    info: (message, ...args) => console.log(`[ResumableUpload] ${message}`, ...args),
    warn: (message, ...args) => console.warn(`[ResumableUpload] ${message}`, ...args),
    error: (message, ...args) => console.error(`[ResumableUpload] ${message}`, ...args)
};


class ResumableUpload {
    constructor(file, options = {}) {
        this.file = file;
        this.options = {
            chunkSize: options.chunkSize || 5 * 1024 * 1024, // 5MB default
            maxRetries: options.maxRetries || 3,
            uploadSessionId: options.uploadSessionId,
            organization: options.organization,
            baseFolder: options.baseFolder,
            folderName: options.folderName,
            originalPath: options.originalPath || file.name,
            onProgress: options.onProgress || this.defaultProgressHandler,
            onComplete: options.onComplete || this.defaultCompleteHandler,
            onError: options.onError || this.defaultErrorHandler,
            onChunkComplete: options.onChunkComplete || this.defaultChunkCompleteHandler,
            ...options
        };
        
        this.uploadId = null;
        this.totalChunks = 0;
        this.completedChunks = 0;
        this.failedChunks = 0;
        this.currentChunk = 0;
        this.isUploading = false;
        this.isPaused = false;
        this.retryCount = 0;
        
        // Calculate total chunks
        this.totalChunks = Math.ceil(this.file.size / this.options.chunkSize);
        
        logger.info(`ResumableUpload initialized for ${file.name} (${file.size} bytes, ${this.totalChunks} chunks)`);
    }
    
    /**
     * Start the resumable upload process
     */
    async upload() {
        try {
            this.isUploading = true;
            
            // Initialize upload session
            await this.initializeUpload();
            
            // Upload chunks sequentially
            for (let chunkNum = 0; chunkNum < this.totalChunks; chunkNum++) {
                if (this.isPaused) {
                    logger.info(`Upload paused at chunk ${chunkNum}`);
                    return;
                }
                
                this.currentChunk = chunkNum;
                await this.uploadChunk(chunkNum);
                this.completedChunks++;
                
                // Call progress callback
                this.options.onProgress({
                    uploadId: this.uploadId,
                    filename: this.file.name,
                    completedChunks: this.completedChunks,
                    totalChunks: this.totalChunks,
                    completedBytes: this.completedChunks * this.options.chunkSize,
                    totalBytes: this.file.size,
                    progress: (this.completedChunks / this.totalChunks) * 100
                });
                
                // Call chunk complete callback
                this.options.onChunkComplete({
                    chunkNumber: chunkNum,
                    completedChunks: this.completedChunks,
                    totalChunks: this.totalChunks
                });
            }
            
            this.isUploading = false;
            
            // Wait for server-side assembly to complete
            await this.waitForCompletion();
            
            // Call completion callback
            this.options.onComplete({
                uploadId: this.uploadId,
                filename: this.file.name,
                fileSize: this.file.size
            });
            
        } catch (error) {
            this.isUploading = false;
            logger.error(`ResumableUpload failed for ${this.file.name}:`, error);
            this.options.onError(error);
        }
    }
    
    /**
     * Initialize the upload session on the server
     */
    async initializeUpload() {
        const payload = {
            filename: this.file.name,
            fileSize: this.file.size,
            chunkSize: this.options.chunkSize,
            contentType: this.file.type,
            organization: this.options.organization,
            baseFolder: this.options.baseFolder,
            folderName: this.options.folderName,
            originalPath: this.options.originalPath
        };
        
        logger.info(`Initializing resumable upload for ${this.file.name}...`);
        
        const response = await fetch('/storage/upload/resumable/init/', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': this.getCsrfToken()
            },
            body: JSON.stringify(payload)
        });
        
        if (!response.ok) {
            let errorMessage = `HTTP ${response.status}: ${response.statusText}`;
            try {
                const error = await response.json();
                errorMessage = error.error || error.message || errorMessage;
            } catch (e) {
                // Response might not be JSON
                try {
                    const textError = await response.text();
                    if (textError) errorMessage = textError;
                } catch (e2) {
                    // Use default error message
                }
            }
            throw new Error(errorMessage);
        }
        
        const result = await response.json();
        this.uploadId = result.uploadId;
        this.totalChunks = result.totalChunks;
        
        logger.info(`Upload initialized with ID: ${this.uploadId}`);
    }
    
    /**
     * Upload a single chunk
     */
    async uploadChunk(chunkNumber) {
        const start = chunkNumber * this.options.chunkSize;
        const end = Math.min(start + this.options.chunkSize, this.file.size);
        const chunk = this.file.slice(start, end);
        
        logger.info(`Uploading chunk ${chunkNumber + 1}/${this.totalChunks} (${chunk.size} bytes)`);
        
        let retries = 0;
        while (retries <= this.options.maxRetries) {
            try {
                logger.info(`Making chunk upload request: PUT /storage/upload/resumable/chunk/`);
                logger.info(`Headers: Content-Range=bytes ${start}-${end-1}/${this.file.size}, X-Upload-ID=${this.uploadId}, X-Chunk-Number=${chunkNumber}`);
                
                const headers = {
                    'Content-Range': `bytes ${start}-${end-1}/${this.file.size}`,
                    'X-Upload-ID': this.uploadId,
                    'X-Chunk-Number': chunkNumber.toString()
                };
                
                // Only add CSRF token if available (backend is @csrf_exempt anyway)
                const csrfToken = this.getCsrfToken();
                if (csrfToken) {
                    headers['X-CSRFToken'] = csrfToken;
                }
                
                const response = await fetch('/storage/upload/resumable/chunk/', {
                    method: 'PUT',
                    headers: headers,
                    body: chunk
                });
                
                if (!response.ok) {
                    const error = await response.json();
                    throw new Error(error.error || 'Chunk upload failed');
                }
                
                const result = await response.json();
                if (result.status === 'success' || result.status === 'already_completed') {
                    logger.info(`Chunk ${chunkNumber} uploaded successfully`);
                    return;
                }
                
                throw new Error('Unexpected response status');
                
            } catch (error) {
                retries++;
                logger.warn(`Chunk ${chunkNumber} upload failed (attempt ${retries}/${this.options.maxRetries + 1}):`, error);
                
                if (retries > this.options.maxRetries) {
                    throw error;
                }
                
                // For NetworkError, wait longer before retry
                const isNetworkError = error.name === 'TypeError' && error.message.includes('NetworkError');
                const waitTime = isNetworkError 
                    ? Math.pow(2, retries) * 2000  // Double wait time for network errors
                    : Math.pow(2, retries) * 1000;
                    
                logger.info(`Waiting ${waitTime}ms before retry...`);
                await this.sleep(waitTime);
            }
        }
    }
    
    /**
     * Wait for server-side assembly to complete
     */
    async waitForCompletion() {
        logger.info(`Waiting for server assembly to complete...`);
        
        let attempts = 0;
        const maxAttempts = 60; // 60 seconds timeout
        
        while (attempts < maxAttempts) {
            const status = await this.getUploadStatus();
            
            if (status.status === 'completed') {
                logger.info(`Upload completed successfully`);
                return;
            }
            
            if (status.status === 'failed') {
                throw new Error(status.errorMessage || 'Upload failed during assembly');
            }
            
            // Wait 1 second before checking again
            await this.sleep(1000);
            attempts++;
        }
        
        throw new Error('Timeout waiting for upload completion');
    }
    
    /**
     * Get upload status from server
     */
    async getUploadStatus() {
        const response = await fetch(`/storage/upload/resumable/status/${this.uploadId}/`);
        
        if (!response.ok) {
            throw new Error('Failed to get upload status');
        }
        
        return await response.json();
    }
    
    /**
     * Pause the upload
     */
    pause() {
        this.isPaused = true;
        logger.info(`Upload paused for ${this.file.name}`);
    }
    
    /**
     * Resume a paused upload
     */
    async resume() {
        if (!this.uploadId) {
            throw new Error('Cannot resume - upload not initialized');
        }
        
        try {
            const response = await fetch(`/storage/upload/resumable/resume/${this.uploadId}/`, {
                method: 'POST',
                headers: {
                    'X-CSRFToken': this.getCsrfToken()
                }
            });
            
            if (!response.ok) {
                const error = await response.json();
                throw new Error(error.error || 'Failed to resume upload');
            }
            
            const result = await response.json();
            this.completedChunks = result.completedChunks;
            this.failedChunks = result.failedChunks;
            this.currentChunk = this.completedChunks;
            this.isPaused = false;
            
            logger.info(`Upload resumed for ${this.file.name} at chunk ${this.currentChunk}`);
            
            // Continue uploading from where we left off
            return this.upload();
            
        } catch (error) {
            logger.error(`Failed to resume upload for ${this.file.name}:`, error);
            throw error;
        }
    }
    
    /**
     * Cancel the upload
     */
    cancel() {
        this.isPaused = true;
        this.isUploading = false;
        logger.info(`Upload cancelled for ${this.file.name}`);
    }
    
    /**
     * Get upload progress as percentage
     */
    getProgress() {
        return this.totalChunks > 0 ? (this.completedChunks / this.totalChunks) * 100 : 0;
    }
    
    /**
     * Utility functions
     */
    sleep(ms) {
        return new Promise(resolve => setTimeout(resolve, ms));
    }
    
    getCsrfToken() {
        // Try multiple ways to get CSRF token
        const fromInput = document.querySelector('[name=csrfmiddlewaretoken]');
        if (fromInput) {
            const token = fromInput.value;
            console.log('CSRF token from input:', token ? `${token.substring(0, 10)}...` : 'empty');
            return token;
        }
        
        // Fallback to cookie method
        const cookieValue = document.cookie
            .split('; ')
            .find(row => row.startsWith('csrftoken='))
            ?.split('=')[1];
            
        if (cookieValue) {
            console.log('CSRF token from cookie:', `${cookieValue.substring(0, 10)}...`);
            return cookieValue;
        }
        
        // Last resort - try meta tag
        const metaTag = document.querySelector('meta[name=csrf-token]');
        if (metaTag) {
            const token = metaTag.getAttribute('content');
            console.log('CSRF token from meta:', token ? `${token.substring(0, 10)}...` : 'empty');
            return token;
        }
        
        console.error('Could not find CSRF token');
        return '';
    }
    
    /**
     * Default event handlers
     */
    defaultProgressHandler(progress) {
        console.log(`Upload Progress: ${progress.filename} - ${progress.progress.toFixed(1)}%`);
    }
    
    defaultChunkCompleteHandler(chunk) {
        console.log(`Chunk Complete: ${chunk.chunkNumber + 1}/${chunk.totalChunks}`);
    }
    
    defaultCompleteHandler(result) {
        console.log(`Upload Complete: ${result.filename}`);
    }
    
    defaultErrorHandler(error) {
        console.error('Upload Error:', error);
    }
}

/**
 * ResumableUploadManager - Manages multiple resumable uploads
 */
class ResumableUploadManager {
    constructor(options = {}) {
        this.options = {
            maxConcurrent: options.maxConcurrent || 2,
            fileSizeThreshold: options.fileSizeThreshold || 50 * 1024 * 1024, // 50MB
            chunkSize: options.chunkSize || 5 * 1024 * 1024, // 5MB
            ...options
        };
        
        this.uploads = new Map();
        this.activeUploads = 0;
        this.queue = [];
    }
    
    /**
     * Add a file for resumable upload
     */
    addFile(file, uploadOptions = {}) {
        // Skip empty files (they cause chunking issues)
        if (file.size === 0) {
            console.warn(`[ResumableUploadManager] Skipping empty file: ${file.name}`);
            // Call completion handler immediately for empty files
            this.options.onComplete?.({ 
                filename: file.name, 
                skipped: true, 
                reason: 'Empty file' 
            });
            return null;
        }
        
        // Use resumable upload for all files for consistency
        const upload = new ResumableUpload(file, {
            ...this.options,
            ...uploadOptions,
            onProgress: (progress) => {
                this.options.onProgress?.(progress);
            },
            onComplete: (result) => {
                this.handleUploadComplete(file.name, result);
            },
            onError: (error) => {
                this.handleUploadError(file.name, error);
            }
        });
        
        this.uploads.set(file.name, upload);
        this.queue.push(upload);
        
        return upload;
    }
    
    /**
     * Start processing the upload queue
     */
    async processQueue() {
        while (this.queue.length > 0 && this.activeUploads < this.options.maxConcurrent) {
            const upload = this.queue.shift();
            this.activeUploads++;
            
            // Start upload (don't await - run concurrently)
            upload.upload().finally(() => {
                this.activeUploads--;
                this.processQueue(); // Process next in queue
            });
        }
    }
    
    /**
     * Handle upload completion
     */
    handleUploadComplete(filename, result) {
        logger.info(`ResumableUpload completed: ${filename}`);
        this.uploads.delete(filename);
        this.options.onComplete?.(result);
    }
    
    /**
     * Handle upload error
     */
    handleUploadError(filename, error) {
        logger.error(`ResumableUpload failed: ${filename}`, error);
        this.uploads.delete(filename);
        this.options.onError?.(error);
    }
    
    /**
     * Pause all uploads
     */
    pauseAll() {
        this.uploads.forEach(upload => upload.pause());
    }
    
    /**
     * Resume all paused uploads
     */
    resumeAll() {
        this.uploads.forEach(upload => {
            if (upload.isPaused) {
                upload.resume();
            }
        });
    }
    
    /**
     * Cancel all uploads
     */
    cancelAll() {
        this.uploads.forEach(upload => upload.cancel());
        this.uploads.clear();
        this.queue = [];
        this.activeUploads = 0;
    }
    
    /**
     * Get overall progress across all uploads
     */
    getOverallProgress() {
        if (this.uploads.size === 0) return 100;
        
        let totalProgress = 0;
        this.uploads.forEach(upload => {
            totalProgress += upload.getProgress();
        });
        
        return totalProgress / this.uploads.size;
    }
}

// Export for use in other modules
if (typeof window !== 'undefined') {
    console.log('Exporting classes. ResumableUpload:', typeof ResumableUpload, 'ResumableUploadManager:', typeof ResumableUploadManager);
    window.ResumableUpload = ResumableUpload;
    window.ResumableUploadManager = ResumableUploadManager;
    console.log('Exported both classes to window');
}

})(); // End IIFE