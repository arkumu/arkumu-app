import { modalManager } from '../../modal.js';

export function renderVideoPlayer(fileData) {
    const html = `
        <video id="${fileData.bucket_type}/${fileData.path}" controls style="max-width: 100%; max-height: 800px;">
            <source src="/archivist/stream/${fileData.bucket_type}/${fileData.path}" type="${fileData.type}">
            Your browser does not support the video tag.
        </video>
        <div class="mt-4 text-sm text-gray-600">
            <p>File Type: ${fileData.type}</p>
            <p>Last Modified: ${fileData.last_modified}</p>
            <p>Size: ${fileData.size} bytes</p>
        </div>
    `;
    
    modalManager.setContent(html);
}
