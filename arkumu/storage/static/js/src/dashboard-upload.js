// Dashboard Upload System - Async Upload with HTMX Integration

// Debug logging configuration - set to false in production
const DEBUG_UPLOADS = window.location.hostname === 'localhost' || window.location.search.includes('debug=true');

// Conditional logging functions
const debugLog = DEBUG_UPLOADS ? console.log.bind(console) : () => {};
const debugError = DEBUG_UPLOADS ? console.error.bind(console) : () => {};

// Global upload tracker for coordinating multiple uploads
const uploadTracker = {
    activeUploads: new Map(), // filename -> upload state
    totalFiles: 0,
    completedFiles: 0,
    failedFiles: 0,
    totalBytes: 0,
    uploadedBytes: 0,
    startTime: null,
    
    startSession(files) {
        this.totalFiles = files.length;
        this.completedFiles = 0;
        this.failedFiles = 0;
        this.totalBytes = files.reduce((sum, f) => sum + f.size, 0);
        this.uploadedBytes = 0;
        this.startTime = Date.now();
        this.activeUploads.clear();
    },
    
    trackFile(filename, size) {
        this.activeUploads.set(filename, {
            size: size,
            uploadedBytes: 0,
            progress: 0,
            status: 'queued',
            startTime: null
        });
    },
    
    updateFileProgress(filename, uploadedBytes, totalBytes) {
        const file = this.activeUploads.get(filename);
        if (file) {
            file.uploadedBytes = uploadedBytes;
            file.progress = (uploadedBytes / totalBytes) * 100;
            file.status = 'uploading';
            if (!file.startTime) {
                file.startTime = Date.now();
            }
            
            // Update global progress
            this.calculateGlobalProgress();
        }
    },
    
    completeFile(filename) {
        const file = this.activeUploads.get(filename);
        if (file) {
            file.status = 'completed';
            file.progress = 100;
            this.completedFiles++;
            this.uploadedBytes += file.size;
            this.calculateGlobalProgress();
        }
    },
    
    failFile(filename) {
        const file = this.activeUploads.get(filename);
        if (file) {
            file.status = 'failed';
            this.failedFiles++;
            this.calculateGlobalProgress();
        }
    },
    
    calculateGlobalProgress() {
        // Update overall folder progress if exists
        const overallProgress = document.getElementById('folder-overall-progress');
        const uploadStatus = document.getElementById('folder-upload-status');
        
        if (this.totalFiles > 0) {
            const processedFiles = this.completedFiles + this.failedFiles;
            const progress = (processedFiles / this.totalFiles) * 100;
            
            if (overallProgress) {
                overallProgress.value = progress;
            }
            if (uploadStatus) {
                uploadStatus.textContent = `${processedFiles} / ${this.totalFiles} files`;
            }
            
            // Calculate and display overall speed
            const elapsed = (Date.now() - this.startTime) / 1000;
            if (elapsed > 0 && this.uploadedBytes > 0) {
                const speed = this.uploadedBytes / elapsed;
                const speedElement = document.getElementById('folder-upload-speed');
                if (speedElement) {
                    speedElement.textContent = formatSpeed(speed);
                }
                
                // Calculate ETA
                const remainingBytes = this.totalBytes - this.uploadedBytes;
                const eta = remainingBytes / speed;
                const etaElement = document.getElementById('folder-upload-eta');
                if (etaElement) {
                    etaElement.textContent = `ETA: ${formatTime(eta)}`;
                }
            }
        }
    },
    
    getStatus() {
        return {
            totalFiles: this.totalFiles,
            completedFiles: this.completedFiles,
            failedFiles: this.failedFiles,
            progress: this.totalFiles > 0 ? ((this.completedFiles + this.failedFiles) / this.totalFiles) * 100 : 0,
            uploadedBytes: this.uploadedBytes,
            totalBytes: this.totalBytes
        };
    }
};

// Upload mode switching for dashboard
function switchToFilesMode() {
    const fileInput = document.getElementById('dashboard-file-picker');
    const filesBtn = document.getElementById('files-mode-btn');
    const folderBtn = document.getElementById('folder-mode-btn');
    
    if (fileInput) {
        // Enable multiple file selection
        fileInput.setAttribute('multiple', '');
        fileInput.removeAttribute('webkitdirectory');
        fileInput.removeAttribute('directory');
        fileInput.value = ''; // Clear selection when switching modes
    }
    
    // Update button states
    if (filesBtn) {
        filesBtn.classList.add('btn-active');
        filesBtn.classList.remove('btn-outline');
    }
    if (folderBtn) {
        folderBtn.classList.remove('btn-active');
        folderBtn.classList.add('btn-outline');
    }
    
    debugLog('📄 Dashboard: Switched to files mode');
}

function switchToFolderMode() {
    const fileInput = document.getElementById('dashboard-file-picker');
    const filesBtn = document.getElementById('files-mode-btn');
    const folderBtn = document.getElementById('folder-mode-btn');
    
    if (fileInput) {
        // Enable folder selection
        fileInput.setAttribute('webkitdirectory', '');
        fileInput.setAttribute('directory', '');
        fileInput.removeAttribute('multiple');
        fileInput.value = ''; // Clear selection when switching modes
    }
    
    // Update button states
    if (folderBtn) {
        folderBtn.classList.add('btn-active');
        folderBtn.classList.remove('btn-outline');
    }
    if (filesBtn) {
        filesBtn.classList.remove('btn-active');
        filesBtn.classList.add('btn-outline');
    }
    
    debugLog('📁 Dashboard: Switched to folder mode');
}

// Async Upload System for Dashboard
async function initializeDashboardUpload() {
    const fileInput = document.getElementById('dashboard-file-picker');
    if (!fileInput) return;

    fileInput.addEventListener('change', async function(e) {
        const files = Array.from(e.target.files);
        const uploadArea = document.getElementById('dashboard-upload-area');
        const orgSelector = document.querySelector('#upload-org-selector select[name="organization"]');
        const baseFolderSelector = document.getElementById('base-folder');
        
        if (files.length === 0) return;
        
        // Validate organization and base folder selection
        const organization = orgSelector ? orgSelector.value : '';
        const baseFolder = baseFolderSelector ? baseFolderSelector.value : '';
        
        if (!organization) {
            alert('Please select an organization first');
            return;
        }
        
        if (!baseFolder) {
            alert('Please select a base folder (data or metadata)');
            return;
        }
        
        // Build folder path: just baseFolder
        const folderPath = baseFolder;
        
        debugLog('🚀 ASYNC: Starting async upload session');
        
        try {
            // Phase 1: Initialize upload session and get presigned URLs
            const sessionResponse = await initializeAsyncUploadSession(files, folderPath);
            
            if (!sessionResponse.success) {
                throw new Error('Failed to initialize upload session');
            }
            
            // Clear previous uploads
            uploadArea.innerHTML = '';
            
            // Phase 2: Create UI cards for each file  
            createAsyncUploadCards(sessionResponse.results || sessionResponse.uploads, uploadArea);
            
            // Phase 3: Start uploading files to S3 automatically
            await startUploads(sessionResponse.results || sessionResponse.uploads, files);
            
        } catch (error) {
            debugError('❌ ASYNC: Upload failed:', error);
            showUploadError(uploadArea, 'Upload failed: ' + error.message);
        }
    });
}

async function initializeAsyncUploadSession(files, folderPath) {
    // Get the selected organization
    const orgSelector = document.querySelector('#upload-org-selector select[name="organization"]');
    const organization = orgSelector ? orgSelector.value : '';
    
    const batchData = {
        files: files.map(file => ({
            name: file.name,
            relativePath: file.webkitRelativePath || file.name,
            size: file.size,
            type: file.type
        })),
        folder: folderPath,
        organization: organization
    };
    
    debugLog('📡 ASYNC: Initializing session with', files.length, 'files');
    
    const response = await fetch('/storage/upload/presigned/batch/', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCsrfToken(),
        },
        credentials: 'include',
        body: JSON.stringify(batchData)
    });
    
    if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
    }
    
    return await response.json();
}

function createAsyncUploadCards(uploads, uploadArea) {
    // Check if this is a folder upload (many files or files with relative paths)
    const isFolderUpload = uploads.length > 10 || uploads.some(upload => upload.relativePath && upload.relativePath.includes('/'));
    
    if (isFolderUpload) {
        createFolderUploadSummary(uploads, uploadArea);
    } else {
        createIndividualFilesList(uploads, uploadArea);
    }
}

