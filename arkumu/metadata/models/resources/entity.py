"""
Entity resource wrapper for RDF-style entity management.
Represents RDF entities in the semantic web.
"""

from typing import Optional, Dict, Any, List, Union
from django.db import transaction
from arkumu.metadata.models.resource import Resource, ResourceType
from arkumu.metadata.models.triples import Triple
from .base import BaseResource
from .class_resource import ClassResource
from .property import PropertyResource
from arkumu.importer.services.execution.resource_manager import ResourceManager
import uuid



class EntityResource(BaseResource):
    """
    Wrapper class for RDF Entity resources.
    Represents actual entities/data instances in the semantic web.
    """

    _resource_type = ResourceType.ENTITY

    def __init__(self, resource: Resource):
        """
        Initialize an entity resource wrapper.

        Args:
            resource: The underlying Django Resource model instance
        """
        super().__init__(resource)

    @classmethod
    def get_or_create(cls, uri: str, **kwargs) -> tuple['EntityResource', bool]:
        """
        Get or create an entity resource.

        Args:
            uri: URI for the entity resource
            **kwargs: Additional fields for creation

        Returns:
            Tuple of (entity_resource_instance, was_created)
        """
        resource, created = Resource.objects.get_or_create(
            uri=uri,
            defaults={
                **kwargs,
                "resource_type": cls._resource_type,
            }
        )
        return cls(resource), created
    
    @classmethod
    def create_by_organization_and_dataset_name(cls, organization: str, dataset_name:str, base_uri: str = "http://arkumu.org/data", **kwargs) -> tuple['EntityResource', bool]:
        """
        Create an entity resource for a specified Organization 

        Args:
            organization: Organization object
            dataset_name: Name of the dataset for which a new entity will be created
            **kwargs: Additional fields for creation

        Returns:
            Tuple of (entity_resource_instance, was_created)
        """
        resource_manager = ResourceManager(
            organization=organization,
            base_uri=base_uri
        )
        entity_id = uuid.uuid4()
        uri = resource_manager.generate_entity_uri(dataset_name=dataset_name, entity_id=entity_id)
        return cls.get_or_create(uri=uri)

    @property
    def name(self) -> str:
        """Get the name of this entity."""
        return self._resource.name

    def set_type(self, class_resource: ClassResource) -> None:
        """
        Set the type/class of this entity using rdf:type relationship.

        Args:
            class_resource: The class resource this entity should be an instance of
        """
        # Create rdf:type relationship - using the same approach as existing code
        with transaction.atomic():
            rdf_type_resource = Resource.objects.get(uri="http://www.w3.org/1999/02/22-rdf-syntax-ns#type")
            # Direct creation of triple using string predicate (avoiding potential UUID issues)
            Triple.objects.create(
                subject=self._resource,
                predicate=rdf_type_resource,
                object=class_resource._resource
            )

    def set_property(self, property_resource: PropertyResource, value: Union[str, int, float, 'EntityResource']) -> None:
        """
        Set a property value for this entity.

        Args:
            property_resource: The property resource to set
            value: The value (can be string, number, or another EntityResource)
        """
        with transaction.atomic():
            # Handle different value types
            if isinstance(value, EntityResource):
                # Create a relationship to another entity
                Triple.objects.create(
                    subject=self._resource,
                    predicate=property_resource._resource,
                    object=value._resource
                )
            else:
                # Create a literal value
                from arkumu.metadata.models.resource import Resource as ResourceModel

                # Get or create literal resource
                literal_resource, _ = ResourceModel.objects.get_or_create(
                    resource_type=ResourceType.LITERAL,
                    value=str(value),
                    defaults={
                        "name": str(value)[:100],
                    }
                )

                # Create the relationship with literal value
                Triple.objects.create(
                    subject=self._resource,
                    predicate=property_resource._resource,
                    object=literal_resource
                )

    def get_property(self, property_resource: PropertyResource) -> List[Union[str, 'EntityResource']]:
        """
        Get the values for a specific property of this entity.

        Args:
            property_resource: The property resource to get values for

        Returns:
            List of property values (strings or EntityResources)
        """
        # Get triples where this entity is the subject and property is the predicate
        triples = Triple.objects.filter(
            subject=self._resource,
            predicate=property_resource._resource
        )

        results = []
        for triple in triples:
            # If object is an entity
            if triple.object.resource_type == ResourceType.ENTITY:
                results.append(EntityResource(triple.object))
            # If object is a literal
            elif triple.object.resource_type == ResourceType.LITERAL:
                results.append(triple.object.value)
            # If object is another resource type, return as URI string
            else:
                results.append(triple.object.uri)

        return results

    def save(self) -> None:
        """
        Save the entity resource to the database.
        """
        self._resource.save()
