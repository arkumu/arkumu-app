"""
Tests for CatalogUriGenerator
"""

import pytest
from arkumu.metadata.services.harmonization.catalog_uri_generator import CatalogUriGenerator


class TestCatalogUriGenerator:
    """Test cases for CatalogUriGenerator."""
    
    def test_default_initialization(self):
        """Test generator initializes with defaults."""
        generator = CatalogUriGenerator()
        
        assert generator.base_uri == "http://arkumu.org/data/catalog/"
        assert generator.CATALOG_INSTITUTION_CODE == "catalog"
    
    def test_custom_base_uri(self):
        """Test generator with custom base URI."""
        custom_uri = "http://custom.example.org/catalog/"
        generator = CatalogUriGenerator(base_uri=custom_uri)
        
        assert generator.base_uri == custom_uri
    
    def test_generate_property_uri(self):
        """Test generating property URIs."""
        generator = CatalogUriGenerator()
        
        uri = generator.generate_property_uri("artwork_title")
        expected = "http://arkumu.org/data/catalog/catalog/properties/artwork-title"
        
        assert uri == expected
    
    def test_generate_property_uri_with_special_characters(self):
        """Test property URI generation with special characters."""
        generator = CatalogUriGenerator()
        
        uri = generator.generate_property_uri("Artwork Title & Description")
        
        # Should be slugified
        assert "artwork-title-and-description" in uri
        assert uri.startswith("http://arkumu.org/data/catalog/catalog/properties/")
    
    def test_generate_class_uri(self):
        """Test generating class URIs."""
        generator = CatalogUriGenerator()
        
        uri = generator.generate_class_uri("Artwork")
        expected = "http://arkumu.org/data/catalog/catalog/classes/artwork"
        
        assert uri == expected
    
    def test_generate_concept_uri(self):
        """Test generating concept URIs."""
        generator = CatalogUriGenerator()
        
        uri = generator.generate_concept_uri("Digital Media")
        expected = "http://arkumu.org/data/catalog/catalog/concepts/digital-media"
        
        assert uri == expected
    
    def test_generate_vocabulary_uri(self):
        """Test generating vocabulary URIs."""
        generator = CatalogUriGenerator()
        
        uri = generator.generate_vocabulary_uri("Media Types")
        expected = "http://arkumu.org/data/catalog/catalog/vocabularies/media-types"
        
        assert uri == expected
    
    def test_generate_mapping_uri_with_id(self):
        """Test generating mapping URIs with specific ID."""
        generator = CatalogUriGenerator()
        
        uri = generator.generate_mapping_uri("khm", "title-mapping-001")
        expected = "http://arkumu.org/data/catalog/catalog/mappings/khm/title-mapping-001"
        
        assert uri == expected
    
    def test_generate_mapping_uri_without_id(self):
        """Test generating mapping URIs without specific ID."""
        generator = CatalogUriGenerator()
        
        uri = generator.generate_mapping_uri("khm")
        expected = "http://arkumu.org/data/catalog/catalog/mappings/khm"
        
        assert uri == expected
    
    def test_is_catalog_uri_positive(self):
        """Test identifying catalog URIs correctly."""
        generator = CatalogUriGenerator()
        
        catalog_uri = "http://arkumu.org/data/catalog/catalog/properties/title"
        
        assert generator.is_catalog_uri(catalog_uri) is True
    
    def test_is_catalog_uri_negative(self):
        """Test identifying non-catalog URIs correctly."""
        generator = CatalogUriGenerator()
        
        external_uri = "http://example.org/properties/title"
        
        assert generator.is_catalog_uri(external_uri) is False
    
    def test_extract_catalog_identifier(self):
        """Test extracting identifier from catalog URI."""
        generator = CatalogUriGenerator()
        
        catalog_uri = "http://arkumu.org/data/catalog/catalog/properties/title"
        identifier = generator.extract_catalog_identifier(catalog_uri)
        
        assert identifier == "title"
    
    def test_extract_catalog_identifier_complex(self):
        """Test extracting identifier from complex catalog URI."""
        generator = CatalogUriGenerator()
        
        catalog_uri = "http://arkumu.org/data/catalog/catalog/mappings/khm/title-mapping-001"
        identifier = generator.extract_catalog_identifier(catalog_uri)
        
        assert identifier == "title-mapping-001"
    
    def test_extract_catalog_identifier_invalid_uri(self):
        """Test extracting identifier from non-catalog URI raises error."""
        generator = CatalogUriGenerator()
        
        external_uri = "http://example.org/properties/title"
        
        with pytest.raises(ValueError, match="is not a catalog URI"):
            generator.extract_catalog_identifier(external_uri)
    
    def test_extract_catalog_identifier_malformed_catalog_uri(self):
        """Test extracting identifier from malformed catalog URI raises error."""
        generator = CatalogUriGenerator()
        
        # Missing the catalog institution code part
        malformed_uri = "http://arkumu.org/data/catalog/properties/title"
        
        with pytest.raises(ValueError, match="Unexpected catalog URI format"):
            generator.extract_catalog_identifier(malformed_uri)
    
    def test_uri_consistency(self):
        """Test that generated URIs are consistent with extraction."""
        generator = CatalogUriGenerator()
        
        property_name = "test_property"
        generated_uri = generator.generate_property_uri(property_name)
        
        assert generator.is_catalog_uri(generated_uri)
        
        # Note: The extracted identifier will be slugified
        extracted_id = generator.extract_catalog_identifier(generated_uri)
        assert extracted_id == "test-property"  # Slugified version
    
    def test_custom_base_uri_consistency(self):
        """Test URI generation with custom base URI."""
        custom_base = "http://custom.org/catalog/"
        generator = CatalogUriGenerator(base_uri=custom_base)
        
        uri = generator.generate_property_uri("test_property")
        
        assert uri.startswith(custom_base)
        assert generator.is_catalog_uri(uri)
        
        identifier = generator.extract_catalog_identifier(uri)
        assert identifier == "test-property"