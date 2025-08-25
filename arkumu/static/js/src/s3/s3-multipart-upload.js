/**
 * S3 Multipart Upload Handler
 * 
 * Splits individual files into chunks and uploads them directly to S3
 * using S3's native multipart upload capability for true resumability.
 * 
 * Key differences from chunked-upload.js:
 * - Chunks are pieces of individual files, not batches of files
 * - Each chunk uploads directly to S3 (no Redis assembly)
 * - S3 handles the final assembly automatically
 */
class S3MultipartUploadHandler {
    constructor(options = {}) {
        this.chunkSize = options.chunkSize || 5 * 1024 * 1024; // 5MB per chunk (S3 minimum)
        this.maxConcurrent = options.maxConcurrent || 3; // Concurrent chunks
        this.initUrl = options.initUrl || '/storage/upload/multipart/init/';
        this.chunkUrl = options.chunkUrl || '/storage/upload/multipart/chunk/';
        this.completeUrl = options.completeUrl || '/storage/upload/multipart/complete/';
        this.onProgress = options.onProgress || this.defaultProgressHandler;
        this.onFileComplete = options.onFileComplete || this.defaultFileCompleteHandler;
        this.onComplete = options.onComplete || this.defaultCompleteHandler;
        this.onError = options.onError || this.defaultErrorHandler;
        
        this.totalFiles = 0;
        this.completedFiles = 0;
        this.failedFiles = 0;
        this.totalSize = 0;
        this.uploadedSize = 0;
        this.results = [];
        this.isUploading = false;
        this.abortController = null;
        
        // Track active multipart uploads
        this.activeUploads = new Map(); // filename -> upload session
        
        // Performance tracking
        this.startTime = null;
    }

    /**
     * Main upload method - processes each file with S3 multipart
     */
    async uploadFiles(files, folderName, organization = '', baseFolder = '') {
        if (this.isUploading) {
            throw new Error('Upload already in progress');
        }

        this.isUploading = true;
        this.totalFiles = files.length;
        this.totalSize = Array.from(files).reduce((sum, file) => sum + file.size, 0);
        this.completedFiles = 0;
        this.failedFiles = 0;
        this.uploadedSize = 0;
        this.results = [];
        this.startTime = Date.now();
        this.abortController = new AbortController();
        this.activeUploads.clear();

        console.log(`🚀 Starting S3 multipart upload: ${files.length} files, ${formatFileSize(this.totalSize)}`);

        try {
            // Process files with controlled concurrency
            await this.uploadFilesWithConcurrency(Array.from(files), folderName, organization, baseFolder);

            // Create final summary
            const summary = this.createSummary();
            this.onComplete(summary);
            
            return summary;

        } catch (error) {
            if (error.name === 'AbortError') {
                console.log('⏹️ Upload was cancelled');
                await this.cleanupActiveUploads();
                return this.createSummary(true);
            }
            
            console.error('❌ Upload error:', error);
            this.onError(error);
            throw error;
        } finally {
            this.isUploading = false;
            this.abortController = null;
            this.activeUploads.clear();
        }
    }

    /**
     * Upload files with controlled concurrency
     */
    async uploadFilesWithConcurrency(files, folderName, organization, baseFolder) {
        const activeFileUploads = new Set();
        let fileIndex = 0;
        const errors = [];

        return new Promise((resolve, reject) => {
            const processNextFile = async () => {
                try {
                    // Check if cancelled
                    if (this.abortController.signal.aborted) {
                        reject(new DOMException('Upload cancelled', 'AbortError'));
                        return;
                    }

                    // Check if we're done
                    if (fileIndex >= files.length && activeFileUploads.size === 0) {
                        if (errors.length > 0) {
                            console.warn(`⚠️ Upload completed with ${errors.length} file errors`);
                        }
                        resolve();
                        return;
                    }

                    // Start new uploads if we have capacity and files remaining
                    while (activeFileUploads.size < this.maxConcurrent && fileIndex < files.length) {
                        const file = files[fileIndex++];
                        
                        const uploadPromise = this.uploadSingleFile(file, folderName, organization, baseFolder)
                            .then(result => {
                                this.handleFileResult(file, result);
                            })
                            .catch(error => {
                                errors.push({ file: file.name, error });
                                this.handleFileError(file, error);
                            })
                            .finally(() => {
                                activeFileUploads.delete(uploadPromise);
                                processNextFile(); // Process next file
                            });

                        activeFileUploads.add(uploadPromise);
                    }
                } catch (error) {
                    reject(error);
                }
            };

            processNextFile();
        });
    }

