/**
 * Upload Form Handler with Chunked Upload Support
 * 
 * Handles the upload form with automatic chunking for large file uploads.
 * Integrates with the existing streaming upload system.
 */
class UploadFormHandler {
    constructor() {
        this.selectedFiles = [];
        this.currentUploader = null;
        this.isUploading = false;
        
        this.initializeElements();
        this.bindEvents();
    }

    initializeElements() {
        // Form elements
        this.form = document.getElementById('streaming-upload-form');
        this.fileInput = document.getElementById('file-input');
        this.baseFolderSelect = document.getElementById('base-folder');
        this.organizationInput = document.getElementById('organization');
        this.uploadButton = document.getElementById('upload-button');
        
        // Progress elements
        this.progressContainer = document.getElementById('upload-progress');
        this.progressText = document.getElementById('progress-text');
        this.progressPercentage = document.getElementById('progress-percentage');
        this.progressBar = document.getElementById('progress-bar');
        
        // Status and results elements
        this.statusContainer = document.getElementById('upload-status');
        this.resultsContainer = document.getElementById('upload-results');
        this.selectedFilesInfo = document.getElementById('selected-files-info');
        this.fileCountSpan = document.getElementById('file-count');
        this.totalSizeSpan = document.getElementById('total-size');
        
        // Results elements
        this.resultFilesCount = document.getElementById('result-files-count');
        this.resultTotalSize = document.getElementById('result-total-size');
        this.resultDuration = document.getElementById('result-duration');
    }

    bindEvents() {
        // File selection - use event delegation for dynamic elements
        document.addEventListener('change', (e) => {
            if (e.target && e.target.id === 'file-input') {
                this.handleFileSelection(e.target.files);
            }
        });

        // Upload button - only intercept if not using HTMX
        if (this.uploadButton && !this.form.hasAttribute('hx-post')) {
            this.uploadButton.addEventListener('click', (e) => {
                e.preventDefault();
                this.handleUploadClick();
            });
        }
        
        // Listen for HTMX after swap events to refresh file input reference
        document.addEventListener('htmx:afterSwap', (e) => {
            if (e.detail.target.id === 'upload-input-container') {
                this.refreshFileInput();
            }
        });
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

        if (this.baseFolderSelect && !this.baseFolderSelect.value) {
            return { valid: false, message: 'Please select a base folder' };
        }

        return { valid: true };
    }

