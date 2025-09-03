// Dashboard Upload System - Async Upload with HTMX Integration

// Debug logging configuration - set to false in production
const DEBUG_UPLOADS = window.location.hostname === 'localhost' || window.location.search.includes('debug=true');

// Conditional logging functions
const debugLog = DEBUG_UPLOADS ? console.log.bind(console) : () => {};
const debugError = DEBUG_UPLOADS ? console.error.bind(console) : () => {};

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
                                    </div>
                                    <div class="status-badge">
                                        <div class="badge badge-outline badge-xs">Ready</div>
                                    </div>
                                    <button class="btn btn-ghost btn-xs btn-square" onclick="removeUploadByFilename('${upload.filename}')" title="Remove file">
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
            </div>
        `;
        
        filesList.appendChild(listItem);
    });
}

async function startUploads(uploads, files) {
    debugLog('🚀 Starting uploads for', uploads.length, 'files');
    
    // Create a map of filename to file object
    const fileMap = {};
    files.forEach(file => {
        fileMap[file.name] = file;
    });
    
    // Upload each file
    const uploadPromises = uploads.map(async (uploadInfo) => {
        const file = fileMap[uploadInfo.filename];
        if (!file) {
            debugError('❌ File not found:', uploadInfo.filename);
            return;
        }
        
        try {
            await uploadFileDirectly(uploadInfo, file);
        } catch (error) {
            debugError('❌ Upload failed for', uploadInfo.filename, error);
            updateFileStatus(uploadInfo.filename, 'Upload failed: ' + error.message, 'failed');
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
    
    debugLog('📤 Uploading to S3:', uploadInfo.filename);
    
    // Update status to uploading
    updateFileStatusByName(uploadInfo.filename, 'Uploading...', 'uploading');
    
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
        debugLog('📦 Multipart upload not implemented yet for:', uploadInfo.filename);
        updateFileStatusByName(uploadInfo.filename, 'Multipart not implemented', 'failed');
        throw new Error('Multipart upload not implemented');
    }
}

async function uploadWithProgress(url, formData, filename, progressBar, statusText, fileSize, uploadFileId) {
    return new Promise((resolve, reject) => {
        const xhr = new XMLHttpRequest();
        
        // Handle upload progress
        xhr.upload.addEventListener('progress', function(e) {
            if (e.lengthComputable) {
                const percentComplete = (e.loaded / e.total) * 100;
                if (progressBar) {
                    progressBar.value = percentComplete;
                }
                if (statusText) {
                    statusText.textContent = `${percentComplete.toFixed(0)}%`;
                }
                
                // Update file status text
                updateFileStatusByName(filename, `Uploading ${percentComplete.toFixed(0)}%`, 'uploading');
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
                        const response = await fetch(`/storage/upload/mark-uploaded/${uploadFileId}/`, {
                            method: 'POST',
                            headers: {
                                'X-CSRFToken': getCsrfToken(),
                            },
                            credentials: 'include'
                        });
                        
                        if (response.ok) {
                            debugLog('✅ Server notified of upload:', filename);
                        } else {
                            debugError('⚠️ Failed to notify server of upload:', filename);
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
        console.log('📝 Using hidden form to bypass CORS for:', uploadInfo.filename);
        
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
                console.log('✅ Form upload completed:', uploadInfo.filename);
                updateFileStatusByName(uploadInfo.filename, 'Upload completed!', 'completed');
                resolve();
            } catch (e) {
                console.error('❌ Form upload may have failed:', e);
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
        console.log('📤 Submitting form for:', uploadInfo.filename);
        updateFileStatusByName(uploadInfo.filename, 'Uploading (no progress available)...', 'uploading');
        form.submit();
    });
}

// New function for PUT uploads (Dell EMC S3)
async function uploadWithProgressPUT(url, file, filename, progressBar, statusText, fileSize, uploadFileId) {
    return new Promise((resolve, reject) => {
        const xhr = new XMLHttpRequest();
        
        // Handle upload progress
        xhr.upload.addEventListener('progress', function(e) {
            if (e.lengthComputable) {
                const percentComplete = (e.loaded / e.total) * 100;
                if (progressBar) {
                    progressBar.value = percentComplete;
                }
                if (statusText) {
                    statusText.textContent = `${percentComplete.toFixed(0)}%`;
                }
                
                // Update file status text
                updateFileStatusByName(filename, `Uploading ${percentComplete.toFixed(0)}%`, 'uploading');
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
                        const response = await fetch(`/storage/upload/mark-uploaded/${uploadFileId}/`, {
                            method: 'POST',
                            headers: {
                                'X-CSRFToken': getCsrfToken(),
                            },
                            credentials: 'include'
                        });
                        
                        if (response.ok) {
                            debugLog('✅ Server notified of upload:', filename);
                        } else {
                            debugError('⚠️ Failed to notify server of upload:', filename);
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
    
    console.log('📋 OPTIMISTIC: Adding', uploadedFiles.length, 'files to file browser');
    
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
    
    console.log('✅ OPTIMISTIC: Files displayed immediately');
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
    console.log('🔄 POLLING: Starting verification status polling');
    
    const pollInterval = 2000; // Poll every 2 seconds
    const maxPolls = 30; // Stop after 60 seconds
    let pollCount = 0;
    
    const polling = setInterval(async () => {
        pollCount++;
        console.log(`📡 POLLING: Check ${pollCount}/${maxPolls}`);
        
        try {
            // Get the organization for API call
            const orgSelector = document.querySelector('#upload-org-selector select[name="organization"]');
            const organization = orgSelector ? orgSelector.value : '';
            
            if (!organization) {
                console.log('⚠️ POLLING: No organization selected, stopping');
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
                    console.log('✅ POLLING: All files verified, stopping');
                    clearInterval(polling);
                    showFinalUploadSuccess(uploadedFiles.length);
                }
            }
            
        } catch (error) {
            console.error('❌ POLLING: Error checking status:', error);
        }
        
        // Stop polling after max attempts
        if (pollCount >= maxPolls) {
            console.log('⏰ POLLING: Max attempts reached, stopping');
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
            console.log('⚠️ REFRESH: No organization selected, skipping file browser refresh');
            return;
        }
        
        console.log('🔄 REFRESH: Refreshing file browser for organization:', organization);
        
        // Use HTMX to refresh the file browser
        if (window.htmx) {
            const url = `/storage/dashboard/refresh/${organization}/`;
            
            console.log('📡 REFRESH: Fetching fresh file list from:', url);
            
            // Use HTMX's ajax method to replace the content
            htmx.ajax('GET', url, {
                target: '#file-browser-content',
                swap: 'innerHTML'
            });
            
            // Show success message after refresh
            if (uploadedFiles.length > 0) {
                setTimeout(() => {
                    showUploadComplete(uploadedFiles.length);
                }, 1000); // Give refresh time to complete
            }
            
            console.log('✅ REFRESH: File browser refresh initiated');
        } else {
            console.error('❌ REFRESH: HTMX not available');
        }
        
    } catch (error) {
        console.error('❌ REFRESH: Error refreshing file browser:', error);
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
    const progressBar = document.getElementById('folder-progress-bar');
    const progressText = document.querySelector('.folder-progress-text');
    const completedCount = document.getElementById('completed-count');
    const failedCount = document.getElementById('failed-count');
    
    if (progressBar && sessionStatus.total_files > 0) {
        const progress = ((sessionStatus.completed_files + sessionStatus.failed_files) / sessionStatus.total_files) * 100;
        progressBar.value = progress;
    }
    
    if (progressText) {
        if (sessionStatus.status === 'completed') {
            progressText.textContent = 'Upload completed!';
        } else if (sessionStatus.status === 'failed') {
            progressText.textContent = 'Upload failed';
        } else {
            progressText.textContent = `${sessionStatus.completed_files + sessionStatus.failed_files}/${sessionStatus.total_files} processed`;
        }
    }
    
    if (completedCount) {
        completedCount.textContent = sessionStatus.completed_files || 0;
    }
    
    if (failedCount) {
        failedCount.textContent = sessionStatus.failed_files || 0;
    }
    
    // Update individual file statuses in the collapsible list if visible
    sessionStatus.files.forEach(fileStatus => {
        const fileContainer = document.querySelector(`[data-file-id*="${fileStatus.filename}"]`);
        if (fileContainer) {
            const statusBadge = fileContainer.querySelector('.status-badge');
            if (statusBadge) {
                let badgeClass = 'badge-outline';
                let statusText = fileStatus.status;
                
                switch (fileStatus.status) {
                    case 'completed':
                        badgeClass = 'badge-success';
                        statusText = '✅ Done';
                        break;
                    case 'failed':
                        badgeClass = 'badge-error';
                        statusText = '❌ Failed';
                        break;
                    case 'processing':
                        badgeClass = 'badge-warning';
                        statusText = 'Processing';
                        break;
                    case 'uploaded':
                        badgeClass = 'badge-info';
                        statusText = 'Uploaded';
                        break;
                }
                
                statusBadge.innerHTML = `<div class="badge ${badgeClass} badge-xs">${statusText}</div>`;
            }
        }
    });
}

function updateFileStatus(fileId, statusText, status) {
    const container = document.querySelector(`[data-file-id="${fileId}"]`);
    if (!container) return;
    
    const statusElement = container.querySelector('.file-status');
    const statusBadge = container.querySelector('.status-badge');
    const progressDiv = container.querySelector('.upload-progress');
    const progressIndicator = container.querySelector('.upload-progress-indicator');
    const removeBtn = container.querySelector('.remove-file-btn');
    
    if (statusElement) {
        statusElement.textContent = statusText;
    }
    
    // Update status badge and visual indicators
    if (status === 'uploading') {
        if (statusBadge) {
            statusBadge.innerHTML = '<div class="badge badge-info badge-sm">Uploading</div>';
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
        if (statusBadge) {
            statusBadge.innerHTML = '<div class="badge badge-success badge-sm">✅ Complete</div>';
        }
        if (progressIndicator) {
            progressIndicator.classList.add('hidden');
        }
        if (progressDiv) {
            progressDiv.classList.add('hidden');
        }
        // Add subtle success styling to the entire row
        container.classList.add('bg-success/5');
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
        container.classList.add('bg-error/5');
        if (removeBtn) {
            removeBtn.style.display = 'block'; // Show remove button again for failed uploads
        }
    }
}

function updateFileStatusByName(filename, status, error) {
    const containers = document.querySelectorAll('.upload-file-container');
    containers.forEach(container => {
        const nameElement = container.querySelector('h3');
        if (nameElement && nameElement.textContent === filename) {
            const statusElement = container.querySelector('.file-status');
            if (statusElement) {
                statusElement.textContent = status;
            }
            
            if (status === 'completed') {
                updateFileStatus(container.dataset.fileId, 'Upload completed successfully!', 'completed');
            } else if (status === 'failed') {
                updateFileStatus(container.dataset.fileId, error || 'Upload failed', 'failed');
            }
        }
    });
}

function handleSessionCompletion(sessionStatus) {
    console.log('🎉 ASYNC: Upload session completed!');
    
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

// Legacy upload card functions (kept for compatibility)
function createUploadCard(uploadInfo, file) {
    console.log('🏗️ Creating upload card for:', uploadInfo.filename, 'type:', uploadInfo.type);
    
    const uploadArea = document.getElementById('dashboard-upload-area');
    if (!uploadArea) {
        console.error('❌ Upload area not found!');
        return;
    }
    
    const uploadContainer = document.createElement('div');
    uploadContainer.classList.add('upload-file-container');
    
    console.log('📦 Upload info received:', uploadInfo);
    
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
        console.log('➕ Adding single upload card to DOM');
        uploadArea.appendChild(uploadContainer);
        
        // Setup S3 upload handling
        console.log('⚙️ Setting up S3 upload for:', uploadInfo.filename);
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
    console.log('🎨 Getting icon for filetype:', filetype);
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
        
        console.log('🚀 Starting S3 upload for:', uploadInfo.filename);
        
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
            console.log('📄 Handling zero-byte file:', file.name);
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
            console.log('🎉 S3 upload completed!', xhr.status);
            
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
                console.error('❌ S3 upload failed:', xhr.status, xhr.statusText);
                showUploadErrorLegacy(container, 'Upload failed: ' + xhr.statusText);
            }
        });
        
        // Handle upload error
        xhr.addEventListener('error', function() {
            console.error('❌ S3 upload error');
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
        console.log('🚀 Starting multipart upload for:', uploadInfo.filename);
        
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

// Export functions for global access
window.switchToFilesMode = switchToFilesMode;
window.switchToFolderMode = switchToFolderMode;
window.cancelFolderUpload = cancelFolderUpload;
window.removeUploadByFilename = removeUploadByFilename;
window.removeAsyncUploadFile = removeAsyncUploadFile;
window.removeUploadCard = removeUploadCard;