function createFolderUploadSummary(uploads, uploadArea) {
    const summaryContainer = document.createElement('div');
    summaryContainer.classList.add('async-upload-summary');
    summaryContainer.innerHTML = `
        <div class="card bg-base-100 shadow-sm">
            <div class="card-body p-4">
                <!-- Overall Progress -->
                <div class="mb-4">
                    <div class="flex justify-between items-center mb-2">
                        <h3 class="text-sm font-semibold">Upload Progress</h3>
                        <span class="text-sm text-base-content/70">
                            <span id="folder-upload-status">0 / ${uploads.length} files</span>
                        </span>
                    </div>
                    <progress id="folder-overall-progress" class="progress progress-primary w-full" value="0" max="100"></progress>
                    <div class="flex justify-between text-xs text-base-content/60 mt-1">
                        <span id="folder-upload-speed"></span>
                        <span id="folder-upload-eta"></span>
                    </div>
                </div>
                
                <!-- Collapsible File List -->
                <div class="collapse collapse-arrow bg-base-200">
                    <input type="checkbox" />
                    <div class="collapse-title text-sm font-medium">
                        View all ${uploads.length} files
                    </div>
                    <div class="collapse-content">
                        <ul class="list mt-2" id="folder-files-list">
                            ${uploads.map(upload => `
                                <li class="list-row py-2 upload-file-container" data-filename="${upload.filename}">
                                    <div class="flex-shrink-0">
                                        ${getCompactFileIcon(upload.filename)}
                                    </div>
                                    <div class="list-col-grow">
                                        <div class="text-sm">${upload.filename}</div>
                                        ${upload.relativePath && upload.relativePath !== upload.filename ? 
                                            `<div class="text-xs opacity-60">${upload.relativePath}</div>` : 
                                            ''
                                        }
                                        <div class="upload-progress hidden mt-1">
                                            <progress class="progress progress-primary progress-xs w-full" value="0" max="100"></progress>
                                        </div>
                                    </div>
                                    <div class="upload-progress-indicator hidden">
                                        <span class="text-xs status-text">0%</span>
                                    </div>
                                    <div class="status-badge">
                                        <div class="badge badge-outline badge-xs">Ready</div>
                                    </div>
                                    <button class="btn btn-ghost btn-xs btn-square remove-file-btn" onclick="removeUploadByFilename('${upload.filename}')" title="Remove file">
                                        <svg xmlns="http://www.w3.org/2000/svg" class="h-3 w-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
                                        </svg>
                                    </button>
                                </li>
                            `).join('')}
                        </ul>
                    </div>
                </div>
            </div>
        </div>
    `;
    
    uploadArea.appendChild(summaryContainer);
}

function createIndividualFilesList(uploads, uploadArea) {
    // Create detailed list for smaller uploads (original implementation)
    const listContainer = document.createElement('div');
    listContainer.classList.add('async-upload-list');
    listContainer.innerHTML = `
        <div class="card bg-base-100 shadow-sm">
            <div class="card-body p-0">
                <div class="p-4 pb-2">
                    <h3 class="text-sm font-semibold opacity-60 tracking-wide">Files ready for upload</h3>
                </div>
                <ul class="list" id="async-files-list">
                </ul>
            </div>
        </div>
    `;
    
    uploadArea.appendChild(listContainer);
    const filesList = listContainer.querySelector('#async-files-list');
    
    uploads.forEach((uploadInfo, index) => {
        const listItem = document.createElement('li');
        listItem.classList.add('list-row', 'upload-file-container');
        listItem.dataset.filename = uploadInfo.filename;
        
        const fileIcon = getFileIconForType(uploadInfo.filename);
        // File size shown in modal when clicked, not needed in cards
        
        listItem.innerHTML = `
            <!-- File Icon -->
            <div class="flex-shrink-0">
                ${fileIcon}
            </div>
            
            <!-- File Info (Growing Column) -->
            <div class="list-col-grow">
                <div class="font-medium text-base-content">${uploadInfo.filename}</div>
                <div class="text-xs opacity-60 file-status">Ready to upload</div>
            </div>
            
            <!-- Upload Progress -->
            <div class="upload-progress-indicator hidden">
                <div class="flex items-center gap-2">
                    <span class="loading loading-spinner loading-sm"></span>
                    <span class="text-xs status-text">0%</span>
                    <span class="text-xs upload-speed hidden"></span>
                </div>
            </div>
            
            <!-- Status Badge -->
            <div class="status-badge">
                <div class="badge badge-outline badge-sm">Queued</div>
            </div>
            
            <!-- Action Button -->
            <button class="btn btn-ghost btn-sm btn-square remove-file-btn" onclick="removeUploadByFilename('${uploadInfo.filename}')" title="Remove file">
                <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
                </svg>
            </button>
            
            <!-- Full-width progress bar (hidden by default) -->
            <div class="upload-progress list-col-wrap hidden mt-2">
                <progress class="progress progress-primary w-full" value="0" max="100"></progress>
                <div class="flex justify-between text-xs text-base-content/60 mt-1">
                    <span class="upload-details"></span>
                    <span class="upload-eta"></span>
                </div>
            </div>
        `;
        
        filesList.appendChild(listItem);
    });
}

async function startUploads(uploads, files) {
    debugLog('🚀 Starting uploads for', uploads.length, 'files');
    
    // Initialize upload tracker
    uploadTracker.startSession(files);
    
    // Create a map of filename to file object
    const fileMap = {};
    files.forEach(file => {
        fileMap[file.name] = file;
        uploadTracker.trackFile(file.name, file.size);
    });
    
    // Upload each file
    const uploadPromises = uploads.map(async (uploadInfo) => {
        const file = fileMap[uploadInfo.filename];
        if (!file) {
            debugError('❌ File not found:', uploadInfo.filename);
            uploadTracker.failFile(uploadInfo.filename);
            return;
        }
        
        try {
            await uploadFileDirectly(uploadInfo, file);
            uploadTracker.completeFile(uploadInfo.filename);
        } catch (error) {
            debugError('❌ Upload failed for', uploadInfo.filename, error);
            updateFileStatus(uploadInfo.filename, 'Upload failed: ' + error.message, 'failed');
            uploadTracker.failFile(uploadInfo.filename);
        }
    });
    
    await Promise.allSettled(uploadPromises);
    
    // Extract uploaded filenames to verify they exist
    const uploadedFiles = uploads.map(upload => ({
        filename: upload.filename,
        path: upload.relativePath || upload.filename
    }));
    
    // Show coordinated "verifying files" message instead of immediate success
    showUploadVerifying(uploads.length, uploadedFiles);
    
    // Add small delay to improve S3 consistency before refresh
    debugLog('⏳ Waiting 0.5s for S3 eventual consistency...');
    await new Promise(resolve => setTimeout(resolve, 500));
    
    // Refresh file browser with expected files list for verification
    await refreshFileBrowserOOB(uploadedFiles);
}

async function uploadFileDirectly(uploadInfo, file) {
    const container = document.querySelector(`[data-filename="${uploadInfo.filename}"]`);
    const progressBar = container?.querySelector('progress');
    const statusText = container?.querySelector('.status-text');
    const uploadDetails = container?.querySelector('.upload-details');
    const uploadEta = container?.querySelector('.upload-eta');
    const uploadSpeed = container?.querySelector('.upload-speed');
    
    debugLog('📤 Uploading to S3:', uploadInfo.filename);
    
    // Update status to uploading and show progress bar immediately
    updateFileStatusByName(uploadInfo.filename, 'Starting upload...', 'uploading');
    showUploadProgress(container);
    
    if (uploadInfo.type === 'single') {
        // Debug: Log what method we received
        debugLog('📊 Upload method received:', uploadInfo.method);
        debugLog('📊 Full uploadInfo:', uploadInfo);
        
        // Check upload method
        if (uploadInfo.method === 'PUT') {
            // Direct PUT upload with progress tracking
            debugLog('✅ Using PUT method with AWS4 signature');
            return uploadWithProgressPUT(uploadInfo.url, file, uploadInfo.filename, progressBar, statusText, file.size, uploadInfo.upload_file_id);
        } else if (uploadInfo.method === 'FORM_POST') {
            // Form-based upload fallback
            debugLog('⚠️ Using FORM_POST method - no progress tracking');
            return uploadWithHiddenForm(uploadInfo, file, progressBar, statusText);
        } else {
            // FormData POST upload for MinIO/AWS
            const formData = new FormData();
            Object.entries(uploadInfo.fields).forEach(([key, value]) => {
                formData.append(key, value);
            });
            formData.append('file', file);
            
            return uploadWithProgress(uploadInfo.url, formData, uploadInfo.filename, progressBar, statusText, file.size, uploadInfo.upload_file_id);
        }
        
    } else if (uploadInfo.type === 'multipart') {
        // TODO: Implement multipart upload if needed
        // Use S3 multipart upload handler for large files
        debugLog('📦 Starting S3 multipart upload for:', uploadInfo.filename);
        updateFileStatusByName(uploadInfo.filename, 'Initializing multipart upload...', 'uploading');
        return await handleMultipartUpload(uploadInfo, file);
    }
}

async function uploadWithProgress(url, formData, filename, progressBar, statusText, fileSize, uploadFileId) {
    return new Promise((resolve, reject) => {
        const xhr = new XMLHttpRequest();
        const startTime = Date.now();
        let lastLoaded = 0;
        let lastTime = startTime;
        
        // Handle upload progress
        xhr.upload.addEventListener('progress', function(e) {
            if (e.lengthComputable) {
                const percentComplete = (e.loaded / e.total) * 100;
                const currentTime = Date.now();
                const timeDiff = (currentTime - lastTime) / 1000; // in seconds
                
                if (progressBar) {
                    progressBar.value = percentComplete;
                }
                if (statusText) {
                    statusText.textContent = `${percentComplete.toFixed(0)}%`;
                }
                
                // Calculate upload speed and ETA
                if (timeDiff > 0.5) { // Update every 500ms
                    const bytesUploaded = e.loaded - lastLoaded;
                    const uploadSpeed = bytesUploaded / timeDiff;
                    const remainingBytes = e.total - e.loaded;
                    const remainingTime = remainingBytes / uploadSpeed;
                    
                    updateUploadMetrics(filename, {
                        progress: percentComplete,
                        loaded: e.loaded,
                        total: e.total,
                        speed: uploadSpeed,
                        remainingTime: remainingTime
                    });
                    
                    lastLoaded = e.loaded;
                    lastTime = currentTime;
                }
                
                // Update tracker
                uploadTracker.updateFileProgress(filename, e.loaded, e.total);
                
                // Update file status text (don't repeat percentage, it's shown in status-text)
                updateFileStatusByName(filename, 'Uploading...', 'uploading');
            }
        });
        
        // Handle upload completion
        xhr.addEventListener('load', async function() {
            if (xhr.status >= 200 && xhr.status < 300) {
                debugLog('✅ S3 upload completed:', filename);
                updateFileStatusByName(filename, 'Upload completed!', 'completed');
                
                // Notify server that file was uploaded
                if (uploadFileId) {
                    try {
                        const csrfToken = getCsrfToken();
                        debugLog('🔑 CSRF Token for mark-uploaded:', csrfToken ? 'Found' : 'Missing');
                        
                        const response = await fetch(`/storage/upload/mark-uploaded/${uploadFileId}/`, {
                            method: 'POST',
                            headers: {
                                'X-CSRFToken': csrfToken,
                            },
                            credentials: 'include'
                        });
                        
                        if (response.ok) {
                            debugLog('✅ Server notified of upload:', filename);
                        } else {
                            const errorText = await response.text();
                            debugError('⚠️ Failed to notify server of upload:', filename, `Status: ${response.status}, Error: ${errorText.substring(0, 200)}`);
                        }
                    } catch (error) {
                        debugError('⚠️ Error notifying server:', error);
                    }
                }
                
                resolve();
            } else {
                debugError('❌ Upload failed:', xhr.status, xhr.statusText);
                updateFileStatusByName(filename, 'Upload failed: ' + xhr.statusText, 'failed');
                reject(new Error('Upload failed: ' + xhr.statusText));
            }
        });
        
        // Handle upload error
        xhr.addEventListener('error', function() {
            debugError('❌ Network error during upload');
            updateFileStatusByName(filename, 'Network error during upload', 'failed');
            reject(new Error('Network error during upload'));
        });
        
        // Send to S3
        xhr.open('POST', url);
        xhr.send(formData);
    });
}

