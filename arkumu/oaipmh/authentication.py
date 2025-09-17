"""
Authentication for OAI-PMH endpoint using HTTP Basic Authentication.
This allows Rosetta and other OAI-PMH harvesters to authenticate with username/password.
"""

import base64
import logging
from functools import wraps

from django.contrib.auth import authenticate
from django.http import HttpResponse
from django.utils import timezone

logger = logging.getLogger(__name__)


def parse_basic_auth(auth_header):
    """Parse HTTP Basic Authentication header."""
    if not auth_header or not auth_header.startswith('Basic '):
        return None, None

    try:
        auth_decoded = base64.b64decode(auth_header[6:]).decode('utf-8')
        username, password = auth_decoded.split(':', 1)
        return username, password
    except (ValueError, TypeError):
        return None, None


def oai_authentication_required(view_func):
    """
    Decorator that checks for authentication via:
    1. HTTP Basic Authentication (username/password) - for Rosetta and other harvesters
    2. Django session (if already logged in via web interface)

    This allows Rosetta to authenticate with normal credentials.
    """
    @wraps(view_func)
    def wrapped_view(request, *args, **kwargs):
        # Check if user is already authenticated via Django session
        if request.user.is_authenticated:
            return view_func(request, *args, **kwargs)

        # Try HTTP Basic Authentication
        auth_header = request.META.get('HTTP_AUTHORIZATION', '')
        username, password = parse_basic_auth(auth_header)

        if username and password:
            user = authenticate(request, username=username, password=password)
            if user and user.is_active:
                request.user = user
                logger.info(f"OAI-PMH access via Basic Auth for user: {username}")
                return view_func(request, *args, **kwargs)

        # Authentication failed - return 401 with WWW-Authenticate header
        response = HttpResponse(
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<OAI-PMH xmlns="http://www.openarchives.org/OAI/2.0/">\n'
            '  <responseDate>' + timezone.now().strftime("%Y-%m-%dT%H:%M:%SZ") + '</responseDate>\n'
            '  <request/>\n'
            '  <error code="badVerb">Authentication required for OAI-PMH access</error>\n'
            '</OAI-PMH>',
            status=401,
            content_type='text/xml; charset=utf-8'
        )
        response['WWW-Authenticate'] = 'Basic realm="OAI-PMH Repository"'
        return response

    return wrapped_view