"""
Base resource wrapper class for RDF-style resource management.
All resource types should inherit from this base class.
"""

from typing import Optional, Any, Dict, List, Union
from django.db import transaction
from arkumu.metadata.models.resource import Resource, ResourceType
from arkumu.metadata.models.triples import Triple


class BaseResource:
    """
    Base class for all resource wrapper classes.
    Provides common functionality for resource creation and management.
    """

    def __init__(self, resource: Resource):
        """
        Initialize a resource wrapper with an existing Resource instance.

        Args:
            resource: The underlying Django Resource model instance
        """
        self._resource = resource

    @property
    def uri(self) -> str:
        """Get the URI of this resource."""
        return self._resource.uri

    @property
    def resource_type(self) -> str:
        """Get the resource type."""
        return self._resource.resource_type

    @property
    def name(self) -> str:
        """Get the name of this resource."""
        return self._resource.name

    @property
    def id(self) -> str:
        """Get the internal ID of this resource."""
        return str(self._resource.id)

    def save(self) -> None:
        """
        Save the resource to the database.
        This should be called after any modifications to ensure persistence.
        """
        self._resource.save()

    def __str__(self) -> str:
        """String representation of the resource."""
        return f"{self.__class__.__name__}({self.uri})"

    def __repr__(self) -> str:
        """Developer representation of the resource."""
        return f"<{self.__class__.__name__}: {self.uri}>"

    @classmethod
    def get_or_create(cls, uri: str, **kwargs) -> tuple['BaseResource', bool]:
        """
        Get or create a resource of this type.

        Args:
            uri: URI for the resource
            **kwargs: Additional fields for creation

        Returns:
            Tuple of (resource_instance, was_created)
        """
        resource, created = Resource.objects.get_or_create(
            uri=uri,
            defaults={**kwargs, "resource_type": cls._resource_type}
        )
        return cls(resource), created

    def get_triples(self, predicate: Optional[str] = None) -> List[Triple]:
        """
        Get triples where this resource is the subject.

        Args:
            predicate: Optional predicate URI to filter by

        Returns:
            List of Triples
        """
        query = Triple.objects.filter(subject=self._resource)
        if predicate:
            query = query.filter(predicate=predicate)
        return list(query)
