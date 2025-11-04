"""
Literal resource wrapper for RDF-style entity management.
Represents RDF literal values in the semantic web.
"""

from typing import Optional, Dict, Any
from arkumu.metadata.models.resource import Resource, ResourceType
from .base import BaseResource
from arkumu.common.uri_utils import normalize_text_input


class LiteralResource(BaseResource):
    """
    Wrapper class for RDF Literal resources.
    Represents literal values in the semantic web.
    """

    _resource_type = ResourceType.LITERAL

    def __init__(self, resource: Resource):
        """
        Initialize a literal resource wrapper.

        Args:
            resource: The underlying Django Resource model instance
        """
        super().__init__(resource)

    @classmethod
    def get_or_create(cls, value: str, datatype: Optional[str] = None, language: Optional[str] = None, **kwargs) -> tuple['LiteralResource', bool]:
        """
        Get or create a literal resource.

        Args:
            value: The literal value
            datatype: Optional datatype URI (e.g., xsd:string, xsd:integer)
            language: Optional language tag (e.g., 'en', 'de')
            **kwargs: Additional fields for creation

        Returns:
            Tuple of (literal_resource_instance, was_created)
        """
        # Create a hash for deduplication
        from arkumu.common.hash_utils import generate_value_hash
        normalized_value = normalize_text_input(value)
        if normalized_value is None:
            raise ValueError("Literal value cannot be empty")
        value_hash = generate_value_hash(normalized_value)

        resource, created = Resource.objects.get_or_create(
            value_hash=value_hash,
            value=normalized_value,
            datatype=datatype,
            language=language,
            defaults={
                **kwargs,
                "resource_type": cls._resource_type,
                "value": normalized_value,
                "name": normalized_value[:100],  # Truncate name for display
            }
        )
        return cls(resource), created

    @property
    def value(self) -> str:
        """Get the literal value."""
        return self._resource.value

    @property
    def datatype(self) -> Optional[str]:
        """Get the datatype of this literal."""
        return self._resource.datatype

    @property
    def language(self) -> Optional[str]:
        """Get the language of this literal."""
        return self._resource.language

    def save(self) -> None:
        """
        Save the literal resource to the database.
        """
        self._resource.save()
