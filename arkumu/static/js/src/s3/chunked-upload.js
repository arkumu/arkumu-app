/**
 * Chunked Upload Handler
 * 
 * Splits large file uploads into smaller batches to avoid Django's 
 * DATA_UPLOAD_MAX_NUMBER_FILES limit while maintaining performance.
 * 
 * Integrates with existing StreamingUploadHandler architecture.
 */
class ChunkedUploadHandler {
    constructor(options = {}) {
        this.chunkSize = options.chunkSize || 75; // Files per chunk
        this.maxConcurrent = options.maxConcurrent || 3; // Concurrent chunks
        this.uploadUrl = options.uploadUrl || '/storage/upload/streaming/';
        this.preserveFolderStructure = options.preserveFolderStructure || false;
        this.onProgress = options.onProgress || this.defaultProgressHandler;
        this.onChunkComplete = options.onChunkComplete || this.defaultChunkCompleteHandler;
        this.onComplete = options.onComplete || this.defaultCompleteHandler;
        this.onError = options.onError || this.defaultErrorHandler;
        
        this.totalFiles = 0;
        this.processedFiles = 0;
        this.completedFiles = 0;
        this.failedFiles = 0;
        this.results = [];
        this.isUploading = false;
        this.abortController = null;
        
        // Performance tracking
        this.startTime = null;
        this.chunkTimes = [];
    }

    /**
     * Main upload method - splits files into chunks and uploads them
     */
    async uploadFiles(files, folderName, organization = '', baseFolder = '') {
        if (this.isUploading) {
            throw new Error('Upload already in progress');
        }

        this.isUploading = true;
        this.totalFiles = files.length;
        this.processedFiles = 0;
        this.completedFiles = 0;
        this.failedFiles = 0;
        this.results = [];
        this.startTime = Date.now();
        this.abortController = new AbortController();

        console.log(`🚀 Starting chunked upload: ${files.length} files, chunk size: ${this.chunkSize}`);

        try {
            // Step 1: Split files into chunks
            const chunks = this.createChunks(files);
            console.log(`📦 Created ${chunks.length} chunks`);

            // Step 2: Upload chunks with controlled concurrency
            await this.uploadChunksWithConcurrency(chunks, folderName, organization, baseFolder);

            // Step 3: Process final results
            const summary = this.createSummary();
            this.onComplete(summary);
            
            return summary;

        } catch (error) {
            if (error.name === 'AbortError') {
                console.log('⏹️ Upload was cancelled');
                return this.createSummary(true);
            }
            
            console.error('❌ Upload error:', error);
            this.onError(error);
            throw error;
        } finally {
            this.isUploading = false;
            this.abortController = null;
        }
    }

    /**
     * Cancel the current upload
     */
    cancelUpload() {
        if (this.abortController) {
            console.log('🛑 Cancelling upload...');
            this.abortController.abort();
        }
    }

    /**
     * Split files array into smaller chunks
     * Smart chunking: considers both file count and size
     */
    createChunks(files) {
        const chunks = [];
        const maxChunkSize = 500 * 1024 * 1024; // 500MB per chunk
        const maxFilesPerChunk = this.chunkSize; // 75 files default
        
        let currentChunk = {
            index: 0,
            files: [],
            totalSize: 0,
            startIndex: 0,
            endIndex: 0
        };
        
        // Sort files by size (largest first) for better packing
        const sortedFiles = Array.from(files).sort((a, b) => b.size - a.size);
        
        sortedFiles.forEach((file, index) => {
            // Check if adding this file would exceed limits
            const wouldExceedSize = currentChunk.totalSize + file.size > maxChunkSize;
            const wouldExceedCount = currentChunk.files.length >= maxFilesPerChunk;
            
            // If file is huge (>500MB), give it its own chunk
            const isHugeFile = file.size > maxChunkSize;
            
            if (currentChunk.files.length > 0 && (wouldExceedSize || wouldExceedCount || isHugeFile)) {
                // Finish current chunk
                currentChunk.endIndex = currentChunk.startIndex + currentChunk.files.length - 1;
                chunks.push(currentChunk);
                
                // Start new chunk
                currentChunk = {
                    index: chunks.length,
                    files: [],
                    totalSize: 0,
                    startIndex: currentChunk.endIndex + 1,
                    endIndex: 0
                };
            }
            
            // Add file to current chunk
            currentChunk.files.push(file);
            currentChunk.totalSize += file.size;
        });
        
        // Don't forget the last chunk
        if (currentChunk.files.length > 0) {
            currentChunk.endIndex = currentChunk.startIndex + currentChunk.files.length - 1;
            chunks.push(currentChunk);
        }
        
        console.log(`📦 Created ${chunks.length} smart chunks:`);
        chunks.forEach((chunk, i) => {
            console.log(`  Chunk ${i + 1}: ${chunk.files.length} files, ${formatFileSize(chunk.totalSize)}`);
        });
        
        return chunks;
    }