// Hidden form upload - bypasses CORS completely!
async function uploadWithHiddenForm(uploadInfo, file, progressBar, statusText) {
    return new Promise((resolve, reject) => {
        debugLog('📝 Using hidden form to bypass CORS for:', uploadInfo.filename);
        
        // Create hidden iframe for form target
        const iframe = document.createElement('iframe');
        iframe.name = 'upload-iframe-' + Date.now();
        iframe.style.display = 'none';
        document.body.appendChild(iframe);
        
        // Create form
        const form = document.createElement('form');
        form.method = 'POST';
        form.action = uploadInfo.url;
        form.enctype = 'multipart/form-data';
        form.target = iframe.name;
        form.style.display = 'none';
        
        // Add all fields from presigned POST
        Object.entries(uploadInfo.fields).forEach(([key, value]) => {
            const input = document.createElement('input');
            input.type = 'hidden';
            input.name = key;
            input.value = value;
            form.appendChild(input);
        });
        
        // Add file input
        const fileInput = document.createElement('input');
        fileInput.type = 'file';
        fileInput.name = 'file';
        const dataTransfer = new DataTransfer();
        dataTransfer.items.add(file);
        fileInput.files = dataTransfer.files;
        form.appendChild(fileInput);
        
        document.body.appendChild(form);
        
        // Listen for iframe load (upload complete)
        iframe.onload = () => {
            // Check if upload succeeded
            try {
                // S3 returns empty response on success
                debugLog('✅ Form upload completed:', uploadInfo.filename);
                updateFileStatusByName(uploadInfo.filename, 'Upload completed!', 'completed');
                resolve();
            } catch (e) {
                console.error('Form upload may have failed:', e);
                updateFileStatusByName(uploadInfo.filename, 'Upload status unknown', 'warning');
                resolve(); // Resolve anyway since we can't get error details
            } finally {
                // Cleanup
                setTimeout(() => {
                    document.body.removeChild(form);
                    document.body.removeChild(iframe);
                }, 1000);
            }
        };
        
        // Submit form
        debugLog('📤 Submitting form for:', uploadInfo.filename);
        updateFileStatusByName(uploadInfo.filename, 'Uploading (no progress available)...', 'uploading');
        form.submit();
    });
}

// New function for PUT uploads (Dell EMC S3)
async function uploadWithProgressPUT(url, file, filename, progressBar, statusText, fileSize, uploadFileId) {
    return new Promise((resolve, reject) => {
        const xhr = new XMLHttpRequest();
        const startTime = Date.now();
        let lastLoaded = 0;
        let lastTime = startTime;
        
        // Handle upload progress
        xhr.upload.addEventListener('progress', function(e) {
            if (e.lengthComputable) {
                const percentComplete = (e.loaded / e.total) * 100;
                const currentTime = Date.now();
                const timeDiff = (currentTime - lastTime) / 1000; // in seconds
                
                if (progressBar) {
                    progressBar.value = percentComplete;
                }
                if (statusText) {
                    statusText.textContent = `${percentComplete.toFixed(0)}%`;
                }
                
                // Calculate upload speed and ETA
                if (timeDiff > 0.5) { // Update every 500ms
                    const bytesUploaded = e.loaded - lastLoaded;
                    const uploadSpeed = bytesUploaded / timeDiff;
                    const remainingBytes = e.total - e.loaded;
                    const remainingTime = remainingBytes / uploadSpeed;
                    
                    updateUploadMetrics(filename, {
                        progress: percentComplete,
                        loaded: e.loaded,
                        total: e.total,
                        speed: uploadSpeed,
                        remainingTime: remainingTime
                    });
                    
                    lastLoaded = e.loaded;
                    lastTime = currentTime;
                }
                
                // Update tracker
                uploadTracker.updateFileProgress(filename, e.loaded, e.total);
                
                // Update file status text (don't repeat percentage, it's shown in status-text)
                updateFileStatusByName(filename, 'Uploading...', 'uploading');
            }
        });
        
        // Handle upload completion
        xhr.addEventListener('load', async function() {
            if (xhr.status >= 200 && xhr.status < 300) {
                debugLog('✅ S3 PUT upload completed:', filename);
                updateFileStatusByName(filename, 'Upload completed!', 'completed');
                
                // Notify server that file was uploaded
                if (uploadFileId) {
                    try {
                        const csrfToken = getCsrfToken();
                        debugLog('🔑 CSRF Token for mark-uploaded:', csrfToken ? 'Found' : 'Missing');
                        
                        const response = await fetch(`/storage/upload/mark-uploaded/${uploadFileId}/`, {
                            method: 'POST',
                            headers: {
                                'X-CSRFToken': csrfToken,
                            },
                            credentials: 'include'
                        });
                        
                        if (response.ok) {
                            debugLog('✅ Server notified of upload:', filename);
                        } else {
                            const errorText = await response.text();
                            debugError('⚠️ Failed to notify server of upload:', filename, `Status: ${response.status}, Error: ${errorText.substring(0, 200)}`);
                        }
                    } catch (error) {
                        debugError('⚠️ Error notifying server:', error);
                    }
                }
                
                resolve();
            } else {
                debugError('❌ PUT upload failed:', xhr.status, xhr.statusText);
                updateFileStatusByName(filename, 'Upload failed: ' + xhr.statusText, 'failed');
                reject(new Error('Upload failed: ' + xhr.statusText));
            }
        });
        
        // Handle upload error
        xhr.addEventListener('error', function() {
            debugError('❌ Network error during PUT upload');
            updateFileStatusByName(filename, 'Network error during upload', 'failed');
            reject(new Error('Network error during upload'));
        });
        
        // Send PUT request with file directly in body
        xhr.open('PUT', url);
        xhr.setRequestHeader('Content-Type', file.type || 'application/octet-stream');
        xhr.send(file);
    });
}

// Upload verifying helper - shows coordinated loading state
function showUploadVerifying(fileCount, uploadedFiles) {
    const uploadArea = document.getElementById('dashboard-upload-area');
    const verifyingMessage = document.createElement('div');
    verifyingMessage.className = 'alert alert-info mt-4';
    verifyingMessage.id = 'upload-verifying-message';
    
    const fileNames = uploadedFiles.slice(0, 3).map(f => f.filename).join(', ') + 
                     (uploadedFiles.length > 3 ? ` and ${uploadedFiles.length - 3} more` : '');
    
    verifyingMessage.innerHTML = `
        <div class="flex items-center gap-3">
            <span class="loading loading-spinner loading-sm"></span>
            <div>
                <div class="font-medium">Files uploaded, verifying availability...</div>
                <div class="text-sm opacity-70">Uploaded: ${fileNames}</div>
            </div>
        </div>
    `;
    uploadArea.appendChild(verifyingMessage);
}

// Final completion helper - called after files are confirmed in browser
function showUploadComplete(fileCount) {
    // Remove the verifying message if it exists
    const verifyingMessage = document.getElementById('upload-verifying-message');
    if (verifyingMessage) {
        verifyingMessage.remove();
    }
    
    const uploadArea = document.getElementById('dashboard-upload-area');
    const completionMessage = document.createElement('div');
    completionMessage.className = 'alert alert-success mt-4';
    completionMessage.innerHTML = `
        <svg xmlns="http://www.w3.org/2000/svg" class="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7" />
        </svg>
        <span>✅ All ${fileCount} files uploaded and verified!</span>
        <button class="btn btn-ghost btn-sm" onclick="this.closest('.alert').remove()">
            <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
            </svg>
        </button>
    `;
    uploadArea.appendChild(completionMessage);
}

