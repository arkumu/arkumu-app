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
            chunkSize: options.chunkSize || this.calculateOptimalChunkSize(file.size),
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
        this.storageKey = `resumable_upload_${this.file.name}_${this.file.size}_${this.file.lastModified}`;
        
        // Calculate total chunks
        this.totalChunks = Math.ceil(this.file.size / this.options.chunkSize);
        
        // Resume functionality disabled
        // this.restoreState();
        
        logger.info(`ResumableUpload initialized for ${file.name} (${file.size} bytes, ${this.totalChunks} chunks)`);
    }
    
    /**
     * Calculate optimal chunk size based on file size
     */
    calculateOptimalChunkSize(fileSize) {
        const MB = 1024 * 1024;
        
        if (fileSize < 100 * MB) {
            return 8 * MB;    // 8MB for small files
        } else if (fileSize < 500 * MB) {
            return 16 * MB;   // 16MB for medium files  
        } else if (fileSize < 2000 * MB) {
            return 32 * MB;   // 32MB for large files
        } else {
            return 64 * MB;   // 64MB for very large files
        }
    }
    
    /**
     * Save current state to localStorage
     */
    saveState() {
        if (!this.uploadId) return;
        
        const state = {
            uploadId: this.uploadId,
            totalChunks: this.totalChunks,
            completedChunks: this.completedChunks,
            failedChunks: this.failedChunks,
            currentChunk: this.currentChunk,
            options: {
                organization: this.options.organization,
                baseFolder: this.options.baseFolder,
                folderName: this.options.folderName,
                originalPath: this.options.originalPath,
                chunkSize: this.options.chunkSize
            },
            timestamp: Date.now()
        };
        
        try {
            localStorage.setItem(this.storageKey, JSON.stringify(state));
            logger.info(`State saved for ${this.file.name}`);
        } catch (error) {
            logger.warn(`Failed to save state for ${this.file.name}:`, error);
        }
    }
    
    /**
     * Restore state from localStorage
     */
    restoreState() {
        try {
            const stateData = localStorage.getItem(this.storageKey);
            if (!stateData) return false;
            
            const state = JSON.parse(stateData);
            
            // Check if state is not too old (24 hours)
            const maxAge = 24 * 60 * 60 * 1000;
            if (Date.now() - state.timestamp > maxAge) {
                this.clearState();
                return false;
            }
            
            this.uploadId = state.uploadId;
            this.totalChunks = state.totalChunks;
            this.completedChunks = state.completedChunks;
            this.failedChunks = state.failedChunks;
            this.currentChunk = state.currentChunk;
            
            logger.info(`State restored for ${this.file.name}: ${this.completedChunks}/${this.totalChunks} chunks completed`);
            return true;
        } catch (error) {
            logger.warn(`Failed to restore state for ${this.file.name}:`, error);
            this.clearState();
            return false;
        }
    }
    
    /**
     * Clear saved state
     */
    clearState() {
        try {
            localStorage.removeItem(this.storageKey);
        } catch (error) {
            logger.warn(`Failed to clear state for ${this.file.name}:`, error);
        }
    }
    
    /**
     * Check if this upload can be resumed
     */
    canResume() {
        return this.uploadId && this.completedChunks > 0 && this.completedChunks < this.totalChunks;
    }
    
    /**
     * Start the resumable upload process
     */
    async upload() {
        try {
            this.isUploading = true;
            
            // Resume functionality disabled
            // if (this.canResume()) {
            //     logger.info(`Resuming upload for ${this.file.name} from chunk ${this.completedChunks}`);
            //     return await this.resume();
            // }
            
            // Initialize upload session
            await this.initializeUpload();
            
            // Resume functionality disabled
            // this.saveState();
            
            // Upload chunks in parallel batches
            await this.uploadChunksInParallel();
            
            this.isUploading = false;
            
            // Wait for server-side assembly to complete
            await this.waitForCompletion();
            
            // Resume functionality disabled
            // this.clearState();
            
            // Call completion callback
            this.options.onComplete({
                uploadId: this.uploadId,
                filename: this.file.name,
                fileSize: this.file.size
            });
            
        } catch (error) {
            this.isUploading = false;
            // this.saveState(); // Resume functionality disabled
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
     * Upload chunks in parallel batches for better performance
     */
    async uploadChunksInParallel() {
        const maxConcurrency = 3; // Upload 3 chunks at once
        const remainingChunks = [];
        
        // Build list of remaining chunks to upload
        for (let chunkNum = this.currentChunk; chunkNum < this.totalChunks; chunkNum++) {
            remainingChunks.push(chunkNum);
        }
        
        logger.info(`📦 Starting parallel upload of ${remainingChunks.length} chunks with max concurrency: ${maxConcurrency}`);
        
        // Process chunks in batches
        for (let i = 0; i < remainingChunks.length; i += maxConcurrency) {
            if (this.isPaused) {
                logger.info(`Upload paused at chunk batch starting at ${remainingChunks[i]}`);
                return;
            }
            
            const batch = remainingChunks.slice(i, i + maxConcurrency);
            logger.info(`📦 Uploading batch: chunks ${batch.map(c => c + 1).join(', ')}`);
            
            // Upload batch in parallel
            const batchPromises = batch.map(chunkNum => this.uploadChunkWithProgress(chunkNum));
            
            try {
                await Promise.all(batchPromises);
                logger.info(`✅ Completed batch: chunks ${batch.map(c => c + 1).join(', ')}`);
            } catch (error) {
                logger.error(`❌ Batch failed:`, error);
                throw error;
            }
        }
        
        logger.info(`🎉 All ${this.totalChunks} chunks uploaded successfully`);
    }
    
    /**
     * Upload a single chunk with progress tracking
     */
    async uploadChunkWithProgress(chunkNumber) {
        await this.uploadChunk(chunkNumber);
        this.completedChunks++;
        this.currentChunk = Math.max(this.currentChunk, chunkNumber + 1);
        
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
            chunkNumber: chunkNumber,
            completedChunks: this.completedChunks,
            totalChunks: this.totalChunks
        });
    }
    
    /**
     * Upload a single chunk
     */
    async uploadChunk(chunkNumber) {
        const start = chunkNumber * this.options.chunkSize;
        const end = Math.min(start + this.options.chunkSize, this.file.size);
        const chunk = this.file.slice(start, end);
        
        logger.info(`📁 UPLOADING: Chunk ${chunkNumber + 1}/${this.totalChunks} (${chunk.size} bytes)`);
        
        let retries = 0;
        while (retries <= this.options.maxRetries) {
            try {
                const startTime = Date.now();
                logger.info(`📁 REQUEST: Starting chunk upload request at ${new Date().toISOString()}`);
                logger.info(`📁 HEADERS: Content-Range=bytes ${start}-${end-1}/${this.file.size}, X-Upload-ID=${this.uploadId}, X-Chunk-Number=${chunkNumber}`);
                
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
                
                // Add timeout to prevent hanging
                const controller = new AbortController();
                const timeoutId = setTimeout(() => {
                    logger.error(`📁 TIMEOUT: Chunk ${chunkNumber} upload timed out after 30 seconds`);
                    controller.abort();
                }, 30000); // 30 second timeout
                
                const response = await fetch('/storage/upload/resumable/chunk/', {
                    method: 'PUT',
                    headers: headers,
                    body: chunk,
                    signal: controller.signal
                });
                
                clearTimeout(timeoutId);
                
                const duration = Date.now() - startTime;
                logger.info(`📁 RESPONSE: Got response after ${duration}ms`);
                
                if (!response.ok) {
                    const error = await response.json();
                    logger.error(`📁 HTTP ERROR: ${response.status} ${response.statusText}`);
                    throw new Error(error.error || 'Chunk upload failed');
                }
                
                const result = await response.json();
                if (result.status === 'success' || result.status === 'already_completed') {
                    logger.info(`📁 SUCCESS: Chunk ${chunkNumber} uploaded successfully in ${duration}ms`);
                    return;
                }
                
                throw new Error('Unexpected response status');
                
            } catch (error) {
                retries++;
                logger.error(`📁 CHUNK FAIL: Chunk ${chunkNumber} failed (attempt ${retries}/${this.options.maxRetries + 1}):`, error);
                logger.error(`📁 ERROR TYPE: ${error.name}, MESSAGE: ${error.message}`);
                
                if (retries > this.options.maxRetries) {
                    // Check if this is a network error that could be resumed
                    const isNetworkError = error.name === 'TypeError' && error.message.includes('NetworkError') ||
                                         error.name === 'AbortError' ||
                                         error.message.includes('fetch') ||
                                         error.message.includes('timeout') ||
                                         error.message.includes('connection') ||
                                         error.message.includes('aborted');
                    
                    if (isNetworkError) {
                        // Save state before throwing error for potential resume
                        this.saveState();
                        logger.info(`Network error detected, state saved for potential resume`);
                    }
                    
                    throw error;
                }
                
                // For NetworkError, wait longer before retry
                const isNetworkError = error.name === 'TypeError' && error.message.includes('NetworkError') ||
                                     error.message.includes('fetch') ||
                                     error.message.includes('timeout') ||
                                     error.message.includes('connection');
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
            logger.info(`Attempting to resume upload for ${this.file.name} with ID ${this.uploadId}`);
            
            const response = await fetch(`/storage/upload/resumable/resume/${this.uploadId}/`, {
                method: 'POST',
                headers: {
                    'X-CSRFToken': this.getCsrfToken()
                }
            });
            
            if (!response.ok) {
                const error = await response.json();
                const errorMessage = error.error || 'Failed to resume upload';
                
                // If upload cannot be resumed (expired/not found), clear state and start fresh
                if (response.status === 400 && errorMessage.includes('cannot be resumed')) {
                    logger.warn(`Upload session expired for ${this.file.name}, starting fresh upload`);
                    this.clearState();
                    
                    // Reset upload state for fresh start
                    this.uploadId = null;
                    this.completedChunks = 0;
                    this.currentChunk = 0;
                    this.isPaused = false;
                    this.isUploading = false;
                    
                    // Start a new upload instead
                    return await this.upload();
                }
                
                throw new Error(errorMessage);
            }
            
            const result = await response.json();
            this.completedChunks = result.completedChunks;
            this.failedChunks = result.failedChunks;
            this.currentChunk = this.completedChunks;
            this.isPaused = false;
            this.isUploading = true;
            
            logger.info(`Upload resumed for ${this.file.name} at chunk ${this.currentChunk}`);
            
            // Save updated state
            this.saveState();
            
            // Continue uploading from where we left off
            for (let chunkNum = this.currentChunk; chunkNum < this.totalChunks; chunkNum++) {
                if (this.isPaused) {
                    logger.info(`Upload paused at chunk ${chunkNum}`);
                    this.saveState();
                    return;
                }
                
                this.currentChunk = chunkNum;
                await this.uploadChunk(chunkNum);
                this.completedChunks++;
                
                // Resume functionality disabled
                // this.saveState();
                
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
            
            // Resume functionality disabled
            // this.clearState();
            
            // Call completion callback
            this.options.onComplete({
                uploadId: this.uploadId,
                filename: this.file.name,
                fileSize: this.file.size
            });
            
        } catch (error) {
            this.isUploading = false;
            // this.saveState(); // Resume functionality disabled
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
        this.clearState(); // Clear state when cancelled
        logger.info(`Upload cancelled for ${this.file.name}`);
    }
    
    /**
     * Static method to get all incomplete uploads from localStorage
     */
    static getIncompleteUploads() {
        const incompleteUploads = [];
        
        try {
            for (let i = 0; i < localStorage.length; i++) {
                const key = localStorage.key(i);
                if (key && key.startsWith('resumable_upload_')) {
                    const stateData = localStorage.getItem(key);
                    if (stateData) {
                        const state = JSON.parse(stateData);
                        
                        // Check if state is not too old (24 hours)
                        const maxAge = 24 * 60 * 60 * 1000;
                        if (Date.now() - state.timestamp > maxAge) {
                            localStorage.removeItem(key);
                            continue;
                        }
                        
                        // Check if upload is incomplete
                        if (state.completedChunks < state.totalChunks) {
                            incompleteUploads.push({
                                key: key,
                                uploadId: state.uploadId,
                                completedChunks: state.completedChunks,
                                totalChunks: state.totalChunks,
                                options: state.options,
                                timestamp: state.timestamp
                            });
                        } else {
                            // Remove completed uploads
                            localStorage.removeItem(key);
                        }
                    }
                }
            }
        } catch (error) {
            logger.warn('Error checking for incomplete uploads:', error);
        }
        
        return incompleteUploads;
    }
    
    /**
     * Clear expired or invalid upload sessions
     */
    static clearExpiredUploads() {
        const keysToRemove = [];
        
        try {
            for (let i = 0; i < localStorage.length; i++) {
                const key = localStorage.key(i);
                if (key && key.startsWith('resumable_upload_')) {
                    const stateData = localStorage.getItem(key);
                    if (stateData) {
                        const state = JSON.parse(stateData);
                        
                        // Remove uploads older than 1 hour (backend sessions likely expired)
                        const maxAge = 60 * 60 * 1000; // 1 hour
                        if (Date.now() - state.timestamp > maxAge) {
                            keysToRemove.push(key);
                        }
                    }
                }
            }
            
            // Remove expired uploads
            keysToRemove.forEach(key => localStorage.removeItem(key));
            
            if (keysToRemove.length > 0) {
                logger.info(`Cleared ${keysToRemove.length} expired upload sessions`);
            }
            
        } catch (error) {
            logger.warn('Error clearing expired uploads:', error);
        }
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
        logger.info(`Adding file to manager: ${file.name} (${file.size} bytes)`);
        
        // Skip empty files (they cause chunking issues)
        if (file.size === 0) {
            logger.warn(`Skipping empty file: ${file.name}`);
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
        
        logger.info(`Added ${file.name} to queue. Queue length: ${this.queue.length}, Uploads map size: ${this.uploads.size}`);
        
        return upload;
    }
    
    /**
     * Start processing the upload queue
     */
    async processQueue() {
        logger.info(`Processing queue: ${this.queue.length} files in queue, ${this.activeUploads} active uploads`);
        
        while (this.queue.length > 0 && this.activeUploads < this.options.maxConcurrent) {
            const upload = this.queue.shift();
            this.activeUploads++;
            
            logger.info(`Starting upload for ${upload.file.name}, active uploads: ${this.activeUploads}`);
            
            // Start upload (don't await - run concurrently)
            upload.upload().catch((error) => {
                logger.error(`Upload failed for ${upload.file.name}:`, error);
                // Call error handler even if upload.upload() throws
                this.handleUploadError(upload.file.name, error);
            }).finally(() => {
                this.activeUploads--;
                logger.info(`Upload finished for ${upload.file.name}, active uploads: ${this.activeUploads}`);
                this.processQueue(); // Process next in queue
            });
        }
        
        if (this.queue.length === 0 && this.activeUploads === 0) {
            logger.info('All uploads completed!');
        }
    }
    
    /**
     * Handle upload completion
     */
    handleUploadComplete(filename, result) {
        logger.info(`ResumableUpload completed: ${filename}`, result);
        this.uploads.delete(filename);
        this.options.onComplete?.(result);
    }
    
    /**
     * Handle upload error
     */
    handleUploadError(filename, error) {
        logger.error(`ResumableUpload failed: ${filename}`, error);
        
        // Check if this is a network error that could be auto-resumed
        const isNetworkError = error.message && (
            error.message.includes('NetworkError') ||
            error.message.includes('fetch') ||
            error.message.includes('timeout') ||
            error.message.includes('connection')
        );
        
        if (isNetworkError && this.options.autoRetryNetworkErrors !== false) {
            logger.info(`Network error detected for ${filename}, will attempt auto-resume in 5 seconds...`);
            
            // Don't delete the upload yet, try to resume it
            setTimeout(() => {
                this.attemptAutoResume(filename);
            }, 5000);
        } else {
            // For non-network errors or if auto-retry is disabled, remove the upload
            this.uploads.delete(filename);
        }
        
        this.options.onError?.({
            filename: filename,
            message: error.message || error
        });
    }
    
    /**
     * Attempt to automatically resume a failed upload
     */
    async attemptAutoResume(filename) {
        const upload = this.uploads.get(filename);
        if (!upload) {
            logger.warn(`Cannot auto-resume ${filename}: upload not found`);
            return;
        }
        
        if (!upload.canResume()) {
            logger.warn(`Cannot auto-resume ${filename}: upload not resumable`);
            this.uploads.delete(filename);
            return;
        }
        
        try {
            logger.info(`Auto-resuming upload for ${filename}...`);
            
            // Reset the upload state
            upload.isPaused = false;
            upload.isUploading = false;
            
            // Attempt resume
            await upload.resume();
            
            logger.info(`Auto-resume successful for ${filename}`);
            
        } catch (error) {
            logger.error(`Auto-resume failed for ${filename}:`, error);
            
            // Remove the upload after failed auto-resume
            this.uploads.delete(filename);
            
            // Call error handler again for the auto-resume failure
            this.options.onError?.({
                filename: filename,
                message: `Auto-resume failed: ${error.message || error}`
            });
        }
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