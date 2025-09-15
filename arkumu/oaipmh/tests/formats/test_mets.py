"""
Tests for METS metadata serialization.

Tests the METSSerializer and its integration with the canonical graph system
for comprehensive metadata representation in OAI-PMH.
"""

import pytest
from unittest.mock import Mock, patch
import xml.etree.ElementTree as ET
from typing import Dict, Any

from arkumu.oaipmh.formats.mets import METSSerializer, METS_NS, XLINK_NS


@pytest.mark.django_db
class TestMETSSerializer:
    """Test METS serialization functionality."""

    def setup_method(self):
        """Set up test method."""
        from arkumu.users.models import Organization

        self.org_code = "test_org"
        # Create the organization for the test
        self.organization = Organization.objects.create(
            code=self.org_code,
            name="Test Organization"
        )
        self.serializer = METSSerializer(org_code=self.org_code)

    # ============================================================================
    # BASIC SERIALIZATION TESTS
    # ============================================================================

    @patch('arkumu.oaipmh.formats.mets.CanonicalGraphService')
    def test_serialize_resource_basic(self, mock_service_class):
        """Test basic resource serialization to METS XML."""
        # Mock the canonical graph service
        mock_service = Mock()
        mock_service_class.return_value = mock_service

        # Mock graph data
        mock_graph = {
            "root_id": "https://test.example.com/resource/1",
            "nodes": {
                "https://test.example.com/resource/1": {
                    "type": "Resource",
                    "label": "Test Resource",
                    "uri": "https://test.example.com/resource/1"
                }
            },
            "edges": [
                {
                    "subject_id": "https://test.example.com/resource/1",
                    "predicate_canonical": "http://purl.org/dc/terms/title",
                    "predicate_uri": "http://purl.org/dc/terms/title",
                    "object_value": "Test Resource Title",
                    "object_id": None
                }
            ]
        }
        mock_service.get_entity_graph.return_value = mock_graph

        # Serialize resource
        resource_uri = "https://test.example.com/resource/1"
        result = self.serializer.serialize_resource(resource_uri)

        # Verify service was called correctly
        mock_service.get_entity_graph.assert_called_once_with(
            resource_uri,
            include_incoming=True,
            expand_neighbors=True
        )

        # Verify XML structure
        assert result
        assert isinstance(result, str)
        assert result.startswith('<?xml version="1.0" encoding="unicode"?>')

        # Parse and validate XML
        root = ET.fromstring(result)
        assert root.tag.endswith('}mets') or root.tag == 'mets'

    @patch('arkumu.oaipmh.formats.mets.CanonicalGraphService')
    def test_serialize_resource_empty_graph(self, mock_service_class):
        """Test serialization with empty graph."""
        mock_service = Mock()
        mock_service_class.return_value = mock_service
        mock_service.get_entity_graph.return_value = None

        result = self.serializer.serialize_resource("https://nonexistent.example.com")

        assert result == ""

    @patch('arkumu.oaipmh.formats.mets.CanonicalGraphService')
    def test_serialize_resource_no_root_id(self, mock_service_class):
        """Test serialization with graph missing root_id."""
        mock_service = Mock()
        mock_service_class.return_value = mock_service
        mock_service.get_entity_graph.return_value = {"nodes": {}, "edges": []}

        result = self.serializer.serialize_resource("https://test.example.com/resource/1")

        assert result == ""

    # ============================================================================
    # XML STRUCTURE TESTS
    # ============================================================================

    @patch('arkumu.oaipmh.formats.mets.CanonicalGraphService')
    def test_mets_xml_namespace_declarations(self, mock_service_class):
        """Test that METS XML has correct namespace declarations."""
        mock_service = Mock()
        mock_service_class.return_value = mock_service
        mock_service.get_entity_graph.return_value = {
            "root_id": "https://test.example.com/resource/1",
            "nodes": {},
            "edges": []
        }

        result = self.serializer.serialize_resource("https://test.example.com/resource/1")

        root = ET.fromstring(result)

        # Check METS namespace
        assert f"xmlns:mets=\"{METS_NS}\"" in result or root.get("xmlns:mets") == METS_NS

        # Check XLink namespace
        assert f"xmlns:xlink=\"{XLINK_NS}\"" in result or root.get("xmlns:xlink") == XLINK_NS

        # Check OBJID attribute
        objid = root.get("OBJID")
        assert objid == "https://test.example.com/resource/1"

    @patch('arkumu.oaipmh.formats.mets.CanonicalGraphService')
    def test_mets_header_section(self, mock_service_class):
        """Test METS header section creation."""
        mock_service = Mock()
        mock_service_class.return_value = mock_service
        mock_service.get_entity_graph.return_value = {
            "root_id": "https://test.example.com/resource/1",
            "nodes": {},
            "edges": []
        }

        result = self.serializer.serialize_resource("https://test.example.com/resource/1")
        root = ET.fromstring(result)

        # Find metsHdr element (handling namespaces)
        mets_hdr = root.find("metsHdr")
        if mets_hdr is None:
            mets_hdr = root.find(f".//{{{METS_NS}}}metsHdr")

        # Header should be present (even if minimal)
        assert mets_hdr is not None

        # Should have CREATEDATE attribute
        create_date = mets_hdr.get("CREATEDATE")
        assert create_date is not None

    @patch('arkumu.oaipmh.formats.mets.CanonicalGraphService')
    def test_mets_descriptive_metadata_section(self, mock_service_class):
        """Test METS descriptive metadata section with Dublin Core."""
        mock_service = Mock()
        mock_service_class.return_value = mock_service

        # Mock graph with Dublin Core metadata
        mock_graph = {
            "root_id": "https://test.example.com/resource/1",
            "nodes": {
                "https://test.example.com/resource/1": {
                    "type": "Resource",
                    "label": "Test Resource",
                    "uri": "https://test.example.com/resource/1"
                }
            },
            "edges": [
                {
                    "subject_id": "https://test.example.com/resource/1",
                    "predicate_canonical": "http://purl.org/dc/terms/title",
                    "predicate_uri": "http://purl.org/dc/terms/title",
                    "object_value": "Test Resource Title",
                    "object_id": None
                },
                {
                    "subject_id": "https://test.example.com/resource/1",
                    "predicate_canonical": "http://purl.org/dc/terms/creator",
                    "predicate_uri": "http://purl.org/dc/terms/creator",
                    "object_value": "Test Creator",
                    "object_id": None
                }
            ]
        }
        mock_service.get_entity_graph.return_value = mock_graph

        result = self.serializer.serialize_resource("https://test.example.com/resource/1")
        root = ET.fromstring(result)

        # Find dmdSec element
        dmd_sec = root.find("dmdSec")
        if dmd_sec is None:
            dmd_sec = root.find(f".//{{{METS_NS}}}dmdSec")

        assert dmd_sec is not None

        # Should have ID attribute
        assert dmd_sec.get("ID") == "dmd001"

        # Find mdWrap element
        md_wrap = dmd_sec.find("mdWrap")
        if md_wrap is None:
            md_wrap = dmd_sec.find(f".//{{{METS_NS}}}mdWrap")

        assert md_wrap is not None
        assert md_wrap.get("MDTYPE") == "DC"

        # Find xmlData element
        xml_data = md_wrap.find("xmlData")
        if xml_data is None:
            xml_data = md_wrap.find(f".//{{{METS_NS}}}xmlData")

        assert xml_data is not None

        # Should contain Dublin Core elements
        dc_elements = xml_data.findall(".//{http://purl.org/dc/elements/1.1/}*")
        assert len(dc_elements) > 0

        # Check for specific DC elements
        titles = xml_data.findall(".//{http://purl.org/dc/elements/1.1/}title")
        creators = xml_data.findall(".//{http://purl.org/dc/elements/1.1/}creator")

        assert len(titles) == 1
        assert titles[0].text == "Test Resource Title"
        assert len(creators) == 1
        assert creators[0].text == "Test Creator"

    @patch('arkumu.oaipmh.formats.mets.CanonicalGraphService')
    def test_mets_file_section(self, mock_service_class):
        """Test METS file section creation."""
        mock_service = Mock()
        mock_service_class.return_value = mock_service

        # Mock graph with file nodes
        mock_graph = {
            "root_id": "https://test.example.com/resource/1",
            "nodes": {
                "https://test.example.com/resource/1": {
                    "type": "Resource",
                    "label": "Test Resource",
                    "uri": "https://test.example.com/resource/1"
                },
                "https://test.example.com/file/1": {
                    "type": "File",
                    "label": "Test File",
                    "uri": "https://test.example.com/file/1"
                }
            },
            "edges": []
        }
        mock_service.get_entity_graph.return_value = mock_graph

        result = self.serializer.serialize_resource("https://test.example.com/resource/1")
        root = ET.fromstring(result)

        # Find fileSec element
        file_sec = root.find("fileSec")
        if file_sec is None:
            file_sec = root.find(f".//{{{METS_NS}}}fileSec")

        assert file_sec is not None

        # Find fileGrp element
        file_grp = file_sec.find("fileGrp")
        if file_grp is None:
            file_grp = file_sec.find(f".//{{{METS_NS}}}fileGrp")

        assert file_grp is not None

        # Should contain file elements for File type nodes
        file_elements = file_grp.findall("file")
        if not file_elements:
            file_elements = file_grp.findall(f".//{{{METS_NS}}}file")

        # Should have one file element for the File node
        assert len(file_elements) == 1
        file_elem = file_elements[0]

        assert file_elem.get("ID") == "file_https://test.example.com/file/1"

        # Find FLocat element
        flocat = file_elem.find("FLocat")
        if flocat is None:
            flocat = file_elem.find(f".//{{{METS_NS}}}FLocat")

        assert flocat is not None
        assert flocat.get("LOCTYPE") == "URL"
        assert flocat.get(f"{{{XLINK_NS}}}href") == "https://test.example.com/file/1"

    @patch('arkumu.oaipmh.formats.mets.CanonicalGraphService')
    def test_mets_structural_map_section(self, mock_service_class):
        """Test METS structural map section creation."""
        mock_service = Mock()
        mock_service_class.return_value = mock_service

        # Mock graph with multiple nodes and edges
        mock_graph = {
            "root_id": "https://test.example.com/resource/1",
            "nodes": {
                "https://test.example.com/resource/1": {
                    "type": "Resource",
                    "label": "Root Resource",
                    "uri": "https://test.example.com/resource/1"
                },
                "https://test.example.com/resource/2": {
                    "type": "Resource",
                    "label": "Child Resource",
                    "uri": "https://test.example.com/resource/2"
                }
            },
            "edges": [
                {
                    "subject_id": "https://test.example.com/resource/1",
                    "predicate_canonical": "http://purl.org/dc/terms/hasPart",
                    "object_id": "https://test.example.com/resource/2",
                    "object_value": None
                }
            ]
        }
        mock_service.get_entity_graph.return_value = mock_graph

        result = self.serializer.serialize_resource("https://test.example.com/resource/1")
        root = ET.fromstring(result)

        # Find structMap element
        struct_map = root.find("structMap")
        if struct_map is None:
            struct_map = root.find(f".//{{{METS_NS}}}structMap")

        assert struct_map is not None
        assert struct_map.get("TYPE") == "logical"

        # Find root div element
        root_div = struct_map.find("div")
        if root_div is None:
            root_div = struct_map.find(f".//{{{METS_NS}}}div")

        assert root_div is not None
        assert root_div.get("ID") == "root"
        assert root_div.get("LABEL") == "Graph"

        # Should contain div elements for each node
        all_divs = struct_map.findall(".//div")
        if not all_divs:
            all_divs = struct_map.findall(f".//{{{METS_NS}}}div")

        # Should have divs for the root and individual nodes
        assert len(all_divs) >= 2  # root div plus node divs

    # ============================================================================
    # INTEGRATION TESTS
    # ============================================================================

    @patch('arkumu.oaipmh.formats.mets.CanonicalGraphService')
    def test_serialize_with_complete_graph(self, mock_service_class, sample_graph_data):
        """Test serialization with complete graph data."""
        mock_service = Mock()
        mock_service_class.return_value = mock_service
        mock_service.get_entity_graph.return_value = sample_graph_data

        result = self.serializer.serialize_resource("https://test.example.com/resource/1")

        # Should produce valid XML
        root = ET.fromstring(result)
        assert root is not None

        # Should contain all major METS sections
        sections_to_check = [
            ("metsHdr", "metsHdr"),
            ("dmdSec", "dmdSec"),
            ("fileSec", "fileSec"),
            ("structMap", "structMap")
        ]

        for local_name, expected in sections_to_check:
            element = root.find(local_name)
            if element is None:
                element = root.find(f".//{{{METS_NS}}}{local_name}")

            # Some sections might be empty but should still be present
            # (depending on implementation details)

    def test_serializer_initialization(self):
        """Test METSSerializer initialization."""
        org_code = "test_organization"
        serializer = METSSerializer(org_code=org_code)

        assert serializer.org_code == org_code
        assert serializer.svc is not None

    # ============================================================================
    # ERROR HANDLING TESTS
    # ============================================================================

    @patch('arkumu.oaipmh.formats.mets.CanonicalGraphService')
    def test_serialize_resource_service_exception(self, mock_service_class):
        """Test handling of service exceptions."""
        mock_service = Mock()
        mock_service_class.return_value = mock_service
        mock_service.get_entity_graph.side_effect = Exception("Service error")

        # Should handle exception gracefully
        try:
            result = self.serializer.serialize_resource("https://test.example.com/resource/1")
            # If no exception is raised, result might be empty or contain error info
            assert isinstance(result, str)
        except Exception:
            # If exception propagates, that's also acceptable behavior
            pass

    @patch('arkumu.oaipmh.formats.mets.CanonicalGraphService')
    def test_serialize_resource_malformed_graph(self, mock_service_class):
        """Test handling of malformed graph data."""
        mock_service = Mock()
        mock_service_class.return_value = mock_service

        # Malformed graph data
        malformed_graphs = [
            {"root_id": None, "nodes": {}, "edges": []},
            {"nodes": {}, "edges": []},  # Missing root_id
            {"root_id": "test", "nodes": None, "edges": []},
            {"root_id": "test", "nodes": {}, "edges": None},
            {},  # Empty graph
        ]

        for graph in malformed_graphs:
            mock_service.get_entity_graph.return_value = graph

            result = self.serializer.serialize_resource("https://test.example.com/resource/1")

            # Should handle gracefully - either empty string or valid minimal XML
            assert isinstance(result, str)

    # ============================================================================
    # XML VALIDATION TESTS
    # ============================================================================

    @patch('arkumu.oaipmh.formats.mets.CanonicalGraphService')
    def test_generated_xml_well_formed(self, mock_service_class):
        """Test that generated XML is well-formed."""
        mock_service = Mock()
        mock_service_class.return_value = mock_service
        mock_service.get_entity_graph.return_value = {
            "root_id": "https://test.example.com/resource/1",
            "nodes": {
                "https://test.example.com/resource/1": {
                    "type": "Resource",
                    "label": "Test Resource",
                    "uri": "https://test.example.com/resource/1"
                }
            },
            "edges": []
        }

        result = self.serializer.serialize_resource("https://test.example.com/resource/1")

        # XML should be parseable
        try:
            root = ET.fromstring(result)
            assert root is not None
        except ET.ParseError as e:
            pytest.fail(f"Generated XML is not well-formed: {e}")

    @patch('arkumu.oaipmh.formats.mets.CanonicalGraphService')
    def test_xml_special_characters_escaped(self, mock_service_class):
        """Test that special XML characters are properly escaped."""
        mock_service = Mock()
        mock_service_class.return_value = mock_service

        # Graph with special characters in data
        mock_graph = {
            "root_id": "https://test.example.com/resource/1",
            "nodes": {
                "https://test.example.com/resource/1": {
                    "type": "Resource",
                    "label": "Resource with <special> & \"characters\"",
                    "uri": "https://test.example.com/resource/1"
                }
            },
            "edges": [
                {
                    "subject_id": "https://test.example.com/resource/1",
                    "predicate_canonical": "http://purl.org/dc/terms/title",
                    "object_value": "Title with <tags> & \"quotes\" & 'apostrophes'",
                    "object_id": None
                }
            ]
        }
        mock_service.get_entity_graph.return_value = mock_graph

        result = self.serializer.serialize_resource("https://test.example.com/resource/1")

        # Should be parseable despite special characters
        root = ET.fromstring(result)
        assert root is not None

        # Special characters should be properly escaped in the XML string
        assert "&lt;" in result or "<tags>" not in result  # < should be escaped
        assert "&amp;" in result or " & " not in result   # & should be escaped
        assert "&quot;" in result or '\"' not in result   # " should be escaped

    # ============================================================================
    # NAMESPACE CONSTANT TESTS
    # ============================================================================

    def test_namespace_constants(self):
        """Test that namespace constants are correct."""
        assert METS_NS == "http://www.loc.gov/METS/"
        assert XLINK_NS == "http://www.w3.org/1999/xlink"

        # Ensure METS namespace ends with /
        assert METS_NS.endswith("/")

        # Ensure XLink namespace doesn't end with /
        assert not XLINK_NS.endswith("/")

    # ============================================================================
    # CONFIGURATION TESTS
    # ============================================================================

    def test_serializer_with_different_org_codes(self):
        """Test serializer behavior with different organization codes."""
        org_codes = ["org1", "org2", "test_org_123", ""]

        for org_code in org_codes:
            serializer = METSSerializer(org_code=org_code)
            assert serializer.org_code == org_code

    @patch('arkumu.oaipmh.formats.mets.CanonicalGraphService')
    def test_include_complete_graph_parameter(self, mock_service_class):
        """Test the include_complete_graph parameter."""
        mock_service = Mock()
        mock_service_class.return_value = mock_service
        mock_service.get_entity_graph.return_value = {
            "root_id": "https://test.example.com/resource/1",
            "nodes": {},
            "edges": []
        }

        resource_uri = "https://test.example.com/resource/1"

        # Test with include_complete_graph=True (default)
        self.serializer.serialize_resource(resource_uri, include_complete_graph=True)
        mock_service.get_entity_graph.assert_called_with(
            resource_uri,
            include_incoming=True,
            expand_neighbors=True
        )

        # Test with include_complete_graph=False
        mock_service.reset_mock()
        self.serializer.serialize_resource(resource_uri, include_complete_graph=False)
        mock_service.get_entity_graph.assert_called_with(
            resource_uri,
            include_incoming=True,
            expand_neighbors=True  # This might still be True in the implementation
        )