// Optimistic Updates: Show files immediately with verification badges
function showFilesOptimistically(uploadedFiles) {
    const fileBrowserContent = document.getElementById('file-browser-content');
    if (!fileBrowserContent) {
        debugError('❌ File browser content not found');
        return;
    }
    
    debugLog('📋 OPTIMISTIC: Adding', uploadedFiles.length, 'files to file browser');
    
    // Create optimistic file entries
    uploadedFiles.forEach(file => {
        const fileElement = createOptimisticFileElement(file);
        // Find the file list and prepend new files
        const fileList = fileBrowserContent.querySelector('.file-list, .list, [class*="file"]');
        if (fileList) {
            fileList.insertBefore(fileElement, fileList.firstChild);
        } else {
            // If no file list exists, create one
            const listContainer = document.createElement('div');
            listContainer.className = 'optimistic-file-list space-y-2';
            listContainer.appendChild(fileElement);
            fileBrowserContent.insertBefore(listContainer, fileBrowserContent.firstChild);
        }
    });
    
    debugLog('✅ OPTIMISTIC: Files displayed immediately');
}

function createOptimisticFileElement(file) {
    const fileElement = document.createElement('div');
    fileElement.className = 'file-item optimistic-file p-3 bg-base-100 border border-base-300 rounded-lg';
    fileElement.dataset.filename = file.filename;
    fileElement.dataset.optimistic = 'true';
    
    const extension = file.filename.split('.').pop().toLowerCase();
    const icon = getFileIconForType(file.filename);
    
    fileElement.innerHTML = `
        <div class="flex items-center gap-3">
            <!-- File Icon -->
            <div class="flex-shrink-0">
                ${icon}
            </div>
            
            <!-- File Info -->
            <div class="flex-1 min-w-0">
                <div class="font-medium text-base-content truncate">${file.filename}</div>
                <div class="text-sm text-base-content/60">${file.path !== file.filename ? file.path : ''}</div>
            </div>
            
            <!-- Verification Status Badge -->
            <div class="verification-badge">
                <div class="badge badge-warning badge-sm gap-1">
                    <span class="loading loading-spinner loading-xs"></span>
                    Verifying
                </div>
            </div>
        </div>
    `;
    
    return fileElement;
}

// Verification polling for real-time updates
function startVerificationPolling(uploadedFiles) {
    debugLog('🔄 POLLING: Starting verification status polling');
    
    const pollInterval = 2000; // Poll every 2 seconds
    const maxPolls = 30; // Stop after 60 seconds
    let pollCount = 0;
    
    const polling = setInterval(async () => {
        pollCount++;
        debugLog(`📡 POLLING: Check ${pollCount}/${maxPolls}`);
        
        try {
            // Get the organization for API call
            const orgSelector = document.querySelector('#upload-org-selector select[name="organization"]');
            const organization = orgSelector ? orgSelector.value : '';
            
            if (!organization) {
                debugLog('⚠️ POLLING: No organization selected, stopping');
                clearInterval(polling);
                return;
            }
            
            // Check verification status
            const response = await fetch(`/storage/api/verification-status/${organization}/`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': getCsrfToken(),
                },
                credentials: 'include',
                body: JSON.stringify({
                    files: uploadedFiles.map(f => f.filename)
                })
            });
            
            if (response.ok) {
                const data = await response.json();
                updateVerificationStatus(data.files || []);
                
                // Check if all files are verified
                const allVerified = data.files.every(f => f.status === 'verified' || f.status === 'failed');
                if (allVerified) {
                    debugLog('✅ POLLING: All files verified, stopping');
                    clearInterval(polling);
                    showFinalUploadSuccess(uploadedFiles.length);
                }
            }
            
        } catch (error) {
            console.error('POLLING: Error checking status:', error);
        }
        
        // Stop polling after max attempts
        if (pollCount >= maxPolls) {
            debugLog('⏰ POLLING: Max attempts reached, stopping');
            clearInterval(polling);
        }
        
    }, pollInterval);
}

function updateVerificationStatus(fileStatuses) {
    fileStatuses.forEach(fileStatus => {
        const fileElement = document.querySelector(`[data-filename="${fileStatus.filename}"][data-optimistic="true"]`);
        if (!fileElement) return;
        
        const badge = fileElement.querySelector('.verification-badge');
        if (!badge) return;
        
        let badgeHTML = '';
        switch (fileStatus.status) {
            case 'verified':
                badgeHTML = '<div class="badge badge-success badge-sm">✅ Verified</div>';
                fileElement.classList.add('verified');
                break;
            case 'failed':
                badgeHTML = `<div class="badge badge-error badge-sm">❌ Failed</div>`;
                fileElement.classList.add('failed');
                break;
            case 'verifying':
            default:
                badgeHTML = `
                    <div class="badge badge-warning badge-sm gap-1">
                        <span class="loading loading-spinner loading-xs"></span>
                        Verifying
                    </div>
                `;
                break;
        }
        
        badge.innerHTML = badgeHTML;
    });
}

function showFinalUploadSuccess(fileCount) {
    const uploadArea = document.getElementById('dashboard-upload-area');
    if (!uploadArea) return;
    
    // Remove verifying message if it exists
    const verifyingMessage = document.getElementById('upload-verifying-message');
    if (verifyingMessage) {
        verifyingMessage.remove();
    }
    
    const completionMessage = document.createElement('div');
    completionMessage.className = 'alert alert-success mt-4';
    completionMessage.innerHTML = `
        <svg xmlns="http://www.w3.org/2000/svg" class="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7" />
        </svg>
        <span>🎉 All ${fileCount} files uploaded and verified!</span>
        <button class="btn btn-ghost btn-sm" onclick="this.closest('.alert').remove()">
            <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
            </svg>
        </button>
    `;
    uploadArea.appendChild(completionMessage);
}

// Refresh file browser - simple and clean
async function refreshFileBrowserOOB(uploadedFiles = []) {
    try {
        // Get the organization from the upload org selector
        const orgSelector = document.querySelector('#upload-org-selector select[name="organization"]');
        const organization = orgSelector ? orgSelector.value : '';

        if (!organization) {
            debugLog('⚠️ REFRESH: No organization selected, skipping file browser refresh');
            return;
        }

        // Build refresh URL and include expected file names for verification/retry
        let url = `/storage/dashboard/refresh/${organization}/`;
        if (uploadedFiles && uploadedFiles.length > 0) {
            const qs = new URLSearchParams();
            uploadedFiles.forEach((f, i) => {
                // Pass only filename; server will search recursively
                qs.append(`expected_${i}`, f.filename || f);
            });
            url += `?${qs.toString()}`;
        }

        debugLog('🔄 REFRESH: Refreshing file browser from:', url);

        // Use HTMX to refresh the file browser and then refresh bucket size
        if (window.htmx) {
            // One-time listener for when the file browser content swaps
            const afterSwapHandler = (evt) => {
                if (evt.target && evt.target.id === 'file-browser-content') {
                    // Force-refresh bucket size stats
                    const bucketSizeContainer = document.getElementById('bucket-size-container');
                    if (bucketSizeContainer) {
                        const sizeUrl = `/storage/dashboard/bucket-size/${organization}/?force_fresh=true`;
                        htmx.ajax('GET', sizeUrl, { target: '#bucket-size-container', swap: 'innerHTML' });
                    }
                    if (uploadedFiles.length > 0) {
                        showUploadComplete(uploadedFiles.length);
                    }
                }
            };
            document.body.addEventListener('htmx:afterSwap', afterSwapHandler, { once: true });

            htmx.ajax('GET', url, { target: '#file-browser-content', swap: 'innerHTML' });

            debugLog('✅ REFRESH: File browser refresh initiated');
        } else {
            console.error('REFRESH: HTMX not available');
        }
    } catch (error) {
        console.error('REFRESH: Error refreshing file browser:', error);
    }
}

// Status update functions
function updateSessionStatus(sessionStatus) {
    // Check if we're in folder upload mode
    const isFolderMode = document.querySelector('.async-upload-summary') !== null;
    
    if (isFolderMode) {
        updateFolderUploadProgress(sessionStatus);
    } else {
        // Update individual file statuses
        sessionStatus.files.forEach(fileStatus => {
            updateFileStatusByName(fileStatus.filename, fileStatus.status, fileStatus.error);
        });
    }
}

function updateFolderUploadProgress(sessionStatus) {
    // Update overall progress bar
    const overallProgress = document.getElementById('folder-overall-progress');
    const uploadStatus = document.getElementById('folder-upload-status');
    const uploadSpeed = document.getElementById('folder-upload-speed');
    const uploadEta = document.getElementById('folder-upload-eta');
    
    const completedFiles = sessionStatus.completed_files || 0;
    const failedFiles = sessionStatus.failed_files || 0;
    const totalFiles = sessionStatus.total_files || 0;
    const processedFiles = completedFiles + failedFiles;
    
    if (overallProgress && totalFiles > 0) {
        const progress = (processedFiles / totalFiles) * 100;
        overallProgress.value = progress;
    }
    
    if (uploadStatus) {
        uploadStatus.textContent = `${processedFiles} / ${totalFiles} files`;
    }
    
    // Update individual file statuses in the collapsible list if visible
    sessionStatus.files?.forEach(fileStatus => {
        const fileContainer = document.querySelector(`[data-filename="${fileStatus.filename}"]`);
        if (fileContainer) {
            const statusBadge = fileContainer.querySelector('.status-badge');
            const progressBar = fileContainer.querySelector('.upload-progress progress');
            const progressDiv = fileContainer.querySelector('.upload-progress');
            const progressIndicator = fileContainer.querySelector('.upload-progress-indicator');
            const statusText = fileContainer.querySelector('.status-text');
            
            if (statusBadge) {
                let badgeClass = 'badge-outline';
                let statusLabel = fileStatus.status;
                
                switch (fileStatus.status) {
                    case 'completed':
                        badgeClass = 'badge-success';
                        statusLabel = '✅ Done';
                        if (progressDiv) progressDiv.classList.add('hidden');
                        if (progressIndicator) progressIndicator.classList.add('hidden');
                        break;
                    case 'failed':
                        badgeClass = 'badge-error';
                        statusLabel = '❌ Failed';
                        if (progressDiv) progressDiv.classList.add('hidden');
                        if (progressIndicator) progressIndicator.classList.add('hidden');
                        break;
                    case 'uploading':
                    case 'processing':
                        badgeClass = 'badge-info animate-pulse';
                        statusLabel = 'Uploading';
                        if (progressDiv) progressDiv.classList.remove('hidden');
                        if (progressIndicator) progressIndicator.classList.remove('hidden');
                        break;
                    case 'queued':
                    default:
                        badgeClass = 'badge-outline';
                        statusLabel = 'Queued';
                        break;
                }
                
                statusBadge.innerHTML = `<div class="badge ${badgeClass} badge-xs">${statusLabel}</div>`;
            }
            
            // Update progress if available
            if (fileStatus.progress !== undefined) {
                if (progressBar) {
                    progressBar.value = fileStatus.progress;
                }
                if (statusText) {
                    statusText.textContent = `${Math.round(fileStatus.progress)}%`;
                }
            }
        }
    });
}