    async startUpload() {
        try {
            this.isUploading = true;
            this.updateUploadButton(true);
            this.hideResults();
            this.clearStatus();

            // Get form values
            const baseFolder = this.baseFolderSelect ? this.baseFolderSelect.value : '';
            const organization = this.organizationInput ? this.organizationInput.value : '';
            
            // Check if we're in folder mode by examining file input attributes
            const isFolderMode = this.fileInput && this.fileInput.hasAttribute('webkitdirectory');
            
            console.log(`📁 FORM HANDLER DEBUG: File input element:`, this.fileInput);
            console.log(`📁 FORM HANDLER DEBUG: Has webkitdirectory attribute:`, this.fileInput?.hasAttribute('webkitdirectory'));
            console.log(`📁 FORM HANDLER DEBUG: isFolderMode = ${isFolderMode}`);
            
            // For folder mode, we need to preserve individual file paths
            let folderName = '';
            if (isFolderMode && this.selectedFiles.length > 0) {
                // Extract the root folder name for display purposes only
                const firstFile = this.selectedFiles[0];
                if (firstFile.webkitRelativePath) {
                    const pathParts = firstFile.webkitRelativePath.split('/');
                    folderName = pathParts[0]; // Just for logging/display
                    console.log(`📁 FORM HANDLER DEBUG: Detected folder upload`);
                    console.log(`📁 FORM HANDLER DEBUG: folderName = "${folderName}"`);
                    console.log(`📁 FORM HANDLER DEBUG: isFolderMode = ${isFolderMode}`);
                    console.log(`📁 FORM HANDLER DEBUG: sample file paths:`, this.selectedFiles.slice(0, 3).map(f => f.webkitRelativePath || f.name));
                }
            }

            // Smart upload strategy - separate large files from small files
            const LARGE_FILE_THRESHOLD = 50 * 1024 * 1024; // 50MB
            const totalSize = this.selectedFiles.reduce((sum, file) => sum + file.size, 0);
            
            // Separate files by size
            const largeFiles = this.selectedFiles.filter(file => file.size >= LARGE_FILE_THRESHOLD);
            const smallFiles = this.selectedFiles.filter(file => file.size < LARGE_FILE_THRESHOLD);
            
            console.log(`📊 Upload strategy analysis:`, {
                totalFiles: this.selectedFiles.length,
                totalSize: formatFileSize(totalSize),
                largeFiles: largeFiles.length,
                smallFiles: smallFiles.length,
                largeFileSizes: largeFiles.map(f => `${f.name}: ${formatFileSize(f.size)}`)
            });
            
            // Strategy 1: Mixed upload - handle large and small files separately
            if (largeFiles.length > 0 && smallFiles.length > 0) {
                console.log(`🔄 Using mixed upload strategy: ${largeFiles.length} large files (resumable) + ${smallFiles.length} small files (batched)`);
                await this.performMixedUpload(largeFiles, smallFiles, folderName, organization, baseFolder, isFolderMode);
            }
            // Strategy 2: Large files only - use resumable upload for each
            else if (largeFiles.length > 0) {
                console.log(`🔄 Using resumable upload for ${largeFiles.length} large files`);
                await this.performLargeFilesUpload(largeFiles, folderName, organization, baseFolder, isFolderMode);
            }
            // Strategy 3: Small files - batch or standard based on count
            else if (smallFiles.length > 75 || totalSize > 500 * 1024 * 1024) {
                console.log(`🔄 Using chunked upload for ${smallFiles.length} small files (total size: ${formatFileSize(totalSize)})`);
                await this.performChunkedUpload(folderName, organization, baseFolder, isFolderMode);
            }
            // Strategy 4: Few small files - standard upload
            else {
                console.log(`📤 Using standard upload for ${smallFiles.length} small files (total size: ${formatFileSize(totalSize)})`);
                await this.performStandardUpload(folderName, organization, baseFolder, isFolderMode);
            }

        } catch (error) {
            console.error('Upload error:', error);
            this.showError(error.message || 'Upload failed');
        } finally {
            this.isUploading = false;
            this.updateUploadButton(false);
        }
    }

    async performChunkedUpload(folderName, organization, baseFolder, isFolderMode) {
        console.log(`📁 CHUNKED UPLOAD DEBUG: Starting chunked upload`);
        console.log(`📁 CHUNKED UPLOAD DEBUG: folderName = "${folderName}"`);
        console.log(`📁 CHUNKED UPLOAD DEBUG: organization = "${organization}"`);
        console.log(`📁 CHUNKED UPLOAD DEBUG: baseFolder = "${baseFolder}"`);
        console.log(`📁 CHUNKED UPLOAD DEBUG: isFolderMode = ${isFolderMode}`);
        
        this.currentUploader = new ChunkedUploadHandler({
            chunkSize: 75,
            maxConcurrent: 3,
            preserveFolderStructure: isFolderMode,
            onProgress: (progress) => this.updateProgress(progress),
            onChunkComplete: (chunk, result) => this.handleChunkComplete(chunk, result),
            onComplete: (summary) => this.handleUploadComplete(summary),
            onError: (error, chunk) => this.handleUploadError(error, chunk)
        });

        this.showProgress();
        
        const result = await this.currentUploader.uploadFiles(
            this.selectedFiles,
            folderName,
            organization,
            baseFolder
        );

        return result;
    }

