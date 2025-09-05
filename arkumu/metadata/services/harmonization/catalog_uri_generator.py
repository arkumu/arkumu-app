"""
Catalog URI Generator

Generates catalog-level URIs for harmonized properties and classes.
Uses the same URI patterns as the rest of the system but with a dedicated catalog namespace.
"""

from arkumu.common.uri_utils import mint_uri, slugify_uri_part


class CatalogUriGenerator:
    """
    Generates standardized URIs for catalog-level properties and classes
    following existing URI conventions.
    """
    
    DEFAULT_CATALOG_BASE_URI = "http://arkumu.org/data/catalog/"
    CATALOG_INSTITUTION_CODE = "catalog"  # Pre-slugified institution code
    
    def __init__(self, base_uri: str = None):
        """
        Initialize the catalog URI generator.
        
        Args:
            base_uri: Base URI for catalog resources. Defaults to DEFAULT_CATALOG_BASE_URI
        """
        self.base_uri = base_uri or self.DEFAULT_CATALOG_BASE_URI
    
    def generate_property_uri(self, property_name: str) -> str:
        """
        Generate catalog-level property URI.
        
        Args:
            property_name: Name of the property to generate URI for
            
        Returns:
            str: Full URI for the catalog property
            
        Example:
            >>> generator = CatalogUriGenerator()
            >>> generator.generate_property_uri("artwork_title")
            'http://arkumu.org/data/catalog/catalog/properties/artwork-title'
        """
        return mint_uri(
            self.base_uri,
            self.CATALOG_INSTITUTION_CODE,
            "properties",
            property_name
        )
    
    def generate_class_uri(self, class_name: str) -> str:
        """
        Generate catalog-level class URI.
        
        Args:
            class_name: Name of the class to generate URI for
            
        Returns:
            str: Full URI for the catalog class
            
        Example:
            >>> generator = CatalogUriGenerator()
            >>> generator.generate_class_uri("Artwork") 
            'http://arkumu.org/data/catalog/catalog/classes/artwork'
        """
        return mint_uri(
            self.base_uri,
            self.CATALOG_INSTITUTION_CODE,
            "classes",
            class_name
        )
    
    def generate_concept_uri(self, concept_name: str) -> str:
        """
        Generate catalog-level concept URI for controlled vocabularies.
        
        Args:
            concept_name: Name of the concept to generate URI for
            
        Returns:
            str: Full URI for the catalog concept
            
        Example:
            >>> generator = CatalogUriGenerator()
            >>> generator.generate_concept_uri("Digital Media")
            'http://arkumu.org/data/catalog/catalog/concepts/digital-media'
        """
        return mint_uri(
            self.base_uri,
            self.CATALOG_INSTITUTION_CODE,
            "concepts",
            concept_name
        )
    
    def generate_vocabulary_uri(self, vocabulary_name: str) -> str:
        """
        Generate catalog-level vocabulary URI.
        
        Args:
            vocabulary_name: Name of the vocabulary to generate URI for
            
        Returns:
            str: Full URI for the catalog vocabulary
            
        Example:
            >>> generator = CatalogUriGenerator()
            >>> generator.generate_vocabulary_uri("Media Types")
            'http://arkumu.org/data/catalog/catalog/vocabularies/media-types'
        """
        return mint_uri(
            self.base_uri,
            self.CATALOG_INSTITUTION_CODE,
            "vocabularies",
            vocabulary_name
        )
    
    def generate_mapping_uri(self, source_org_code: str, mapping_id: str = None) -> str:
        """
        Generate URI for a specific harmonization mapping.
        
        Args:
            source_org_code: Code of the source organization
            mapping_id: Optional specific mapping identifier
            
        Returns:
            str: Full URI for the mapping
            
        Example:
            >>> generator = CatalogUriGenerator()
            >>> generator.generate_mapping_uri("khm", "title-mapping-001")
            'http://arkumu.org/data/catalog/catalog/mappings/khm/title-mapping-001'
        """
        if mapping_id:
            return mint_uri(
                self.base_uri,
                self.CATALOG_INSTITUTION_CODE,
                "mappings",
                source_org_code,
                mapping_id
            )
        else:
            return mint_uri(
                self.base_uri,
                self.CATALOG_INSTITUTION_CODE, 
                "mappings",
                source_org_code
            )
    
    def is_catalog_uri(self, uri: str) -> bool:
        """
        Check if a URI belongs to the catalog namespace.
        
        Args:
            uri: URI to check
            
        Returns:
            bool: True if URI is in catalog namespace
        """
        return uri.startswith(self.base_uri)
    
    def extract_catalog_identifier(self, catalog_uri: str) -> str:
        """
        Extract the identifier part from a catalog URI.
        
        Args:
            catalog_uri: Full catalog URI
            
        Returns:
            str: The identifier portion of the URI
            
        Example:
            >>> generator = CatalogUriGenerator()
            >>> uri = 'http://arkumu.org/data/catalog/catalog/properties/title'
            >>> generator.extract_catalog_identifier(uri)
            'title'
        """
        if not self.is_catalog_uri(catalog_uri):
            raise ValueError(f"URI {catalog_uri} is not a catalog URI")
        
        # Remove base URI and institution code to get the remaining path
        prefix = f"{self.base_uri}{self.CATALOG_INSTITUTION_CODE}/"
        if not catalog_uri.startswith(prefix):
            raise ValueError(f"Unexpected catalog URI format: {catalog_uri}")
        
        remaining_path = catalog_uri[len(prefix):]
        
        # Extract the last part as the identifier
        parts = remaining_path.split('/')
        if len(parts) >= 2:
            return parts[-1]  # Return the last part (the actual identifier)
        else:
            return remaining_path