    /**
     * Upload a single file using S3 multipart upload
     */
    async uploadSingleFile(file, folderName, organization, baseFolder) {
        console.log(`📤 Starting multipart upload: ${file.name} (${formatFileSize(file.size)})`);
        
        // Step 1: Initialize multipart upload
        const initResponse = await this.initializeMultipartUpload(file, folderName, organization, baseFolder);
        const { uploadId, s3Key } = initResponse;
        
        // Track this upload
        this.activeUploads.set(file.name, { uploadId, s3Key, file });
        
        try {
            // Step 2: Upload file in chunks
            const parts = await this.uploadFileChunks(file, uploadId, s3Key);
            
            // Step 3: Complete multipart upload
            const result = await this.completeMultipartUpload(uploadId, s3Key, parts);
            
            // Remove from active uploads
            this.activeUploads.delete(file.name);
            
            return {
                success: true,
                file: file.name,
                size: file.size,
                uploadId,
                s3Key,
                ...result
            };
            
        } catch (error) {
            // Clean up failed upload
            this.activeUploads.delete(file.name);
            await this.abortMultipartUpload(uploadId, s3Key);
            throw error;
        }
    }

    /**
     * Initialize S3 multipart upload
     */
    async initializeMultipartUpload(file, folderName, organization, baseFolder) {
        const formData = new FormData();
        formData.append('filename', file.name);
        formData.append('fileSize', file.size.toString());
        formData.append('contentType', file.type || 'application/octet-stream');
        formData.append('folderName', folderName);
        formData.append('organization', organization);
        formData.append('baseFolder', baseFolder);
        
        // Check if we're in folder mode and should preserve structure
        const fileInput = document.getElementById('file-input');
        const isFolderMode = fileInput && fileInput.hasAttribute('webkitdirectory');
        
        if (isFolderMode) {
            formData.append('preserve_folder_structure', 'true');
            
            // Send the file's relative path using filename as key
            const relativePath = file.webkitRelativePath || file.name;
            formData.append(`path_${file.name}`, relativePath);
            console.log(`📁 Multipart init: ${file.name} -> ${relativePath}`);
        }
        
        formData.append('csrfmiddlewaretoken', this.getCsrfToken());

        const response = await fetch(this.initUrl, {
            method: 'POST',
            body: formData,
            signal: this.abortController.signal
        });

        if (!response.ok) {
            throw new Error(`Failed to initialize upload: ${response.status}`);
        }

        return await response.json();
    }

