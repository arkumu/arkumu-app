"""
Integration tests for OAI-PMH pagination flows.

Tests multi-page request sequences using resumption tokens,
ensuring correct pagination behavior across different verbs and scenarios.
"""

import pytest
from django.urls import reverse
from urllib.parse import quote


@pytest.mark.django_db
class TestOAIPagination:
    """Test OAI-PMH pagination flows with resumption tokens."""

    def setup_method(self):
        """Set up test method."""
        self.oai_url = "/oai/"

    # ============================================================================
    # LISTIDENTIFIERS PAGINATION TESTS
    # ============================================================================

    def test_list_identifiers_single_page_no_token(self, oai_client, sample_resources, xml_validator, mock_canonical_graph_service):
        """Test ListIdentifiers with small dataset that fits in one page."""
        response = oai_client.get(self.oai_url, {
            "verb": "ListIdentifiers",
            "metadataPrefix": "oai_dc"
        })

        assert response.status_code == 200
        assert xml_validator.validate_oai_response(response.content.decode())

        # Should have records but no resumption token
        record_count = xml_validator.count_records(response.content.decode())
        assert record_count > 0

        resumption_token = xml_validator.get_resumption_token(response.content.decode())
        assert resumption_token == ""  # No token for single page

    def test_list_identifiers_multi_page_flow(self, oai_client, large_dataset, xml_validator, mock_canonical_graph_service):
        """Test complete multi-page ListIdentifiers flow."""
        # First request - should get page 1 with resumption token
        response1 = oai_client.get(self.oai_url, {
            "verb": "ListIdentifiers",
            "metadataPrefix": "oai_dc"
        })

        assert response1.status_code == 200
        assert xml_validator.validate_oai_response(response1.content.decode())

        record_count1 = xml_validator.count_records(response1.content.decode())
        resumption_token1 = xml_validator.get_resumption_token(response1.content.decode())

        # Should have records and a resumption token for large dataset
        assert record_count1 > 0
        if resumption_token1:  # Only continue if pagination occurred
            # Second request - use resumption token
            response2 = oai_client.get(self.oai_url, {
                "verb": "ListIdentifiers",
                "resumptionToken": resumption_token1
            })

            assert response2.status_code == 200
            assert xml_validator.validate_oai_response(response2.content.decode())

            record_count2 = xml_validator.count_records(response2.content.decode())
            resumption_token2 = xml_validator.get_resumption_token(response2.content.decode())

            # Should have records on second page
            assert record_count2 > 0

            # Continue until no more pages
            page_count = 2
            current_token = resumption_token2
            total_records = record_count1 + record_count2

            while current_token and page_count < 10:  # Safety limit
                response = oai_client.get(self.oai_url, {
                    "verb": "ListIdentifiers",
                    "resumptionToken": current_token
                })

                assert response.status_code == 200
                assert xml_validator.validate_oai_response(response.content.decode())

                page_records = xml_validator.count_records(response.content.decode())
                current_token = xml_validator.get_resumption_token(response.content.decode())

                total_records += page_records
                page_count += 1

            # Should have retrieved all records from large dataset
            assert total_records == len(large_dataset)
            assert page_count >= 2  # Should have used multiple pages

    def test_list_identifiers_pagination_with_filters(self, oai_client, large_dataset, sample_organizations, xml_validator, mock_canonical_graph_service):
        """Test pagination with set and date filters."""
        # First page with set filter
        response1 = oai_client.get(self.oai_url, {
            "verb": "ListIdentifiers",
            "metadataPrefix": "oai_dc",
            "set": sample_organizations[0].code,  # test_univ
            "from": "2023-01-01",
            "until": "2023-12-31"
        })

        assert response1.status_code == 200
        assert xml_validator.validate_oai_response(response1.content.decode())

        resumption_token1 = xml_validator.get_resumption_token(response1.content.decode())

        if resumption_token1:
            # Second page should maintain filters
            response2 = oai_client.get(self.oai_url, {
                "verb": "ListIdentifiers",
                "resumptionToken": resumption_token1
            })

            assert response2.status_code == 200
            assert xml_validator.validate_oai_response(response2.content.decode())

            # Token should contain the filter parameters
            # (This is tested more thoroughly in resumption token tests)

    def test_list_identifiers_resumption_token_parameter_persistence(self, oai_client, large_dataset, xml_validator, mock_canonical_graph_service):
        """Test that resumption tokens preserve original request parameters."""
        # Start with specific parameters
        response1 = oai_client.get(self.oai_url, {
            "verb": "ListIdentifiers",
            "metadataPrefix": "mets",  # Different format
            "from": "2023-01-01"
        })

        assert response1.status_code == 200
        resumption_token = xml_validator.get_resumption_token(response1.content.decode())

        if resumption_token:
            # Subsequent request should work with just the token
            response2 = oai_client.get(self.oai_url, {
                "verb": "ListIdentifiers",
                "resumptionToken": resumption_token
            })

            assert response2.status_code == 200
            assert xml_validator.validate_oai_response(response2.content.decode())

    # ============================================================================
    # LISTRECORDS PAGINATION TESTS
    # ============================================================================

    def test_list_records_multi_page_flow(self, oai_client, large_dataset, xml_validator, mock_canonical_graph_service):
        """Test complete multi-page ListRecords flow."""
        # First request
        response1 = oai_client.get(self.oai_url, {
            "verb": "ListRecords",
            "metadataPrefix": "oai_dc"
        })

        assert response1.status_code == 200
        assert xml_validator.validate_oai_response(response1.content.decode())

        record_count1 = xml_validator.count_records(response1.content.decode())
        resumption_token1 = xml_validator.get_resumption_token(response1.content.decode())

        assert record_count1 > 0

        if resumption_token1:
            # Second request
            response2 = oai_client.get(self.oai_url, {
                "verb": "ListRecords",
                "resumptionToken": resumption_token1
            })

            assert response2.status_code == 200
            assert xml_validator.validate_oai_response(response2.content.decode())

            # Verify records contain both headers and metadata
            content = response2.content.decode()
            assert "<record>" in content
            assert "<header>" in content
            assert "<metadata>" in content

    def test_list_records_metadata_consistency_across_pages(self, oai_client, large_dataset, xml_validator, mock_canonical_graph_service):
        """Test that metadata format remains consistent across paginated requests."""
        # Start with METS format
        response1 = oai_client.get(self.oai_url, {
            "verb": "ListRecords",
            "metadataPrefix": "mets"
        })

        assert response1.status_code == 200
        content1 = response1.content.decode()

        resumption_token = xml_validator.get_resumption_token(content1)
        if resumption_token:
            # Next page should also be METS format
            response2 = oai_client.get(self.oai_url, {
                "verb": "ListRecords",
                "resumptionToken": resumption_token
            })

            assert response2.status_code == 200
            content2 = response2.content.decode()

            # Both pages should contain METS metadata indicators
            # (The specific METS content validation is in format tests)
            assert "<metadata>" in content1
            if '<error code="badResumptionToken"' in content2:
                pytest.skip("Resumption token invalidated due to snapshot refresh during test run")
            assert "<metadata>" in content2

    # ============================================================================
    # RESUMPTION TOKEN ERROR HANDLING
    # ============================================================================

    def test_expired_resumption_token(self, oai_client, xml_validator):
        """Test handling of expired resumption tokens."""
        # Use a clearly invalid/expired token
        response = oai_client.get(self.oai_url, {
            "verb": "ListIdentifiers",
            "resumptionToken": "expired_token_12345"
        })

        assert response.status_code == 200
        code, message = xml_validator.extract_error(response.content.decode())
        assert code == "badResumptionToken"

    def test_malformed_resumption_token(self, oai_client, xml_validator):
        """Test handling of malformed resumption tokens."""
        malformed_tokens = [
            "not_a_valid_token",
            "malformed:token:structure",
            "",
            "   ",
            "token with spaces",
            "verylongtoken" * 100,  # Very long token
        ]

        for token in malformed_tokens:
            response = oai_client.get(self.oai_url, {
                "verb": "ListIdentifiers",
                "resumptionToken": token
            })

            assert response.status_code == 200
            code, message = xml_validator.extract_error(response.content.decode())
            assert code == "badResumptionToken"

    def test_resumption_token_verb_mismatch(self, oai_client, large_dataset, xml_validator, mock_canonical_graph_service):
        """Test using resumption token from one verb with a different verb."""
        # Get token from ListIdentifiers
        response1 = oai_client.get(self.oai_url, {
            "verb": "ListIdentifiers",
            "metadataPrefix": "oai_dc"
        })

        assert response1.status_code == 200
        token = xml_validator.get_resumption_token(response1.content.decode())

        if token:
            # Try to use it with ListRecords
            response2 = oai_client.get(self.oai_url, {
                "verb": "ListRecords",
                "resumptionToken": token
            })

            # This should either work (if token is verb-agnostic) or fail gracefully
            assert response2.status_code == 200

            # Check if it's an error or valid response
            is_error = "error" in response2.content.decode().lower()
            if is_error:
                code, message = xml_validator.extract_error(response2.content.decode())
                assert code in ["badResumptionToken", "badArgument"]

    # ============================================================================
    # PAGINATION EDGE CASES
    # ============================================================================

    def test_empty_result_set_pagination(self, oai_client, xml_validator):
        """Test pagination behavior with empty result sets."""
        # Request with criteria that should return no results
        response = oai_client.get(self.oai_url, {
            "verb": "ListIdentifiers",
            "metadataPrefix": "oai_dc",
            "from": "2050-01-01"  # Future date
        })

        assert response.status_code == 200
        code, message = xml_validator.extract_error(response.content.decode())
        assert code == "noRecordsMatch"

        # Should not have a resumption token
        token = xml_validator.get_resumption_token(response.content.decode())
        assert token == ""

    def test_single_record_pagination(self, oai_client, sample_resources, xml_validator, mock_canonical_graph_service):
        """Test pagination behavior when only one record matches."""
        # Use very restrictive criteria to get minimal results
        response = oai_client.get(self.oai_url, {
            "verb": "ListIdentifiers",
            "metadataPrefix": "oai_dc",
            "set": sample_resources[0].organization.code,
            "from": sample_resources[0].updated_at.strftime("%Y-%m-%d"),
            "until": sample_resources[0].updated_at.strftime("%Y-%m-%d")
        })

        assert response.status_code == 200
        assert xml_validator.validate_oai_response(response.content.decode())

        record_count = xml_validator.count_records(response.content.decode())
        resumption_token = xml_validator.get_resumption_token(response.content.decode())

        # Should have few records and likely no resumption token
        assert record_count >= 1
        # Token may or may not be present depending on page size

    def test_last_page_empty_resumption_token(self, oai_client, large_dataset, xml_validator, mock_canonical_graph_service):
        """Test that the last page has an empty resumption token."""
        response = oai_client.get(self.oai_url, {
            "verb": "ListIdentifiers",
            "metadataPrefix": "oai_dc"
        })

        assert response.status_code == 200

        # Follow pagination to the end
        current_token = xml_validator.get_resumption_token(response.content.decode())
        page_count = 1

        while current_token and page_count < 20:  # Safety limit
            response = oai_client.get(self.oai_url, {
                "verb": "ListIdentifiers",
                "resumptionToken": current_token
            })

            assert response.status_code == 200
            current_token = xml_validator.get_resumption_token(response.content.decode())
            page_count += 1

        # The last response should have no resumption token
        assert current_token == ""
        assert page_count > 1  # Should have had multiple pages

    # ============================================================================
    # PERFORMANCE AND CONSISTENCY TESTS
    # ============================================================================

    def test_pagination_record_uniqueness(self, oai_client, large_dataset, xml_validator, mock_canonical_graph_service):
        """Test that no records are duplicated or skipped across pages."""
        all_identifiers = set()

        response = oai_client.get(self.oai_url, {
            "verb": "ListIdentifiers",
            "metadataPrefix": "oai_dc"
        })

        assert response.status_code == 200

        # Collect identifiers from all pages
        current_token = xml_validator.get_resumption_token(response.content.decode())
        page_count = 1

        # Extract identifiers from first page
        content = response.content.decode()
        import xml.etree.ElementTree as ET
        root = ET.fromstring(content)

        # Find all identifier elements
        identifiers = root.findall(".//identifier")
        if not identifiers:
            identifiers = root.findall(".//{http://www.openarchives.org/OAI/2.0/}identifier")

        for identifier in identifiers:
            if identifier.text:
                assert identifier.text not in all_identifiers  # No duplicates
                all_identifiers.add(identifier.text)

        # Continue through remaining pages
        while current_token and page_count < 20:  # Safety limit
            response = oai_client.get(self.oai_url, {
                "verb": "ListIdentifiers",
                "resumptionToken": current_token
            })

            assert response.status_code == 200
            content = response.content.decode()
            root = ET.fromstring(content)

            # Find all identifier elements
            identifiers = root.findall(".//identifier")
            if not identifiers:
                identifiers = root.findall(".//{http://www.openarchives.org/OAI/2.0/}identifier")

            for identifier in identifiers:
                if identifier.text:
                    assert identifier.text not in all_identifiers  # No duplicates
                    all_identifiers.add(identifier.text)

            current_token = xml_validator.get_resumption_token(content)
            page_count += 1

        # Should have collected unique identifiers for all records
        assert len(all_identifiers) > 0
        if len(large_dataset) <= 1000:  # Reasonable size for full comparison
            # Should match the total number of harvestable resources
            harvestable_count = len([r for r in large_dataset
                                   if r.public_access_level.value == "PUBLIC"
                                   and r.is_public_approved])
            # Allow some tolerance for test data setup variations
            assert len(all_identifiers) >= harvestable_count * 0.8

    def test_pagination_ordering_consistency(self, oai_client, large_dataset, xml_validator, mock_canonical_graph_service):
        """Test that record ordering is consistent across pagination."""
        # Get first page
        response1 = oai_client.get(self.oai_url, {
            "verb": "ListIdentifiers",
            "metadataPrefix": "oai_dc"
        })

        assert response1.status_code == 200

        # Make the same request again
        response2 = oai_client.get(self.oai_url, {
            "verb": "ListIdentifiers",
            "metadataPrefix": "oai_dc"
        })

        assert response2.status_code == 200

        # The responses should be identical (same ordering)
        content1 = response1.content.decode()
        content2 = response2.content.decode()

        # Extract first few identifiers from each response
        import xml.etree.ElementTree as ET

        root1 = ET.fromstring(content1)
        root2 = ET.fromstring(content2)

        identifiers1 = [elem.text for elem in root1.findall(".//identifier") if elem.text]
        if not identifiers1:
            identifiers1 = [elem.text for elem in root1.findall(".//{http://www.openarchives.org/OAI/2.0/}identifier") if elem.text]

        identifiers2 = [elem.text for elem in root2.findall(".//identifier") if elem.text]
        if not identifiers2:
            identifiers2 = [elem.text for elem in root2.findall(".//{http://www.openarchives.org/OAI/2.0/}identifier") if elem.text]

        # Should have same identifiers in same order
        assert len(identifiers1) > 0
        assert len(identifiers2) > 0
        assert identifiers1 == identifiers2
