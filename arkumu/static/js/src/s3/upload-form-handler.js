/**
 * Simple Upload Form Handler - Chunked Upload Only
 * Handles file uploads using only the chunked upload strategy for simplicity
 */
class UploadFormHandler {
    constructor() {
        console.log('📁 Initializing Upload Form Handler (chunked only)');
        this.selectedFiles = [];
        this.currentUploader = null;
        this.initializeElements();
        this.bindEvents();
    }

    initializeElements() {
        // Form elements
        this.form = document.getElementById('streaming-upload-form');
        this.fileInput = document.getElementById('file-input');
        this.uploadButton = document.getElementById('upload-button');
        this.organizationInput = document.getElementById('organization');
        this.baseFolderSelect = document.getElementById('base-folder');
        
        // Progress and status elements
        this.progressContainer = document.getElementById('upload-progress');
        this.progressBar = document.getElementById('progress-bar');
        this.progressText = document.getElementById('progress-text');
        this.progressPercentage = document.getElementById('progress-percentage');
        this.statusContainer = document.getElementById('upload-status');
        
        // Results elements
        this.resultsContainer = document.getElementById('upload-results');
        this.selectedFilesInfo = document.getElementById('selected-files-info');
        this.fileCountSpan = document.getElementById('file-count');
        this.totalSizeSpan = document.getElementById('total-size');
        this.resultFilesCount = document.getElementById('result-files-count');
        this.resultTotalSize = document.getElementById('result-total-size');
        this.resultDuration = document.getElementById('result-duration');
    }

    bindEvents() {
        if (this.fileInput) {
            this.fileInput.addEventListener('change', (e) => {
                this.handleFileSelection(e.target.files);
            });
        }

        if (this.uploadButton) {
            this.uploadButton.addEventListener('click', () => {
                this.handleUploadClick();
            });
        }
    }
    
    refreshFileInput() {
        // Update file input reference after HTMX swap
        this.fileInput = document.getElementById('file-input');
        // Clear selection state
        this.selectedFiles = [];
        this.updateFileSelectionDisplay();
    }

    handleFileSelection(files) {
        console.log('Files selected:', files.length);
        
        if (files.length > 0) {
            this.selectedFiles = Array.from(files);
            this.updateFileSelectionDisplay();
        }
    }

    updateFileSelectionDisplay() {
        if (this.selectedFiles.length === 0) {
            this.selectedFilesInfo.classList.add('hidden');
            return;
        }

        const totalSize = this.selectedFiles.reduce((sum, file) => sum + file.size, 0);
        
        this.selectedFilesInfo.classList.remove('hidden');
        this.fileCountSpan.textContent = `${this.selectedFiles.length} files selected`;
        this.totalSizeSpan.textContent = formatFileSize(totalSize);
        
        // Show chunking info if many files
        if (this.selectedFiles.length > 100) {
            const chunks = Math.ceil(this.selectedFiles.length / 75);
            this.fileCountSpan.textContent += ` (${chunks} chunks)`;
        }
    }

    async handleUploadClick() {
        if (this.isUploading) {
            // Cancel current upload
            if (this.currentUploader) {
                this.currentUploader.cancelUpload();
            }
            return;
        }

        // Validate form
        const validation = this.validateForm();
        if (!validation.valid) {
            this.showError(validation.message);
            return;
        }

        // Start upload
        await this.startUpload();
    }

    validateForm() {
        if (this.selectedFiles.length === 0) {
            return { valid: false, message: 'Please select files to upload' };
        }

        return { valid: true };
    }

    async startUpload() {
        try {
            // Force clear any existing upload status before starting
            this.clearStatus();
            this.hideResults();
            
            // Additional aggressive clearing to prevent cached content reappearing
            setTimeout(() => {
                this.clearStatus();
            }, 100);
            
            // Get form values
            const baseFolder = this.baseFolderSelect ? this.baseFolderSelect.value : '';
            const organization = this.organizationInput ? this.organizationInput.value : '';
            
            // Use the selected base folder directly
            const folderName = baseFolder;

            // Simple strategy: Use chunked upload for everything
            console.log(`🔄 Using chunked upload for ${this.selectedFiles.length} files`);
            await this.performChunkedUpload(folderName, organization, baseFolder);

        } catch (error) {
            console.error('Upload error:', error);
            this.showError(error.message || 'Upload failed');
        } finally {
            this.updateUploadButton(false);
        }
    }

    async performChunkedUpload(folderName, organization, baseFolder) {
        console.log(`📁 CHUNKED UPLOAD: Starting chunked upload`);
        console.log(`📁 CHUNKED UPLOAD: folderName = "${folderName}"`);
        console.log(`📁 CHUNKED UPLOAD: organization = "${organization}"`);
        console.log(`📁 CHUNKED UPLOAD: baseFolder = "${baseFolder}"`);
        
        this.currentUploader = new ChunkedUploadHandler({
            chunkSize: 75,
            maxConcurrent: 3,
            onProgress: (progress) => this.updateProgress(progress),
            onChunkComplete: (chunk, result) => this.handleChunkComplete(chunk, result),
            onComplete: (summary) => this.handleUploadComplete(summary),
            onError: (error, chunk) => this.handleUploadError(error, chunk)
        });

        const result = await this.currentUploader.uploadFiles(
            this.selectedFiles,
            folderName,
            organization,
            baseFolder
        );

        return result;
    }