    /**
     * Upload file in chunks to S3
     */
    async uploadFileChunks(file, uploadId, s3Key) {
        const fileSize = file.size;
        const totalChunks = Math.ceil(fileSize / this.chunkSize);
        const parts = [];
        
        console.log(`📦 Uploading ${file.name} in ${totalChunks} chunks`);

        // Upload chunks with controlled concurrency
        const activeChunkUploads = new Set();
        let chunkIndex = 0;
        const chunkErrors = [];

        return new Promise((resolve, reject) => {
            const processNextChunk = async () => {
                try {
                    // Check if cancelled
                    if (this.abortController.signal.aborted) {
                        reject(new DOMException('Upload cancelled', 'AbortError'));
                        return;
                    }

                    // Check if we're done
                    if (chunkIndex >= totalChunks && activeChunkUploads.size === 0) {
                        if (chunkErrors.length > 0) {
                            reject(new Error(`${chunkErrors.length} chunks failed to upload`));
                            return;
                        }
                        
                        // Sort parts by part number for S3
                        parts.sort((a, b) => a.partNumber - b.partNumber);
                        resolve(parts);
                        return;
                    }

                    // Start new chunk uploads if we have capacity
                    while (activeChunkUploads.size < this.maxConcurrent && chunkIndex < totalChunks) {
                        const currentChunkIndex = chunkIndex++;
                        const partNumber = currentChunkIndex + 1; // S3 part numbers start at 1
                        
                        const uploadPromise = this.uploadSingleChunk(
                            file, uploadId, s3Key, currentChunkIndex, partNumber, fileSize
                        )
                            .then(etag => {
                                parts.push({ partNumber, etag });
                                this.updateFileProgress(file, currentChunkIndex + 1, totalChunks);
                            })
                            .catch(error => {
                                chunkErrors.push({ chunk: currentChunkIndex, error });
                                console.error(`❌ Chunk ${currentChunkIndex} failed:`, error);
                            })
                            .finally(() => {
                                activeChunkUploads.delete(uploadPromise);
                                processNextChunk();
                            });

                        activeChunkUploads.add(uploadPromise);
                    }
                } catch (error) {
                    reject(error);
                }
            };

            processNextChunk();
        });
    }

    /**
     * Upload a single chunk to S3
     */
    async uploadSingleChunk(file, uploadId, s3Key, chunkIndex, partNumber, fileSize) {
        const start = chunkIndex * this.chunkSize;
        const end = Math.min(start + this.chunkSize, fileSize);
        const chunk = file.slice(start, end);
        
        console.log(`📦 Uploading chunk ${partNumber}/${Math.ceil(fileSize / this.chunkSize)} of ${file.name}`);

        const formData = new FormData();
        formData.append('uploadId', uploadId);
        formData.append('s3Key', s3Key);
        formData.append('partNumber', partNumber.toString());
        formData.append('chunk', chunk);
        formData.append('csrfmiddlewaretoken', this.getCsrfToken());

        const response = await fetch(this.chunkUrl, {
            method: 'POST',
            body: formData,
            signal: this.abortController.signal
        });

        if (!response.ok) {
            throw new Error(`Failed to upload chunk ${partNumber}: ${response.status}`);
        }

        const result = await response.json();
        return result.etag;
    }

    /**
     * Complete S3 multipart upload
     */
    async completeMultipartUpload(uploadId, s3Key, parts) {
        const formData = new FormData();
        formData.append('uploadId', uploadId);
        formData.append('s3Key', s3Key);
        formData.append('parts', JSON.stringify(parts));
        formData.append('csrfmiddlewaretoken', this.getCsrfToken());

        const response = await fetch(this.completeUrl, {
            method: 'POST',
            body: formData,
            headers: {
                'HX-Request': 'true',  // Tell server we want HTMX OOB updates
                'HX-Target': 'toast-container'
            },
            signal: this.abortController.signal
        });

        if (!response.ok) {
            throw new Error(`Failed to complete upload: ${response.status}`);
        }

        // Handle HTMX response (HTML with OOB updates) instead of JSON
        const contentType = response.headers.get('content-type');
        if (contentType && contentType.includes('text/html')) {
            // HTMX HTML response with OOB updates - process them
            const html = await response.text();
            
            // Create temporary container to parse HTML
            const temp = document.createElement('div');
            temp.innerHTML = html;
            
            // Process OOB updates via HTMX
            if (typeof htmx !== 'undefined') {
                htmx.process(temp);
                
                const oobElements = temp.querySelectorAll('[hx-swap-oob]');
                oobElements.forEach(element => {
                    const swapStyle = element.getAttribute('hx-swap-oob');
                    const targetId = element.id;
                    const targetElement = document.getElementById(targetId);
                    
                    if (targetElement && swapStyle === 'innerHTML') {
                        targetElement.innerHTML = element.innerHTML;
                        htmx.process(targetElement);
                    }
                });
                
                console.log(`✅ Multipart: Processed ${oobElements.length} OOB updates`);
            }
            
            // Return success for completion tracking
            return { success: true };
        } else {
            // Fallback JSON response
            return await response.json();
        }
    }

