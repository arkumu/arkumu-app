import { modalManager } from '../modal.js';

/**
 * Handle file view requests from HTMX
 * @param {Event} event - The HTMX afterRequest event
 */
export function handleFileViewRequest(event) {
    if (!event.detail.successful) {
        console.error('File view request failed:', event.detail);
        return;
    }

    const response = event.detail.xhr.responseText;
    if (!response) {
        console.error('Empty response from file view request');
        return;
    }

    // Get the file name from the clicked element
    const clickedElement = event.detail.elt;
    const fileItem = clickedElement.closest('.file-item');
    const fileName = fileItem ? fileItem.querySelector('.file-name').textContent : 'File';

    // Set the modal title to the file name
    const modalTitle = document.getElementById('modalTitle');
    if (modalTitle) {
        modalTitle.textContent = fileName;
    }

    // Set the content and open the modal
    modalManager.setContent(response);
    modalManager.open();

    // Initialize specific viewers based on file type
    initializeViewers(fileName);
}

/**
 * Initialize specific viewers based on file type
 * @param {string} fileName - The name of the file
 */
function initializeViewers(fileName) {

    const extension = fileName.split('.').pop().toLowerCase();
    
    // Initialize audio player if needed
    if (['mp3', 'wav', 'ogg', 'flac'].includes(extension)) {
        initializeAudioPlayer();
    }
    
    // Initialize video player if needed
    if (['mp4', 'webm', 'ogg'].includes(extension)) {
        initializeVideoPlayer();
    }
    
    // Initialize code highlighting for text files
    if (['txt', 'json', 'xml', 'html', 'css', 'js', 'py', 'java', 'c', 'cpp'].includes(extension)) {
        highlightCode();
    }
}

/**
 * Initialize audio player with waveform visualization
 */
function initializeAudioPlayer() {
    const audioElement = document.querySelector('#audioPlayer');
    if (!audioElement) return;

    // If WaveSurfer is available, initialize it
    if (window.WaveSurfer) {
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
        
        // Connect play/pause button
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
        
        // Store wavesurfer instance globally for cleanup
        window.wavesurfer = wavesurfer;
    }
}

/**
 * Initialize video player
 */
function initializeVideoPlayer() {
    const videoElement = document.querySelector('#videoPlayer');
    if (!videoElement) return;
    
    // Add controls if not present
    if (!videoElement.hasAttribute('controls')) {
        videoElement.setAttribute('controls', '');
    }
}

/**
 * Highlight code in pre elements
 */
function highlightCode() {
    // If Prism.js is available, trigger highlighting
    if (window.Prism) {
        Prism.highlightAll();
    }
}