    /**
     * Upload chunks with controlled concurrency
     */
    async uploadChunksWithConcurrency(chunks, folderName, organization, baseFolder) {
        const activeUploads = new Set();
        let chunkIndex = 0;
        const errors = [];

        return new Promise((resolve, reject) => {
            const processNextChunk = async () => {
                try {
                    // Check if cancelled
                    if (this.abortController.signal.aborted) {
                        reject(new DOMException('Upload cancelled', 'AbortError'));
                        return;
                    }

                    // Check if we're done
                    if (chunkIndex >= chunks.length && activeUploads.size === 0) {
                        if (errors.length > 0) {
                            console.warn(`⚠️ Upload completed with ${errors.length} chunk errors`);
                        }
                        resolve();
                        return;
                    }

                    // Start new uploads if we have capacity and chunks remaining
                    while (activeUploads.size < this.maxConcurrent && chunkIndex < chunks.length) {
                        const chunk = chunks[chunkIndex++];
                        
                        const uploadPromise = this.uploadSingleChunk(chunk, folderName, organization, baseFolder)
                            .then(result => {
                                this.handleChunkResult(chunk, result);
                            })
                            .catch(error => {
                                errors.push({ chunk: chunk.index + 1, error });
                                this.handleChunkError(chunk, error);
                            })
                            .finally(() => {
                                activeUploads.delete(uploadPromise);
                                processNextChunk(); // Process next chunk
                            });

                        activeUploads.add(uploadPromise);
                    }
                } catch (error) {
                    reject(error);
                }
            };

            processNextChunk();
        });
    }

    /**
     * Upload a single chunk of files
     */
    async uploadSingleChunk(chunk, folderName, organization, baseFolder) {
        const chunkStartTime = Date.now();
        console.log(`📤 Uploading chunk ${chunk.index + 1}: files ${chunk.startIndex + 1}-${chunk.endIndex + 1}`);

        const formData = new FormData();
        
        // Handle folder structure preservation
        if (this.preserveFolderStructure) {
            // For folder mode, combine baseFolder and folderName to create the full path
            let fullFolderPath = folderName || '';
            if (baseFolder) {
                fullFolderPath = baseFolder + (folderName ? '/' + folderName : '');
            }
            formData.append('folder_name', fullFolderPath);
            formData.append('preserve_folder_structure', 'true');
            
            // Send file paths as a JSON array
            const filePaths = chunk.files.map(file => {
                const relativePath = file.webkitRelativePath || file.name;
                // Remove the folder name prefix if it exists to avoid duplication
                if (folderName && relativePath.startsWith(folderName + '/')) {
                    return relativePath.substring(folderName.length + 1);
                }
                return relativePath;
            });
            
            formData.append('file_paths', JSON.stringify(filePaths));
            
            console.log(`📁 Preserving structure for ${chunk.files.length} files:`, filePaths.slice(0, 3));
            console.log(`📁 Folder name being sent: "${fullFolderPath}"`);
            console.log(`📁 Sample file paths:`, filePaths.slice(0, 5));
        } else {
            // Create the final folder path for non-folder mode
            let finalFolderName = folderName;
            if (baseFolder) {
                finalFolderName = baseFolder + (folderName ? '/' + folderName : '');
            }
            formData.append('folder_name', finalFolderName);
        }
        
        if (organization) {
            formData.append('organization', organization);
        }

        // Add all files in this chunk
        chunk.files.forEach(file => {
            formData.append('files', file);
        });

        // Add CSRF token
        formData.append('csrfmiddlewaretoken', this.getCsrfToken());

        const response = await fetch(this.uploadUrl, {
            method: 'POST',
            body: formData,
            signal: this.abortController.signal,
            headers: {
                // Don't set Content-Type, let browser set it with boundary
                'HX-Request': 'true'  // Tell server this should be treated as HTMX request for OOB updates
            }
        });

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }

        // Check if response is HTML (with OOB updates) or JSON
        const contentType = response.headers.get('content-type');
        if (contentType && contentType.includes('text/html')) {
            // HTML response with OOB updates - process the HTML and extract success info
            const htmlText = await response.text();
            
            // Process OOB updates by inserting HTML into document
            const tempDiv = document.createElement('div');
            tempDiv.innerHTML = htmlText;
            
            console.log(`🔍 OOB DEBUG: Full HTML response length: ${htmlText.length}`);
            console.log(`🔍 OOB DEBUG: Full HTML response preview: ${htmlText.substring(0, 500)}...`);
            
            // Find and process OOB elements
            const oobElements = tempDiv.querySelectorAll('[hx-swap-oob]');
            console.log(`🔍 OOB DEBUG: Found ${oobElements.length} OOB elements`);
            
            oobElements.forEach((element, index) => {
                const targetId = element.id;
                const target = document.getElementById(targetId);
                console.log(`🔍 OOB DEBUG: Element ${index + 1}: id="${targetId}", exists=${!!target}, content length=${element.innerHTML.length}`);
                console.log(`🔍 OOB DEBUG: Element ${index + 1} content preview: ${element.innerHTML.substring(0, 200)}...`);
                
                if (target) {
                    target.innerHTML = element.innerHTML;
                    console.log(`🔄 OOB UPDATE: Updated ${targetId} via chunked upload`);
                } else {
                    console.warn(`⚠️ OOB WARNING: Target element with id "${targetId}" not found`);
                }
            });
            
            // For HTML responses, assume success (server sends OOB updates on success)
            // The actual file count isn't easily extractable from HTML, so we use chunk file count
            const result = {
                success: true,
                success_count: chunk.files.length,
                error_count: 0,
                message: 'Chunk uploaded successfully with OOB updates'
            };
            
            return result;
        } else {
            // JSON response - parse normally
            const result = await response.json();
            
            if (!result.success) {
                throw new Error(result.error || 'Upload failed');
            }
            
            return result;
        }

        // Track timing
        const chunkDuration = Date.now() - chunkStartTime;
        this.chunkTimes.push(chunkDuration);

