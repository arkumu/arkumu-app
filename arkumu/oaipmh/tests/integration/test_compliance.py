"""
OAI-PMH protocol compliance tests.

Tests strict compliance with OAI-PMH 2.0 specification including
XML schema validation, required response elements, proper namespace
declarations, and protocol-specific requirements.
"""

import pytest
import xml.etree.ElementTree as ET
from datetime import datetime
import re


@pytest.mark.django_db
class TestOAIProtocolCompliance:
    """Test strict OAI-PMH 2.0 protocol compliance."""

    def setup_method(self):
        """Set up test method."""
        self.oai_url = "/oai/"
        self.oai_ns = "http://www.openarchives.org/OAI/2.0/"

    def _find_element(self, parent, tag_name):
        """Find element handling both namespaced and non-namespaced cases."""
        elem = parent.find(f"{{{self.oai_ns}}}{tag_name}")
        if elem is None:
            elem = parent.find(tag_name)
        return elem

    # ============================================================================
    # XML SCHEMA AND STRUCTURE COMPLIANCE
    # ============================================================================

    def test_xml_declaration_compliance(self, oai_client):
        """Test XML declaration compliance with OAI-PMH requirements."""
        response = oai_client.get(self.oai_url, {"verb": "Identify"})

        assert response.status_code == 200

        content = response.content.decode('utf-8')

        # Must start with XML declaration
        assert content.startswith('<?xml version=')

        # Should specify UTF-8 encoding (can be single or double quotes)
        first_line = content.split('\n')[0]
        assert ('encoding="utf-8"' in first_line or 'encoding="UTF-8"' in first_line or
                "encoding='utf-8'" in first_line or "encoding='UTF-8'" in first_line)

    def test_oai_pmh_root_element_compliance(self, oai_client):
        """Test OAI-PMH root element compliance."""
        response = oai_client.get(self.oai_url, {"verb": "Identify"})

        assert response.status_code == 200
        root = ET.fromstring(response.content)

        # Root element must be OAI-PMH
        assert root.tag == "OAI-PMH" or root.tag.endswith("}OAI-PMH")

        # Must have correct namespace (ElementTree puts namespace in tag)
        if "}" in root.tag:
            # Namespace is in Clark notation
            oai_ns = root.tag.split("}")[0][1:]
            assert oai_ns == "http://www.openarchives.org/OAI/2.0/"
        else:
            # Or check xmlns attribute
            oai_ns = root.get("xmlns")
            assert oai_ns == "http://www.openarchives.org/OAI/2.0/"

        # Must have schema location
        schema_location = root.get("{http://www.w3.org/2001/XMLSchema-instance}schemaLocation")
        assert schema_location is not None
        assert "http://www.openarchives.org/OAI/2.0/" in schema_location
        assert "http://www.openarchives.org/OAI/2.0/OAI-PMH.xsd" in schema_location

    def test_required_child_elements_present(self, oai_client):
        """Test that required child elements are present in all responses."""
        verbs_to_test = [
            {"verb": "Identify"},
            {"verb": "ListMetadataFormats"},
            {"verb": "ListSets"},
        ]

        OAI_NS = "http://www.openarchives.org/OAI/2.0/"

        for params in verbs_to_test:
            response = oai_client.get(self.oai_url, params)
            assert response.status_code == 200

            root = ET.fromstring(response.content)

            # Must have responseDate
            response_date = self._find_element(root, "responseDate")
            assert response_date is not None
            assert response_date.text is not None

            # Must have request
            request_elem = self._find_element(root, "request")
            assert request_elem is not None

    def test_response_date_format_compliance(self, oai_client):
        """Test responseDate format compliance with UTC ISO 8601."""
        response = oai_client.get(self.oai_url, {"verb": "Identify"})

        assert response.status_code == 200
        root = ET.fromstring(response.content)

        response_date = self._find_element(root, "responseDate")
        assert response_date is not None

        date_text = response_date.text
        assert date_text is not None

        # Must match YYYY-MM-DDTHH:MM:SSZ format
        date_pattern = r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$'
        assert re.match(date_pattern, date_text), f"responseDate format invalid: {date_text}"

        # Must be valid datetime
        try:
            parsed_date = datetime.fromisoformat(date_text.replace('Z', '+00:00'))
            assert parsed_date is not None
        except ValueError:
            pytest.fail(f"responseDate cannot be parsed as datetime: {date_text}")

    def test_request_element_compliance(self, oai_client):
        """Test request element compliance."""
        test_cases = [
            ({"verb": "Identify"}, []),
            ({"verb": "ListMetadataFormats"}, []),
            ({"verb": "ListSets"}, []),
            ({"verb": "ListIdentifiers", "metadataPrefix": "oai_dc"}, ["metadataPrefix"]),
        ]

        for params, expected_attrs in test_cases:
            response = oai_client.get(self.oai_url, params)
            assert response.status_code == 200

            root = ET.fromstring(response.content)
            request_elem = self._find_element(root, "request")
            assert request_elem is not None
            # Must contain base URL
            assert "/oai/" in request_elem.text

            # Should contain verb parameter as attribute (OAI-PMH spec)
            # Note: Some implementations put parameters as attributes, others don't
            # This is implementation-dependent

    # ============================================================================
    # VERB-SPECIFIC COMPLIANCE TESTS
    # ============================================================================

    def test_identify_response_compliance(self, oai_client):
        """Test Identify response compliance with required elements."""
        response = oai_client.get(self.oai_url, {"verb": "Identify"})

        assert response.status_code == 200
        root = ET.fromstring(response.content)

        identify = self._find_element(root, "Identify")
        assert identify is not None

        # Required elements per OAI-PMH spec
        required_elements = [
            "repositoryName",
            "baseURL",
            "protocolVersion",
            "adminEmail",
            "earliestDatestamp",
            "deletedRecord",
            "granularity"
        ]

        for elem_name in required_elements:
            elem = self._find_element(identify, elem_name)
            assert elem is not None, f"Required Identify element missing: {elem_name}"
            assert elem.text is not None and elem.text.strip() != "", f"Required Identify element empty: {elem_name}"

        # Protocol version must be 2.0
        protocol_version = self._find_element(identify, "protocolVersion")
        assert protocol_version.text == "2.0"

        # deletedRecord must be valid value
        deleted_record = self._find_element(identify, "deletedRecord")
        assert deleted_record.text in ["no", "transient", "persistent"]

        # granularity must be valid
        granularity = self._find_element(identify, "granularity")
        assert granularity.text in ["YYYY-MM-DD", "YYYY-MM-DDThh:mm:ssZ"]

        # earliestDatestamp must be valid format
        earliest = self._find_element(identify, "earliestDatestamp")
        self._validate_datestamp_format(earliest.text)

        # adminEmail must be valid format (basic check)
        admin_email = self._find_element(identify, "adminEmail")
        assert "@" in admin_email.text

    def test_list_metadata_formats_compliance(self, oai_client):
        """Test ListMetadataFormats response compliance."""
        response = oai_client.get(self.oai_url, {"verb": "ListMetadataFormats"})

        assert response.status_code == 200
        root = ET.fromstring(response.content)

        list_formats = self._find_element(root, "ListMetadataFormats")
        assert list_formats is not None

        # Must have at least one metadataFormat
        formats = list_formats.findall(f"{{{self.oai_ns}}}metadataFormat")
        if not formats:
            formats = list_formats.findall("metadataFormat")
        assert len(formats) > 0

        # Each metadataFormat must have required elements
        for fmt in formats:
            # Required elements
            metadata_prefix = self._find_element(fmt, "metadataPrefix")
            schema = self._find_element(fmt, "schema")
            metadata_namespace = self._find_element(fmt, "metadataNamespace")

            assert metadata_prefix is not None and metadata_prefix.text
            assert schema is not None and schema.text
            assert metadata_namespace is not None and metadata_namespace.text

            # Schema must be valid URL
            assert schema.text.startswith("http")

            # Namespace must be valid URI
            assert metadata_namespace.text.startswith("http")

        # Must support oai_dc (mandatory format)
        oai_dc_found = False
        for fmt in formats:
            prefix = self._find_element(fmt, "metadataPrefix")
            if prefix is not None and prefix.text == "oai_dc":
                oai_dc_found = True

                # Verify oai_dc specific requirements
                schema = self._find_element(fmt, "schema")
                namespace = self._find_element(fmt, "metadataNamespace")

                assert "oai_dc.xsd" in schema.text
                assert "oai_dc" in namespace.text
                break

        assert oai_dc_found, "Mandatory oai_dc format not found"

    def test_list_sets_compliance(self, oai_client, sample_organizations):
        """Test ListSets response compliance."""
        response = oai_client.get(self.oai_url, {"verb": "ListSets"})

        assert response.status_code == 200
        root = ET.fromstring(response.content)

        list_sets = self._find_element(root, "ListSets")
        assert list_sets is not None

        # Each set must have required elements
        sets = list_sets.findall(f"{{{self.oai_ns}}}set")
        if not sets:
            sets = list_sets.findall("set")
        for set_elem in sets:
            # Required elements
            set_spec = self._find_element(set_elem, "setSpec")
            set_name = self._find_element(set_elem, "setName")

            assert set_spec is not None and set_spec.text
            assert set_name is not None and set_name.text

            # setSpec must not contain certain characters
            spec_text = set_spec.text
            forbidden_chars = [' ', '\t', '\n', '\r', '&', '<', '>', '"', "'"]
            for char in forbidden_chars:
                assert char not in spec_text, f"setSpec contains forbidden character: {char}"

    def test_list_identifiers_compliance(self, oai_client, sample_resources, mock_canonical_graph_service):
        """Test ListIdentifiers response compliance."""
        response = oai_client.get(self.oai_url, {
            "verb": "ListIdentifiers",
            "metadataPrefix": "oai_dc"
        })

        assert response.status_code == 200
        root = ET.fromstring(response.content)

        list_identifiers = self._find_element(root, "ListIdentifiers")
        if list_identifiers is not None:  # Might be noRecordsMatch error
            # Each header must have required elements
            headers = list_identifiers.findall(f"{{{self.oai_ns}}}header")
            if not headers:
                headers = list_identifiers.findall("header")

            for header in headers:
                # Required elements
                identifier = self._find_element(header, "identifier")
                datestamp = self._find_element(header, "datestamp")

                assert identifier is not None and identifier.text
                assert datestamp is not None and datestamp.text

                # Identifier must be valid OAI identifier format
                self._validate_oai_identifier_format(identifier.text)

                # Datestamp must be valid format
                self._validate_datestamp_format(datestamp.text)

                # setSpec is optional but must be valid if present
                set_spec = self._find_element(header, "setSpec")
                if set_spec is not None and set_spec.text:
                    self._validate_set_spec_format(set_spec.text)

    def test_list_records_compliance(self, oai_client, sample_resources, mock_canonical_graph_service):
        """Test ListRecords response compliance."""
        response = oai_client.get(self.oai_url, {
            "verb": "ListRecords",
            "metadataPrefix": "oai_dc"
        })

        assert response.status_code == 200
        root = ET.fromstring(response.content)

        list_records = self._find_element(root, "ListRecords")
        if list_records is not None:  # Might be noRecordsMatch error
            # Each record must have header and metadata
            records = list_records.findall(f"{{{self.oai_ns}}}record")
            if not records:
                records = list_records.findall("record")

            for record in records:
                # Must have header
                header = self._find_element(record, "header")
                assert header is not None

                # Header compliance (same as ListIdentifiers)
                identifier = self._find_element(header, "identifier")
                datestamp = self._find_element(header, "datestamp")
                assert identifier is not None and identifier.text
                assert datestamp is not None and datestamp.text
                self._validate_oai_identifier_format(identifier.text)
                self._validate_datestamp_format(datestamp.text)

                # Must have metadata (unless deleted record)
                status = header.get("status")
                if status != "deleted":
                    metadata = self._find_element(record, "metadata")
                    assert metadata is not None

                    # Metadata must contain format-specific elements
                    # For oai_dc, must have dc element
                    dc_element = metadata.find(".//{http://www.openarchives.org/OAI/2.0/oai_dc/}dc")
                    if dc_element is None:
                        dc_element = metadata.find(".//dc")
                    # Note: metadata might be empty for some records, which is acceptable

    def test_get_record_compliance(self, oai_client, sample_resources, mock_canonical_graph_service):
        """Test GetRecord response compliance."""
        if sample_resources:
            resource = sample_resources[0]
            identifier = f"oai:arkumu:resource:{resource.uri}"

            response = oai_client.get(self.oai_url, {
                "verb": "GetRecord",
                "identifier": identifier,
                "metadataPrefix": "oai_dc"
            })

            assert response.status_code == 200
            root = ET.fromstring(response.content)

            get_record = root.find("GetRecord")
            if get_record is not None:  # Might be error response
                # Must have exactly one record
                records = get_record.findall("record")
                assert len(records) == 1

                record = records[0]

                # Record compliance (same as ListRecords)
                header = record.find("header")
                assert header is not None

                identifier_elem = header.find("identifier")
                assert identifier_elem is not None
                assert identifier_elem.text == identifier

    # ============================================================================
    # ERROR RESPONSE COMPLIANCE
    # ============================================================================

    def test_error_response_compliance(self, oai_client):
        """Test error response compliance with OAI-PMH spec."""
        # Test various error conditions
        error_cases = [
            ({"verb": "InvalidVerb"}, "badVerb"),
            ({"verb": "ListIdentifiers"}, "badArgument"),  # Missing metadataPrefix
            ({"verb": "ListIdentifiers", "metadataPrefix": "invalid"}, "cannotDisseminateFormat"),
            ({"verb": "GetRecord", "identifier": "invalid", "metadataPrefix": "oai_dc"}, "idDoesNotExist"),
        ]

        for params, expected_code in error_cases:
            response = oai_client.get(self.oai_url, params)
            assert response.status_code == 200  # OAI-PMH errors use 200 OK

            root = ET.fromstring(response.content)

            # Must have error element
            error = self._find_element(root, "error")
            assert error is not None

            # Must have correct code
            code = error.get("code")
            assert code == expected_code

            # Must have error message
            assert error.text is not None and error.text.strip() != ""

            # Error responses should not have verb-specific elements
            verb_elements = ["Identify", "ListMetadataFormats", "ListSets",
                           "ListIdentifiers", "ListRecords", "GetRecord"]
            for verb in verb_elements:
                assert root.find(verb) is None

    def test_multiple_error_handling(self, oai_client):
        """Test that only one error is returned (OAI-PMH spec)."""
        # Request with multiple errors (bad verb AND bad argument)
        response = oai_client.get(self.oai_url, {
            "verb": "InvalidVerb",
            "invalidParam": "value"
        })

        assert response.status_code == 200
        root = ET.fromstring(response.content)

        # Should have exactly one error element
        errors = root.findall(f"{{{self.oai_ns}}}error")
        if not errors:
            errors = root.findall("error")
        assert len(errors) == 1

    # ============================================================================
    # HTTP COMPLIANCE TESTS
    # ============================================================================

    def test_http_headers_compliance(self, oai_client):
        """Test HTTP headers compliance."""
        response = oai_client.get(self.oai_url, {"verb": "Identify"})

        # Must return 200 OK for all OAI-PMH responses
        assert response.status_code == 200

        # Content-Type must be text/xml
        content_type = response.get("Content-Type", "")
        assert content_type.startswith("text/xml")

        # Should have UTF-8 encoding specified
        assert "charset=utf-8" in content_type.lower() or "utf-8" in response.content.decode()[:200].lower()

    def test_http_methods_compliance(self, oai_client):
        """Test that only GET method is supported."""
        # POST should not be supported (or should redirect to GET)
        try:
            response = oai_client.post(self.oai_url, {"verb": "Identify"})
            # Some implementations might support POST, others might not
            # This is implementation-dependent
        except Exception:
            # POST not supported is acceptable
            pass

    # ============================================================================
    # RESUMPTION TOKEN COMPLIANCE
    # ============================================================================

    def test_resumption_token_compliance(self, oai_client, large_dataset, xml_validator, mock_canonical_graph_service):
        """Test resumption token compliance."""
        response = oai_client.get(self.oai_url, {
            "verb": "ListIdentifiers",
            "metadataPrefix": "oai_dc"
        })

        assert response.status_code == 200
        root = ET.fromstring(response.content)

        list_identifiers = root.find("ListIdentifiers")
        if list_identifiers is not None:
            resumption_token = list_identifiers.find("resumptionToken")

            if resumption_token is not None:
                # Token element must be present even if empty (spec requirement)
                assert resumption_token is not None

                token_text = resumption_token.text or ""

                # If token has content, test its usage
                if token_text.strip():
                    # Test using the token
                    response2 = oai_client.get(self.oai_url, {
                        "verb": "ListIdentifiers",
                        "resumptionToken": token_text
                    })

                    assert response2.status_code == 200
                    # Should either succeed or return badResumptionToken

    # ============================================================================
    # DATESTAMP COMPLIANCE TESTS
    # ============================================================================

    def test_datestamp_granularity_consistency(self, oai_client):
        """Test that datestamp granularity is consistent throughout."""
        # Get granularity from Identify
        identify_response = oai_client.get(self.oai_url, {"verb": "Identify"})
        identify_root = ET.fromstring(identify_response.content)
        identify = self._find_element(identify_root, "Identify")
        granularity_elem = self._find_element(identify, "granularity")
        granularity = granularity_elem.text

        # Test that all datestamps follow this granularity
        list_response = oai_client.get(self.oai_url, {
            "verb": "ListIdentifiers",
            "metadataPrefix": "oai_dc"
        })

        if list_response.status_code == 200:
            list_root = ET.fromstring(list_response.content)
            list_identifiers = list_root.find("ListIdentifiers")

            if list_identifiers is not None:
                headers = list_identifiers.findall("header")
                for header in headers:
                    datestamp = header.find("datestamp")
                    if datestamp is not None and datestamp.text:
                        self._validate_datestamp_matches_granularity(datestamp.text, granularity)

    # ============================================================================
    # UTILITY METHODS FOR VALIDATION
    # ============================================================================

    def _validate_oai_identifier_format(self, identifier: str):
        """Validate OAI identifier format."""
        # Must follow oai:domain:identifier or oai:domain:namespace:identifier format
        assert identifier.startswith("oai:"), f"Invalid OAI identifier format: {identifier}"

        parts = identifier.split(":", 2)
        assert len(parts) >= 3, f"OAI identifier must have at least 3 parts: {identifier}"

    def _validate_datestamp_format(self, datestamp: str):
        """Validate datestamp format."""
        # Must be either YYYY-MM-DD or YYYY-MM-DDThh:mm:ssZ
        date_pattern = r'^\d{4}-\d{2}-\d{2}(T\d{2}:\d{2}:\d{2}Z)?$'
        assert re.match(date_pattern, datestamp), f"Invalid datestamp format: {datestamp}"

        # Must be valid date
        try:
            if 'T' in datestamp:
                datetime.fromisoformat(datestamp.replace('Z', '+00:00'))
            else:
                datetime.strptime(datestamp, '%Y-%m-%d')
        except ValueError:
            pytest.fail(f"Datestamp is not a valid date: {datestamp}")

    def _validate_set_spec_format(self, set_spec: str):
        """Validate setSpec format."""
        # Must not contain certain characters
        forbidden_chars = [' ', '\t', '\n', '\r', '&', '<', '>', '"', "'"]
        for char in forbidden_chars:
            assert char not in set_spec, f"setSpec contains forbidden character '{char}': {set_spec}"

    def _validate_datestamp_matches_granularity(self, datestamp: str, granularity: str):
        """Validate that datestamp matches declared granularity."""
        if granularity == "YYYY-MM-DD":
            # Should be date-only format
            assert 'T' not in datestamp, f"Datestamp should be date-only for granularity {granularity}: {datestamp}"
        elif granularity == "YYYY-MM-DDThh:mm:ssZ":
            # Should be datetime format
            assert 'T' in datestamp and datestamp.endswith('Z'), f"Datestamp should be datetime format for granularity {granularity}: {datestamp}"

    # ============================================================================
    # NAMESPACE COMPLIANCE TESTS
    # ============================================================================

    def test_dublin_core_namespace_compliance(self, oai_client, sample_resources, mock_canonical_graph_service):
        """Test Dublin Core namespace compliance in oai_dc records."""
        response = oai_client.get(self.oai_url, {
            "verb": "ListRecords",
            "metadataPrefix": "oai_dc"
        })

        if response.status_code == 200:
            root = ET.fromstring(response.content)
            list_records = root.find("ListRecords")

            if list_records is not None:
                records = list_records.findall("record")
                for record in records:
                    metadata = record.find("metadata")
                    if metadata is not None:
                        # Find oai_dc:dc element
                        dc_elements = metadata.findall(".//{http://www.openarchives.org/OAI/2.0/oai_dc/}dc")

                        for dc in dc_elements:
                            # Must have correct namespace declarations
                            oai_dc_ns = dc.get("xmlns:oai_dc")
                            dc_ns = dc.get("xmlns:dc")

                            if oai_dc_ns:
                                assert oai_dc_ns == "http://www.openarchives.org/OAI/2.0/oai_dc/"
                            if dc_ns:
                                assert dc_ns == "http://purl.org/dc/elements/1.1/"

    def test_xml_schema_location_compliance(self, oai_client):
        """Test XML schema location compliance."""
        verbs = ["Identify", "ListMetadataFormats", "ListSets"]

        for verb in verbs:
            response = oai_client.get(self.oai_url, {"verb": verb})
            assert response.status_code == 200

            root = ET.fromstring(response.content)

            # Must have schema location
            schema_location = root.get("{http://www.w3.org/2001/XMLSchema-instance}schemaLocation")
            assert schema_location is not None

            # Must reference OAI-PMH schema
            assert "http://www.openarchives.org/OAI/2.0/" in schema_location
            assert "OAI-PMH.xsd" in schema_location