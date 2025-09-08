"""
Shared test fixtures for catalog tests.
"""
import pytest
from django.contrib.auth import get_user_model
from arkumu.metadata.models import Resource, Triple
from arkumu.users.models import Organization
from arkumu.metadata.models.resource import ResourceType, PublicAccessLevel

User = get_user_model()


@pytest.fixture
def organization():
    """Create a test organization."""
    return Organization.objects.create(
        name="Test University",
        code="TEST_UNI"
    )


@pytest.fixture
def user(organization):
    """Create a test user with organization."""
    return User.objects.create_user(
        username="testuser",
        email="test@example.com",
        organization=organization
    )


@pytest.fixture
def anonymous_user():
    """Create an anonymous user instance for testing.
    
    Note: This returns Django's AnonymousUser class instance,
    not a database user. It's used to simulate unauthenticated requests.
    """
    from django.contrib.auth.models import AnonymousUser
    return AnonymousUser()


@pytest.fixture
def rdf_predicates():
    """Create common RDF predicate resources."""
    rdf_type = Resource.objects.create(
        uri='http://www.w3.org/1999/02/22-rdf-syntax-ns#type',
        name='rdf:type',
        resource_type=ResourceType.PROPERTY
    )
    
    owl_sameas = Resource.objects.create(
        uri='http://www.w3.org/2002/07/owl#sameAs',
        name='owl:sameAs',
        resource_type=ResourceType.PROPERTY
    )
    
    skos_exactmatch = Resource.objects.create(
        uri='http://www.w3.org/2004/02/skos/core#exactMatch',
        name='skos:exactMatch',
        resource_type=ResourceType.PROPERTY
    )
    
    return {
        'rdf_type': rdf_type,
        'owl_sameas': owl_sameas,
        'skos_exactmatch': skos_exactmatch
    }


@pytest.fixture
def arkumu_types():
    """Create Arkumu type resources."""
    project_type = Resource.objects.create(
        uri='http://arkumu.org/types/projekt',
        name='Project',
        resource_type=ResourceType.CLASS
    )
    
    event_type = Resource.objects.create(
        uri='http://arkumu.org/types/ereignis',
        name='Event',
        resource_type=ResourceType.CLASS
    )
    
    return {
        'project': project_type,
        'event': event_type
    }


@pytest.fixture
def catalog_resources():
    """Create catalog target resources for harmonization."""
    project_catalog = Resource.objects.create(
        uri='http://arkumu.org/data/catalog/project',
        name='Catalog Project',
        resource_type=ResourceType.CLASS
    )
    
    event_catalog = Resource.objects.create(
        uri='http://arkumu.org/data/catalog/event',
        name='Catalog Event',
        resource_type=ResourceType.CLASS
    )
    
    return {
        'project': project_catalog,
        'event': event_catalog
    }


@pytest.fixture
def property_resources():
    """Create common property resources."""
    title_prop = Resource.objects.create(
        uri='http://test-uni.de/properties/title',
        name='Title',
        resource_type=ResourceType.PROPERTY
    )
    
    description_prop = Resource.objects.create(
        uri='http://test-uni.de/properties/description',
        name='Description',
        resource_type=ResourceType.PROPERTY
    )
    
    subject_prop = Resource.objects.create(
        uri='http://test-uni.de/properties/faechergruppe',
        name='Subject Area',
        resource_type=ResourceType.PROPERTY
    )
    
    return {
        'title': title_prop,
        'description': description_prop,
        'subject': subject_prop
    }


def create_harmonized_resource(organization, name, uri, rdf_predicates, arkumu_types, catalog_resources, property_resources=None, properties_data=None):
    """
    Helper function to create a fully harmonized resource with properties.
    
    Args:
        organization: Organization instance
        name: Resource name
        uri: Resource URI
        rdf_predicates: Dict with RDF predicates
        arkumu_types: Dict with Arkumu types
        catalog_resources: Dict with catalog resources
        property_resources: Dict with property resources (optional)
        properties_data: Dict with property values (optional)
    
    Returns:
        Created resource instance
    """
    # Create the main resource
    resource = Resource.objects.create(
        organization=organization,
        uri=uri,
        name=name,
        resource_type=ResourceType.IRI,
        public_access_level=PublicAccessLevel.PUBLIC,
        is_public_approved=True
    )
    
    # Add type triple (project by default)
    Triple.objects.create(
        subject=resource,
        predicate=rdf_predicates['rdf_type'],
        object=arkumu_types['project']
    )
    
    # Add harmonization mapping
    Triple.objects.create(
        subject=resource,
        predicate=rdf_predicates['owl_sameas'],
        object=catalog_resources['project']
    )
    
    # Add properties if provided
    if property_resources and properties_data:
        for prop_key, prop_value in properties_data.items():
            if prop_key in property_resources:
                # Create literal resource
                literal = Resource.objects.create(
                    organization=organization,
                    value=prop_value,
                    resource_type=ResourceType.LITERAL,
                    public_access_level=PublicAccessLevel.PUBLIC,
                    is_public_approved=True
                )
                
                # Create triple
                Triple.objects.create(
                    subject=resource,
                    predicate=property_resources[prop_key],
                    object=literal
                )
    
    return resource


@pytest.fixture
def harmonized_project_factory(organization, rdf_predicates, arkumu_types, catalog_resources, property_resources):
    """Factory fixture for creating harmonized projects."""
    def _create_project(name, uri, **properties):
        return create_harmonized_resource(
            organization=organization,
            name=name,
            uri=uri,
            rdf_predicates=rdf_predicates,
            arkumu_types=arkumu_types,
            catalog_resources=catalog_resources,
            property_resources=property_resources,
            properties_data=properties
        )
    
    return _create_project