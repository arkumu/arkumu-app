"""Compatibility decorator for OAI-PMH authentication (currently disabled)."""

from functools import wraps
from typing import Callable


def oai_authentication_required(view_func: Callable):
    """Return the view untouched so OAI remains fully anonymous."""

    @wraps(view_func)
    def wrapped_view(*args, **kwargs):
        return view_func(*args, **kwargs)

    return wrapped_view
