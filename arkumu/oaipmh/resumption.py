"""
Resumption token service for OAI-PMH pagination.

Provides stateless, secure pagination using HMAC-signed tokens.
"""

from __future__ import annotations

import hmac
import hashlib
import json
import base64
from datetime import datetime, timezone
from typing import Optional, Dict, Any, Tuple
from urllib.parse import quote, unquote

from django.conf import settings


class ResumptionTokenService:
    """
    Stateless resumption token service using HMAC signatures.

    Tokens encode pagination state including:
    - offset: current position in result set
    - verb: OAI-PMH verb (ListIdentifiers, ListRecords)
    - metadata_prefix: format specification
    - set: optional set specification
    - from_date: optional temporal filter start
    - until_date: optional temporal filter end
    """

    def __init__(self, secret_key: Optional[str] = None, page_size: int = 100):
        self.secret_key = secret_key or getattr(settings, 'SECRET_KEY', 'default-secret')
        self.page_size = page_size

    def create_token(
        self,
        offset: int,
        verb: str,
        metadata_prefix: str = "oai_dc",
        set_spec: Optional[str] = None,
        from_date: Optional[str] = None,
        until_date: Optional[str] = None,
        total_count: Optional[int] = None,
        snapshot_marker: Optional[str] = None,
        cursor_marker: Optional[str] = None,
        cursor_position: Optional[str] = None,
    ) -> str:
        """
        Create a resumption token with the given parameters.

        Args:
            offset: Current position in result set
            verb: OAI-PMH verb (ListIdentifiers, ListRecords)
            metadata_prefix: Metadata format
            set_spec: Optional set specification
            from_date: Optional temporal filter start (ISO format)
            until_date: Optional temporal filter end (ISO format)
            total_count: Total number of records (for client info)

        Returns:
            Base64-encoded, HMAC-signed resumption token
        """
        token_data = {
            'offset': offset,
            'verb': verb,
            'metadata_prefix': metadata_prefix,
            'page_size': self.page_size,
            'timestamp': datetime.now(timezone.utc).isoformat(),
        }

        if set_spec:
            token_data['set'] = set_spec
        if from_date:
            token_data['from'] = from_date
        if until_date:
            token_data['until'] = until_date
        if total_count is not None:
            token_data['total_count'] = total_count
        if snapshot_marker:
            token_data['snapshot'] = snapshot_marker
            if not cursor_marker:
                token_data['cursor'] = snapshot_marker
        if cursor_marker:
            token_data['cursor'] = cursor_marker
        if cursor_position:
            token_data['cursor_position'] = cursor_position

        # Serialize and encode
        token_json = json.dumps(token_data, sort_keys=True)
        token_bytes = token_json.encode('utf-8')

        # Create HMAC signature
        signature = hmac.new(
            self.secret_key.encode('utf-8'),
            token_bytes,
            hashlib.sha256
        ).hexdigest()

        # Combine token and signature
        signed_token = f"{base64.b64encode(token_bytes).decode('ascii')}:{signature}"

        return quote(signed_token)

    def parse_token(self, token: str) -> Tuple[bool, Optional[Dict[str, Any]], Optional[str]]:
        """
        Parse and validate a resumption token.

        Args:
            token: The resumption token to parse

        Returns:
            Tuple of (is_valid, token_data, error_message)
        """
        try:
            # Decode URL encoding
            unquoted_token = unquote(token)

            # Split token and signature
            if ':' not in unquoted_token:
                return False, None, "Invalid token format"

            token_part, signature = unquoted_token.rsplit(':', 1)

            # Decode base64 token
            try:
                token_bytes = base64.b64decode(token_part.encode('ascii'))
            except Exception:
                return False, None, "Invalid token encoding"

            # Verify HMAC signature
            expected_signature = hmac.new(
                self.secret_key.encode('utf-8'),
                token_bytes,
                hashlib.sha256
            ).hexdigest()

            if not hmac.compare_digest(signature, expected_signature):
                return False, None, "Invalid token signature"

            # Parse JSON data
            try:
                token_data = json.loads(token_bytes.decode('utf-8'))
            except Exception:
                return False, None, "Invalid token data"

            # Basic validation
            required_fields = ['offset', 'verb', 'metadata_prefix', 'page_size', 'timestamp']
            for field in required_fields:
                if field not in token_data:
                    return False, None, f"Missing required field: {field}"

            return True, token_data, None

        except Exception as e:
            return False, None, f"Token parsing error: {str(e)}"

    def get_next_offset(self, token_data: Dict[str, Any]) -> int:
        """Get the next offset for pagination."""
        return token_data['offset'] + token_data['page_size']

    def has_more_records(self, current_offset: int, page_size: int, total_fetched: int) -> bool:
        """Check if there are more records available."""
        return total_fetched == page_size  # If we got a full page, there might be more
