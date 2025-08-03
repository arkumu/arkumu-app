from django import template
import os

register = template.Library()

@register.filter
def is_viewable_file(filename):
    """
    Determine if a file can be viewed with the generic file viewer.
    Returns True if the file extension is supported.
    """
    if not filename:
        return False
    
    # Get file extension
    file_ext = os.path.splitext(filename)[1].lower()
    
    # Define supported file types
    viewable_extensions = {
        # Images
        '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.svg',
        # Documents
        '.pdf',
        # Videos
        '.mp4', '.webm', '.ogg', '.avi', '.mov',
        # Audio
        '.mp3', '.wav', '.ogg', '.flac', '.m4a',
        # Text files
        '.txt', '.json', '.xml', '.html', '.css', '.js', '.py', 
        '.java', '.c', '.cpp', '.md', '.csv'
    }
    
    return file_ext in viewable_extensions

@register.filter
def get_file_type(filename):
    """
    Get the file type category for display purposes.
    """
    if not filename:
        return 'unknown'
    
    file_ext = os.path.splitext(filename)[1].lower()
    
    # Image types
    if file_ext in ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.svg']:
        return 'image'
    # Document types
    elif file_ext in ['.pdf']:
        return 'document'
    # Video types
    elif file_ext in ['.mp4', '.webm', '.ogg', '.avi', '.mov']:
        return 'video'
    # Audio types
    elif file_ext in ['.mp3', '.wav', '.ogg', '.flac', '.m4a']:
        return 'audio'
    # Text types
    elif file_ext in ['.txt', '.json', '.xml', '.html', '.css', '.js', '.py', '.java', '.c', '.cpp', '.md']:
        return 'text'
    # CSV
    elif file_ext in ['.csv']:
        return 'csv'
    else:
        return 'unknown'

@register.filter
def get_file_icon(filename):
    """
    Get an appropriate icon class for the file type.
    """
    file_type = get_file_type(filename)
    
    icon_map = {
        'image': '🖼️',
        'document': '📄',
        'video': '🎥',
        'audio': '🎵',
        'text': '📝',
        'csv': '📊',
        'unknown': '📁'
    }
    
    return icon_map.get(file_type, '📁')