function updateFileStatus(fileId, statusText, status) {
    // Try to find container by file-id or filename
    let container = document.querySelector(`[data-file-id="${fileId}"]`);
    if (!container) {
        container = document.querySelector(`[data-filename="${fileId}"]`);
    }
    if (!container) return;
    
    const statusElement = container.querySelector('.file-status');
    const statusBadge = container.querySelector('.status-badge');
    const progressDiv = container.querySelector('.upload-progress');
    const progressIndicator = container.querySelector('.upload-progress-indicator');
    const progressBar = container.querySelector('progress');
    const removeBtn = container.querySelector('.remove-file-btn');
    
    if (statusElement) {
        statusElement.textContent = statusText;
    }
    
    // Update status badge and visual indicators
    if (status === 'uploading') {
        if (statusBadge) {
            statusBadge.innerHTML = '<div class="badge badge-info badge-sm animate-pulse">Uploading</div>';
        }
        if (progressIndicator) {
            progressIndicator.classList.remove('hidden');
        }
        if (progressDiv) {
            progressDiv.classList.remove('hidden');
        }
        if (removeBtn) {
            removeBtn.style.display = 'none'; // Hide remove button during upload
        }
    } else if (status === 'processing') {
        if (statusBadge) {
            statusBadge.innerHTML = '<div class="badge badge-warning badge-sm">Processing</div>';
        }
        if (progressIndicator) {
            progressIndicator.innerHTML = `
                <div class="flex items-center gap-2">
                    <span class="loading loading-dots loading-sm"></span>
                    <span class="text-xs">Processing</span>
                </div>
            `;
            progressIndicator.classList.remove('hidden');
        }
        if (progressDiv) {
            progressDiv.classList.add('hidden'); // Hide progress bar during processing
        }
    } else if (status === 'completed') {
        // Set progress to 100% before hiding
        if (progressBar) {
            progressBar.value = 100;
        }
        
        // Update badge to success
        if (statusBadge) {
            statusBadge.innerHTML = '<div class="badge badge-success badge-sm">✅ Complete</div>';
        }
        
        // Hide all progress indicators
        if (progressIndicator) {
            progressIndicator.classList.add('hidden');
        }
        if (progressDiv) {
            setTimeout(() => {
                progressDiv.classList.add('hidden');
            }, 500); // Small delay to show 100% before hiding
        }
        
        // Add subtle success styling to the entire row
        container.classList.remove('bg-warning/5', 'bg-error/5');
        container.classList.add('bg-success/5');
        
        // Hide remove button for completed uploads
        if (removeBtn) {
            removeBtn.style.display = 'none';
        }
    } else if (status === 'failed') {
        if (statusBadge) {
            statusBadge.innerHTML = '<div class="badge badge-error badge-sm">❌ Failed</div>';
        }
        if (progressIndicator) {
            progressIndicator.classList.add('hidden');
        }
        if (progressDiv) {
            progressDiv.classList.add('hidden');
        }
        // Add subtle error styling to the entire row
        container.classList.remove('bg-success/5', 'bg-warning/5');
        container.classList.add('bg-error/5');
        if (removeBtn) {
            removeBtn.style.display = 'block'; // Show remove button again for failed uploads
        }
    }
}

function updateFileStatusByName(filename, status, error) {
    // Find containers by data-filename attribute (more reliable)
    const containers = document.querySelectorAll(`[data-filename="${filename}"]`);
    containers.forEach(container => {
        const statusElement = container.querySelector('.file-status');
        if (statusElement) {
            statusElement.textContent = status;
        }
        
        // Call the main updateFileStatus function to handle visual updates
        if (status.includes('completed') || status.includes('Complete')) {
            updateFileStatus(container.dataset.fileId || filename, 'Upload completed successfully!', 'completed');
        } else if (status.includes('failed') || status.includes('Failed')) {
            updateFileStatus(container.dataset.fileId || filename, error || 'Upload failed', 'failed');
        } else if (status.includes('Uploading')) {
            // Keep uploading status
            const statusBadge = container.querySelector('.status-badge');
            if (statusBadge) {
                statusBadge.innerHTML = '<div class="badge badge-info badge-sm animate-pulse">Uploading</div>';
            }
        }
    });
}

function handleSessionCompletion(sessionStatus) {
    debugLog('🎉 ASYNC: Upload session completed!');
    
    const isFolderMode = document.querySelector('.async-upload-summary') !== null;
    
    if (isFolderMode) {
        // For folder uploads, show a completion banner at the top of the summary
        const summaryContainer = document.querySelector('.async-upload-summary .card-body');
        if (summaryContainer) {
            const completionBanner = document.createElement('div');
            completionBanner.className = 'alert alert-success mb-4';
            completionBanner.innerHTML = `
                <svg xmlns="http://www.w3.org/2000/svg" class="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7" />
                </svg>
                <div>
                    <h4 class="font-semibold">Folder upload completed!</h4>
                    <div class="text-sm">
                        ${sessionStatus.completed_files} files uploaded successfully
                        ${sessionStatus.failed_files > 0 ? `, ${sessionStatus.failed_files} failed` : ''}
                    </div>
                </div>
                <button class="btn btn-ghost btn-sm" onclick="this.closest('.alert').remove()">
                    <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
                    </svg>
                </button>
            `;
            summaryContainer.insertBefore(completionBanner, summaryContainer.firstChild);
        }
    } else {
        // For individual files, add completion summary to the list
        const filesList = document.querySelector('#async-files-list');
        if (filesList) {
            const summaryItem = document.createElement('li');
            summaryItem.classList.add('list-row', 'bg-success/10', 'border-l-4', 'border-success');
            summaryItem.innerHTML = `
                <div class="flex-shrink-0">
                    <div class="avatar placeholder">
                        <div class="bg-success text-success-content w-10 rounded-lg">
                            <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7" />
                            </svg>
                        </div>
                    </div>
                </div>
                <div class="list-col-grow">
                    <div class="font-semibold text-success">All uploads completed successfully!</div>
                    <div class="text-xs opacity-60">
                        ${sessionStatus.completed_files} files uploaded and processed
                        ${sessionStatus.failed_files > 0 ? ` • ${sessionStatus.failed_files} failed` : ''}
                    </div>
                </div>
                <button class="btn btn-ghost btn-sm" onclick="this.closest('.list-row').remove()">
                    <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
                    </svg>
                </button>
            `;
            filesList.appendChild(summaryItem);
        }
    }
    
    // Reset file input
    const fileInput = document.getElementById('dashboard-file-picker');
    if (fileInput) {
        fileInput.value = '';
    }
}

function showUploadError(uploadArea, message) {
    const errorDiv = document.createElement('div');
    errorDiv.className = 'alert alert-error mt-4';
    errorDiv.innerHTML = `
        <svg xmlns="http://www.w3.org/2000/svg" class="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4c-.77-.833-1.964-.833-2.732 0L3.732 16.5c-.77.833.192 2.5 1.732 2.5z" />
        </svg>
        <span>❌ ${message}</span>
    `;
    uploadArea.appendChild(errorDiv);
}

// Helper function for modern file type icons
function getFileIconForType(filename) {
    const extension = filename.split('.').pop().toLowerCase();
    
    // Image files
    if (['jpg', 'jpeg', 'png', 'gif', 'bmp', 'webp', 'svg'].includes(extension)) {
        return `
            <div class="avatar placeholder">
                <div class="bg-success text-success-content w-10 rounded-lg">
                    <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z" />
                    </svg>
                </div>
            </div>
        `;
    }
    
    // Video files
    if (['mp4', 'avi', 'mov', 'wmv', 'flv', 'webm', 'mkv'].includes(extension)) {
        return `
            <div class="avatar placeholder">
                <div class="bg-info text-info-content w-10 rounded-lg">
                    <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 10l4.553-2.276A1 1 0 0121 8.618v6.764a1 1 0 01-1.447.894L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z" />
                    </svg>
                </div>
            </div>
        `;
    }
    
    // Audio files
    if (['mp3', 'wav', 'ogg', 'flac', 'aac'].includes(extension)) {
        return `
            <div class="avatar placeholder">
                <div class="bg-warning text-warning-content w-10 rounded-lg">
                    <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 19V6l12-3v13M9 19c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zm12-3c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zM9 10l12-3" />
                    </svg>
                </div>
            </div>
        `;
    }
    
    // Document files
    if (['pdf', 'doc', 'docx', 'txt', 'rtf'].includes(extension)) {
        return `
            <div class="avatar placeholder">
                <div class="bg-primary text-primary-content w-10 rounded-lg">
                    <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                    </svg>
                </div>
            </div>
        `;
    }
    
    // Archive files
    if (['zip', 'rar', '7z', 'tar', 'gz'].includes(extension)) {
        return `
            <div class="avatar placeholder">
                <div class="bg-secondary text-secondary-content w-10 rounded-lg">
                    <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M20 7l-8-4-8 4m16 0l-8 4m8-4v10l-8 4m0-10L4 7m8 4v10M4 7v10l8 4" />
                    </svg>
                </div>
            </div>
        `;
    }
    
    // Default file icon
    return `
        <div class="avatar placeholder">
            <div class="bg-base-300 text-base-content w-10 rounded-lg">
                <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                </svg>
            </div>
        </div>
    `;
}

