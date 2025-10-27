"""
Test file demonstrating Entity class usage patterns.
"""

from arkumu.metadata.models.entity import Entity
from arkumu.metadata.models.resource import Resource, ResourceType
from arkumu.metadata.models.triples import Triple

def test_entity_creation_and_usage():
    """Test creating and using Entity instances."""

    # Test 1: Creating a new entity
    print("=== Test 1: Creating New Entity ===")
    entity1 = Entity.create_new(
        uri="http://arkumu.org/data/test-entity-1",
        name="Test Entity 1",
        initial_properties={
            "http://schema.org/name": "My Test Entity",
            "http://schema.org/description": "This is a test entity"
        }
    )
    print(f"Created: {entity1}")
    print(f"ID: {entity1.id}")
    print(f"URI: {entity1.uri}")
    print(f"Name: {entity1.name}")

    # Test 2: Adding properties to existing entity
    print("\n=== Test 2: Adding Properties ===")
    entity1.set_property(
        predicate="http://schema.org/dateCreated",
        value="2023-01-01",
        value_type=ResourceType.LITERAL
    )

    # Check properties
    props = entity1.get_all_properties()
    print("Properties:", props)

    # Test 3: Loading existing entity
    print("\n=== Test 3: Loading Existing Entity ===")
    try:
        entity2 = Entity.from_existing_uri("http://arkumu.org/data/test-entity-1")
        print(f"Loaded: {entity2}")
        print(f"Properties: {entity2.get_all_properties()}")
    except Exception as e:
        print(f"Could not load existing entity: {e}")

    # Test 4: Setting class
    print("\n=== Test 4: Setting RDF Class ===")
    success = entity1.set_class("http://schema.org/Thing")
    print(f"Set class successfully: {success}")

if __name__ == "__main__":
    test_entity_creation_and_usage()
