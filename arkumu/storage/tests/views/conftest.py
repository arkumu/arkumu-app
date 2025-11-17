import pytest
import json
from urllib.parse import urlencode
from unittest.mock import MagicMock, PropertyMock
from django.test import RequestFactory
from django.contrib.messages.storage.fallback import FallbackStorage
from django.contrib.sessions.backends.base import SessionBase


@pytest.fixture
def request_factory():
    """Fixture for a request factory."""
    return RequestFactory()


@pytest.fixture
def auth_user():
    """Fixture for an authenticated user."""
    user = MagicMock()
    user.is_authenticated = True
    user.is_active = True
    user.id = 1
    user.username = "testuser"
    return user


@pytest.fixture
def prepared_request(request_factory, auth_user):
    """Fixture for preparing a request with user, session, and optional HTMX headers."""
    def _prepare_request(request_path, method='post', data=None, htmx=False, content_type=None):
        data = data or {}
        
        if method.lower() == 'get':
            request = request_factory.get(request_path, data=data if method.lower() == 'get' else None)
        else:
            # Set the Content-Type for POST requests
            if content_type == 'application/json':
                # For JSON content, use json parameter
                request = request_factory.post(
                    request_path, 
                    data=json.dumps(data), 
                    content_type='application/json'
                )
                # For views that expect to parse JSON from request.body
                setattr(request, '_body', json.dumps(data).encode('utf-8'))
            else:
                # For form data, encode via urlencode to produce deterministic POST bodies
                encoded = urlencode(data or {})
                request = request_factory.post(
                    request_path, 
                    data=encoded,
                    content_type='application/x-www-form-urlencoded'
                )
        
        # Set user
        request.user = auth_user
        
        # Set scheme and host
        type(request).scheme = PropertyMock(return_value='http')
        request.get_host = MagicMock(return_value='testserver')
        
        # Add session (will be replaced with dict in tests as needed)
        request.session = {}
        
        # Add messages storage
        messages = FallbackStorage(request)
        setattr(request, '_messages', messages)
        
        # Add HTMX header if needed
        if htmx:
            request.headers = {'HX-Request': 'true'}
        else:
            request.headers = {}
        
        # Add META for cookie handling
        request.META = {'HTTP_COOKIE': 'sessionid=test_session_key'}
        if hasattr(request, 'content_type') and request.content_type:
            request.META['CONTENT_TYPE'] = request.content_type
        
        return request
    
    return _prepare_request 
