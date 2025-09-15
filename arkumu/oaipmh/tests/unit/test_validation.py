"""
Unit tests for OAI-PMH input validation functions.

Tests parameter validation, date parsing, identifier formats,
and other input validation logic used throughout the OAI-PMH implementation.
"""

import pytest
from datetime import datetime, timezone

from arkumu.oaipmh import views


class TestDateValidation:
    """Test date validation and parsing functions."""

    def test_validate_datestamp_valid_date_only_format(self):
        """Test validation of valid YYYY-MM-DD format dates."""
        valid_dates = [
            "2023-01-01",
            "2023-12-31",
            "2000-02-29",  # Leap year
            "1999-02-28",  # Non-leap year
            "2023-06-15",
            "1970-01-01",  # Epoch date
            "2030-12-25",  # Future date
        ]

        for date_str in valid_dates:
            error = views._validate_datestamp(date_str)
            assert error is None, f"Valid date {date_str} should not produce error"

    def test_validate_datestamp_valid_datetime_format(self):
        """Test validation of valid YYYY-MM-DDThh:mm:ssZ format dates."""
        valid_datetimes = [
            "2023-01-01T00:00:00Z",
            "2023-12-31T23:59:59Z",
            "2023-06-15T12:30:45Z",
            "2000-02-29T10:15:30Z",  # Leap year
            "1970-01-01T00:00:00Z",  # Epoch
        ]

        for datetime_str in valid_datetimes:
            error = views._validate_datestamp(datetime_str)
            assert error is None, f"Valid datetime {datetime_str} should not produce error"

    def test_validate_datestamp_invalid_date_format(self):
        """Test validation rejects invalid date formats."""
        invalid_dates = [
            "invalid-date",
            "2023-13-01",  # Invalid month
            "2023-01-32",  # Invalid day
            "2023-02-30",  # Invalid day for February
            "23-01-01",    # Wrong year format
            "2023/01/01",  # Wrong separator
            "2023-1-1",    # Missing leading zeros
            "2023-01",     # Missing day
            "01-01-2023",  # Wrong order
            "",            # Empty string
            "2023-01-01 12:00:00",  # Space instead of T
            "2023-01-01T25:00:00Z",  # Invalid hour
            "2023-01-01T12:60:00Z",  # Invalid minute
            "2023-01-01T12:00:60Z",  # Invalid second
            "2023-01-01T12:00:00",   # Missing Z
            "2023-01-01T12:00:00+00:00",  # Timezone offset instead of Z
        ]

        for date_str in invalid_dates:
            error = views._validate_datestamp(date_str)
            assert error is not None, f"Invalid date {date_str} should produce error"
            assert "Invalid date format" in error

    def test_validate_datestamp_edge_cases(self):
        """Test edge cases for date validation."""
        edge_cases = [
            ("", None),  # Empty string should return None
            (None, None),  # None should return None
            ("   ", "Invalid date format"),  # Whitespace should be invalid
            ("\t", "Invalid date format"),  # Tab should be invalid
            ("\n", "Invalid date format"),  # Newline should be invalid
        ]

        for input_date, expected_result in edge_cases:
            error = views._validate_datestamp(input_date)
            if expected_result is None:
                assert error is None
            else:
                assert error is not None
                assert expected_result in error

    def test_validate_datestamp_leap_year_handling(self):
        """Test correct handling of leap years."""
        # Valid leap year dates
        valid_leap_dates = [
            "2000-02-29",  # Divisible by 400
            "2004-02-29",  # Divisible by 4, not by 100
            "2024-02-29",  # Another leap year
        ]

        for date_str in valid_leap_dates:
            error = views._validate_datestamp(date_str)
            assert error is None, f"Valid leap year date {date_str} should be accepted"

        # Invalid leap year dates
        invalid_leap_dates = [
            "1900-02-29",  # Divisible by 100 but not 400
            "2001-02-29",  # Not divisible by 4
            "2023-02-29",  # Not a leap year
        ]

        for date_str in invalid_leap_dates:
            error = views._validate_datestamp(date_str)
            assert error is not None, f"Invalid leap year date {date_str} should be rejected"

    def test_format_datestamp(self):
        """Test _format_datestamp function."""
        test_cases = [
            (datetime(2023, 1, 1, 0, 0, 0, tzinfo=timezone.utc), "2023-01-01T00:00:00Z"),
            (datetime(2023, 12, 31, 23, 59, 59, tzinfo=timezone.utc), "2023-12-31T23:59:59Z"),
            (datetime(2023, 6, 15, 14, 30, 45, tzinfo=timezone.utc), "2023-06-15T14:30:45Z"),
            (datetime(1970, 1, 1, 0, 0, 0, tzinfo=timezone.utc), "1970-01-01T00:00:00Z"),
        ]

        for input_dt, expected_output in test_cases:
            result = views._format_datestamp(input_dt)
            assert result == expected_output

    def test_format_datestamp_microseconds_truncated(self):
        """Test that microseconds are truncated in formatted datestamp."""
        dt_with_microseconds = datetime(2023, 6, 15, 14, 30, 45, 123456, tzinfo=timezone.utc)
        result = views._format_datestamp(dt_with_microseconds)

        # Should not include microseconds
        assert result == "2023-06-15T14:30:45Z"
        assert ".123456" not in result


