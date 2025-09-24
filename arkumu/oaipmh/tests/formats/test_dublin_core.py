"""
Tests for Dublin Core metadata serialization.

Tests the DublinCoreSerializer and its integration with
the canonical graph system for OAI-PMH metadata output.
"""

import pytest
from typing import Dict, List, Any, Optional

from arkumu.oaipmh.formats.dublin_core import (
    DublinCoreSerializer,
    DEFAULT_PREDICATE_MAP,
    OAI_DC_NS,
    DC_NS,
    DCTERMS_NS
)


class TestDublinCoreSerializer:
    """Test Dublin Core serialization functionality."""

    def setup_method(self):
        """Set up test method."""
        self.serializer = DublinCoreSerializer()

    # ============================================================================
    # BASIC SERIALIZATION TESTS
    # ============================================================================

    def test_serialize_basic_properties(self):
        """Test serialization of basic Dublin Core properties."""
        # Mock triples data
        triples = [
            {
                "predicate_canonical": "http://purl.org/dc/terms/title",
                "object_value": "Test Resource Title"
            },
            {
                "predicate_canonical": "http://purl.org/dc/terms/creator",
                "object_value": "Jane Doe"
            },
            {
                "predicate_canonical": "http://purl.org/dc/terms/description",
                "object_value": "A test resource for Dublin Core serialization"
            }
        ]

        def get_predicate(triple: Dict[str, Any]) -> str:
            return triple["predicate_canonical"]

        def get_object_value(triple: Dict[str, Any]) -> Optional[str]:
            return triple["object_value"]

        result = self.serializer.serialize_from_triples(
            triples, get_predicate=get_predicate, get_object_value=get_object_value
        )

        assert isinstance(result, dict)
        assert "dc:title" in result
        assert "dc:creator" in result
        assert "dc:description" in result

        assert result["dc:title"] == ["Test Resource Title"]
        assert result["dc:creator"] == ["Jane Doe"]
        assert result["dc:description"] == ["A test resource for Dublin Core serialization"]

    def test_serialize_multiple_values_same_property(self):
        """Test serialization with multiple values for the same property."""
        triples = [
            {
                "predicate_canonical": "http://purl.org/dc/terms/creator",
                "object_value": "Jane Doe"
            },
            {
                "predicate_canonical": "http://purl.org/dc/terms/creator",
                "object_value": "John Smith"
            },
            {
                "predicate_canonical": "http://purl.org/dc/terms/subject",
                "object_value": "Computer Science"
            },
            {
                "predicate_canonical": "http://purl.org/dc/terms/subject",
                "object_value": "Metadata"
            }
        ]

        def get_predicate(triple: Dict[str, Any]) -> str:
            return triple["predicate_canonical"]

        def get_object_value(triple: Dict[str, Any]) -> Optional[str]:
            return triple["object_value"]

        result = self.serializer.serialize_from_triples(
            triples, get_predicate=get_predicate, get_object_value=get_object_value
        )

        assert len(result["dc:creator"]) == 2
        assert "Jane Doe" in result["dc:creator"]
        assert "John Smith" in result["dc:creator"]

        assert len(result["dc:subject"]) == 2
        assert "Computer Science" in result["dc:subject"]
        assert "Metadata" in result["dc:subject"]

    def test_serialize_all_dublin_core_elements(self):
        """Test serialization of all standard Dublin Core elements."""
        all_dc_properties = [
            ("title", "Test Title"),
            ("creator", "Test Creator"),
            ("subject", "Test Subject"),
            ("description", "Test Description"),
            ("publisher", "Test Publisher"),
            ("contributor", "Test Contributor"),
            ("date", "2023-01-01"),
            ("type", "Text"),
            ("format", "application/pdf"),
            ("identifier", "https://test.example.com/1"),
            ("source", "Original Source"),
            ("language", "en"),
            ("relation", "Related Resource"),
            ("coverage", "Global"),
            ("rights", "CC BY 4.0")
        ]

        triples = []
        for prop, value in all_dc_properties:
            triples.append({
                "predicate_canonical": f"http://purl.org/dc/terms/{prop}",
                "object_value": value
            })

        def get_predicate(triple: Dict[str, Any]) -> str:
            return triple["predicate_canonical"]

        def get_object_value(triple: Dict[str, Any]) -> Optional[str]:
            return triple["object_value"]

        result = self.serializer.serialize_from_triples(
            triples, get_predicate=get_predicate, get_object_value=get_object_value
        )

        # Should have all 15 Dublin Core elements
        assert len(result) == 15

        for prop, expected_value in all_dc_properties:
            dc_key = f"dc:{prop}"
            assert dc_key in result
            assert result[dc_key] == [expected_value]

    # ============================================================================
    # PREDICATE MAPPING TESTS
    # ============================================================================

    def test_default_predicate_mapping(self):
        """Test that default predicate mapping covers all DC terms."""
        expected_mappings = [
            "title", "creator", "subject", "description", "publisher",
            "contributor", "date", "type", "format", "identifier",
            "source", "language", "relation", "coverage", "rights"
        ]

        for term in expected_mappings:
            dcterms_uri = f"{DCTERMS_NS}{term}"

            assert dcterms_uri in DEFAULT_PREDICATE_MAP
            assert DEFAULT_PREDICATE_MAP[dcterms_uri] == term

    def test_custom_predicate_mapping(self):
        """Test serializer with custom predicate mapping."""
        custom_mapping = {
            "http://example.com/title": "title",
            "http://example.com/author": "creator",
            "http://purl.org/dc/terms/title": "title"  # Keep some defaults
        }

        serializer = DublinCoreSerializer(predicate_map=custom_mapping)

        triples = [
            {
                "predicate_canonical": "http://example.com/title",
                "object_value": "Custom Title"
            },
            {
                "predicate_canonical": "http://example.com/author",
                "object_value": "Custom Author"
            },
            {
                "predicate_canonical": "http://purl.org/dc/terms/description",
                "object_value": "This should be ignored"
            }
        ]

        def get_predicate(triple: Dict[str, Any]) -> str:
            return triple["predicate_canonical"]

        def get_object_value(triple: Dict[str, Any]) -> Optional[str]:
            return triple["object_value"]

        result = serializer.serialize_from_triples(
            triples, get_predicate=get_predicate, get_object_value=get_object_value
        )

        assert "dc:title" in result
        assert result["dc:title"] == ["Custom Title"]
        assert "dc:creator" in result
        assert result["dc:creator"] == ["Custom Author"]
        # Description should not appear (not in custom mapping)
        assert "description" not in result

    # ============================================================================
    # EDGE CASE TESTS
    # ============================================================================

    def test_serialize_empty_triples(self):
        """Test serialization with empty triples list."""
        def get_predicate(triple: Dict[str, Any]) -> str:
            return triple["predicate_canonical"]

        def get_object_value(triple: Dict[str, Any]) -> Optional[str]:
            return triple["object_value"]

        result = self.serializer.serialize_from_triples(
            [], get_predicate=get_predicate, get_object_value=get_object_value
        )

        assert result == {}

    def test_serialize_unmapped_predicates(self):
        """Test that unmapped predicates are ignored."""
        triples = [
            {
                "predicate_canonical": "http://purl.org/dc/terms/title",
                "object_value": "Mapped Title"
            },
            {
                "predicate_canonical": "http://example.com/unmapped",
                "object_value": "This should be ignored"
            },
            {
                "predicate_canonical": "http://purl.org/dc/terms/creator",
                "object_value": "Mapped Creator"
            }
        ]

        def get_predicate(triple: Dict[str, Any]) -> str:
            return triple["predicate_canonical"]

        def get_object_value(triple: Dict[str, Any]) -> Optional[str]:
            return triple["object_value"]

        result = self.serializer.serialize_from_triples(
            triples, get_predicate=get_predicate, get_object_value=get_object_value
        )

        assert len(result) == 2
        assert "dc:title" in result
        assert "dc:creator" in result
        # Unmapped predicate should not appear
        assert not any("unmapped" in key for key in result.keys())

    def test_serialize_null_object_values(self):
        """Test that triples with null object values are ignored."""
        triples = [
            {
                "predicate_canonical": "http://purl.org/dc/terms/title",
                "object_value": "Valid Title"
            },
            {
                "predicate_canonical": "http://purl.org/dc/terms/creator",
                "object_value": None
            },
            {
                "predicate_canonical": "http://purl.org/dc/terms/description",
                "object_value": ""
            }
        ]

        def get_predicate(triple: Dict[str, Any]) -> str:
            return triple["predicate_canonical"]

        def get_object_value(triple: Dict[str, Any]) -> Optional[str]:
            return triple["object_value"]

        result = self.serializer.serialize_from_triples(
            triples, get_predicate=get_predicate, get_object_value=get_object_value
        )

        # Only the valid title should be included
        assert len(result) == 1
        assert "dc:title" in result
        assert result["dc:title"] == ["Valid Title"]

    def test_serialize_unicode_content(self):
        """Test serialization with Unicode content."""
        triples = [
            {
                "predicate_canonical": "http://purl.org/dc/terms/title",
                "object_value": "Título en Español"
            },
            {
                "predicate_canonical": "http://purl.org/dc/terms/creator",
                "object_value": "张三"  # Chinese characters
            },
            {
                "predicate_canonical": "http://purl.org/dc/terms/description",
                "object_value": "Description with émojis 🚀 and àccénts"
            }
        ]

        def get_predicate(triple: Dict[str, Any]) -> str:
            return triple["predicate_canonical"]

        def get_object_value(triple: Dict[str, Any]) -> Optional[str]:
            return triple["object_value"]

        result = self.serializer.serialize_from_triples(
            triples, get_predicate=get_predicate, get_object_value=get_object_value
        )

        assert result["dc:title"] == ["Título en Español"]
        assert result["dc:creator"] == ["张三"]
        assert result["dc:description"] == ["Description with émojis 🚀 and àccénts"]

    def test_serialize_whitespace_only_values(self):
        """Test that whitespace-only values are preserved."""
        triples = [
            {
                "predicate_canonical": "http://purl.org/dc/terms/title",
                "object_value": "   "  # Whitespace only
            },
            {
                "predicate_canonical": "http://purl.org/dc/terms/creator",
                "object_value": "\t\n"  # Tab and newline
            }
        ]

        def get_predicate(triple: Dict[str, Any]) -> str:
            return triple["predicate_canonical"]

        def get_object_value(triple: Dict[str, Any]) -> Optional[str]:
            return triple["object_value"]

        result = self.serializer.serialize_from_triples(
            triples, get_predicate=get_predicate, get_object_value=get_object_value
        )

        # Whitespace-only values should be preserved (Dublin Core allows them)
        assert result["dc:title"] == ["   "]
        assert result["dc:creator"] == ["\t\n"]

    # ============================================================================
    # ACCESSOR FUNCTION TESTS
    # ============================================================================

    def test_different_accessor_functions(self):
        """Test serializer with different accessor function implementations."""
        # Mock triples with different structure
        triples = [
            {
                "pred": "http://purl.org/dc/terms/title",
                "obj": "Title Value",
                "extra_field": "ignored"
            },
            {
                "pred": "http://purl.org/dc/terms/creator",
                "obj": "Creator Value"
            }
        ]

        def get_predicate(triple: Dict[str, Any]) -> str:
            return triple["pred"]  # Different key name

        def get_object_value(triple: Dict[str, Any]) -> Optional[str]:
            return triple["obj"]  # Different key name

        result = self.serializer.serialize_from_triples(
            triples, get_predicate=get_predicate, get_object_value=get_object_value
        )

        assert result["dc:title"] == ["Title Value"]
        assert result["dc:creator"] == ["Creator Value"]

    def test_accessor_function_exceptions(self):
        """Test behavior when accessor functions raise exceptions."""
        triples = [
            {"valid": True, "predicate": "http://purl.org/dc/terms/title", "value": "Title"},
            {"valid": False}  # This will cause accessor to fail
        ]

        def get_predicate(triple: Dict[str, Any]) -> str:
            if not triple.get("valid"):
                raise KeyError("Missing predicate")
            return triple["predicate"]

        def get_object_value(triple: Dict[str, Any]) -> Optional[str]:
            if not triple.get("valid"):
                raise KeyError("Missing value")
            return triple["value"]

        # Should handle exceptions gracefully and continue with valid triples
        result = self.serializer.serialize_from_triples(
            triples, get_predicate=get_predicate, get_object_value=get_object_value
        )

        # Should only include the valid triple
        assert len(result) == 1
        assert result["dc:title"] == ["Title"]

    # ============================================================================
    # INTEGRATION TESTS WITH SAMPLE DATA
    # ============================================================================

    def test_serialize_with_sample_graph_data(self, sample_graph_data):
        """Test serialization with sample graph data from conftest."""
        edges = sample_graph_data["edges"]

        def get_predicate(edge: Dict[str, Any]) -> str:
            return edge["predicate_canonical"]

        def get_object_value(edge: Dict[str, Any]) -> Optional[str]:
            return edge["object_value"]

        result = self.serializer.serialize_from_triples(
            edges, get_predicate=get_predicate, get_object_value=get_object_value
        )

        # Based on sample_graph_data fixture
        assert "dc:title" in result
        assert result["dc:title"] == ["Sample Resource Title"]

        assert "dc:creator" in result
        assert len(result["dc:creator"]) == 2
        assert "Jane Doe" in result["dc:creator"]
        assert "John Smith" in result["dc:creator"]

        assert "dc:subject" in result
        assert result["dc:subject"] == ["Test Subject"]

    def test_serialize_large_dataset(self):
        """Test serialization performance with large dataset."""
        # Create 1000 triples
        triples = []
        for i in range(1000):
            property_name = ["title", "creator", "subject", "description"][i % 4]
            triples.append({
                "predicate_canonical": f"http://purl.org/dc/terms/{property_name}",
                "object_value": f"Value {i}"
            })

        def get_predicate(triple: Dict[str, Any]) -> str:
            return triple["predicate_canonical"]

        def get_object_value(triple: Dict[str, Any]) -> Optional[str]:
            return triple["object_value"]

        result = self.serializer.serialize_from_triples(
            triples, get_predicate=get_predicate, get_object_value=get_object_value
        )

        # Should have 4 properties, each with 250 values
        assert len(result) == 4
        for key in ["dc:title", "dc:creator", "dc:subject", "dc:description"]:
            assert key in result
            assert len(result[key]) == 250

    # ============================================================================
    # NAMESPACE CONSTANT TESTS
    # ============================================================================

    def test_namespace_constants(self):
        """Test that namespace constants are correct."""
        assert OAI_DC_NS == "http://www.openarchives.org/OAI/2.0/oai_dc/"
        assert DC_NS == "http://purl.org/dc/elements/1.1/"
        assert DCTERMS_NS == "http://purl.org/dc/terms/"

        # Ensure they end with proper separators
        assert OAI_DC_NS.endswith("/")
        assert DC_NS.endswith("/")
        assert DCTERMS_NS.endswith("/")

    def test_default_predicate_map_uses_correct_namespaces(self):
        """Test that default predicate map uses correct namespaces."""
        arkumu_prefix = "http://arkumu.org/data/properties/"

        for predicate_uri, dc_term in DEFAULT_PREDICATE_MAP.items():
            if predicate_uri.startswith(DCTERMS_NS):
                dcterms_term = predicate_uri[len(DCTERMS_NS):]
                assert dcterms_term == dc_term or dc_term == "date"
            else:
                assert predicate_uri.startswith(arkumu_prefix)
                assert dc_term in {
                    "title",
                    "description",
                    "identifier",
                    "relation",
                    "subject",
                    "rights",
                    "language",
                    "coverage",
                    "date",
                    "type",
                    "format",
                }
