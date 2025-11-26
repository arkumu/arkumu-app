"""
Tests for the ResumptionTokenService.

Tests token creation, parsing, validation, and security features
of the stateless resumption token system.
"""

import pytest
from datetime import datetime, timezone
from unittest.mock import patch
import json
import base64
import hmac
import hashlib
from urllib.parse import quote, unquote

from arkumu.oaipmh.resumption import ResumptionTokenService
from arkumu.oaipmh.resumption_tailored import TailoredResumptionTokenService


class TestResumptionTokenService:
    """Test ResumptionTokenService functionality."""

    def setup_method(self):
        """Set up test method."""
        self.service = ResumptionTokenService(
            secret_key="test-secret-key",
            page_size=100
        )

    # ============================================================================
    # TOKEN CREATION TESTS
    # ============================================================================

    def test_create_basic_token(self):
        """Test creating a basic token with required parameters."""
        token = self.service.create_token(
            offset=0,
            verb="ListIdentifiers",
            metadata_prefix="oai_dc"
        )

        assert token
        assert isinstance(token, str)
        assert len(token) > 0

        # Token should be URL-encoded
        decoded_token = unquote(token)
        assert ":" in decoded_token  # Should contain signature separator

    def test_create_token_with_all_parameters(self):
        """Test creating token with all optional parameters."""
        token = self.service.create_token(
            offset=100,
            verb="ListRecords",
            metadata_prefix="mets",
            set_spec="test_set",
            from_date="2023-01-01T00:00:00Z",
            until_date="2023-12-31T23:59:59Z",
            total_count=1000
        )

        assert token
        is_valid, token_data, error = self.service.parse_token(token)

        assert is_valid
        assert token_data["offset"] == 100
        assert token_data["verb"] == "ListRecords"
        assert token_data["metadata_prefix"] == "mets"
        assert token_data["set"] == "test_set"
        assert token_data["from"] == "2023-01-01T00:00:00Z"
        assert token_data["until"] == "2023-12-31T23:59:59Z"
        assert token_data["total_count"] == 1000

    def test_create_token_includes_timestamp(self):
        """Test that created tokens include timestamps."""
        with patch('arkumu.oaipmh.resumption.datetime') as mock_dt:
            fixed_time = datetime(2023, 6, 15, 14, 30, 0, tzinfo=timezone.utc)
            mock_dt.now.return_value = fixed_time
            mock_dt.side_effect = lambda *args, **kw: datetime(*args, **kw)

            token = self.service.create_token(
                offset=0,
                verb="ListIdentifiers",
                metadata_prefix="oai_dc"
            )

            is_valid, token_data, error = self.service.parse_token(token)

            assert is_valid
            assert "timestamp" in token_data
            assert token_data["timestamp"] == "2023-06-15T14:30:00+00:00"

    def test_create_token_includes_page_size(self):
        """Test that tokens include page_size."""
        token = self.service.create_token(
            offset=50,
            verb="ListIdentifiers",
            metadata_prefix="oai_dc"
        )

        is_valid, token_data, error = self.service.parse_token(token)

        assert is_valid
        assert token_data["page_size"] == 100

    def test_create_token_with_snapshot_marker_sets_cursor(self):
        """Snapshot marker should populate both snapshot and cursor fields."""
        token = self.service.create_token(
            offset=25,
            verb="ListRecords",
            metadata_prefix="mets",
            snapshot_marker="snapshot-123",
        )

        is_valid, token_data, error = self.service.parse_token(token)

        assert is_valid
        assert token_data["snapshot"] == "snapshot-123"
        assert token_data["cursor"] == "snapshot-123"

    def test_create_token_with_cursor_marker_only(self):
        """Cursor marker should populate cursor even when snapshot is absent."""
        token = self.service.create_token(
            offset=25,
            verb="ListRecords",
            metadata_prefix="mets",
            cursor_marker="cursor-xyz",
        )

        is_valid, token_data, error = self.service.parse_token(token)

        assert is_valid
        assert "snapshot" not in token_data
        assert token_data["cursor"] == "cursor-xyz"

    def test_create_token_with_cursor_position(self):
        """Cursor position should be stored when provided."""
        token = self.service.create_token(
            offset=10,
            verb="ListIdentifiers",
            metadata_prefix="oai_dc",
            cursor_position="2024-01-01T00:00:00+00:00|123",
        )

        is_valid, token_data, error = self.service.parse_token(token)

        assert is_valid
        assert token_data["cursor_position"] == "2024-01-01T00:00:00+00:00|123"

    # ============================================================================
    # TOKEN PARSING TESTS
    # ============================================================================

    def test_parse_valid_token(self):
        """Test parsing a valid token."""
        original_token = self.service.create_token(
            offset=200,
            verb="ListRecords",
            metadata_prefix="oai_dc",
            set_spec="test_org"
        )

        is_valid, token_data, error = self.service.parse_token(original_token)

        assert is_valid
        assert error is None
        assert token_data is not None
        assert token_data["offset"] == 200
        assert token_data["verb"] == "ListRecords"
        assert token_data["metadata_prefix"] == "oai_dc"
        assert token_data["set"] == "test_org"

    def test_parse_token_missing_signature(self):
        """Test parsing token without signature separator."""
        invalid_token = "eyJvZmZzZXQiOiAwfQ=="  # Base64 without signature

        is_valid, token_data, error = self.service.parse_token(invalid_token)

        assert not is_valid
        assert token_data is None
        assert "Invalid token format" in error

    def test_parse_token_invalid_base64(self):
        """Test parsing token with invalid base64."""
        invalid_token = "invalid-base64!!!:signature"

        is_valid, token_data, error = self.service.parse_token(invalid_token)

        assert not is_valid
        assert token_data is None
        assert "Invalid token encoding" in error

    def test_parse_token_invalid_json(self):
        """Test parsing token with invalid JSON."""
        # Create token with invalid JSON
        invalid_json = b"not valid json"
        token_b64 = base64.b64encode(invalid_json).decode('ascii')
        signature = hmac.new(
            self.service.secret_key.encode('utf-8'),
            invalid_json,
            hashlib.sha256
        ).hexdigest()
        invalid_token = quote(f"{token_b64}:{signature}")

        is_valid, token_data, error = self.service.parse_token(invalid_token)

        assert not is_valid
        assert token_data is None
        assert "Invalid token data" in error

    def test_parse_token_missing_required_fields(self):
        """Test parsing token missing required fields."""
        # Create token with missing fields
        incomplete_data = {"offset": 0}  # Missing verb, metadata_prefix, etc.
        token_json = json.dumps(incomplete_data, sort_keys=True)
        token_bytes = token_json.encode('utf-8')
        token_b64 = base64.b64encode(token_bytes).decode('ascii')
        signature = hmac.new(
            self.service.secret_key.encode('utf-8'),
            token_bytes,
            hashlib.sha256
        ).hexdigest()
        invalid_token = quote(f"{token_b64}:{signature}")

        is_valid, token_data, error = self.service.parse_token(invalid_token)

        assert not is_valid
        assert token_data is None
        assert "Missing required field" in error

    # ============================================================================
    # SECURITY TESTS
    # ============================================================================

    def test_token_signature_validation(self):
        """Test that token signatures are properly validated."""
        token = self.service.create_token(
            offset=0,
            verb="ListIdentifiers",
            metadata_prefix="oai_dc"
        )

        # Parse with correct service
        is_valid, token_data, error = self.service.parse_token(token)
        assert is_valid

        # Parse with different secret key
        different_service = ResumptionTokenService(secret_key="different-secret")
        is_valid, token_data, error = different_service.parse_token(token)
        assert not is_valid
        assert "Invalid token signature" in error

    def test_token_tampering_detection(self):
        """Test detection of tampered tokens."""
        token = self.service.create_token(
            offset=0,
            verb="ListIdentifiers",
            metadata_prefix="oai_dc"
        )

        # Tamper with the token
        decoded_token = unquote(token)
        token_part, signature = decoded_token.rsplit(':', 1)

        # Decode and modify the data
        token_bytes = base64.b64decode(token_part.encode('ascii'))
        token_data = json.loads(token_bytes.decode('utf-8'))
        token_data["offset"] = 999  # Tamper with offset

        # Re-encode with original signature (should fail)
        tampered_json = json.dumps(token_data, sort_keys=True)
        tampered_bytes = tampered_json.encode('utf-8')
        tampered_b64 = base64.b64encode(tampered_bytes).decode('ascii')
        tampered_token = quote(f"{tampered_b64}:{signature}")

        is_valid, parsed_data, error = self.service.parse_token(tampered_token)

        assert not is_valid
        assert parsed_data is None
        assert "Invalid token signature" in error

    def test_hmac_timing_attack_protection(self):
        """Test that HMAC comparison uses constant-time comparison."""
        token = self.service.create_token(
            offset=0,
            verb="ListIdentifiers",
            metadata_prefix="oai_dc"
        )

        # Create token with wrong signature
        decoded_token = unquote(token)
        token_part, correct_signature = decoded_token.rsplit(':', 1)
        wrong_signature = "a" * len(correct_signature)
        wrong_token = quote(f"{token_part}:{wrong_signature}")

        # Should use hmac.compare_digest for constant-time comparison
        with patch('arkumu.oaipmh.resumption.hmac.compare_digest', return_value=False) as mock_compare:
            is_valid, token_data, error = self.service.parse_token(wrong_token)

            assert not is_valid
            mock_compare.assert_called_once()

    # ============================================================================
    # URL ENCODING TESTS
    # ============================================================================

    def test_token_url_encoding(self):
        """Test that tokens are properly URL-encoded."""
        token = self.service.create_token(
            offset=0,
            verb="ListIdentifiers",
            metadata_prefix="oai_dc"
        )

        # Token should be URL-encoded (no spaces, +, /, = without encoding)
        assert " " not in token
        decoded = unquote(token)
        assert len(decoded) > len(token) or "+" in decoded or "/" in decoded or "=" in decoded

        # Should parse correctly
        is_valid, token_data, error = self.service.parse_token(token)
        assert is_valid

    def test_token_with_special_characters(self):
        """Test tokens with special characters in parameters."""
        token = self.service.create_token(
            offset=0,
            verb="ListRecords",
            metadata_prefix="oai_dc",
            set_spec="special/set:name",
            from_date="2023-01-01T00:00:00+05:00"
        )

        is_valid, token_data, error = self.service.parse_token(token)

        assert is_valid
        assert token_data["set"] == "special/set:name"
        assert token_data["from"] == "2023-01-01T00:00:00+05:00"

    # ============================================================================
    # UTILITY METHOD TESTS
    # ============================================================================

    def test_get_next_offset(self):
        """Test get_next_offset utility method."""
        token_data = {
            "offset": 100,
            "page_size": 50
        }

        next_offset = self.service.get_next_offset(token_data)
        assert next_offset == 150

    def test_has_more_records_full_page(self):
        """Test has_more_records when full page is returned."""
        has_more = self.service.has_more_records(
            current_offset=0,
            page_size=100,
            total_fetched=100
        )
        assert has_more is True

    def test_has_more_records_partial_page(self):
        """Test has_more_records when partial page is returned."""
        has_more = self.service.has_more_records(
            current_offset=0,
            page_size=100,
            total_fetched=75
        )
        assert has_more is False

    # ============================================================================
    # CONFIGURATION TESTS
    # ============================================================================

    def test_custom_page_size(self):
        """Test service with custom page size."""
        service = ResumptionTokenService(page_size=250)
        token = service.create_token(
            offset=0,
            verb="ListIdentifiers",
            metadata_prefix="oai_dc"
        )

        is_valid, token_data, error = service.parse_token(token)

        assert is_valid
        assert token_data["page_size"] == 250

    def test_default_secret_key_fallback(self):
        """Test fallback to Django settings SECRET_KEY."""
        with patch('arkumu.oaipmh.resumption.settings') as mock_settings:
            mock_settings.SECRET_KEY = "django-secret-key"

            service = ResumptionTokenService()  # No secret_key provided
            assert service.secret_key == "django-secret-key"

    def test_no_secret_key_available(self):
        """Test behavior when no secret key is available."""
        with patch('arkumu.oaipmh.resumption.settings', spec=[]) as mock_settings:
            # Mock settings object without SECRET_KEY attribute
            with patch('arkumu.oaipmh.resumption.getattr', return_value='default-secret'):
                service = ResumptionTokenService()
                assert service.secret_key == "default-secret"

    # ============================================================================
    # EDGE CASE TESTS
    # ============================================================================

    def test_empty_resumption_token(self):
        """Test parsing empty or whitespace-only token."""
        for empty_token in ["", "   ", "\t", "\n"]:
            is_valid, token_data, error = self.service.parse_token(empty_token)
            assert not is_valid
            assert token_data is None
            assert error is not None

    def test_very_long_token(self):
        """Test handling of very long tokens."""
        # Create token with very long values
        long_set_spec = "a" * 1000
        token = self.service.create_token(
            offset=0,
            verb="ListIdentifiers",
            metadata_prefix="oai_dc",
            set_spec=long_set_spec
        )

        is_valid, token_data, error = self.service.parse_token(token)

        assert is_valid
        assert token_data["set"] == long_set_spec

    def test_token_with_unicode_characters(self):
        """Test tokens with Unicode characters."""
        token = self.service.create_token(
            offset=0,
            verb="ListRecords",
            metadata_prefix="oai_dc",
            set_spec="université_测试"
        )

        is_valid, token_data, error = self.service.parse_token(token)

        assert is_valid
        assert token_data["set"] == "université_测试"

    def test_token_round_trip_consistency(self):
        """Test that multiple create/parse cycles are consistent."""
        original_params = {
            "offset": 150,
            "verb": "ListRecords",
            "metadata_prefix": "mets",
            "set_spec": "test_set",
            "from_date": "2023-01-01T00:00:00Z",
            "until_date": "2023-12-31T23:59:59Z"
        }

        # Create token
        token1 = self.service.create_token(**original_params)

        # Parse and re-create
        is_valid, token_data, error = self.service.parse_token(token1)
        assert is_valid

        token2 = self.service.create_token(
            offset=token_data["offset"],
            verb=token_data["verb"],
            metadata_prefix=token_data["metadata_prefix"],
            set_spec=token_data.get("set"),
            from_date=token_data.get("from"),
            until_date=token_data.get("until")
        )

        # Parse second token
        is_valid2, token_data2, error2 = self.service.parse_token(token2)
        assert is_valid2

        # Core data should be identical (timestamps will differ)
        assert token_data2["offset"] == original_params["offset"]
        assert token_data2["verb"] == original_params["verb"]
        assert token_data2["metadata_prefix"] == original_params["metadata_prefix"]
        assert token_data2["set"] == original_params["set_spec"]
        assert token_data2["from"] == original_params["from_date"]
        assert token_data2["until"] == original_params["until_date"]