// Analyze folder structure for summary display
function analyzeFolderStructure(uploads) {
    const stats = {
        totalSize: 0,
        folderCount: 0,
        fileTypes: {}
    };
    
    const folders = new Set();
    
    uploads.forEach(upload => {
        // Calculate total size
        stats.totalSize += upload.file_size || 0;
        
        // Track folders
        const relativePath = upload.relativePath || upload.filename;
        const pathParts = relativePath.split('/');
        if (pathParts.length > 1) {
            // Add all folder paths
            for (let i = 1; i < pathParts.length; i++) {
                folders.add(pathParts.slice(0, i).join('/'));
            }
        }
        
        // Track file types
        const extension = upload.filename.split('.').pop().toLowerCase();
        const fileType = getFileTypeCategory(extension);
        stats.fileTypes[fileType] = (stats.fileTypes[fileType] || 0) + 1;
    });
    
    stats.folderCount = folders.size;
    
    return stats;
}

// Get file type category for grouping
function getFileTypeCategory(extension) {
    const imageExts = ['jpg', 'jpeg', 'png', 'gif', 'bmp', 'webp', 'svg'];
    const videoExts = ['mp4', 'avi', 'mov', 'wmv', 'flv', 'webm', 'mkv'];
    const audioExts = ['mp3', 'wav', 'ogg', 'flac', 'aac'];
    const docExts = ['pdf', 'doc', 'docx', 'txt', 'rtf'];
    const archiveExts = ['zip', 'rar', '7z', 'tar', 'gz'];
    
    if (imageExts.includes(extension)) return 'Images';
    if (videoExts.includes(extension)) return 'Videos';
    if (audioExts.includes(extension)) return 'Audio';
    if (docExts.includes(extension)) return 'Documents';
    if (archiveExts.includes(extension)) return 'Archives';
    
    return 'Other';
}

// Get file type icon for stats
function getFileTypeIcon(fileType) {
    const icons = {
        'Images': `<svg xmlns="http://www.w3.org/2000/svg" class="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z" />
        </svg>`,
        'Videos': `<svg xmlns="http://www.w3.org/2000/svg" class="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 10l4.553-2.276A1 1 0 0121 8.618v6.764a1 1 0 01-1.447.894L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z" />
        </svg>`,
        'Audio': `<svg xmlns="http://www.w3.org/2000/svg" class="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 19V6l12-3v13M9 19c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zm12-3c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zM9 10l12-3" />
        </svg>`,
        'Documents': `<svg xmlns="http://www.w3.org/2000/svg" class="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
        </svg>`,
        'Archives': `<svg xmlns="http://www.w3.org/2000/svg" class="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M20 7l-8-4-8 4m16 0l-8 4m8-4v10l-8 4m0-10L4 7m8 4v10M4 7v10l8 4" />
        </svg>`,
        'Other': `<svg xmlns="http://www.w3.org/2000/svg" class="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
        </svg>`
    };
    
    return icons[fileType] || icons['Other'];
}

// Get compact file icon for collapsible list
function getCompactFileIcon(filename) {
    const extension = filename.split('.').pop().toLowerCase();
    const fileType = getFileTypeCategory(extension);
    
    const colorMap = {
        'Images': 'text-success',
        'Videos': 'text-info',
        'Audio': 'text-warning',
        'Documents': 'text-primary',
        'Archives': 'text-secondary',
        'Other': 'text-base-content'
    };
    
    return `<div class="w-4 h-4 ${colorMap[fileType]}">${getFileTypeIcon(fileType)}</div>`;
}

// Cancel entire folder upload
function cancelFolderUpload() {
    const summaryContainer = document.querySelector('.async-upload-summary');
    if (summaryContainer) {
        summaryContainer.remove();
    }
    
    // Reset file input
    const fileInput = document.getElementById('dashboard-file-picker');
    if (fileInput) {
        fileInput.value = '';
    }
}

// Remove individual file from upload queue
function removeUploadByFilename(filename) {
    const container = document.querySelector(`[data-filename="${filename}"]`);
    if (container) {
        container.remove();
        
        // Check if list is empty and show empty state
        const filesList = document.querySelector('#async-files-list') || document.querySelector('#folder-files-list');
        if (filesList && filesList.children.length === 0) {
            const listContainer = document.querySelector('.async-upload-list') || document.querySelector('.async-upload-summary');
            if (listContainer) {
                listContainer.remove();
            }
        }
    }
}

// Remove individual file from async upload queue (legacy)
function removeAsyncUploadFile(fileId) {
    removeUploadByFilename(fileId); // Fallback
}

// Helper function to get CSRF token
function getCsrfToken() {
    const tokenElement = document.querySelector('[name=csrfmiddlewaretoken]');
    if (tokenElement) return tokenElement.value;
    
    // Fallback: get from cookie
    const name = 'csrftoken';
    let cookieValue = null;
    if (document.cookie && document.cookie !== '') {
        const cookies = document.cookie.split(';');
        for (let i = 0; i < cookies.length; i++) {
            const cookie = cookies[i].trim();
            if (cookie.substring(0, name.length + 1) === (name + '=')) {
                cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                break;
            }
        }
    }
    return cookieValue;
}

// Show upload progress UI
function showUploadProgress(container) {
    if (!container) return;
    
    const progressIndicator = container.querySelector('.upload-progress-indicator');
    const progressDiv = container.querySelector('.upload-progress');
    const statusBadge = container.querySelector('.status-badge');
    
    if (progressIndicator) {
        progressIndicator.classList.remove('hidden');
    }
    if (progressDiv) {
        progressDiv.classList.remove('hidden');
    }
    if (statusBadge) {
        statusBadge.innerHTML = '<div class="badge badge-info badge-sm animate-pulse">Uploading</div>';
    }
}

// Update upload metrics (speed, ETA, etc.)
function updateUploadMetrics(filename, metrics) {
    const container = document.querySelector(`[data-filename="${filename}"]`);
    if (!container) return;
    
    const uploadSpeed = container.querySelector('.upload-speed');
    const uploadDetails = container.querySelector('.upload-details');
    const uploadEta = container.querySelector('.upload-eta');
    
    // Format speed
    if (uploadSpeed && metrics.speed) {
        const speedStr = formatSpeed(metrics.speed);
        uploadSpeed.textContent = `• ${speedStr}`;
        uploadSpeed.classList.remove('hidden');
    }
    
    // Format uploaded/total
    if (uploadDetails && metrics.loaded && metrics.total) {
        const loadedStr = formatFileSize(metrics.loaded);
        const totalStr = formatFileSize(metrics.total);
        uploadDetails.textContent = `${loadedStr} / ${totalStr}`;
    }
    
    // Format ETA
    if (uploadEta && metrics.remainingTime) {
        const etaStr = formatTime(metrics.remainingTime);
        uploadEta.textContent = `ETA: ${etaStr}`;
    }
}