    /**
     * Abort a multipart upload
     */
    async abortMultipartUpload(uploadId, s3Key) {
        try {
            const formData = new FormData();
            formData.append('uploadId', uploadId);
            formData.append('s3Key', s3Key);
            formData.append('csrfmiddlewaretoken', this.getCsrfToken());

            await fetch('/storage/upload/multipart/abort/', {
                method: 'POST',
                body: formData
            });
        } catch (error) {
            console.warn('Failed to abort multipart upload:', error);
        }
    }

    /**
     * Clean up all active uploads
     */
    async cleanupActiveUploads() {
        const cleanupPromises = Array.from(this.activeUploads.values()).map(upload => 
            this.abortMultipartUpload(upload.uploadId, upload.s3Key)
        );
        
        await Promise.allSettled(cleanupPromises);
    }

    /**
     * Update progress for a specific file
     */
    updateFileProgress(file, uploadedChunks, totalChunks) {
        const fileProgress = uploadedChunks / totalChunks;
        const chunkSize = Math.min(this.chunkSize, file.size - (uploadedChunks - 1) * this.chunkSize);
        
        // Update global progress
        this.uploadedSize += chunkSize;
        
        this.onProgress({
            file: file.name,
            fileProgress: Math.round(fileProgress * 100),
            globalProgress: Math.round((this.uploadedSize / this.totalSize) * 100),
            uploadedSize: this.uploadedSize,
            totalSize: this.totalSize,
            completedFiles: this.completedFiles,
            totalFiles: this.totalFiles
        });
    }

    /**
     * Handle successful file upload
     */
    handleFileResult(file, result) {
        console.log(`✅ File completed: ${file.name}`);
        
        this.completedFiles++;
        this.results.push({
            file: file.name,
            success: true,
            result: result
        });

        this.onFileComplete(file, result);
    }

    /**
     * Handle file upload error
     */
    handleFileError(file, error) {
        console.error(`❌ File failed: ${file.name}`, error);
        
        this.failedFiles++;
        this.results.push({
            file: file.name,
            success: false,
            error: error.message
        });

        this.onError(error, file);
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
            completedFiles: this.completedFiles,
            failedFiles: this.failedFiles,
            total_uploaded_files: this.completedFiles,
            total_size: this.totalSize,
            total_size_formatted: formatFileSize(this.totalSize),
            duration: elapsed,
            duration_seconds: Math.round(elapsed / 1000),
            results: this.results
        };
    }

    /**
     * Cancel the current upload
     */
    cancelUpload() {
        if (this.abortController) {
            console.log('🛑 Cancelling multipart upload...');
            this.abortController.abort();
        }
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
        console.log(`📊 Progress: ${progress.globalProgress}% (${progress.completedFiles}/${progress.totalFiles} files)`);
    }

    defaultFileCompleteHandler(file, result) {
        console.log(`✅ File completed: ${file.name}`);
    }

    defaultCompleteHandler(summary) {
        console.log('🎉 Multipart upload complete:', summary);
    }

    defaultErrorHandler(error, file) {
        console.error('❌ Multipart upload error:', error);
    }
}

/**
 * Easy-to-use function for S3 multipart uploads
 */
async function uploadFilesWithMultipart(files, folderName, organization = '', baseFolder = '', options = {}) {
    const uploader = new S3MultipartUploadHandler(options);
    return await uploader.uploadFiles(files, folderName, organization, baseFolder);
}

// Use the same utility functions
function formatFileSize(bytes) {
    if (bytes === 0) return '0 Bytes';
    
    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
}

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
        S3MultipartUploadHandler, 
        uploadFilesWithMultipart,
        formatFileSize,
        formatDuration
    };
}