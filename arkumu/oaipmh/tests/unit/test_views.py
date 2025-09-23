"""
Unit tests for OAI-PMH view functions.

Tests individual verb handler functions in isolation,
focusing on logic and XML generation without HTTP layer.
"""

import pytest
from datetime import datetime, timezone
from unittest.mock import Mock, patch
import xml.etree.ElementTree as ET
from urllib.parse import quote

from django.http import HttpRequest
from django.test import RequestFactory

from arkumu.oaipmh import views
from arkumu.oaipmh.views import ROSETTA_METS_NS, ROSETTA_DNX_NS
from arkumu.metadata.models.resource import Resource, PublicAccessLevel
from arkumu.projects import (
    ProjectRecord,
    ProjectDigitalObject,
    ProjectInstitution,
    ProjectCategory,
    ProjectCatchphrase,
    ProjectActor,
    ProjectEvent,
    ProjectType,
)


class TestOAIViewFunctions:
    """Test individual OAI-PMH view functions."""

    def setup_method(self):
        """Set up test method."""
        self.factory = RequestFactory()

    def _build_snapshot_record(self, resource: Resource, include_files: bool = False) -> ProjectRecord:
        digital_objects = []
        if include_files:
            digital_objects.append(
                ProjectDigitalObject(
                    path="org/test1.txt",
                    storage_key="org/test1.txt",
                    file_name="test1.txt",
                    content_type="text/plain",
                    size_bytes=123,
                    access_url="https://download.example/test1.txt",
                )
            )
            digital_objects.append(
                ProjectDigitalObject(
                    path="org/test2.pdf",
                    storage_key="org/test2.pdf",
                    file_name="test2.pdf",
                    content_type="application/pdf",
                    size_bytes=456,
                    access_url="https://download.example/test2.pdf",
                )
            )

        return ProjectRecord(
            subject_id="subj-1",
            uri=resource.uri,
            title="Sample Project",
            description="Sample description",
            institution=ProjectInstitution(label="Test Institution", code="ti"),
            categories=[ProjectCategory(label="Category One", slug="category-one")],
            catchphrases=[ProjectCatchphrase(label="Keyword")],
            actors=[ProjectActor(name="Jane Doe", roles=["Creator"])],
            events=[ProjectEvent(name="Launch", start="2020-01-01", location="Berlin")],
            project_type=ProjectType(label="Type A"),
            digital_objects=digital_objects,
            institution_codes=["ti"],
        )

    # ============================================================================
    # XML UTILITY FUNCTION TESTS
    # ============================================================================

    def test_oai_envelope_creation(self):
        """Test _oai_envelope creates proper XML structure."""
        request = self.factory.get('/oai/')
        oai = views._oai_envelope(request)

        # Check root element and namespaces
        assert oai.tag == "OAI-PMH"
        assert oai.get("xmlns") == "http://www.openarchives.org/OAI/2.0/"
        assert oai.get("xmlns:oai_dc") == "http://www.openarchives.org/OAI/2.0/oai_dc/"
        assert oai.get("xmlns:dc") == "http://purl.org/dc/elements/1.1/"
        assert oai.get("xmlns:xsi") == "http://www.w3.org/2001/XMLSchema-instance"

        # Check required child elements
        response_date = oai.find("responseDate")
        assert response_date is not None
        assert response_date.text is not None

        request_elem = oai.find("request")
        assert request_elem is not None
        assert "/oai/" in request_elem.text

    def test_error_creation(self):
        """Test _error creates proper error elements."""
        request = self.factory.get('/oai/')
        oai = views._oai_envelope(request)
        error_oai = views._error(oai, "badVerb", "Invalid verb")

        error_elem = error_oai.find("error")
        assert error_elem is not None
        assert error_elem.get("code") == "badVerb"
        assert error_elem.text == "Invalid verb"

    def test_xml_response_creation(self):
        """Test _xml_response creates proper HttpResponse."""
        request = self.factory.get('/oai/')
        oai = views._oai_envelope(request)
        response = views._xml_response(oai)

        assert response.status_code == 200
        assert response['Content-Type'] == "text/xml"
        assert response.content.startswith(b"<?xml version='1.0' encoding='utf-8'?>")

    # ============================================================================
    # IDENTIFY FUNCTION TESTS
    # ============================================================================

    def test_identify_function(self):
        """Test _identify creates proper Identify response."""
        request = self.factory.get('/oai/')
        oai = views._oai_envelope(request)
        result_oai = views._identify(oai, request)

        identify = result_oai.find("Identify")
        assert identify is not None

        # Check required elements
        assert identify.find("repositoryName").text == "Arkumu Repository"
        # baseURL should be absolute
        assert identify.find("baseURL").text == "http://testserver/oai/"
        assert identify.find("protocolVersion").text == "2.0"
        assert identify.find("adminEmail").text == "admin@example.org"
        assert identify.find("earliestDatestamp").text == "1970-01-01T00:00:00Z"
        assert identify.find("deletedRecord").text == "no"
        assert identify.find("granularity").text == "YYYY-MM-DDThh:mm:ssZ"

    @pytest.mark.django_db
    @patch('arkumu.oaipmh.views._get_snapshot_record')
    def test_dc_includes_file_relations_when_present(self, mock_get_record, sample_resources):
        """_build_metadata_element for oai_dc should include dc:relation URLs when files exist."""
        resource = sample_resources[0]
        record = self._build_snapshot_record(resource, include_files=True)
        mock_get_record.return_value = record

        metadata = views._build_metadata_element(resource, "oai_dc")

        dc_root = metadata.find(".//{http://www.openarchives.org/OAI/2.0/oai_dc/}dc")
        assert dc_root is not None
        relations = dc_root.findall("{http://purl.org/dc/elements/1.1/}relation")
        assert any(e.text == 'https://download.example/test1.txt' for e in relations)

    # ============================================================================
    # LIST METADATA FORMATS FUNCTION TESTS
    # ============================================================================

    def test_list_metadata_formats_function(self):
        """Test _list_metadata_formats creates proper response."""
        request = self.factory.get('/oai/')
        oai = views._oai_envelope(request)
        result_oai = views._list_metadata_formats(oai)

        list_formats = result_oai.find("ListMetadataFormats")
        assert list_formats is not None

        formats = list_formats.findall("metadataFormat")
        assert len(formats) >= 2  # At least oai_dc and mets

        # Check Dublin Core format
        dc_format = None
        mets_format = None
        for fmt in formats:
            prefix = fmt.find("metadataPrefix").text
            if prefix == "oai_dc":
                dc_format = fmt
            elif prefix == "mets":
                mets_format = fmt

        assert dc_format is not None
        assert dc_format.find("schema").text == "http://www.openarchives.org/OAI/2.0/oai_dc.xsd"
        assert dc_format.find("metadataNamespace").text == "http://www.openarchives.org/OAI/2.0/oai_dc/"

        assert mets_format is not None
        assert mets_format.find("schema").text == views.ROSETTA_METS_NS
        assert mets_format.find("metadataNamespace").text == views.ROSETTA_METS_NS

    # ============================================================================
    # LIST SETS FUNCTION TESTS
    # ============================================================================

    def test_list_sets_function(self, sample_organizations):
        """Test _list_sets creates proper response with organizations."""
        request = self.factory.get('/oai/')
        oai = views._oai_envelope(request)
        result_oai = views._list_sets(oai)

        list_sets = result_oai.find("ListSets")
        assert list_sets is not None

        sets = list_sets.findall("set")
        # Should have 2 active organizations
        assert len(sets) == 2

        # Check set structure
        for set_elem in sets:
            set_spec = set_elem.find("setSpec")
            set_name = set_elem.find("setName")

            assert set_spec is not None
            assert set_name is not None
            assert set_spec.text in ["test_univ", "research_inst"]

    # ============================================================================
    # IDENTIFIER AND URI PARSING TESTS
    # ============================================================================

    def test_build_identifier(self):
        """Test _build_identifier creates proper OAI identifiers."""
        test_uri = "https://test.example.com/resource/123"
        identifier = views._build_identifier(test_uri)

        expected = f"oai:arkumu:resource:{quote(test_uri)}"
        assert identifier == expected

    def test_parse_identifier_new_format(self):
        """Test _parse_identifier with new format."""
        test_uri = "https://test.example.com/resource/123"
        identifier = f"oai:arkumu:resource:{quote(test_uri)}"

        parsed_uri = views._parse_identifier(identifier)
        assert parsed_uri == test_uri

    def test_parse_identifier_legacy_format(self):
        """Test _parse_identifier with legacy format."""
        test_uri = "https://test.example.com/resource/123"
        identifier = f"oai:arkumu:legacy:{quote(test_uri)}"

        parsed_uri = views._parse_identifier(identifier)
        assert parsed_uri == test_uri

    def test_parse_identifier_passthrough(self):
        """Test _parse_identifier with non-OAI identifier."""
        test_uri = "https://test.example.com/resource/123"
        parsed_uri = views._parse_identifier(test_uri)
        assert parsed_uri == test_uri

    # ============================================================================
    # RECORD HEADER BUILDING TESTS
    # ============================================================================

    def test_build_record_header(self, sample_resources):
        """Test _build_record_header creates proper header."""
        resource = sample_resources[0]
        header = views._build_record_header(resource)

        assert header.tag == "header"

        identifier_elem = header.find("identifier")
        assert identifier_elem is not None
        assert identifier_elem.text.startswith("oai:arkumu:resource:")

        datestamp_elem = header.find("datestamp")
        assert datestamp_elem is not None
        assert "T" in datestamp_elem.text  # ISO datetime format
        assert datestamp_elem.text.endswith("Z")

        set_spec_elem = header.find("setSpec")
        if resource.organization:
            assert set_spec_elem is not None
            assert set_spec_elem.text == resource.organization.code

    # ============================================================================
    # DATE FORMATTING AND VALIDATION TESTS
    # ============================================================================

    def test_format_datestamp(self):
        """Test _format_datestamp produces correct format."""
        test_date = datetime(2023, 6, 15, 14, 30, 45, tzinfo=timezone.utc)
        formatted = views._format_datestamp(test_date)

        assert formatted == "2023-06-15T14:30:45Z"

    def test_validate_datestamp_valid_formats(self):
        """Test _validate_datestamp with valid date formats."""
        valid_dates = [
            "2023-01-01",
            "2023-12-31",
            "2023-06-15T14:30:45Z",
            "2023-01-01T00:00:00Z"
        ]

        for date_str in valid_dates:
            error = views._validate_datestamp(date_str)
            assert error is None, f"Valid date {date_str} should not produce error"

    def test_validate_datestamp_invalid_formats(self):
        """Test _validate_datestamp with invalid date formats."""
        invalid_dates = [
            "invalid-date",
            "2023-13-01",  # Invalid month
            "2023-01-32",  # Invalid day
            "23-01-01",    # Wrong year format
            "2023/01/01",  # Wrong separator
            "2023-01-01T25:00:00Z"  # Invalid hour
        ]

        for date_str in invalid_dates:
            error = views._validate_datestamp(date_str)
            assert error is not None, f"Invalid date {date_str} should produce error"
            assert "Invalid date format" in error

    def test_validate_datestamp_empty(self):
        """Test _validate_datestamp with empty input."""
        assert views._validate_datestamp("") is None
        assert views._validate_datestamp(None) is None

    # ============================================================================
    # RESOURCE QUERYSET BUILDING TESTS
    # ============================================================================

    def test_get_resources_queryset_basic(self, sample_resources):
        """Test _get_resources_queryset returns only public approved resources."""
        queryset = views._get_resources_queryset()
        resources = list(queryset)

        # Should only include public approved resources (6 total: 5 + 1)
        assert len(resources) == 6

        for resource in resources:
            assert resource.public_access_level == PublicAccessLevel.PUBLIC
            assert resource.is_public_approved is True

    def test_get_resources_queryset_with_set_filter(self, sample_resources, sample_organizations):
        """Test _get_resources_queryset with set specification."""
        queryset = views._get_resources_queryset(set_spec="test_univ")
        resources = list(queryset)

        # Should only include resources from test_univ organization
        assert len(resources) == 5

        for resource in resources:
            assert resource.organization.code == "test_univ"

    def test_get_resources_queryset_with_date_filters(self, sample_resources):
        """Test _get_resources_queryset with temporal filtering."""
        # First check that we have harvestable resources
        all_queryset = views._get_resources_queryset()
        all_resources = list(all_queryset)
        assert len(all_resources) > 0, "No harvestable resources found"

        # Test that date filtering doesn't crash and returns a queryset
        # (Even if no resources match, the function should work)
        queryset = views._get_resources_queryset(
            from_date="2023-01-01",
            until_date="2023-12-31"
        )
        resources = list(queryset)
        # Date filtering might reduce results, but should not crash
        assert isinstance(resources, list)

        # Test with datetime format
        queryset = views._get_resources_queryset(
            from_date="2023-01-01T00:00:00Z",
            until_date="2023-12-31T23:59:59Z"
        )
        resources = list(queryset)
        assert isinstance(resources, list)

    def test_get_resources_queryset_invalid_dates(self, sample_resources):
        """Test _get_resources_queryset ignores invalid dates."""
        # Should not crash with invalid dates, just ignore them
        queryset = views._get_resources_queryset(
            from_date="invalid-date",
            until_date="2023-invalid"
        )
        resources = list(queryset)

        # Should return all resources (dates ignored)
        assert len(resources) == 6

    # ============================================================================
    # DUBLIN CORE METADATA BUILDING TESTS
    # ============================================================================

    def test_build_dc_payload_from_record(self, sample_resources):
        """_build_dc_payload_from_record assembles title, identifiers, and relations."""
        resource = sample_resources[0]
        record = self._build_snapshot_record(resource, include_files=True)

        payload = views._build_dc_payload_from_record(record, resource)

        assert "dc:title" in payload
        assert record.title in payload["dc:title"]
        assert "dc:identifier" in payload
        assert resource.uri in payload["dc:identifier"]
        assert any(value.startswith('https://download.example') for value in payload.get("dc:relation", []))

    # ============================================================================
    # METADATA ELEMENT BUILDING TESTS
    # ============================================================================

    @patch('arkumu.oaipmh.views._get_snapshot_record')
    def test_build_metadata_element_dublin_core(self, mock_get_record, sample_resources):
        """Test _build_metadata_element with Dublin Core format."""
        resource = sample_resources[0]
        record = self._build_snapshot_record(resource, include_files=True)
        mock_get_record.return_value = record

        metadata = views._build_metadata_element(resource, "oai_dc")

        assert metadata.tag == "metadata"

        # Should contain oai_dc element
        dc_element = metadata.find(".//{http://www.openarchives.org/OAI/2.0/oai_dc/}dc")
        assert dc_element is not None

    @patch('arkumu.oaipmh.views._get_snapshot_record')
    def test_build_metadata_element_mets(self, mock_get_record, sample_resources):
        """Test _build_metadata_element with METS format."""
        resource = sample_resources[0]
        record = self._build_snapshot_record(resource, include_files=True)
        mock_get_record.return_value = record

        metadata = views._build_metadata_element(resource, "mets")

        assert metadata.tag == "metadata"

        # Should contain METS element
        mets_elements = metadata.findall(".//{http://www.exlibrisgroup.com/xsd/dps/rosettaMets}mets")
        assert len(mets_elements) > 0

    @patch('arkumu.oaipmh.views._get_snapshot_record')
    def test_rosetta_mets_structure(self, mock_get_record, sample_resources):
        """Ensure Rosetta METS output matches expected structural profile."""
        resource = sample_resources[0]
        record = self._build_snapshot_record(resource, include_files=True)
        mock_get_record.return_value = record

        metadata = views._build_metadata_element(resource, "mets")
        mets_root = metadata.find(f".//{{{ROSETTA_METS_NS}}}mets")
        assert mets_root is not None

        # Intellectual entity ADM sections
        rights_md = mets_root.find(f".//{{{ROSETTA_METS_NS}}}rightsMD[@ID='ie-amd-rights']")
        assert rights_md is not None
        source_md = mets_root.find(f".//{{{ROSETTA_METS_NS}}}sourceMD[@ID='ie-amd-source-OTHER']")
        assert source_md is not None
        epicur = source_md.find(f".//{{{ROSETTA_DNX_NS}}}epicur")
        assert epicur is not None

        resources = epicur.findall(f".//{{{ROSETTA_DNX_NS}}}resource")
        assert len(resources) >= len(record.digital_objects)

        # File groups and structural maps should mirror digital objects
        file_grps = mets_root.findall(f".//{{{ROSETTA_METS_NS}}}fileGrp")
        assert len(file_grps) == len(record.digital_objects)

        struct_maps = mets_root.findall(f".//{{{ROSETTA_METS_NS}}}structMap")
        assert len(struct_maps) == len(record.digital_objects)

        # Each structMap should point to a file
        for struct_map in struct_maps:
            fptr = struct_map.find(f".//{{{ROSETTA_METS_NS}}}fptr")
            assert fptr is not None

    def test_build_metadata_element_no_organization(self):
        """Test _build_metadata_element with resource without organization."""
        # Create a mock resource without organization
        mock_resource = Mock()
        mock_resource.organization = None

        with patch('arkumu.oaipmh.views._get_snapshot_record', return_value=None):
            metadata = views._build_metadata_element(mock_resource, "oai_dc")

        assert metadata.tag == "metadata"
        # Should be empty metadata element
        assert len(list(metadata)) == 0

    # ============================================================================
    # LIST IDENTIFIERS FUNCTION TESTS
    # ============================================================================

    @patch('arkumu.oaipmh.views._get_resources_queryset')
    def test_list_identifiers_basic(self, mock_queryset, sample_resources):
        """Test _list_identifiers function basic functionality."""
        mock_queryset.return_value = sample_resources[:2]  # Return 2 resources

        request = self.factory.get('/oai/', {
            'metadataPrefix': 'oai_dc'
        })
        oai = views._oai_envelope(request)
        result_oai = views._list_identifiers(oai, request)

        list_identifiers = result_oai.find("ListIdentifiers")
        assert list_identifiers is not None

        headers = list_identifiers.findall("header")
        assert len(headers) == 2

    def test_list_identifiers_missing_metadata_prefix(self):
        """Test _list_identifiers with missing metadataPrefix."""
        request = self.factory.get('/oai/')  # No metadataPrefix
        oai = views._oai_envelope(request)
        result_oai = views._list_identifiers(oai, request)

        error_elem = result_oai.find("error")
        assert error_elem is not None
        assert error_elem.get("code") == "cannotDisseminateFormat"

    def test_list_identifiers_invalid_metadata_prefix(self):
        """Test _list_identifiers with invalid metadataPrefix."""
        request = self.factory.get('/oai/', {
            'metadataPrefix': 'invalid_format'
        })
        oai = views._oai_envelope(request)
        result_oai = views._list_identifiers(oai, request)

        error_elem = result_oai.find("error")
        assert error_elem is not None
        assert error_elem.get("code") == "cannotDisseminateFormat"

    @patch('arkumu.oaipmh.views._get_resources_queryset')
    def test_list_identifiers_no_records_match(self, mock_queryset):
        """Test _list_identifiers when no records match."""
        mock_queryset.return_value = []  # No resources

        request = self.factory.get('/oai/', {
            'metadataPrefix': 'oai_dc'
        })
        oai = views._oai_envelope(request)
        result_oai = views._list_identifiers(oai, request)

        error_elem = result_oai.find("error")
        assert error_elem is not None
        assert error_elem.get("code") == "noRecordsMatch"

    # ============================================================================
    # LIST RECORDS FUNCTION TESTS
    # ============================================================================

    @patch('arkumu.oaipmh.views._get_snapshot_record')
    @patch('arkumu.oaipmh.views._get_resources_queryset')
    def test_list_records_basic(self, mock_queryset, mock_get_record, sample_resources):
        """Test _list_records function basic functionality."""
        mock_queryset.return_value = sample_resources[:1]  # Return 1 resource
        mock_get_record.return_value = self._build_snapshot_record(sample_resources[0], include_files=True)

        request = self.factory.get('/oai/', {
            'metadataPrefix': 'oai_dc'
        })
        oai = views._oai_envelope(request)
        result_oai = views._list_records(oai, request)

        list_records = result_oai.find("ListRecords")
        assert list_records is not None

        records = list_records.findall("record")
        assert len(records) == 1

        # Each record should have header and metadata
        record = records[0]
        assert record.find("header") is not None
        assert record.find("metadata") is not None

    def test_list_records_missing_metadata_prefix(self):
        """Test _list_records with missing metadataPrefix."""
        request = self.factory.get('/oai/')  # No metadataPrefix
        oai = views._oai_envelope(request)
        result_oai = views._list_records(oai, request)

        error_elem = result_oai.find("error")
        assert error_elem is not None
        assert error_elem.get("code") == "cannotDisseminateFormat"