// Format upload speed
function formatSpeed(bytesPerSecond) {
    if (bytesPerSecond === 0) return '0 B/s';
    
    const k = 1024;
    const sizes = ['B/s', 'KB/s', 'MB/s', 'GB/s'];
    const i = Math.floor(Math.log(bytesPerSecond) / Math.log(k));
    
    return parseFloat((bytesPerSecond / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
}

// Format time remaining
function formatTime(seconds) {
    if (!isFinite(seconds) || seconds < 0) return 'calculating...';
    
    seconds = Math.round(seconds);
    
    if (seconds < 60) {
        return `${seconds}s`;
    } else if (seconds < 3600) {
        const minutes = Math.floor(seconds / 60);
        const secs = seconds % 60;
        return secs > 0 ? `${minutes}m ${secs}s` : `${minutes}m`;
    } else {
        const hours = Math.floor(seconds / 3600);
        const minutes = Math.floor((seconds % 3600) / 60);
        return minutes > 0 ? `${hours}h ${minutes}m` : `${hours}h`;
    }
}

// Format file size
function formatFileSize(bytes) {
    if (bytes === 0) return '0 B';
    
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
}

// Legacy upload card functions (kept for compatibility)
function createUploadCard(uploadInfo, file) {
    debugLog('🏗️ Creating upload card for:', uploadInfo.filename, 'type:', uploadInfo.type);
    
    const uploadArea = document.getElementById('dashboard-upload-area');
    if (!uploadArea) {
        console.error('Upload area not found!');
        return;
    }
    
    const uploadContainer = document.createElement('div');
    uploadContainer.classList.add('upload-file-container');
    
    debugLog('📦 Upload info received:', uploadInfo);
    
    if (uploadInfo.type === 'single') {
        // Create single upload card
        uploadContainer.innerHTML = `
            <div class="card bg-base-100 border border-base-300">
                <div class="card-body">
                    <div class="flex items-center justify-between">
                        <div class="flex items-center space-x-3">
                            <div class="flex-shrink-0">
                                ${getFileIcon(uploadInfo.filetype)}
                            </div>
                            <div class="flex-1">
                                <h3 class="text-sm font-medium text-base-content">${uploadInfo.filename}</h3>
                                <p class="text-xs text-base-content/60">
                                    ${uploadInfo.filetype}
                                </p>
                            </div>
                        </div>
                        <div class="flex items-center space-x-2">
                            <button type="button" class="btn btn-ghost btn-sm" onclick="removeUploadCard(this)">
                                Cancel
                            </button>
                        </div>
                    </div>
                    
                    <!-- S3 Upload Form -->
                    <form class="mt-4 s3-upload-form" data-filename="${uploadInfo.filename}" data-s3-key="${uploadInfo.s3_key}">
                        <!-- Progress Indicator -->
                        <div class="upload-progress hidden mb-4">
                            <div class="flex items-center space-x-2">
                                <span class="loading loading-spinner loading-sm"></span>
                                <span class="text-sm">Uploading to S3...</span>
                            </div>
                            <progress class="progress progress-primary w-full" max="100"></progress>
                        </div>
                        
                        <!-- Upload Button -->
                        <div class="flex justify-between items-center mt-4">
                            <div class="text-xs text-base-content/60">
                                Direct upload to S3
                            </div>
                            <button type="submit" class="btn btn-primary btn-sm">
                                <svg class="h-4 w-4 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
                                </svg>
                                Upload ${uploadInfo.filename}
                            </button>
                        </div>
                    </form>
                </div>
            </div>
        `;
        
        // Add to DOM
        debugLog('➕ Adding single upload card to DOM');
        uploadArea.appendChild(uploadContainer);
        
        // Setup S3 upload handling
        debugLog('⚙️ Setting up S3 upload for:', uploadInfo.filename);
        setupS3Upload(uploadContainer, uploadInfo, file);
        
    } else if (uploadInfo.type === 'multipart') {
        // Create multipart upload card
        uploadContainer.innerHTML = `
            <div class="card bg-base-100 border border-base-300">
                <div class="card-body">
                    <div class="flex items-center justify-between">
                        <div class="flex items-center space-x-3">
                            <div class="flex-shrink-0">
                                ${getFileIcon(uploadInfo.filetype)}
                            </div>
                            <div class="flex-1">
                                <h3 class="text-sm font-medium text-base-content">${uploadInfo.filename}</h3>
                                <p class="text-xs text-base-content/60">
                                    ${uploadInfo.filetype} • Large file (multipart)
                                </p>
                            </div>
                        </div>
                        <div class="flex items-center space-x-2">
                            <button type="button" class="btn btn-ghost btn-sm" onclick="removeUploadCard(this)">
                                Cancel
                            </button>
                        </div>
                    </div>
                    
                    <!-- Multipart Upload Controls -->
                    <div class="mt-4">
                        <div class="upload-progress hidden mb-4">
                            <div class="flex items-center space-x-2">
                                <span class="loading loading-spinner loading-sm"></span>
                                <span class="text-sm">Uploading chunks to S3...</span>
                            </div>
                            <progress class="progress progress-primary w-full" max="100"></progress>
                        </div>
                        
                        <div class="flex justify-between items-center">
                            <div class="text-xs text-base-content/60">
                                Multipart upload • ${uploadInfo.filename}
                            </div>
                            <button type="button" class="btn btn-primary btn-sm multipart-upload-btn" 
                                    data-upload-id="${uploadInfo.upload_id}" 
                                    data-s3-key="${uploadInfo.s3_key}">
                                <svg class="h-4 w-4 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
                                </svg>
                                Start Multipart Upload
                            </button>
                        </div>
                    </div>
                </div>
            </div>
        `;
        
        // Add to DOM
        uploadArea.appendChild(uploadContainer);
        
        // Setup multipart upload handling
        setupMultipartUpload(uploadContainer, uploadInfo, file);
    }
}

// Helper functions
function getFileIcon(filetype) {
    debugLog('🎨 Getting icon for filetype:', filetype);
    if (filetype.includes('image/')) {
        return `<svg class="h-8 w-8 text-success" fill="currentColor" viewBox="0 0 20 20">
            <path fill-rule="evenodd" d="M4 3a2 2 0 00-2 2v10a2 2 0 002 2h12a2 2 0 002-2V5a2 2 0 00-2-2H4zm12 12H4l4-8 3 6 2-4 3 6z" clip-rule="evenodd" />
        </svg>`;
    } else if (filetype.includes('video/')) {
        return `<svg class="h-8 w-8 text-info" fill="currentColor" viewBox="0 0 20 20">
            <path d="M2 6a2 2 0 012-2h6a2 2 0 012 2v8a2 2 0 01-2 2H4a2 2 0 01-2-2V6zM14.553 7.106A1 1 0 0014 8v4a1 1 0 00.553.894l2 1A1 1 0 0018 13V7a1 1 0 00-1.447-.894l-2 1z" />
        </svg>`;
    } else {
        return `<svg class="h-8 w-8 text-base-400" fill="currentColor" viewBox="0 0 20 20">
            <path fill-rule="evenodd" d="M4 4a2 2 0 012-2h4.586A2 2 0 0112 2.586L15.414 6A2 2 0 0116 7.414V16a2 2 0 01-2 2H6a2 2 0 01-2-2V4z" clip-rule="evenodd" />
        </svg>`;
    }
}


function removeUploadCard(button) {
    const card = button.closest('.upload-file-container');
    if (card) {
        card.remove();
        updateUploadControls();
    }
}

function setupS3Upload(container, uploadInfo, file) {
    const form = container.querySelector('.s3-upload-form');
    const progressDiv = container.querySelector('.upload-progress');
    const uploadButton = form.querySelector('button[type="submit"]');
    
    form.addEventListener('submit', function(e) {
        e.preventDefault();
        
        debugLog('🚀 Starting S3 upload for:', uploadInfo.filename);
        
        // Show progress
        if (progressDiv) {
            progressDiv.classList.remove('hidden');
        }
        
        // Disable button
        uploadButton.disabled = true;
        uploadButton.innerHTML = `
            <span class="loading loading-spinner loading-sm mr-2"></span>
            Uploading...
        `;
        
        // Create FormData for S3 upload
        const formData = new FormData();
        
        // Add S3 fields
        Object.entries(uploadInfo.fields).forEach(([key, value]) => {
            formData.append(key, value);
        });
        
        // Add file (handle zero-byte files specially)
        if (file.size === 0) {
            // For zero-byte files, create an empty blob
            debugLog('📄 Handling zero-byte file:', file.name);
            formData.append('file', new Blob([], {type: file.type}));
        } else {
            formData.append('file', file);
        }
        
        // Create XMLHttpRequest for S3 upload
        const xhr = new XMLHttpRequest();
        
        // Handle upload progress
        xhr.upload.addEventListener('progress', function(e) {
            if (e.lengthComputable) {
                const percentComplete = (e.loaded / e.total) * 100;
                // Progress logging disabled for performance
                
                const progressBar = progressDiv?.querySelector('progress');
                if (progressBar) {
                    progressBar.value = percentComplete;
                }
            }
        });
        
        // Handle upload completion
        xhr.addEventListener('load', function() {
            debugLog('🎉 S3 upload completed!', xhr.status);
            
            if (xhr.status >= 200 && xhr.status < 300) {
                // Success
                container.innerHTML = `
                    <div class="alert alert-success">
                        <svg xmlns="http://www.w3.org/2000/svg" class="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7" />
                        </svg>
                        <span>✅ ${uploadInfo.filename} uploaded successfully!</span>
                    </div>
                `;
                updateUploadControls();
            } else {
                // Error
                console.error('S3 upload failed:', xhr.status, xhr.statusText);
                showUploadErrorLegacy(container, 'Upload failed: ' + xhr.statusText);
            }
        });
        
        // Handle upload error
        xhr.addEventListener('error', function() {
            console.error('S3 upload error');
            showUploadErrorLegacy(container, 'Upload failed: Network error');
        });
        
        // Send to S3
        xhr.open('POST', uploadInfo.url);
        xhr.send(formData);
    });
}

function setupMultipartUpload(container, uploadInfo, file) {
    const button = container.querySelector('.multipart-upload-btn');
    const progressDiv = container.querySelector('.upload-progress');
    
    button.addEventListener('click', function() {
        debugLog('🚀 Starting multipart upload for:', uploadInfo.filename);
        
        // Show progress
        if (progressDiv) {
            progressDiv.classList.remove('hidden');
        }
        
        // Disable button
        button.disabled = true;
        button.innerHTML = `
            <span class="loading loading-spinner loading-sm mr-2"></span>
            Uploading chunks...
        `;
        
        // TODO: Implement multipart upload logic
        // This would involve:
        // 1. Calculate chunk size and number of parts
        // 2. Get presigned URLs for each part
        // 3. Upload parts in parallel
        // 4. Complete multipart upload
        
        // For now, show placeholder
        setTimeout(() => {
            container.innerHTML = `
                <div class="alert alert-info">
                    <svg xmlns="http://www.w3.org/2000/svg" class="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                    </svg>
                    <span>📦 Multipart upload for ${uploadInfo.filename} - Implementation pending</span>
                </div>
            `;
            updateUploadControls();
        }, 2000);
    });
}

function showUploadErrorLegacy(container, message) {
    const form = container.querySelector('.s3-upload-form');
    const uploadButton = form?.querySelector('button[type="submit"]');
    const progressDiv = container.querySelector('.upload-progress');
    
    // Re-enable button
    if (uploadButton) {
        uploadButton.disabled = false;
        uploadButton.innerHTML = `
            <svg class="h-4 w-4 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
            </svg>
            Retry Upload
        `;
    }
    
    // Hide progress
    if (progressDiv) {
        progressDiv.classList.add('hidden');
    }
    
    // Show error message
    const errorDiv = document.createElement('div');
    errorDiv.className = 'alert alert-error mt-2';
    errorDiv.innerHTML = `
        <svg xmlns="http://www.w3.org/2000/svg" class="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4c-.77-.833-1.964-.833-2.732 0L3.732 16.5c-.77.833.192 2.5 1.732 2.5z" />
        </svg>
        <span>❌ ${message}</span>
    `;
    container.appendChild(errorDiv);
}


// File viewer integration
function initializeFileViewer() {
    document.addEventListener('htmx:afterRequest', function(event) {
        // Check if this is a file viewer request
        if (event.detail.xhr.getResponseHeader('content-type')?.includes('text/html') && 
            event.target.closest('#file-viewer-modal')) {
            
            // Initialize viewers after content is loaded
            setTimeout(() => {
                // Initialize audio players if WaveSurfer is available
                const audioElement = document.querySelector('#audioPlayer');
                if (audioElement && window.WaveSurfer) {
                    const wavesurfer = WaveSurfer.create({
                        container: '#waveform',
                        waveColor: '#4F46E5',
                        progressColor: '#818CF8',
                        cursorColor: '#C7D2FE',
                        barWidth: 2,
                        barRadius: 3,
                        cursorWidth: 1,
                        height: 80,
                        barGap: 2
                    });
                    
                    wavesurfer.load(audioElement.src);
                    
                    const playButton = document.querySelector('#playButton');
                    if (playButton) {
                        playButton.addEventListener('click', () => {
                            wavesurfer.playPause();
                            
                            const isPlaying = wavesurfer.isPlaying();
                            const playIcon = playButton.querySelector('.play-icon');
                            const pauseIcon = playButton.querySelector('.pause-icon');
                            
                            if (isPlaying) {
                                playIcon.classList.add('hidden');
                                pauseIcon.classList.remove('hidden');
                            } else {
                                playIcon.classList.remove('hidden');
                                pauseIcon.classList.add('hidden');
                            }
                        });
                    }
                }
                
                // Initialize code highlighting if Prism.js is available
                if (window.Prism) {
                    Prism.highlightAll();
                }
            }, 100);
        }
    });
}

// Batch Upload Control Functions
function updateUploadControls() {
    const uploadArea = document.getElementById('dashboard-upload-area');
    const uploadControls = document.getElementById('upload-controls');
    const filesCount = document.getElementById('files-count');
    
    if (!uploadArea || !uploadControls || !filesCount) return;
    
    const uploadForms = uploadArea.querySelectorAll('.card form, .card .multipart-upload-btn');
    const count = uploadForms.length;
    
    if (count > 0) {
        uploadControls.classList.remove('hidden');
        filesCount.textContent = count;
    } else {
        uploadControls.classList.add('hidden');
    }
}



// Initialize all dashboard upload functionality
function initializeDashboard() {
    initializeDashboardUpload();
    initializeFileViewer();
}

// Initialize when DOM is ready
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initializeDashboard);
} else {
    initializeDashboard();
}