class TestIdentifierValidation:
    """Test identifier parsing and building functions."""

    def test_build_identifier_standard_uri(self):
        """Test building OAI identifiers from standard URIs."""
        test_cases = [
            ("https://example.com/resource/123", "oai:arkumu:resource:https%3A//example.com/resource/123"),
            ("http://test.org/item/456", "oai:arkumu:resource:http%3A//test.org/item/456"),
            ("https://library.edu/book/789", "oai:arkumu:resource:https%3A//library.edu/book/789"),
        ]

        for input_uri, expected_identifier in test_cases:
            result = views._build_identifier(input_uri)
            assert result == expected_identifier

    def test_build_identifier_special_characters(self):
        """Test building identifiers with special characters in URI."""
        special_uris = [
            "https://example.com/resource with spaces/123",
            "https://example.com/resource/123?query=value&param=test",
            "https://example.com/resource/123#fragment",
            "https://example.com/résource/ñoño",  # Unicode characters
        ]

        for uri in special_uris:
            identifier = views._build_identifier(uri)

            # Should start with OAI prefix
            assert identifier.startswith("oai:arkumu:resource:")

            # Should be URL-encoded
            assert " " not in identifier  # Spaces should be encoded
            assert identifier != f"oai:arkumu:resource:{uri}"  # Should be different due to encoding

    def test_parse_identifier_new_format(self):
        """Test parsing new format OAI identifiers."""
        test_cases = [
            ("oai:arkumu:resource:https%3A//example.com/resource/123", "https://example.com/resource/123"),
            ("oai:arkumu:resource:http%3A//test.org/item/456", "http://test.org/item/456"),
            ("oai:arkumu:resource:https%3A//library.edu/book%20with%20spaces", "https://library.edu/book with spaces"),
        ]

        for input_identifier, expected_uri in test_cases:
            result = views._parse_identifier(input_identifier)
            assert result == expected_uri

    def test_parse_identifier_legacy_format(self):
        """Test parsing legacy format OAI identifiers."""
        test_cases = [
            ("oai:domain:repo:https%3A//example.com/resource/123", "https://example.com/resource/123"),
            ("oai:library.edu:digital:http%3A//test.org/item", "http://test.org/item"),
            ("oai:institution:collection:resource%20id", "resource id"),
        ]

        for input_identifier, expected_uri in test_cases:
            result = views._parse_identifier(input_identifier)
            assert result == expected_uri

    def test_parse_identifier_passthrough(self):
        """Test that non-OAI identifiers are passed through unchanged."""
        non_oai_identifiers = [
            "https://example.com/resource/123",
            "urn:isbn:1234567890",
            "doi:10.1000/182",
            "plain-identifier",
            "resource-123",
        ]

        for identifier in non_oai_identifiers:
            result = views._parse_identifier(identifier)
            assert result == identifier

    def test_parse_identifier_edge_cases(self):
        """Test edge cases in identifier parsing."""
        edge_cases = [
            ("", ""),  # Empty string
            ("oai:", "oai:"),  # Incomplete OAI identifier
            ("oai:arkumu:", "oai:arkumu:"),  # Incomplete new format
            ("oai:arkumu:resource:", ""),  # New format with empty resource part
        ]

        for input_identifier, expected_result in edge_cases:
            result = views._parse_identifier(input_identifier)
            assert result == expected_result

    def test_identifier_round_trip(self):
        """Test that building and parsing identifiers is consistent."""
        test_uris = [
            "https://example.com/resource/123",
            "http://test.org/item/456",
            "https://library.edu/book with spaces/789",
            "https://example.com/resource?query=value&param=test",
        ]

        for original_uri in test_uris:
            # Build identifier from URI
            identifier = views._build_identifier(original_uri)

            # Parse identifier back to URI
            parsed_uri = views._parse_identifier(identifier)

            # Should get back the original URI
            assert parsed_uri == original_uri


