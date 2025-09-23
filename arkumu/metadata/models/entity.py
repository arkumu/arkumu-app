"""
Entity model for working with RDF triples in the metadata system.

This class provides a unified interface for accessing and creating entities
based on RDF triples, supporting both existing data retrieval and new entity creation.
"""

from typing import Dict, List, Optional, Union, Any, Tuple
from django.db import transaction
from django.db.models import QuerySet
from arkumu.metadata.models.resource import Resource, ResourceType
from arkumu.metadata.models.triples import Triple
from arkumu.metadata.utils.rdf_helpers import (
    get_or_create_resource,
    create_triple_if_not_exists,
    add_semantic_triple,
    add_class_to_resource
)
import uuid


class Entity:
    """
    An Entity represents a resource in the RDF knowledge graph.

    It provides methods to:
    - Access existing entities via URIs, IDs, or Triples
    - Create new entities with associated RDF triples
    - Manage entity properties through RDF predicates
    """

    def __init__(self, arg: Union[str, uuid.UUID, Resource, Triple, None] = None):
        """
        Initialize an Entity instance.

        Args:
            arg: Can be a URI string, UUID, Resource object, or Triple object
        """
        self._id: Optional[uuid.UUID] = None
        self._uri: Optional[str] = None
        self._name: Optional[str] = None
        self._properties: Dict[str, List[Union[str, Resource]]] = {}
        self._resources: Dict[str, List[Resource]] = {}
        self._field_names: List[str] = []

        if arg is not None:
            self._initialize_from_arg(arg)

        # Initialize the old-style resources API for backward compatibility
        self.resources = {}  # For backward compatibility with catalog views
        self.properties = {}  # For backward compatibility with catalog views

        # Populate resources for backward compatibility
        self._populate_backward_compatibility()

    def _initialize_from_arg(self, arg):
        """Initialize Entity from various argument types."""
        if isinstance(arg, str):
            self._uri = arg
            self._load_entity_by_uri()
        elif isinstance(arg, uuid.UUID):
            self._id = arg
            self._load_entity_by_id()
        elif isinstance(arg, Resource):
            self._id = arg.id
            self._uri = arg.uri
            self._name = arg.name
            self._load_entity_properties()
        elif isinstance(arg, Triple):
            self._load_entity_from_triple(arg)
        else:
            raise ValueError(f"Cannot initialize Entity from argument of type: {type(arg)}")

    def _load_entity_by_uri(self):
        """Load entity information from URI."""
        try:
            resource = Resource.objects.get(uri=self._uri)
            self._id = resource.id
            self._name = resource.name
            self._load_entity_properties()
        except Resource.DoesNotExist:
            # Entity doesn't exist yet
            self._name = self._extract_name_from_uri(self._uri)

    def _extract_name_from_uri(self, uri: str) -> str:
        """Extract a reasonable name from a URI."""
        # Simple extraction - could be enhanced
        if '#' in uri:
            return uri.split('#')[-1]
        elif '/' in uri:
            return uri.split('/')[-1]
        else:
            return uri

    def _load_entity_by_id(self):
        """Load entity information from ID."""
        try:
            resource = Resource.objects.get(id=self._id)
            self._uri = resource.uri
            self._name = resource.name
            self._load_entity_properties()
        except Resource.DoesNotExist:
            # Entity doesn't exist yet
            self._name = "Unknown"

    def _load_entity_from_triple(self, triple: Triple):
        """Load entity information from a Triple object."""
        # We're using the subject of the triple as our entity
        self._id = triple.subject_id
        self._uri = triple.subject.uri
        self._name = triple.subject.name
        self._load_entity_properties()

    def _load_entity_properties(self):
        """Load all properties (triples) for this entity."""
        # Clear existing properties
        self._properties = {}
        self._resources = {}
        self._field_names = []

        # Retrieve all triples where this entity is the subject
        triples = Triple.objects.filter(subject_id=self._id)

        # Process each triple to build properties
        for triple in triples:
            predicate_name = triple.predicate.name or str(triple.predicate.uri)
            predicate_name_clean = predicate_name

            # Store as property
            if predicate_name_clean not in self._properties:
                self._properties[predicate_name_clean] = []
            self._properties[predicate_name_clean].append(triple.object.uri or triple.object.value)

            # Also store the actual Resource objects
            if predicate_name_clean not in self._resources:
                self._resources[predicate_name_clean] = []
            self._resources[predicate_name_clean].append(triple.object)

            # Track field names for backward compatibility
            if predicate_name_clean not in self._field_names:
                self._field_names.append(predicate_name_clean)

        # Update backward compatibility fields
        self._populate_backward_compatibility()

    def _populate_backward_compatibility(self):
        """Populate the resources and properties dictionaries for backward compatibility."""
        # Copy resource dictionaries (maintains format expected by catalog views)
        self.resources = {}
        for field_name, resources in self._resources.items():
            self.resources[field_name] = resources

        # Properties is also a copy of resources in older API
        self.properties = {}
        for field_name, resource_list in self._resources.items():
            self.properties[field_name] = resource_list

    @property
    def id(self) -> Optional[uuid.UUID]:
        """Get the entity's ID."""
        return self._id

    @property
    def uri(self) -> Optional[str]:
        """Get the entity's URI."""
        return self._uri

    @property
    def name(self) -> Optional[str]:
        """Get the entity's name."""
        return self._name

    def get_property(self, predicate_name: str) -> List[Union[str, Resource]]:
        """
        Get all values for a particular property (predicate).

        Args:
            predicate_name: Name of the property/predicate

        Returns:
            List of values associated with this predicate
        """
        return self._properties.get(predicate_name, [])

    def get_property_resources(self, predicate_name: str) -> List[Resource]:
        """
        Get all Resource objects for a particular property (predicate).

        Args:
            predicate_name: Name of the property/predicate

        Returns:
            List of Resource objects associated with this predicate
        """
        return self._resources.get(predicate_name, [])

    def has_property(self, predicate_name: str) -> bool:
        """
        Check if entity has a particular property.

        Args:
            predicate_name: Name of the property/predicate

        Returns:
            True if property exists, False otherwise
        """
        return predicate_name in self._properties

    @classmethod
    def create_new(cls, uri: str, name: str, resource_type: str = ResourceType.IRI,
                   organization=None, **initial_properties) -> 'Entity':
        """
        Create a new entity with initial properties.

        Args:
            uri: URI for the new entity
            name: Name of the new entity
            resource_type: Type of resource (IRI, LITERAL, etc.)
            organization: Organization this entity belongs to
            **initial_properties: Initial properties to set

        Returns:
            Newly created Entity instance
        """
        # Create the resource (entity)
        resource, created = get_or_create_resource(
            uri=uri,
            resource_type=resource_type,
            name=name,
            source=organization.name if organization else ""
        )

        # Create the entity instance
        entity = cls(resource)

        # Set initial properties if provided
        for predicate, values in initial_properties.items():
            if not isinstance(values, list):
                values = [values]
            for value in values:
                entity.set_property(predicate, value)

        return entity

    @classmethod
    def from_existing_uri(cls, uri: str) -> 'Entity':
        """
        Create an Entity instance from an existing URI.

        Args:
            uri: URI of existing entity

        Returns:
            Entity instance representing the existing entity
        """
        return cls(uri)

    @classmethod
    def from_existing_id(cls, entity_id: uuid.UUID) -> 'Entity':
        """
        Create an Entity instance from an existing entity ID.

        Args:
            entity_id: ID of existing entity

        Returns:
            Entity instance representing the existing entity
        """
        return cls(entity_id)

    @classmethod
    def from_triple(cls, triple: Triple) -> 'Entity':
        """
        Create an Entity instance from a Triple.

        Args:
            triple: Triple object where this entity is the subject

        Returns:
            Entity instance representing the entity in the triple
        """
        return cls(triple)

    def set_property(self, predicate: str, value: Union[str, Resource],
                     value_type: str = ResourceType.LITERAL,
                     datatype: Optional[str] = None,
                     language: Optional[str] = None) -> bool:
        """
        Set a property value for this entity.

        Args:
            predicate: Predicate URI or name
            value: Value to set (URI for non-literals, string for literals)
            value_type: Type of value (IRI or LITERAL)
            datatype: Datatype for literal values
            language: Language tag for language-tagged literals

        Returns:
            True if property was set successfully, False otherwise
        """
        try:
            with transaction.atomic():
                # Create/get the predicate resource
                predicate_resource, _ = get_or_create_resource(
                    uri=predicate if predicate.startswith('http') else None,
                    resource_type=ResourceType.PROPERTY,
                    name=predicate,
                    source=""
                )

                # Create/get the object resource based on value type
                if value_type == ResourceType.LITERAL:
                    object_resource, _ = get_or_create_resource(
                        resource_type=ResourceType.LITERAL,
                        value=value,
                        datatype=datatype,
                        language=language,
                        source=""
                    )
                else:
                    object_resource, _ = get_or_create_resource(
                        uri=value if value.startswith('http') else None,
                        resource_type=ResourceType.IRI,
                        name=value if not value.startswith('http') else None,
                        source=""
                    )

                # Create the triple if it doesn't exist
                _, created = create_triple_if_not_exists(
                    subject=Resource.objects.get(id=self._id),
                    predicate=predicate_resource,
                    object=object_resource
                )

                # Update our cached properties and backward compatibility structures
                predicate_name = predicate_resource.name or predicate
                if predicate_name not in self._properties:
                    self._properties[predicate_name] = []
                if object_resource.uri:
                    self._properties[predicate_name].append(object_resource.uri)
                else:
                    self._properties[predicate_name].append(object_resource.value)

                # Also update the resources cache
                if predicate_name not in self._resources:
                    self._resources[predicate_name] = []
                self._resources[predicate_name].append(object_resource)

                # Update backward compatibility fields
                if predicate_name not in self._field_names:
                    self._field_names.append(predicate_name)
                self._populate_backward_compatibility()

                return created

        except Exception as e:
            print(f"Error setting property: {e}")
            return False

    def set_class(self, class_uri: str) -> bool:
        """
        Set the RDF class (rdf:type) for this entity.

        Args:
            class_uri: URI of the class to set

        Returns:
            True if class was set successfully, False otherwise
        """
        try:
            # Create the triple
            _, created = add_class_to_resource(
                resource_uri=self._uri,
                class_uri=class_uri,
                source=""
            )
            return created
        except Exception as e:
            print(f"Error setting class: {e}")
            return False

    def add_property_from_value(self, predicate: str, value: str) -> bool:
        """
        Add a new property-value pair to this entity.

        Args:
            predicate: Predicate name or URI
            value: Value for the property

        Returns:
            True if property was added successfully, False otherwise
        """
        return self.set_property(predicate, value, value_type=ResourceType.LITERAL)

    def add_property_from_uri(self, predicate: str, object_uri: str) -> bool:
        """
        Add a new property with URI value to this entity.

        Args:
            predicate: Predicate name or URI
            object_uri: URI of the object resource

        Returns:
            True if property was added successfully, False otherwise
        """
        return self.set_property(predicate, object_uri, value_type=ResourceType.IRI)

    def add_property_from_resource(self, predicate: str, object_resource: Resource) -> bool:
        """
        Add a new property using an existing Resource object.

        Args:
            predicate: Predicate name or URI
            object_resource: Resource object for the property value

        Returns:
            True if property was added successfully, False otherwise
        """
        try:
            with transaction.atomic():
                # Create the predicate resource
                predicate_resource, _ = get_or_create_resource(
                    uri=predicate if predicate.startswith('http') else None,
                    resource_type=ResourceType.PROPERTY,
                    name=predicate,
                    source=""
                )

                # Create the triple
                _, created = create_triple_if_not_exists(
                    subject=Resource.objects.get(id=self._id),
                    predicate=predicate_resource,
                    object=object_resource
                )

                # Update our cached properties and backward compatibility structures
                predicate_name = predicate_resource.name or predicate
                if predicate_name not in self._properties:
                    self._properties[predicate_name] = []
                self._properties[predicate_name].append(object_resource.uri or object_resource.value)

                # Also update the resource cache
                if predicate_name not in self._resources:
                    self._resources[predicate_name] = []
                self._resources[predicate_name].append(object_resource)

                # Update backward compatibility fields
                if predicate_name not in self._field_names:
                    self._field_names.append(predicate_name)
                self._populate_backward_compatibility()

                return created

        except Exception as e:
            print(f"Error adding property from resource: {e}")
            return False

    def get_all_properties(self) -> Dict[str, List[Union[str, Resource]]]:
        """
        Get all properties and their values for this entity.

        Returns:
            Dictionary mapping property names to lists of values
        """
        return self._properties.copy()

    def get_all_resource_properties(self) -> Dict[str, List[Resource]]:
        """
        Get all properties and their Resource objects for this entity.

        Returns:
            Dictionary mapping property names to lists of Resource objects
        """
        return self._resources.copy()

    def save(self):
        """Save current entity state to database."""
        # The Entity model is designed to maintain state automatically
        # No explicit save method needed since we create resources/triples as we go
        pass

    def __str__(self):
        """String representation of the Entity."""
        name = self._name or "Unnamed Entity"
        uri = self._uri or "no-uri"
        return f"Entity({name}, {uri})"

    def __repr__(self):
        """Detailed representation of the Entity."""
        return f"Entity(id={self._id}, uri={self._uri}, name={self._name})"
