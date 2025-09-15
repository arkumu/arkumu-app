"""
Integration tests for the OAI-PMH HTTP endpoint.

Tests complete request/response cycle for all OAI-PMH verbs
following the OAI-PMH 2.0 specification.
"""

import pytest
from django.urls import reverse
from urllib.parse import quote


@pytest.mark.django_db
class TestOAIEndpoint:
    """Test OAI-PMH HTTP endpoint with all verbs and error conditions."""

    def setup_method(self):
        """Set up test method."""
        self.oai_url = "/oai/"

    # ============================================================================
    # IDENTIFY VERB TESTS
    # ============================================================================

    def test_identify_success(self, oai_client, xml_validator):
        """Test successful Identify request."""
        response = oai_client.get(self.oai_url, {"verb": "Identify"})

        assert response.status_code == 200
        assert response["Content-Type"] == "text/xml"
        assert xml_validator.validate_oai_response(response.content.decode())

        # Check for required Identify elements
        content = response.content.decode()
        assert "<Identify>" in content
        assert "<repositoryName>Arkumu Repository</repositoryName>" in content
        assert "<baseURL>/oai/</baseURL>" in content
        assert "<protocolVersion>2.0</protocolVersion>" in content
        assert "<adminEmail>admin@example.org</adminEmail>" in content
        assert "<earliestDatestamp>1970-01-01T00:00:00Z</earliestDatestamp>" in content
        assert "<deletedRecord>no</deletedRecord>" in content
        assert "<granularity>YYYY-MM-DDThh:mm:ssZ</granularity>" in content

    def test_identify_with_extra_parameters(self, oai_client, xml_validator):
        """Test Identify with illegal extra parameters."""
        response = oai_client.get(self.oai_url, {
            "verb": "Identify",
            "metadataPrefix": "oai_dc"  # Illegal for Identify
        })

        assert response.status_code == 200
        code, message = xml_validator.extract_error(response.content.decode())
        assert code == "badArgument"
        assert "Illegal argument(s): metadataPrefix" in message

    # ============================================================================
    # LISTMETADATAFORMATS VERB TESTS
    # ============================================================================

    def test_list_metadata_formats_success(self, oai_client, xml_validator):
        """Test successful ListMetadataFormats request."""
        response = oai_client.get(self.oai_url, {"verb": "ListMetadataFormats"})

        assert response.status_code == 200
        assert xml_validator.validate_oai_response(response.content.decode())

        content = response.content.decode()
        assert "<ListMetadataFormats>" in content
        assert "<metadataFormat>" in content

        # Check for Dublin Core format (mandatory)
        assert "<metadataPrefix>oai_dc</metadataPrefix>" in content
        assert "http://www.openarchives.org/OAI/2.0/oai_dc.xsd" in content
        assert "http://www.openarchives.org/OAI/2.0/oai_dc/" in content

        # Check for METS format
        assert "<metadataPrefix>mets</metadataPrefix>" in content
        assert "http://www.loc.gov/standards/mets/mets.xsd" in content

    def test_list_metadata_formats_with_identifier(self, oai_client, sample_resources, xml_validator):
        """Test ListMetadataFormats with valid identifier parameter."""
        resource = sample_resources[0]  # First public resource
        identifier = f"oai:arkumu:resource:{quote(resource.uri)}"

        response = oai_client.get(self.oai_url, {
            "verb": "ListMetadataFormats",
            "identifier": identifier
        })

        assert response.status_code == 200
        assert xml_validator.validate_oai_response(response.content.decode())

    def test_list_metadata_formats_invalid_identifier(self, oai_client, xml_validator):
        """Test ListMetadataFormats with non-existent identifier."""
        response = oai_client.get(self.oai_url, {
            "verb": "ListMetadataFormats",
            "identifier": "oai:arkumu:resource:https://nonexistent.example.com"
        })

        assert response.status_code == 200
        code, message = xml_validator.extract_error(response.content.decode())
        assert code == "idDoesNotExist"

    # ============================================================================
    # LISTSETS VERB TESTS
    # ============================================================================

    def test_list_sets_success(self, oai_client, sample_organizations, xml_validator):
        """Test successful ListSets request."""
        response = oai_client.get(self.oai_url, {"verb": "ListSets"})

        assert response.status_code == 200
        assert xml_validator.validate_oai_response(response.content.decode())

        content = response.content.decode()
        assert "<ListSets>" in content
        assert "<set>" in content

        # Check for active organizations only
        assert "<setSpec>test_univ</setSpec>" in content
        assert "<setName>Test University Library</setName>" in content
        assert "<setSpec>research_inst</setSpec>" in content
        assert "<setName>Research Institute</setName>" in content

        # Inactive organization should not appear
        assert "inactive_org" not in content

    def test_list_sets_with_illegal_arguments(self, oai_client, xml_validator):
        """Test ListSets with illegal arguments."""
        response = oai_client.get(self.oai_url, {
            "verb": "ListSets",
            "metadataPrefix": "oai_dc"  # Illegal for ListSets
        })

        assert response.status_code == 200
        code, message = xml_validator.extract_error(response.content.decode())
        assert code == "badArgument"

    # ============================================================================
    # LISTIDENTIFIERS VERB TESTS
    # ============================================================================

    def test_list_identifiers_success(self, oai_client, sample_resources, xml_validator, mock_canonical_graph_service):
        """Test successful ListIdentifiers request."""
        response = oai_client.get(self.oai_url, {
            "verb": "ListIdentifiers",
            "metadataPrefix": "oai_dc"
        })

        assert response.status_code == 200
        assert xml_validator.validate_oai_response(response.content.decode())

        content = response.content.decode()
        assert "<ListIdentifiers>" in content
        assert "<header>" in content
        assert "<identifier>" in content
        assert "<datestamp>" in content

        # Should only include public approved resources
        record_count = xml_validator.count_records(response.content.decode())
        assert record_count == 6  # 5 from test_univ + 1 from research_inst

    def test_list_identifiers_missing_metadata_prefix(self, oai_client, xml_validator):
        """Test ListIdentifiers without required metadataPrefix."""
        response = oai_client.get(self.oai_url, {"verb": "ListIdentifiers"})

        assert response.status_code == 200
        code, message = xml_validator.extract_error(response.content.decode())
        assert code == "badArgument"
        assert "metadataPrefix is required" in message

    def test_list_identifiers_invalid_metadata_prefix(self, oai_client, xml_validator):
        """Test ListIdentifiers with unsupported metadataPrefix."""
        response = oai_client.get(self.oai_url, {
            "verb": "ListIdentifiers",
            "metadataPrefix": "unsupported_format"
        })

        assert response.status_code == 200
        code, message = xml_validator.extract_error(response.content.decode())
        assert code == "cannotDisseminateFormat"

    def test_list_identifiers_with_set_filter(self, oai_client, sample_resources, xml_validator, mock_canonical_graph_service):
        """Test ListIdentifiers with set parameter."""
        response = oai_client.get(self.oai_url, {
            "verb": "ListIdentifiers",
            "metadataPrefix": "oai_dc",
            "set": "test_univ"
        })

        assert response.status_code == 200
        assert xml_validator.validate_oai_response(response.content.decode())

        # Should only include resources from test_univ organization
        record_count = xml_validator.count_records(response.content.decode())
        assert record_count == 5

    def test_list_identifiers_with_date_filter(self, oai_client, sample_resources, xml_validator, mock_canonical_graph_service):
        """Test ListIdentifiers with from/until date parameters."""
        response = oai_client.get(self.oai_url, {
            "verb": "ListIdentifiers",
            "metadataPrefix": "oai_dc",
            "from": "2023-01-02",
            "until": "2023-01-04"
        })

        assert response.status_code == 200
        assert xml_validator.validate_oai_response(response.content.decode())

    def test_list_identifiers_invalid_date_format(self, oai_client, xml_validator):
        """Test ListIdentifiers with invalid date format."""
        response = oai_client.get(self.oai_url, {
            "verb": "ListIdentifiers",
            "metadataPrefix": "oai_dc",
            "from": "invalid-date"
        })

        assert response.status_code == 200
        code, message = xml_validator.extract_error(response.content.decode())
        assert code == "badArgument"
        assert "Invalid 'from' parameter" in message

    def test_list_identifiers_from_after_until(self, oai_client, xml_validator):
        """Test ListIdentifiers with from date after until date."""
        response = oai_client.get(self.oai_url, {
            "verb": "ListIdentifiers",
            "metadataPrefix": "oai_dc",
            "from": "2023-01-10",
            "until": "2023-01-01"
        })

        assert response.status_code == 200
        code, message = xml_validator.extract_error(response.content.decode())
        assert code == "badArgument"
        assert "from' date must be earlier than 'until' date" in message

    def test_list_identifiers_no_records_match(self, oai_client, xml_validator):
        """Test ListIdentifiers when no records match criteria."""
        response = oai_client.get(self.oai_url, {
            "verb": "ListIdentifiers",
            "metadataPrefix": "oai_dc",
            "from": "2050-01-01"  # Future date
        })

        assert response.status_code == 200
        code, message = xml_validator.extract_error(response.content.decode())
        assert code == "noRecordsMatch"

    def test_list_identifiers_with_resumption_token(self, oai_client, large_dataset, xml_validator, mock_canonical_graph_service):
        """Test ListIdentifiers with resumption token."""
        # First request to get resumption token
        response = oai_client.get(self.oai_url, {
            "verb": "ListIdentifiers",
            "metadataPrefix": "oai_dc"
        })

        assert response.status_code == 200
        token = xml_validator.get_resumption_token(response.content.decode())

        if token:  # If pagination occurred
            # Request next page with token
            response2 = oai_client.get(self.oai_url, {
                "verb": "ListIdentifiers",
                "resumptionToken": token
            })

            assert response2.status_code == 200
            assert xml_validator.validate_oai_response(response2.content.decode())

    def test_list_identifiers_resumption_token_exclusive(self, oai_client, xml_validator):
        """Test that resumptionToken cannot be combined with other arguments."""
        response = oai_client.get(self.oai_url, {
            "verb": "ListIdentifiers",
            "resumptionToken": "dummy_token",
            "metadataPrefix": "oai_dc"
        })

        assert response.status_code == 200
        code, message = xml_validator.extract_error(response.content.decode())
        assert code == "badArgument"
        assert "resumptionToken cannot be combined with other arguments" in message

    def test_list_identifiers_invalid_resumption_token(self, oai_client, xml_validator):
        """Test ListIdentifiers with invalid resumption token."""
        response = oai_client.get(self.oai_url, {
            "verb": "ListIdentifiers",
            "resumptionToken": "invalid_token"
        })

        assert response.status_code == 200
        code, message = xml_validator.extract_error(response.content.decode())
        assert code == "badResumptionToken"

    # ============================================================================
    # LISTRECORDS VERB TESTS
    # ============================================================================

    def test_list_records_success(self, oai_client, sample_resources, xml_validator, mock_canonical_graph_service):
        """Test successful ListRecords request."""
        response = oai_client.get(self.oai_url, {
            "verb": "ListRecords",
            "metadataPrefix": "oai_dc"
        })

        assert response.status_code == 200
        assert xml_validator.validate_oai_response(response.content.decode())

        content = response.content.decode()
        assert "<ListRecords>" in content
        assert "<record>" in content
        assert "<header>" in content
        assert "<metadata>" in content

        # Check Dublin Core metadata structure
        assert 'xmlns:oai_dc="http://www.openarchives.org/OAI/2.0/oai_dc/"' in content
        assert 'xmlns:dc="http://purl.org/dc/elements/1.1/"' in content

    def test_list_records_mets_format(self, oai_client, sample_resources, xml_validator, mock_canonical_graph_service):
        """Test ListRecords with METS metadata format."""
        response = oai_client.get(self.oai_url, {
            "verb": "ListRecords",
            "metadataPrefix": "mets"
        })

        assert response.status_code == 200
        assert xml_validator.validate_oai_response(response.content.decode())

        content = response.content.decode()
        assert "<ListRecords>" in content
        # Note: METS XML structure would be checked in format-specific tests

    def test_list_records_missing_metadata_prefix(self, oai_client, xml_validator):
        """Test ListRecords without required metadataPrefix."""
        response = oai_client.get(self.oai_url, {"verb": "ListRecords"})

        assert response.status_code == 200
        code, message = xml_validator.extract_error(response.content.decode())
        assert code == "badArgument"
        assert "metadataPrefix is required" in message

    # ============================================================================
    # GETRECORD VERB TESTS
    # ============================================================================

    def test_get_record_success(self, oai_client, sample_resources, xml_validator, mock_canonical_graph_service):
        """Test successful GetRecord request."""
        resource = sample_resources[0]  # First public resource
        identifier = f"oai:arkumu:resource:{quote(resource.uri)}"

        response = oai_client.get(self.oai_url, {
            "verb": "GetRecord",
            "identifier": identifier,
            "metadataPrefix": "oai_dc"
        })

        assert response.status_code == 200
        assert xml_validator.validate_oai_response(response.content.decode())

        content = response.content.decode()
        assert "<GetRecord>" in content
        assert "<record>" in content
        assert "<header>" in content
        assert "<metadata>" in content
        assert identifier in content

    def test_get_record_mets_format(self, oai_client, sample_resources, xml_validator, mock_canonical_graph_service):
        """Test GetRecord with METS format."""
        resource = sample_resources[0]
        identifier = f"oai:arkumu:resource:{quote(resource.uri)}"

        response = oai_client.get(self.oai_url, {
            "verb": "GetRecord",
            "identifier": identifier,
            "metadataPrefix": "mets"
        })

        assert response.status_code == 200
        assert xml_validator.validate_oai_response(response.content.decode())

    def test_get_record_missing_identifier(self, oai_client, xml_validator):
        """Test GetRecord without required identifier."""
        response = oai_client.get(self.oai_url, {
            "verb": "GetRecord",
            "metadataPrefix": "oai_dc"
        })

        assert response.status_code == 200
        code, message = xml_validator.extract_error(response.content.decode())
        assert code == "badArgument"
        assert "identifier and metadataPrefix are required" in message

    def test_get_record_missing_metadata_prefix(self, oai_client, xml_validator):
        """Test GetRecord without required metadataPrefix."""
        response = oai_client.get(self.oai_url, {
            "verb": "GetRecord",
            "identifier": "oai:arkumu:resource:https://test.example.com"
        })

        assert response.status_code == 200
        code, message = xml_validator.extract_error(response.content.decode())
        assert code == "badArgument"
        assert "identifier and metadataPrefix are required" in message

    def test_get_record_invalid_identifier(self, oai_client, xml_validator):
        """Test GetRecord with non-existent identifier."""
        response = oai_client.get(self.oai_url, {
            "verb": "GetRecord",
            "identifier": "oai:arkumu:resource:https://nonexistent.example.com",
            "metadataPrefix": "oai_dc"
        })

        assert response.status_code == 200
        code, message = xml_validator.extract_error(response.content.decode())
        assert code == "idDoesNotExist"

    def test_get_record_private_resource(self, oai_client, sample_resources, xml_validator):
        """Test GetRecord with private resource (should not be accessible)."""
        # Private resource is at index 6 in sample_resources
        private_resource_uri = "https://test.example.com/private/1"
        identifier = f"oai:arkumu:resource:{quote(private_resource_uri)}"

        response = oai_client.get(self.oai_url, {
            "verb": "GetRecord",
            "identifier": identifier,
            "metadataPrefix": "oai_dc"
        })

        assert response.status_code == 200
        code, message = xml_validator.extract_error(response.content.decode())
        assert code == "idDoesNotExist"

    # ============================================================================
    # GENERAL ERROR TESTS
    # ============================================================================

    def test_missing_verb(self, oai_client, xml_validator):
        """Test request without verb parameter."""
        response = oai_client.get(self.oai_url)

        assert response.status_code == 200
        code, message = xml_validator.extract_error(response.content.decode())
        assert code == "badVerb"
        assert "Missing verb" in message

    def test_invalid_verb(self, oai_client, xml_validator):
        """Test request with invalid verb."""
        response = oai_client.get(self.oai_url, {"verb": "InvalidVerb"})

        assert response.status_code == 200
        code, message = xml_validator.extract_error(response.content.decode())
        assert code == "badVerb"
        assert "Illegal verb: InvalidVerb" in message

    def test_response_date_present(self, oai_client):
        """Test that all responses include responseDate element."""
        response = oai_client.get(self.oai_url, {"verb": "Identify"})

        assert response.status_code == 200
        content = response.content.decode()
        assert "<responseDate>" in content
        # Date should be in ISO format
        import re
        date_pattern = r'<responseDate>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z</responseDate>'
        assert re.search(date_pattern, content)

    def test_request_element_present(self, oai_client):
        """Test that all responses include request element with correct URL."""
        response = oai_client.get(self.oai_url, {"verb": "Identify"})

        assert response.status_code == 200
        content = response.content.decode()
        assert "<request>" in content and "</request>" in content
        assert self.oai_url in content

    def test_xml_declaration_and_content_type(self, oai_client):
        """Test proper XML declaration and Content-Type header."""
        response = oai_client.get(self.oai_url, {"verb": "Identify"})

        assert response.status_code == 200
        assert response["Content-Type"] == "text/xml"

        content = response.content.decode()
        assert content.startswith('<?xml version="1.0" encoding="utf-8"?>')

    def test_oai_pmh_namespace(self, oai_client):
        """Test that OAI-PMH namespace is correctly declared."""
        response = oai_client.get(self.oai_url, {"verb": "Identify"})

        assert response.status_code == 200
        content = response.content.decode()
        assert 'xmlns="http://www.openarchives.org/OAI/2.0/"' in content
        assert 'xsi:schemaLocation' in content
        assert 'http://www.openarchives.org/OAI/2.0/OAI-PMH.xsd' in content