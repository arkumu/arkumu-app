class ModalManager {
    constructor() {
        // Initialize immediately if document is already loaded
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', () => this.init());
        } else {
            this.init();
        }
    }

    init() {
        console.log('Initializing ModalManager');
        this.modal = document.getElementById('fileModal');
        this.modalContent = document.getElementById('modalContent');
        
        if (!this.modal || !this.modalContent) {
            console.error('Modal elements not found!');
            return;
        }
        
        this.setupEventListeners();
    }

    setupEventListeners() {
        console.log('Setting up event listeners');
        
        // Close modal when clicking outside
        this.modal.addEventListener('click', (e) => {
            if (e.target === this.modal) {
                console.log('Clicked modal background');
                this.close();
            }
        });

        // Close modal when clicking the X button
        const closeButton = this.modal.querySelector('.modal-close');
        console.log('Found close button:', closeButton);
        
        if (closeButton) {
            closeButton.addEventListener('click', (e) => {
                console.log('Close button clicked!');
                e.stopPropagation();
                this.close();
            });
        } else {
            console.error('Close button not found!');
        }
    }

    open() {
        console.log('Opening modal');
        this.modal.classList.remove('opacity-0', 'pointer-events-none');
        this.modal.classList.add('opacity-100', 'pointer-events-auto');
    }

    close() {
        console.log('🔴 MODAL CLOSE CALLED - Starting cleanup process');
        
        // Stop media playback BEFORE clearing content
        const audioElement = this.modal.querySelector('audio');
        if (audioElement) {
            console.log('Stopping audio playback');
            audioElement.pause();
            audioElement.currentTime = 0;
            audioElement.src = '';
            audioElement.load();
        }

        const videoElement = this.modal.querySelector('video');
        if (videoElement) {
            console.log('🎥 FOUND VIDEO ELEMENT - Starting video cleanup');
            
            // Pause video first
            videoElement.pause();
            videoElement.currentTime = 0;
            
            // Remove all source elements
            const sources = videoElement.querySelectorAll('source');
            sources.forEach(source => source.remove());
            
            // Clear src and load to try to stop requests
            videoElement.src = "";
            videoElement.load();
            
            // Most aggressive approach: replace with dummy video to force Chrome to abort requests
            const dummyVideo = document.createElement('video');
            dummyVideo.src = 'data:video/mp4;base64,AAAAHGZ0eXBpc29tAAACAGlzb21pc28ybXA0MQAAAAhmcmVlAAAAG21kYXQAAAGzABAHAAABthADAowdbb9/AAAC6W1vb3YAAABsbXZoZAAAAAB8JbCAfCWwgAAAA+gAAAAAAAEAAAEAAAAAAAAAAAAAAAABAAAAAAAAAAAAAAAAAAAAAQAAAAAAAAAAAAAAAAAAQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAIAAAIVdHJhawAAAFx0a2hkAAAAD3wlsIB8JbCAAAAAAQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAABAAAAAAAAAAAAAAAAAAAAAQAAAAAAAAAAAAAAAAAAQAAAAAALAAAACgAAAAAAJGVkdHMAAAAcZWxzdAAAAAAAAAABAAAAAQAACgAAAAABAAAAAAAAAAAAAAD//w==';
            videoElement.parentNode.replaceChild(dummyVideo, videoElement);
            
            // Immediately remove the dummy too
            dummyVideo.remove();
            
            console.log('✅ VIDEO CLEANUP COMPLETE - Element removed from DOM');
        } else {
            console.log('No video element found in modal');
        }

        // Stop WaveSurfer if exists
        if (window.wavesurfer) {
            window.wavesurfer.pause();
            window.wavesurfer.destroy();
            window.wavesurfer = null;
        }

        this.modal.classList.remove('opacity-100', 'pointer-events-auto');
        this.modal.classList.add('opacity-0', 'pointer-events-none');

        // Clear content after stopping media
        this.modalContent.innerHTML = '';
        
        console.log('🟢 MODAL CLOSE COMPLETE - All cleanup finished');
    }

    setContent(content) {
        this.modalContent.innerHTML = content;
        // Get the viewer type from the content
        const viewerType = this._detectViewerType(content);
        this.modal.setAttribute('data-viewer-type', viewerType);
    }

    _detectViewerType(content) {
        if (content.includes('audioPlayer')) return 'audio';
        if (content.includes('<video')) return 'video';
        if (content.includes('elan-viewer')) return 'elan';
        // Add more viewer types as needed
        return 'default';
    }
}

// Create and export the modal manager instance
const modalManager = new ModalManager();
export { modalManager };