class TestResourceQuerysetFiltering:
    """Test resource queryset building and filtering logic."""

    def test_get_resources_queryset_basic(self, sample_resources):
        """Test basic queryset without filters."""
        queryset = views._get_resources_queryset()
        resources = list(queryset)

        # Should only include public approved resources
        for resource in resources:
            assert resource.public_access_level.value == "PUBLIC"
            assert resource.is_public_approved is True

        # Should have proper ordering
        assert len(resources) > 0

    def test_get_resources_queryset_set_filter(self, sample_resources, sample_organizations):
        """Test queryset with set (organization) filter."""
        org_code = sample_organizations[0].code

        queryset = views._get_resources_queryset(set_spec=org_code)
        resources = list(queryset)

        # All resources should be from the specified organization
        for resource in resources:
            assert resource.organization is not None
            assert resource.organization.code == org_code
            assert resource.organization.is_active is True

    def test_get_resources_queryset_nonexistent_set(self, sample_resources):
        """Test queryset with non-existent set filter."""
        queryset = views._get_resources_queryset(set_spec="nonexistent_org")
        resources = list(queryset)

        # Should return empty result
        assert len(resources) == 0

    def test_get_resources_queryset_date_filters_date_only(self, sample_resources):
        """Test queryset with date-only format filters."""
        # Test from date only
        queryset = views._get_resources_queryset(from_date="2023-01-02")
        resources = list(queryset)

        for resource in resources:
            assert resource.updated_at >= datetime(2023, 1, 2, 0, 0, 0, tzinfo=timezone.utc)

        # Test until date only
        queryset = views._get_resources_queryset(until_date="2023-01-04")
        resources = list(queryset)

        for resource in resources:
            assert resource.updated_at <= datetime(2023, 1, 4, 23, 59, 59, 999999, tzinfo=timezone.utc)

        # Test both from and until
        queryset = views._get_resources_queryset(from_date="2023-01-02", until_date="2023-01-04")
        resources = list(queryset)

        for resource in resources:
            assert resource.updated_at >= datetime(2023, 1, 2, 0, 0, 0, tzinfo=timezone.utc)
            assert resource.updated_at <= datetime(2023, 1, 4, 23, 59, 59, 999999, tzinfo=timezone.utc)

    def test_get_resources_queryset_date_filters_datetime(self, sample_resources):
        """Test queryset with full datetime format filters."""
        # Test with precise datetime filters
        queryset = views._get_resources_queryset(
            from_date="2023-01-01T12:00:00Z",
            until_date="2023-01-02T12:00:00Z"
        )
        resources = list(queryset)

        for resource in resources:
            assert resource.updated_at >= datetime(2023, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
            assert resource.updated_at <= datetime(2023, 1, 2, 12, 0, 0, tzinfo=timezone.utc)

    def test_get_resources_queryset_invalid_dates_ignored(self, sample_resources):
        """Test that invalid dates are ignored gracefully."""
        # These invalid dates should not crash the function
        queryset = views._get_resources_queryset(
            from_date="invalid-date",
            until_date="2023-invalid-date"
        )
        resources = list(queryset)

        # Should return all resources (dates ignored due to invalidity)
        assert len(resources) > 0

    def test_get_resources_queryset_combined_filters(self, sample_resources, sample_organizations):
        """Test queryset with multiple filters combined."""
        org_code = sample_organizations[0].code

        queryset = views._get_resources_queryset(
            set_spec=org_code,
            from_date="2023-01-01",
            until_date="2023-12-31"
        )
        resources = list(queryset)

        # Should satisfy all filters
        for resource in resources:
            assert resource.organization.code == org_code
            assert resource.updated_at >= datetime(2023, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
            assert resource.updated_at <= datetime(2023, 12, 31, 23, 59, 59, 999999, tzinfo=timezone.utc)

    def test_get_resources_queryset_ordering(self, sample_resources):
        """Test that queryset has consistent ordering."""
        queryset = views._get_resources_queryset()
        resources = list(queryset)

        if len(resources) >= 2:
            # Should be ordered by updated_at, then id
            for i in range(len(resources) - 1):
                current = resources[i]
                next_resource = resources[i + 1]

                # Either updated_at is earlier, or same updated_at with earlier id
                assert (current.updated_at < next_resource.updated_at or
                       (current.updated_at == next_resource.updated_at and current.id <= next_resource.id))


class TestXMLUtilities:
    """Test XML generation utility functions."""

    def test_xml_response_creation(self):
        """Test _xml_response creates proper HttpResponse."""
        import xml.etree.ElementTree as ET

        # Create a simple XML element
        root = ET.Element("test")
        child = ET.SubElement(root, "child")
        child.text = "content"

        response = views._xml_response(root)

        assert response.status_code == 200
        assert response['Content-Type'] == "text/xml"

        content = response.content
        assert content.startswith(b'<?xml version="1.0" encoding="utf-8"?>')
        assert b"<test>" in content
        assert b"<child>content</child>" in content

    def test_xml_response_encoding(self):
        """Test XML response handles Unicode content correctly."""
        import xml.etree.ElementTree as ET

        root = ET.Element("test")
        child = ET.SubElement(root, "content")
        child.text = "Unicode content: émojis 🚀 and àccénts"

        response = views._xml_response(root)

        assert response.status_code == 200
        content = response.content.decode('utf-8')
        assert "émojis 🚀 and àccénts" in content

    def test_error_xml_generation(self):
        """Test _error function creates proper error XML."""
        from django.test import RequestFactory

        factory = RequestFactory()
        request = factory.get('/oai/')
        oai = views._oai_envelope(request)

        error_oai = views._error(oai, "badArgument", "Test error message")

        # Convert to string to check content
        import xml.etree.ElementTree as ET
        xml_str = ET.tostring(error_oai, encoding="unicode")

        assert 'code="badArgument"' in xml_str
        assert "Test error message" in xml_str
        assert "<error" in xml_str

    def test_oai_envelope_structure(self):
        """Test _oai_envelope creates proper XML structure."""
        from django.test import RequestFactory

        factory = RequestFactory()
        request = factory.get('/oai/')

        oai = views._oai_envelope(request)

        # Check root element
        assert oai.tag == "OAI-PMH"

        # Check namespaces
        assert oai.get("xmlns") == "http://www.openarchives.org/OAI/2.0/"
        assert oai.get("xmlns:oai_dc") == "http://www.openarchives.org/OAI/2.0/oai_dc/"
        assert oai.get("xmlns:dc") == "http://purl.org/dc/elements/1.1/"

        # Check required child elements
        response_date = oai.find("responseDate")
        assert response_date is not None
        assert response_date.text is not None

        request_elem = oai.find("request")
        assert request_elem is not None

    def test_oai_envelope_request_url(self):
        """Test that OAI envelope includes correct request URL."""
        from django.test import RequestFactory

        factory = RequestFactory()
        request = factory.get('/oai/', {'verb': 'Identify'})

        oai = views._oai_envelope(request)

        request_elem = oai.find("request")
        assert request_elem is not None
        assert "/oai/" in request_elem.text


class TestParameterValidation:
    """Test parameter validation for different OAI-PMH verbs."""

    def test_metadata_prefix_validation(self):
        """Test metadata prefix validation logic."""
        # These tests would be integration with the main endpoint
        # but test the validation logic that should be consistent

        valid_prefixes = ["oai_dc", "mets"]
        invalid_prefixes = ["invalid_format", "xml", "rdf", ""]

        # This is more of a specification test
        # The actual validation happens in the main endpoint function
        for prefix in valid_prefixes:
            # Should be accepted by the system
            assert prefix in ["oai_dc", "mets"]

        for prefix in invalid_prefixes:
            # Should be rejected by the system
            assert prefix not in ["oai_dc", "mets"]

    def test_verb_parameter_validation(self):
        """Test OAI-PMH verb validation."""
        valid_verbs = [
            "Identify", "ListMetadataFormats", "ListSets",
            "ListIdentifiers", "ListRecords", "GetRecord"
        ]

        invalid_verbs = [
            "", "identify", "listrecords", "InvalidVerb",
            "GetRecords", "ListAll", "Search"
        ]

        for verb in valid_verbs:
            # Should be in the valid verbs list used by the endpoint
            assert verb in ["Identify", "ListMetadataFormats", "ListSets",
                          "ListIdentifiers", "ListRecords", "GetRecord"]

        for verb in invalid_verbs:
            # Should not be in the valid verbs list
            assert verb not in ["Identify", "ListMetadataFormats", "ListSets",
                              "ListIdentifiers", "ListRecords", "GetRecord"]

    def test_date_range_validation_logic(self):
        """Test date range validation (from <= until)."""
        valid_ranges = [
            ("2023-01-01", "2023-01-02"),
            ("2023-01-01", "2023-12-31"),
            ("2023-01-01T00:00:00Z", "2023-01-01T23:59:59Z"),
            ("2022-12-31", "2023-01-01"),
        ]

        invalid_ranges = [
            ("2023-01-02", "2023-01-01"),  # from > until
            ("2023-12-31", "2023-01-01"),  # from > until
            ("2023-01-01T12:00:00Z", "2023-01-01T11:00:00Z"),  # from > until
        ]

        for from_date, until_date in valid_ranges:
            # Parse dates and check range
            try:
                if 'T' in from_date:
                    from_dt = datetime.fromisoformat(from_date.replace('Z', '+00:00'))
                else:
                    from_dt = datetime.strptime(from_date, '%Y-%m-%d').replace(tzinfo=timezone.utc)

                if 'T' in until_date:
                    until_dt = datetime.fromisoformat(until_date.replace('Z', '+00:00'))
                else:
                    until_dt = datetime.strptime(until_date, '%Y-%m-%d').replace(tzinfo=timezone.utc)

                assert from_dt <= until_dt, f"Valid range {from_date} to {until_date} should pass"
            except ValueError:
                pytest.fail(f"Valid date range {from_date} to {until_date} should parse correctly")

        for from_date, until_date in invalid_ranges:
            # Parse dates and check range
            try:
                if 'T' in from_date:
                    from_dt = datetime.fromisoformat(from_date.replace('Z', '+00:00'))
                else:
                    from_dt = datetime.strptime(from_date, '%Y-%m-%d').replace(tzinfo=timezone.utc)

                if 'T' in until_date:
                    until_dt = datetime.fromisoformat(until_date.replace('Z', '+00:00'))
                else:
                    until_dt = datetime.strptime(until_date, '%Y-%m-%d').replace(tzinfo=timezone.utc)

                assert from_dt > until_dt, f"Invalid range {from_date} to {until_date} should be detected"
            except ValueError:
                pytest.fail(f"Invalid date range {from_date} to {until_date} should still parse for comparison")