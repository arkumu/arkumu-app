from django.conf import settings


def upload_client_config(request):
    """Expose selected upload settings to templates for client-side JS."""
    cfg = getattr(settings, 'MULTIPART_UPLOAD_SETTINGS', {}) or {}
    # Provide optimized defaults for performance
    default_chunk = 100 * 1024 * 1024  # 100MB chunks for better performance
    default_concurrency = 8
    default_part_concurrency = 6
    default_threshold = 100 * 1024 * 1024

    return {
        'UPLOAD_CLIENT_CONFIG': {
            'chunk_size': int(cfg.get('chunk_size', default_chunk)),
            'max_concurrency': int(cfg.get('max_concurrency', default_concurrency)),
            'part_upload_concurrency': int(cfg.get('part_upload_concurrency', default_part_concurrency)),
            'multipart_threshold': int(cfg.get('multipart_threshold', default_threshold)),
            'max_retries': int(cfg.get('max_retries', 3)),
            'retry_delay_base': float(cfg.get('retry_delay_base', 0.5)),
        }
    }

