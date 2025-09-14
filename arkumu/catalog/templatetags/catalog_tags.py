from django import template

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
