from django import template
from django.templatetags.static import static

from urllib.parse import urlparse

register = template.Library()


@register.filter
def get_item(dictionary, key):
    """Get item from dictionary by key."""
    return dictionary.get(key, [])


@register.filter
def uri_tail(value: str) -> str:
    """Return a human-friendly tail for a URI or key.

    - If it's a URI, return the last path segment.
    - Replace '-' and '_' with spaces and title-case the result.
    """
    if not value:
        return ''
    s = str(value)
    # Get tail after last '/'
    if '/' in s:
        s = s.rstrip('/').split('/')[-1]
    s = s.replace('-', ' ').replace('_', ' ').strip()
    return ' '.join(w.capitalize() for w in s.split())


@register.simple_tag
def project_image_url(path: str) -> str:
    """Return a safe image URL for project cards.

    - HTTP(S) / protocol-relative URLs are used as-is
    - S3 or other storage schemes are returned untouched
    - Relative paths fall back to Django's staticfiles lookup
    - Any lookup failure (missing manifest entry, etc.) returns the default card image
    """

    default_url = static('images/main/card_1.png')

    if not path:
        return default_url

    normalized = str(path).strip()
    if not normalized:
        return default_url

    # Replace Windows-style separators and leading slashes
    normalized = normalized.replace('\\', '/').lstrip('/')

    parsed = urlparse(normalized)
    if parsed.scheme in {'http', 'https'}:
        return normalized

    if parsed.scheme and parsed.scheme not in {'http', 'https'}:
        return normalized

    # Treat manifest-unknown hashed literals (e.g., csm_* files) as missing
    if normalized.lower().startswith('csm_'):
        return default_url

    try:
        return static(normalized)
    except ValueError:
        return default_url