        return result;
    }

    /**
     * Handle successful chunk upload
     */
    handleChunkResult(chunk, result) {
        const successCount = result.success_count || 0;
        const failureCount = result.error_count || 0;
        
        console.log(`✅ Chunk ${chunk.index + 1} completed: ${successCount}/${chunk.files.length} files succeeded`);
        
        this.completedFiles += successCount;
        this.failedFiles += failureCount;
        this.processedFiles += chunk.files.length;
        
        this.results.push({
            chunk: chunk.index + 1,
            result: result,
            files: chunk.files.map(f => f.name)
        });

        this.onChunkComplete(chunk, result);
        this.updateProgress();
    }

    /**
     * Handle chunk upload error
     */
    handleChunkError(chunk, error) {
        console.error(`❌ Chunk ${chunk.index + 1} failed:`, error);
        
        this.failedFiles += chunk.files.length;
        this.processedFiles += chunk.files.length;
        
        this.results.push({
            chunk: chunk.index + 1,
            error: error.message,
            files: chunk.files.map(f => f.name)
        });

        this.onError(error, chunk);
        this.updateProgress();
    }

    /**
     * Update progress and notify callback
     */
    updateProgress() {
        const elapsed = Date.now() - this.startTime;
        const avgChunkTime = this.chunkTimes.length > 0 
            ? this.chunkTimes.reduce((a, b) => a + b, 0) / this.chunkTimes.length 
            : 0;
        
        const progress = {
            totalFiles: this.totalFiles,
            processedFiles: this.processedFiles,
            completedFiles: this.completedFiles,
            failedFiles: this.failedFiles,
            percentage: Math.round((this.processedFiles / this.totalFiles) * 100),
            elapsed: elapsed,
            avgChunkTime: avgChunkTime,
            estimatedRemaining: this.calculateEstimatedTime()
        };

        this.onProgress(progress);
    }

    /**
     * Calculate estimated remaining time
     */
    calculateEstimatedTime() {
        if (this.chunkTimes.length === 0 || this.processedFiles === 0) {
            return null;
        }

        const avgTimePerFile = this.chunkTimes.reduce((a, b) => a + b, 0) / this.processedFiles;
        const remainingFiles = this.totalFiles - this.processedFiles;
        const activeChunks = Math.min(this.maxConcurrent, Math.ceil(remainingFiles / this.chunkSize));
        
        return Math.round((remainingFiles * avgTimePerFile) / Math.max(activeChunks, 1));
    }

    /**
     * Create final summary
     */
    createSummary(cancelled = false) {
        const elapsed = Date.now() - this.startTime;
        
        return {
            success: !cancelled && this.failedFiles === 0,
            cancelled: cancelled,
            totalFiles: this.totalFiles,
            processedFiles: this.processedFiles,
            completedFiles: this.completedFiles,
            failedFiles: this.failedFiles,
            chunks: this.results.length,
            duration: elapsed,
            avgChunkTime: this.chunkTimes.length > 0 
                ? Math.round(this.chunkTimes.reduce((a, b) => a + b, 0) / this.chunkTimes.length)
                : 0,
            results: this.results
        };
    }

    /**
     * Get CSRF token from page
     */
    getCsrfToken() {
        const csrfToken = document.querySelector('[name=csrfmiddlewaretoken]');
        return csrfToken ? csrfToken.value : '';
    }

    // Default event handlers
    defaultProgressHandler(progress) {
        console.log(`📊 Progress: ${progress.percentage}% (${progress.processedFiles}/${progress.totalFiles})`);
    }

    defaultChunkCompleteHandler(chunk, result) {
        console.log(`✅ Chunk ${chunk.index + 1} completed`);
    }

    defaultCompleteHandler(summary) {
        console.log('🎉 Upload complete:', summary);
    }

    defaultErrorHandler(error, chunk) {
        console.error('❌ Upload error:', error);
    }
}

/**
 * Easy-to-use function for simple uploads
 */
async function uploadFilesInChunks(files, folderName, organization = '', baseFolder = '', options = {}) {
    const uploader = new ChunkedUploadHandler(options);
    return await uploader.uploadFiles(files, folderName, organization, baseFolder);
}

/**
 * Utility function to format file sizes
 */
function formatFileSize(bytes) {
    if (bytes === 0) return '0 Bytes';
    
    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
}

/**
 * Utility function to format duration
 */
function formatDuration(milliseconds) {
    const seconds = Math.floor(milliseconds / 1000);
    const minutes = Math.floor(seconds / 60);
    const hours = Math.floor(minutes / 60);
    
    if (hours > 0) {
        return `${hours}h ${minutes % 60}m ${seconds % 60}s`;
    } else if (minutes > 0) {
        return `${minutes}m ${seconds % 60}s`;
    } else {
        return `${seconds}s`;
    }
}

// Export for use in other scripts
if (typeof module !== 'undefined' && module.exports) {
    module.exports = { 
        ChunkedUploadHandler, 
        uploadFilesInChunks,
        formatFileSize,
        formatDuration
    };
} 