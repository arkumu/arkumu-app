"""
Property resource wrapper for RDF-style entity management.
Represents RDF properties/predicates in the semantic web.
"""

from typing import Optional, Dict, Any
from arkumu.metadata.models.resource import Resource, ResourceType
from .base import BaseResource


class PropertyResource(BaseResource):
    """
    Wrapper class for RDF Property resources.
    Represents properties/predicates in the semantic web.
    """

    _resource_type = ResourceType.PROPERTY

    def __init__(self, resource: Resource):
        """
        Initialize a property resource wrapper.

        Args:
            resource: The underlying Django Resource model instance
        """
        super().__init__(resource)

    @classmethod
    def get_or_create(cls, canonical_uri: str, name: str, **kwargs) -> tuple['PropertyResource', bool]:
        """
        Get or create a property resource.

        Args:
            uri: URI for the property resource
            name: Name of the property
            **kwargs: Additional fields for creation

        Returns:
            Tuple of (property_resource_instance, was_created)
        """
        resource, created = Resource.objects.get_or_create(
            canonical_uri=canonical_uri,
            defaults={
                **kwargs,
                "resource_type": cls._resource_type,
                "name": name,
            }
        )
        return cls(resource), created

    @property
    def name(self) -> str:
        """Get the name of this property."""
        return self._resource.name

    def save(self) -> None:
        """
        Save the property resource to the database.
        """
        self._resource.save()