// Handle multipart upload using S3MultipartUploadHandler
async function handleMultipartUpload(uploadInfo, file) {
    try {
        // Get organization info (for logging only)
        const orgSelector = document.querySelector('#upload-org-selector select[name="organization"]');
        const baseFolderSelector = document.getElementById('base-folder');
        const organization = orgSelector ? orgSelector.value : '';
        const baseFolder = baseFolderSelector ? baseFolderSelector.value : '';

        // Show upload progress UI immediately
        const container = document.querySelector(`[data-filename="${uploadInfo.filename}"]`);
        showUploadProgress(container);

        // Fetch presigned URLs for parts (server computes optimal part plan)
        const partResp = await fetch('/storage/upload/presigned/multipart/parts/', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCsrfToken(),
            },
            credentials: 'include',
            body: JSON.stringify({
                upload_id: uploadInfo.upload_id,
                s3_key: uploadInfo.s3_key,
                filesize: file.size,
                organization: organization
            })
        });
        if (!partResp.ok) {
            throw new Error(`Failed to get presigned part URLs: ${partResp.status}`);
        }
        const partData = await partResp.json();
        if (!partData.success || !Array.isArray(partData.presigned_urls)) {
            throw new Error(partData.error || 'Invalid presigned URLs response');
        }

        const urls = partData.presigned_urls;
        // Use server-calculated chunk size for optimal performance
        const chunkSize = (partData.part_info && partData.part_info.chunk_size) || (window.UPLOAD_CONFIG && window.UPLOAD_CONFIG.chunkSize) || (100 * 1024 * 1024);
        // Increase concurrency for better performance with fewer, larger parts
        const maxConcurrent = Math.min(Math.max((window.UPLOAD_CONFIG && window.UPLOAD_CONFIG.part_upload_concurrency) || 8, 6), 12);

        // Upload with a worker pool
        let uploadedCount = 0;
        const parts = new Array(urls.length);

        function updateProgressUI() {
            if (!container) return;
            const progressBar = container.querySelector('progress');
            const statusText = container.querySelector('.status-text');
            const pct = Math.round((uploadedCount / urls.length) * 100);
            if (progressBar) progressBar.value = pct;
            if (statusText) statusText.textContent = `${pct}%`;
            updateUploadMetrics(uploadInfo.filename, {
                progress: pct,
                loaded: Math.min(uploadedCount * chunkSize, file.size),
                total: file.size,
                speed: 0,
                remainingTime: 0
            });
            updateFileStatusByName(uploadInfo.filename, 'Uploading multipart...', 'uploading');
        }

        async function uploadOne(i) {
            const { part_number, presigned_url } = urls[i];
            const start = (part_number - 1) * chunkSize;
            const end = Math.min(start + chunkSize, file.size);
            const blob = file.slice(start, end);
            
            // Retry logic for failed uploads
            const maxRetries = 3;
            let attempt = 0;
            
            while (attempt <= maxRetries) {
                try {
                    const controller = new AbortController();
                    const timeoutId = setTimeout(() => controller.abort(), 300000); // 5 min timeout per part
                    
                    const resp = await fetch(presigned_url, { 
                        method: 'PUT', 
                        body: blob,
                        signal: controller.signal,
                        headers: {
                            'Content-Type': 'application/octet-stream',
                            'Cache-Control': 'no-cache'
                        },
                        // Performance optimizations for large uploads
                        keepalive: false, // Don't use keepalive for large requests  
                        cache: 'no-store' // Disable caching for upload requests
                    });
                    
                    clearTimeout(timeoutId);
                    
                    if (!resp.ok) {
                        throw new Error(`Part ${part_number} failed: ${resp.status} ${resp.statusText}`);
                    }
                    
                    const etag = resp.headers.get('ETag');
                    if (!etag) {
                        throw new Error(`Part ${part_number} missing ETag in response`);
                    }
                    
                    parts[i] = { ETag: etag, PartNumber: part_number };
                    uploadedCount++;
                    updateProgressUI();
                    return; // Success, exit retry loop
                    
                } catch (error) {
                    attempt++;
                    if (attempt > maxRetries) {
                        throw new Error(`Part ${part_number} failed after ${maxRetries} attempts: ${error.message}`);
                    }
                    // Exponential backoff delay
                    const delay = Math.min(1000 * Math.pow(2, attempt - 1), 10000);
                    debugLog(`🔄 Retrying part ${part_number} in ${delay}ms (attempt ${attempt}/${maxRetries})`);
                    await new Promise(resolve => setTimeout(resolve, delay));
                }
            }
        }

        let nextIndex = 0;
        async function worker() {
            while (true) {
                const i = nextIndex++;
                if (i >= urls.length) break;
                await uploadOne(i);
            }
        }
        const workers = Array.from({ length: maxConcurrent }, () => worker());
        await Promise.all(workers);

        // Complete multipart upload
        const completeForm = new FormData();
        completeForm.append('upload_id', uploadInfo.upload_id);
        completeForm.append('s3_key', uploadInfo.s3_key);
        completeForm.append('filename', uploadInfo.filename);
        completeForm.append('parts', JSON.stringify(parts.filter(Boolean)));
        completeForm.append('csrfmiddlewaretoken', getCsrfToken());

        const completeResp = await fetch('/storage/upload/presigned/multipart/complete/', {
            method: 'POST',
            body: completeForm,
            credentials: 'include'
        });
        if (!completeResp.ok) {
            throw new Error(`Failed to complete multipart: ${completeResp.status}`);
        }

        // Mark file uploaded to trigger verification pipeline
        if (uploadInfo.upload_file_id) {
            try {
                await fetch(`/storage/upload/mark-uploaded/${uploadInfo.upload_file_id}/`, {
                    method: 'POST',
                    headers: { 'X-CSRFToken': getCsrfToken() },
                    credentials: 'include'
                });
            } catch (e) {
                debugError('⚠️ Failed to mark uploaded:', e);
            }
        }

        updateFileStatusByName(uploadInfo.filename, 'Upload completed!', 'completed');

    } catch (error) {
        debugError('❌ Multipart upload failed:', error);
        updateFileStatusByName(uploadInfo.filename, 'Multipart upload failed: ' + error.message, 'failed');
        throw error;
    }
}

// Export functions for global access
window.switchToFilesMode = switchToFilesMode;
window.switchToFolderMode = switchToFolderMode;
window.cancelFolderUpload = cancelFolderUpload;
window.removeUploadByFilename = removeUploadByFilename;
window.removeAsyncUploadFile = removeAsyncUploadFile;
window.removeUploadCard = removeUploadCard;