class TestTailoredResumptionTokenService:
    """Tailored service specific token guarantees."""

    def setup_method(self):
        self.service = TailoredResumptionTokenService(
            secret_key="test-tailored",
            page_size=5,
        )

    def test_tailored_tokens_include_profile_and_version(self):
        token = self.service.create_token(
            offset=5,
            verb="ListIdentifiers",
            metadata_prefix="oai_dc",
            cursor_marker="tailored-marker",
            cursor_position="2024-01-01T00:00:00+00:00|42",
        )

        is_valid, token_data, error = self.service.parse_token(token)

        assert is_valid
        assert error is None
        assert token_data["profile"] == "tailored"
        assert token_data["rt_version"] == 1
        assert token_data["cursor"] == "tailored-marker"
        assert token_data["cursor_position"] == "2024-01-01T00:00:00+00:00|42"

    def test_tailored_token_requires_cursor_marker(self):
        with pytest.raises(ValueError):
            self.service.create_token(
                offset=0,
                verb="ListRecords",
                metadata_prefix="mets",
            )

    def test_tailored_service_accepts_legacy_tokens_when_allowed(self):
        base_service = ResumptionTokenService(secret_key="shared", page_size=3)
        legacy_token = base_service.create_token(
            offset=0,
            verb="ListIdentifiers",
            metadata_prefix="oai_dc",
            cursor_marker="legacy-cursor",
        )

        compat_service = TailoredResumptionTokenService(
            secret_key="shared",
            page_size=3,
            accept_legacy_tokens=True,
        )
        is_valid, token_data, error = compat_service.parse_token(legacy_token)

        assert is_valid
        assert error is None
        assert token_data is not None
        assert token_data.get("cursor") == "legacy-cursor"

    def test_tailored_service_rejects_legacy_tokens_when_disallowed(self):
        base_service = ResumptionTokenService(secret_key="shared", page_size=3)
        legacy_token = base_service.create_token(
            offset=0,
            verb="ListIdentifiers",
            metadata_prefix="oai_dc",
            cursor_marker="legacy-cursor",
        )

        strict_service = TailoredResumptionTokenService(
            secret_key="shared",
            page_size=3,
            accept_legacy_tokens=False,
        )
        is_valid, token_data, error = strict_service.parse_token(legacy_token)

        assert not is_valid
        assert token_data is None
        assert error == "Tailored resumption token missing profile"

    def test_tailored_service_rejects_wrong_profile(self):
        token = self.service.create_token(
            offset=0,
            verb="ListIdentifiers",
            metadata_prefix="oai_dc",
            cursor_marker="tailored-marker",
            profile="other",
        )

        is_valid, token_data, error = self.service.parse_token(token)

        assert not is_valid
        assert token_data is None
        assert error == "Token profile does not match endpoint"

    def test_tailored_service_rejects_version_mismatch(self):
        token = self.service.create_token(
            offset=0,
            verb="ListRecords",
            metadata_prefix="oai_dc",
            cursor_marker="tailored-marker",
            rt_version=99,
        )

        is_valid, token_data, error = self.service.parse_token(token)

        assert not is_valid
        assert token_data is None
        assert error == "Unsupported tailored resumption token version"
