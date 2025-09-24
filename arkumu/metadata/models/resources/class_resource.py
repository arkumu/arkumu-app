"""
Class resource wrapper for RDF-style entity management.
Represents RDF classes/typenames in the semantic web.
"""

from typing import Optional, Dict, Any
from arkumu.metadata.models.resource import Resource, ResourceType
from .base import BaseResource


class ClassResource(BaseResource):
    """
    Wrapper class for RDF Class resources.
    Represents entity types/classes in the semantic web.
    """

    _resource_type = ResourceType.CLASS

    def __init__(self, resource: Resource):
        """
        Initialize a class resource wrapper.

        Args:
            resource: The underlying Django Resource model instance
        """
        super().__init__(resource)

    @classmethod
    def get_or_create(cls, uri: str, name: str, **kwargs) -> tuple['ClassResource', bool]:
        """
        Get or create a class resource.

        Args:
            uri: URI for the class resource
            name: Name of the class
            **kwargs: Additional fields for creation

        Returns:
            Tuple of (class_resource_instance, was_created)
        """
        resource, created = Resource.objects.get_or_create(
            uri=uri,
            defaults={
                **kwargs,
                "resource_type": cls._resource_type,
                "name": name,
            }
        )
        return cls(resource), created

    @property
    def name(self) -> str:
        """Get the name of this class."""
        return self._resource.name

    def save(self) -> None:
        """
        Save the class resource to the database.
        """
        self._resource.save()