    updateProgress(progress) {
        if (!this.progressContainer) return;
        
        // Show progress container
        this.progressContainer.classList.remove('hidden');
        
        // Update progress bar
        if (this.progressBar && typeof progress.percentage === 'number') {
            this.progressBar.value = progress.percentage;
        }
        
        // Update percentage text
        if (this.progressPercentage && typeof progress.percentage === 'number') {
            this.progressPercentage.textContent = `${Math.round(progress.percentage)}%`;
        }
        
        // Update progress text
        if (this.progressText) {
            let text = 'Uploading...';
            
            if (progress.processedFiles !== undefined && progress.totalFiles !== undefined) {
                text = `Uploading ${progress.processedFiles}/${progress.totalFiles} files`;
            } else if (progress.processedChunks !== undefined && progress.totalChunks !== undefined) {
                text = `Processing chunk ${progress.processedChunks}/${progress.totalChunks}`;
            }
            
            this.progressText.textContent = text;
        }
    }

    handleChunkComplete(chunk, result) {
        console.log(`✅ Chunk ${chunk.index + 1} completed:`, result);
        
        // Remove per-chunk status updates - too verbose
        // this.showStatus(`Completed chunk ${chunk.index + 1}`, 'info');
    }

    handleUploadComplete(summary) {
        this.hideProgress();
        
        if (summary.success) {
            // Don't show results here - HTMX OOB update already handles this
            // this.showResults(summary);
            
            console.log('🔄 UploadFormHandler: Upload completed successfully');
        } else {
            const message = summary.cancelled 
                ? 'Upload was cancelled'
                : summary.error || 'Upload failed';
            this.showError(message);
        }
    }

    handleUploadError(error, chunk) {
        console.error('Upload error:', error, chunk);
        
        const message = chunk 
            ? `Error uploading chunk ${chunk.index + 1}: ${error.message || error}`
            : error.message || error;
        
        this.showError(message);
    }

    showProgress() {
        if (this.progressContainer) {
            this.progressContainer.classList.remove('hidden');
        }
    }

    hideProgress() {
        if (this.progressContainer) {
            this.progressContainer.classList.add('hidden');
        }
    }

    showStatus(message, type = 'info') {
        if (!this.statusContainer) return;
        
        const alertClass = type === 'error' ? 'alert-error' : 
                          type === 'success' ? 'alert-success' : 'alert-info';
        
        this.statusContainer.innerHTML = `
            <div class="alert ${alertClass}">
                <span>${message}</span>
            </div>
        `;
    }

    showError(message) {
        this.showStatus(message, 'error');
    }

    clearStatus() {
        if (this.statusContainer) {
            this.statusContainer.innerHTML = '';
            // Also clear any data attributes that might be cached
            this.statusContainer.removeAttribute('data-cached-content');
            console.log('✅ Status container cleared');
        }
    }

    showResults(summary) {
        if (!this.resultsContainer) return;
        
        this.resultsContainer.classList.remove('hidden');
        
        // Update result stats
        if (this.resultFilesCount) {
            this.resultFilesCount.textContent = summary.total_uploaded_files || summary.processedFiles || 0;
        }
        
        if (this.resultTotalSize) {
            const totalSize = summary.total_size_formatted || 
                            (summary.total_size ? formatFileSize(summary.total_size) : '0 bytes');
            this.resultTotalSize.textContent = totalSize;
        }
        
        if (this.resultDuration) {
            let duration = '0s';
            if (summary.duration_seconds) {
                duration = `${summary.duration_seconds}s`;
            } else if (summary.duration) {
                duration = `${Math.round(summary.duration / 1000)}s`;
            }
            this.resultDuration.textContent = duration;
        }
    }

    hideResults() {
        if (this.resultsContainer) {
            this.resultsContainer.classList.add('hidden');
        }
    }

    updateUploadButton(isUploading) {
        if (!this.uploadButton) return;
        
        this.isUploading = isUploading;
        
        if (isUploading) {
            this.uploadButton.textContent = 'Cancel Upload';
            this.uploadButton.classList.remove('btn-primary');
            this.uploadButton.classList.add('btn-error');
        } else {
            this.uploadButton.textContent = 'Upload Files';
            this.uploadButton.classList.remove('btn-error');
            this.uploadButton.classList.add('btn-primary');
        }
    }
}

// Initialize when DOM is ready
document.addEventListener('DOMContentLoaded', function() {
    // Only initialize if the upload form exists
    if (document.getElementById('streaming-upload-form')) {
        window.uploadFormHandler = new UploadFormHandler();
        console.log('📁 Upload form handler initialized');
    }
});