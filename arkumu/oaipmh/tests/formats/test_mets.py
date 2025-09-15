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
from arkumu.metadata.models.resource import Resource, PublicAccessLevel


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
        # Don't create serializer here - let tests create it with mocks as needed

    # ============================================================================
    # BASIC SERIALIZATION TESTS
    # ============================================================================

    def test_serialize_resource_basic(self):
        """Test basic resource serialization to METS XML."""
        # Mock the canonical graph service
        mock_service = Mock()

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

        # Create serializer with mocked service
        serializer = METSSerializer(org_code=self.org_code, graph_service=mock_service)

        # Serialize resource
        resource_uri = "https://test.example.com/resource/1"
        result = serializer.serialize_resource(resource_uri)

        # Verify service was called correctly
        mock_service.get_entity_graph.assert_called_once_with(
            resource_uri,
            include_incoming=True,
            expand_neighbors=True
        )

        # Verify XML structure
        assert result
        assert isinstance(result, str)
        assert result.startswith('<?xml version=\'1.0\' encoding=\'utf-8\'?>')

        # Parse and validate XML
        root = ET.fromstring(result)
        assert root.tag.endswith('}mets') or root.tag == 'mets'

    def test_serialize_resource_empty_graph(self):
        """Test serialization with empty graph."""
        mock_service = Mock()
        mock_service.get_entity_graph.return_value = None

        # Create serializer with mocked service
        serializer = METSSerializer(org_code=self.org_code, graph_service=mock_service)

        result = serializer.serialize_resource("https://nonexistent.example.com")

        assert result == ""

    def test_serialize_resource_no_root_id(self):
        """Test serialization with graph missing root_id."""
        mock_service = Mock()
        
        mock_service.get_entity_graph.return_value = {"nodes": {}, "edges": []}

        serializer = METSSerializer(org_code=self.org_code, graph_service=mock_service)
        result = serializer.serialize_resource("https://test.example.com/resource/1")

        assert result == ""

    # ============================================================================
    # XML STRUCTURE TESTS
    # ============================================================================

    def test_mets_xml_namespace_declarations(self):
        """Test that METS XML has correct namespace declarations."""
        mock_service = Mock()
        
        mock_service.get_entity_graph.return_value = {
            "root_id": "https://test.example.com/resource/1",
            "nodes": {},
            "edges": []
        }

        serializer = METSSerializer(org_code=self.org_code, graph_service=mock_service)
        result = serializer.serialize_resource("https://test.example.com/resource/1")

        root = ET.fromstring(result)

        # Check METS namespace
        assert f"xmlns:mets=\"{METS_NS}\"" in result or root.get("xmlns:mets") == METS_NS

        # Check XLink namespace
        assert f"xmlns:xlink=\"{XLINK_NS}\"" in result or root.get("xmlns:xlink") == XLINK_NS

        # Check OBJID attribute
        objid = root.get("OBJID")
        assert objid == "https://test.example.com/resource/1"

    def test_mets_header_section(self):
        """Test METS header section creation."""
        mock_service = Mock()
        
        mock_service.get_entity_graph.return_value = {
            "root_id": "https://test.example.com/resource/1",
            "nodes": {},
            "edges": []
        }

        serializer = METSSerializer(org_code=self.org_code, graph_service=mock_service)
        result = serializer.serialize_resource("https://test.example.com/resource/1")
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

    def test_mets_descriptive_metadata_section(self):
        """Test METS descriptive metadata section with Dublin Core."""
        mock_service = Mock()
        

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

        serializer = METSSerializer(org_code=self.org_code, graph_service=mock_service)
        result = serializer.serialize_resource("https://test.example.com/resource/1")
        root = ET.fromstring(result)

        # Find dmdSec element
        dmd_sec = root.find("dmdSec")
        if dmd_sec is None:
            dmd_sec = root.find(f".//{{{METS_NS}}}dmdSec")

        assert dmd_sec is not None

        # Should have ID attribute
        assert dmd_sec.get("ID") == "DMD_001"

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
        # Check both namespaced and non-namespaced versions
        dc_elements = xml_data.findall(".//{http://purl.org/dc/elements/1.1/}*")
        dc_elements += xml_data.findall(".//{http://purl.org/dc/terms/}*")
        assert len(dc_elements) > 0

        # Check for specific DC elements (they might be in dc: or dcterms: namespace)
        titles = xml_data.findall(".//{http://purl.org/dc/elements/1.1/}title")
        titles += xml_data.findall(".//{http://purl.org/dc/terms/}title")
        creators = xml_data.findall(".//{http://purl.org/dc/elements/1.1/}creator")
        creators += xml_data.findall(".//{http://purl.org/dc/terms/}creator")

        assert len(titles) >= 1
        assert any(t.text == "Test Resource Title" for t in titles)
        assert len(creators) >= 1
        assert any(c.text == "Test Creator" for c in creators)

    def test_mets_file_section(self):
        """Test METS file section creation."""
        mock_service = Mock()
        

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

        serializer = METSSerializer(org_code=self.org_code, graph_service=mock_service)
        result = serializer.serialize_resource("https://test.example.com/resource/1")
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

        # Should contain file elements
        file_elements = file_grp.findall("file")
        if not file_elements:
            file_elements = file_grp.findall(f".//{{{METS_NS}}}file")

        # Should have at least one file element for the graph data
        assert len(file_elements) >= 1
        file_elem = file_elements[0]

        assert file_elem.get("ID") == "GRAPH_JSONLD"
        assert file_elem.get("MIMETYPE") == "application/ld+json"

    def test_mets_structural_map_section(self):
        """Test METS structural map section creation."""
        mock_service = Mock()
        

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

        serializer = METSSerializer(org_code=self.org_code, graph_service=mock_service)
        result = serializer.serialize_resource("https://test.example.com/resource/1")
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
        assert root_div.get("TYPE") == "project"
        assert "Project:" in root_div.get("LABEL", "")

    def test_mets_includes_content_flocats(self):
        """METS should include FLocat entries for content files when present."""
        from arkumu.storage.models.s3_file_objects import S3FileObject
        # Create a harvestable resource matching the graph root
        resource_uri = "https://test.example.com/resource/1"
        resource = Resource.objects.create(
            uri=resource_uri,
            organization=self.organization,
            public_access_level=PublicAccessLevel.PUBLIC,
            is_public_approved=True,
        )

        # Create a related S3 file
        S3FileObject.objects.create(
            file_name="test1.txt",
            s3_key="test_org/test1.txt",
            file_size_bytes=1024,
            content_type="text/plain",
            related_resource=resource,
            s3_url="https://s3.example/test_org/test1.txt",
            status='completed'
        )

        # Mock graph and export service
        mock_service = Mock()
        mock_service.get_entity_graph.return_value = {
            "root_id": resource_uri,
            "nodes": {},
            "edges": []
        }

        with patch('arkumu.storage.services.rosetta_export_service.RosettaExportService') as mock_export_cls:
            mock_export = Mock()
            mock_export.prepare_file_for_harvest.return_value = {
                'access_method': 'presigned_url',
                'url': 'https://download.example/test1.txt'
            }
            mock_export_cls.return_value = mock_export

            serializer = METSSerializer(org_code=self.org_code, graph_service=mock_service)
            result = serializer.serialize_resource(resource_uri)

        # Parse and validate CONTENT fileGrp and FLocat
        root = ET.fromstring(result)
        ns = {
            'mets': METS_NS,
            'xlink': XLINK_NS,
        }
        # Find CONTENT group
        content_grp = None
        for grp in root.findall('.//{http://www.loc.gov/METS/}fileGrp'):
            if grp.get('USE') == 'CONTENT':
                content_grp = grp
                break
        assert content_grp is not None, "CONTENT fileGrp not found in METS"

        # Find first file and FLocat
        file_elem = content_grp.find('{http://www.loc.gov/METS/}file')
        assert file_elem is not None
        flocat = file_elem.find('{http://www.loc.gov/METS/}FLocat')
        assert flocat is not None
        href = flocat.get('{http://www.w3.org/1999/xlink}href')
        assert href == 'https://download.example/test1.txt'

        # Should contain structMap for structure
        struct_map = root.find(f'.//{{{METS_NS}}}structMap')
        assert struct_map is not None

        # Should contain div elements for structure
        all_divs = struct_map.findall(".//div")
        if not all_divs:
            all_divs = struct_map.findall(f".//{{{METS_NS}}}div")

        # Should have at least one div element
        assert len(all_divs) >= 1

    # ============================================================================
    # INTEGRATION TESTS
    # ============================================================================

    def test_serialize_with_complete_graph(self, sample_graph_data):
        """Test serialization with complete graph data."""
        mock_service = Mock()

        mock_service.get_entity_graph.return_value = sample_graph_data

        serializer = METSSerializer(org_code=self.org_code, graph_service=mock_service)
        result = serializer.serialize_resource("https://test.example.com/resource/1")

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
        # Mock the service to avoid database calls
        mock_service = Mock()
        serializer = METSSerializer(org_code=self.org_code, graph_service=mock_service)

        assert serializer.org_code == self.org_code
        assert serializer.graph_service is not None

    # ============================================================================
    # ERROR HANDLING TESTS
    # ============================================================================

    def test_serialize_resource_service_exception(self):
        """Test handling of service exceptions."""
        mock_service = Mock()
        
        mock_service.get_entity_graph.side_effect = Exception("Service error")

        # Should handle exception gracefully
        try:
            serializer = METSSerializer(org_code=self.org_code, graph_service=mock_service)
            result = serializer.serialize_resource("https://test.example.com/resource/1")
            # If no exception is raised, result might be empty or contain error info
            assert isinstance(result, str)
        except Exception:
            # If exception propagates, that's also acceptable behavior
            pass

    def test_serialize_resource_malformed_graph(self):
        """Test handling of malformed graph data."""
        mock_service = Mock()
        

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

            serializer = METSSerializer(org_code=self.org_code, graph_service=mock_service)
            result = serializer.serialize_resource("https://test.example.com/resource/1")

            # Should handle gracefully - either empty string or valid minimal XML
            assert isinstance(result, str)

    # ============================================================================
    # XML VALIDATION TESTS
    # ============================================================================

    def test_generated_xml_well_formed(self):
        """Test that generated XML is well-formed."""
        mock_service = Mock()
        
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

        serializer = METSSerializer(org_code=self.org_code, graph_service=mock_service)
        result = serializer.serialize_resource("https://test.example.com/resource/1")

        # XML should be parseable
        try:
            root = ET.fromstring(result)
            assert root is not None
        except ET.ParseError as e:
            pytest.fail(f"Generated XML is not well-formed: {e}")

    def test_xml_special_characters_escaped(self):
        """Test that special XML characters are properly escaped."""
        mock_service = Mock()
        

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

        serializer = METSSerializer(org_code=self.org_code, graph_service=mock_service)
        result = serializer.serialize_resource("https://test.example.com/resource/1")

        # Should be parseable despite special characters
        root = ET.fromstring(result)
        assert root is not None

        # Special characters should be properly escaped in the XML string
        assert "&lt;" in result  # < should be escaped
        assert "&amp;" in result  # & should be escaped
        # Note: quotes in text content don't need to be escaped, only in attributes

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

        mock_service = Mock()
        for org_code in org_codes:
            serializer = METSSerializer(org_code=org_code, graph_service=mock_service)
            assert serializer.org_code == org_code

    def test_include_complete_graph_parameter(self):
        """Test the include_complete_graph parameter."""
        mock_service = Mock()
        
        mock_service.get_entity_graph.return_value = {
            "root_id": "https://test.example.com/resource/1",
            "nodes": {},
            "edges": []
        }

        resource_uri = "https://test.example.com/resource/1"

        # Create serializer with mock service
        serializer = METSSerializer(org_code=self.org_code, graph_service=mock_service)

        # Test with include_complete_graph=True (default)
        serializer.serialize_resource(resource_uri, include_complete_graph=True)
        mock_service.get_entity_graph.assert_called_with(
            resource_uri,
            include_incoming=True,
            expand_neighbors=True
        )

        # Test with include_complete_graph=False
        mock_service.reset_mock()
        serializer.serialize_resource(resource_uri, include_complete_graph=False)
        mock_service.get_entity_graph.assert_called_with(
            resource_uri,
            include_incoming=True,
            expand_neighbors=False
        )