    async performStandardUpload(folderName, organization, baseFolder, isFolderMode) {
        this.showProgress();
        
        // Use existing streaming upload
        const formData = new FormData();
        
        // For folder mode, we don't set a single folder_name
        // Instead, we let the backend handle individual file paths
        if (!isFolderMode) {
            // Create the final folder path for non-folder mode
            let finalFolderName = folderName;
            if (baseFolder) {
                finalFolderName = baseFolder + (folderName ? '/' + folderName : '');
            }
            formData.append('folder_name', finalFolderName);
        } else {
            // For folder mode, set the base folder only
            formData.append('folder_name', baseFolder || '');
            formData.append('preserve_folder_structure', 'true');
        }
        
        if (organization) {
            formData.append('organization', organization);
        }

        this.selectedFiles.forEach(file => {
            formData.append('files', file);
        });

        // Add CSRF token
        const csrfToken = document.querySelector('[name=csrfmiddlewaretoken]');
        if (csrfToken) {
            formData.append('csrfmiddlewaretoken', csrfToken.value);
        }

        try {
            // Route to raw streaming endpoint for data uploads
            const uploadUrl = baseFolder === 'data' ? '/storage/upload/streaming/raw/' : '/storage/upload/streaming/';
            console.log(`📡 Using endpoint: ${uploadUrl} for baseFolder: ${baseFolder}`);
            
            const response = await fetch(uploadUrl, {
                method: 'POST',
                body: formData
            });

            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }

            const result = await response.json();
            
            if (result.success) {
                this.handleUploadComplete(result);
            } else {
                throw new Error(result.error || 'Upload failed');
            }

        } catch (error) {
            this.handleUploadError(error);
        }
    }

    updateProgress(progress) {
        if (!this.progressContainer) return;

        this.progressContainer.classList.remove('hidden');
        
        // Update progress bar
        if (this.progressBar) {
            this.progressBar.value = progress.percentage;
        }
        
        if (this.progressPercentage) {
            this.progressPercentage.textContent = `${progress.percentage}%`;
        }
        
        if (this.progressText) {
            let text = `Uploading ${progress.processedFiles}/${progress.totalFiles} files`;
            
            if (progress.estimatedRemaining) {
                text += ` (${formatDuration(progress.estimatedRemaining)} remaining)`;
            }
            
            this.progressText.textContent = text;
        }
    }

    handleChunkComplete(chunk, result) {
        console.log(`Chunk ${chunk.index + 1} completed:`, result);
        
        // Could add per-chunk status updates here
        this.showStatus(`Completed chunk ${chunk.index + 1}`, 'info');
    }

    handleUploadComplete(summary) {
        console.log('Upload completed:', summary);
        
        this.hideProgress();
        
        if (summary.success) {
            this.showResults(summary);
            
            // Refresh file browser after successful upload
            console.log('🔄 UploadFormHandler: Triggering file browser refresh...');
            if (typeof refreshFileBrowser === 'function') {
                refreshFileBrowser();
            } else {
                console.warn('⚠️ refreshFileBrowser function not found');
            }
        } else {
            const message = summary.cancelled 
                ? 'Upload was cancelled' 
                : `Upload completed with ${summary.failedFiles} failed files`;
            this.showStatus(message, summary.cancelled ? 'info' : 'warning');
            this.showResults(summary);
        }
    }

    handleUploadError(error, chunk) {
        console.error('Upload error:', error);
        
        this.hideProgress();
        
        let message = 'Upload failed: ' + (error.message || 'Unknown error');
        if (chunk) {
            message += ` (Chunk ${chunk.index + 1})`;
        }
        
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

        const alertClass = {
            'success': 'alert-success',
            'error': 'alert-error',
            'warning': 'alert-warning',
            'info': 'alert-info'
        }[type] || 'alert-info';

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
        }
    }

    showResults(summary) {
        if (!this.resultsContainer) return;

        this.resultsContainer.classList.remove('hidden');
        
        if (this.resultFilesCount) {
            // Use server-provided count for accurate results
            this.resultFilesCount.textContent = summary.total_uploaded_files || summary.completedFiles || 0;
        }
        
        if (this.resultTotalSize) {
            // Use server-provided formatted size for accuracy
            this.resultTotalSize.textContent = summary.total_size_formatted || formatFileSize(summary.total_size_bytes || 0);
        }
        
        if (this.resultDuration) {
            // Convert seconds to milliseconds for formatDuration, or display seconds directly
            const durationSeconds = summary.duration_seconds || summary.duration || 0;
            if (durationSeconds < 1) {
                this.resultDuration.textContent = `${(durationSeconds * 1000).toFixed(0)}ms`;
            } else {
                this.resultDuration.textContent = `${durationSeconds.toFixed(1)}s`;
            }
        }
    }

    hideResults() {
        if (this.resultsContainer) {
            this.resultsContainer.classList.add('hidden');
        }
    }

    updateUploadButton(isUploading) {
        if (!this.uploadButton) return;

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

    async performMixedUpload(largeFiles, smallFiles, folderName, organization, baseFolder, isFolderMode) {
        console.log(`🔄 MIXED UPLOAD: Starting mixed upload strategy`);
        
        const results = {
            largeFileResults: [],
            smallFileResults: null,
            totalFiles: largeFiles.length + smallFiles.length,
            completedFiles: 0,
            failedFiles: 0
        };

        try {
            // Step 1: Upload large files individually with resumable upload
            for (let i = 0; i < largeFiles.length; i++) {
                const file = largeFiles[i];
                console.log(`📤 LARGE FILE ${i + 1}/${largeFiles.length}: ${file.name} (${formatFileSize(file.size)})`);
                
                const resumableUpload = new ResumableUpload(file, {
                    chunkSize: 8 * 1024 * 1024, // 8MB chunks
                    maxRetries: 5,
                    organization: organization,
                    baseFolder: baseFolder,
                    folderName: folderName,
                    originalPath: isFolderMode ? file.webkitRelativePath : file.name,
                    onProgress: (progress) => {
                        // Update overall progress
                        const overallProgress = {
                            processedFiles: results.completedFiles,
                            totalFiles: results.totalFiles,
                            percentage: Math.round((results.completedFiles / results.totalFiles) * 100),
                            currentFile: file.name,
                            fileProgress: progress.progress
                        };
                        this.updateProgress(overallProgress);
                    },
                    onComplete: (result) => {
                        console.log(`✅ LARGE FILE COMPLETE: ${file.name}`);
                        results.completedFiles++;
                        results.largeFileResults.push({file: file.name, success: true, result});
                    },
                    onError: (error) => {
                        console.error(`❌ LARGE FILE ERROR: ${file.name}:`, error);
                        results.failedFiles++;
                        results.largeFileResults.push({file: file.name, success: false, error});
                    }
                });

                try {
                    await resumableUpload.upload();
                } catch (error) {
                    console.error(`❌ Failed to upload large file ${file.name}:`, error);
                    results.failedFiles++;
                }
            }

            // Step 2: Upload small files in batch if any
            if (smallFiles.length > 0) {
                console.log(`📦 SMALL FILES: Uploading ${smallFiles.length} small files in batch`);
                
                // Temporarily replace selectedFiles with small files for chunked upload
                const originalFiles = this.selectedFiles;
                this.selectedFiles = smallFiles;
                
                try {
                    results.smallFileResults = await this.performChunkedUpload(folderName, organization, baseFolder, isFolderMode);
                    results.completedFiles += smallFiles.length;
                } catch (error) {
                    console.error(`❌ Small files batch upload failed:`, error);
                    results.failedFiles += smallFiles.length;
                } finally {
                    // Restore original files
                    this.selectedFiles = originalFiles;
                }
            }

            // Show completion
            this.handleUploadComplete({
                success: results.failedFiles === 0,
                total_uploaded_files: results.completedFiles,
                failed_files: results.failedFiles,
                total_size_formatted: formatFileSize(this.selectedFiles.reduce((sum, f) => sum + f.size, 0)),
                duration_seconds: 0 // TODO: track actual duration
            });

        } catch (error) {
            console.error('Mixed upload error:', error);
            this.handleUploadError(error);
        }
    }

    async performLargeFilesUpload(largeFiles, folderName, organization, baseFolder, isFolderMode) {
        console.log(`🔄 LARGE FILES ONLY: Uploading ${largeFiles.length} large files with resumable upload`);
        
        // For now, delegate to mixed upload with no small files
        return await this.performMixedUpload(largeFiles, [], folderName, organization, baseFolder, isFolderMode);
    }
}

// Initialize when DOM is ready
document.addEventListener('DOMContentLoaded', function() {
    // Only initialize on non-HTMX upload form pages
    const form = document.getElementById('streaming-upload-form');
    if (form && !form.hasAttribute('hx-post')) {
        window.uploadFormHandler = new UploadFormHandler();
        console.log('📁 Upload form handler initialized');
    }
}); 