from django.conf import settings


def upload_client_config(request):
    """Expose selected upload settings to templates for client-side JS."""
    cfg = getattr(settings, 'MULTIPART_UPLOAD_SETTINGS', {}) or {}
    # Provide safe defaults if settings are missing
    default_chunk = 8 * 1024 * 1024
    default_concurrency = 6
    default_threshold = 100 * 1024 * 1024

    return {
        'UPLOAD_CLIENT_CONFIG': {
            'chunk_size': int(cfg.get('chunk_size', default_chunk)),
            'max_concurrency': int(cfg.get('max_concurrency', default_concurrency)),
            'multipart_threshold': int(cfg.get('multipart_threshold', default_threshold)),
        }
    }

