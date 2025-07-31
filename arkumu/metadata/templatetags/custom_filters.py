from django import template

register = template.Library()

@register.filter
def lookup(dictionary, key):
    """Template filter to lookup dictionary values by key"""
    if isinstance(dictionary, dict):
        return dictionary.get(key, [])
    return []

@register.filter
def length(value):
    """Template filter to get length of a value"""
    try:
        return len(value)
    except (TypeError, AttributeError):
        return 0