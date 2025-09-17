"""
Tests for project view services (CardView and ProjectView)
"""

import pytest
from django.test import TestCase
from arkumu.metadata.models.resource import Resource, ResourceType
from arkumu.metadata.models.triples import Triple
from arkumu.users.models import Organization, User
from arkumu.catalog.services.project_views import CardView, ProjectView, get_card_view_data, get_project_view_data


@pytest.fixture
def organization():
    """Create test organization"""
    return Organization.objects.create(
        name="Test University",
        code="test",
        description="Test organization"
    )


@pytest.fixture
def user(organization):
    """Create test user"""
    return User.objects.create_user(
        username="testuser",
        email="test@example.com",
        organization=organization
    )


@pytest.fixture
def project_resource(organization):
    """Create a test project resource"""
    return Resource.objects.create(
        uri="http://arkumu.org/data/test/entities/projekt/123",
        resource_type=ResourceType.CLASS,
        organization=organization
    )


@pytest.fixture
def event_resource(organization):
    """Create a test event resource"""
    return Resource.objects.create(
        uri="http://arkumu.org/data/test/entities/ereignis/456",
        resource_type=ResourceType.CLASS,
        organization=organization
    )


@pytest.fixture
def institution_resource(organization):
    """Create a test institution resource"""
    return Resource.objects.create(
        uri="http://arkumu.org/data/test/entities/institution/789",
        resource_type=ResourceType.CLASS,
        organization=organization
    )


@pytest.fixture
def actor_resource(organization):
    """Create a test actor resource"""
    return Resource.objects.create(
        uri="http://arkumu.org/data/test/entities/actor/101",
        resource_type=ResourceType.CLASS,
        organization=organization
    )


@pytest.fixture
def property_resources(organization):
    """Create property resources"""
    properties = {}

    property_uris = [
        "http://arkumu.org/data/properties/bevorzugter-titel",
        "http://arkumu.org/data/properties/bevorzugter-untertitel",
        "http://arkumu.org/data/properties/vorschaubild",
        "http://arkumu.org/data/properties/ereignis",
        "http://arkumu.org/data/properties/einliefernde-hochschule",
        "http://arkumu.org/data/properties/projektkategorie",
        "http://arkumu.org/data/properties/ereignisbeginn",
        "http://arkumu.org/data/properties/ereignisende",
        "http://arkumu.org/data/properties/akteurin-im-ereignis",
        "http://arkumu.org/data/properties/deutscher-name",
        "http://arkumu.org/data/properties/deutscher-name-der-einliefernden-hochschule",
    ]

    for uri in property_uris:
        properties[uri] = Resource.objects.create(
            uri=uri,
            resource_type=ResourceType.PROPERTY,
            organization=organization
        )

    return properties


@pytest.fixture
def literal_resources(organization):
    """Create literal resources"""
    literals = {}

    literal_data = {
        "title": "Test Project Title",
        "subtitle": "Test Project Subtitle",
        "image": "test_image.jpg",
        "start_date": "2023-01-01",
        "end_date": "2023-12-31",
        "actor_name": "Test Actor",
        "institution_name": "Test Institution"
    }

    for key, value in literal_data.items():
        literals[key] = Resource.objects.create(
            uri=f"http://arkumu.org/data/test/literals/{key}",
            resource_type=ResourceType.LITERAL,
            literal_value=value,
            organization=organization
        )

    return literals


@pytest.fixture
def test_triples(project_resource, event_resource, institution_resource, actor_resource,
                property_resources, literal_resources, organization):
    """Create test triples that represent a complete project"""
    triples = []

    # Project title
    triples.append(Triple.objects.create(
        subject=project_resource,
        predicate=property_resources["http://arkumu.org/data/properties/bevorzugter-titel"],
        object=literal_resources["title"],
        source=organization
    ))

    # Project subtitle
    triples.append(Triple.objects.create(
        subject=project_resource,
        predicate=property_resources["http://arkumu.org/data/properties/bevorzugter-untertitel"],
        object=literal_resources["subtitle"],
        source=organization
    ))

    # Project image
    triples.append(Triple.objects.create(
        subject=project_resource,
        predicate=property_resources["http://arkumu.org/data/properties/vorschaubild"],
        object=literal_resources["image"],
        source=organization
    ))

    # Project -> Event relationship
    triples.append(Triple.objects.create(
        subject=project_resource,
        predicate=property_resources["http://arkumu.org/data/properties/ereignis"],
        object=event_resource,
        source=organization
    ))

    # Project -> Institution relationship
    triples.append(Triple.objects.create(
        subject=project_resource,
        predicate=property_resources["http://arkumu.org/data/properties/einliefernde-hochschule"],
        object=institution_resource,
        source=organization
    ))

    # Event start date
    triples.append(Triple.objects.create(
        subject=event_resource,
        predicate=property_resources["http://arkumu.org/data/properties/ereignisbeginn"],
        object=literal_resources["start_date"],
        source=organization
    ))

    # Event end date
    triples.append(Triple.objects.create(
        subject=event_resource,
        predicate=property_resources["http://arkumu.org/data/properties/ereignisende"],
        object=literal_resources["end_date"],
        source=organization
    ))

    # Institution name
    triples.append(Triple.objects.create(
        subject=institution_resource,
        predicate=property_resources["http://arkumu.org/data/properties/deutscher-name-der-einliefernden-hochschule"],
        object=literal_resources["institution_name"],
        source=organization
    ))

    # Actor name
    triples.append(Triple.objects.create(
        subject=actor_resource,
        predicate=property_resources["http://arkumu.org/data/properties/deutscher-name"],
        object=literal_resources["actor_name"],
        source=organization
    ))

    return triples


@pytest.mark.django_db
class TestCardView:
    """Test CardView data extraction"""

    def test_card_view_basic_properties(self, project_resource, test_triples):
        """Test basic property extraction"""
        card_view = CardView(project_resource.uri)
        card_data = card_view.get_card_data()

        assert card_data is not None
        assert card_data.uri == project_resource.uri
        assert card_data.title == "Test Project Title"
        assert card_data.subtitle == "Test Project Subtitle"
        assert card_data.image == "test_image.jpg"

    def test_card_view_institution(self, project_resource, test_triples):
        """Test institution extraction"""
        card_view = CardView(project_resource.uri)
        card_data = card_view.get_card_data()

        assert card_data is not None
        assert card_data.institution == "Test Institution"

    def test_card_view_event_dates(self, project_resource, test_triples):
        """Test event date extraction"""
        card_view = CardView(project_resource.uri)
        card_data = card_view.get_card_data()

        assert card_data is not None
        assert card_data.event_start == "2023-01-01"
        assert card_data.event_end == "2023-12-31"

    def test_card_view_nonexistent_project(self):
        """Test with non-existent project URI"""
        card_view = CardView("http://nonexistent.uri")
        card_data = card_view.get_card_data()

        assert card_data is None

    def test_get_card_view_data_convenience_function(self, project_resource, test_triples):
        """Test convenience function"""
        card_data = get_card_view_data(project_resource.uri)

        assert card_data is not None
        assert card_data.title == "Test Project Title"


@pytest.mark.django_db
class TestProjectView:
    """Test ProjectView data extraction"""

    def test_project_view_extends_card_view(self, project_resource, test_triples):
        """Test that ProjectView includes all CardView data"""
        project_view = ProjectView(project_resource.uri)
        project_data = project_view.get_project_data()

        assert project_data is not None
        assert project_data.uri == project_resource.uri
        assert project_data.title == "Test Project Title"
        assert project_data.subtitle == "Test Project Subtitle"
        assert project_data.institution == "Test Institution"

    def test_get_project_view_data_convenience_function(self, project_resource, test_triples):
        """Test convenience function"""
        project_data = get_project_view_data(project_resource.uri)

        assert project_data is not None
        assert project_data.title == "Test Project Title"


@pytest.mark.django_db
class TestDatabaseQueries:
    """Test actual database queries and performance"""

    def test_triple_query_structure(self, project_resource, property_resources, literal_resources):
        """Test that our Triple queries work correctly"""
        # Create a specific triple to test
        triple = Triple.objects.create(
            subject=project_resource,
            predicate=property_resources["http://arkumu.org/data/properties/bevorzugter-titel"],
            object=literal_resources["title"]
        )

        # Test the query pattern used in _get_literal_value
        found_triple = Triple.objects.filter(
            subject__uri=project_resource.uri,
            predicate__uri="http://arkumu.org/data/properties/bevorzugter-titel",
            object__resource_type=ResourceType.LITERAL
        ).first()

        assert found_triple is not None
        assert found_triple.object.literal_value == "Test Project Title"

    def test_related_resource_query(self, project_resource, event_resource, property_resources):
        """Test related resource queries"""
        # Create a relationship triple
        triple = Triple.objects.create(
            subject=project_resource,
            predicate=property_resources["http://arkumu.org/data/properties/ereignis"],
            object=event_resource
        )

        # Test the query pattern used in _get_related_resource_uri
        found_triple = Triple.objects.filter(
            subject__uri=project_resource.uri,
            predicate__uri="http://arkumu.org/data/properties/ereignis",
            object__resource_type__in=[ResourceType.CLASS, ResourceType.PROPERTY]
        ).first()

        assert found_triple is not None
        assert found_triple.object.uri == event_resource.uri


@pytest.mark.django_db
class TestRealDatabaseData:
    """Test with actual data from the database"""

    def test_find_real_projects(self):
        """Find real projects in the database for testing"""
        # Look for actual project resources
        project_resources = Resource.objects.filter(
            uri__contains="projekt"
        )[:5]

        print(f"\nFound {project_resources.count()} project resources:")
        for project in project_resources:
            print(f"  - {project.uri}")

            # Try to get card data
            card_data = get_card_view_data(project.uri)
            if card_data:
                print(f"    Title: {card_data.title}")
                print(f"    Institution: {card_data.institution}")
            else:
                print(f"    No card data extracted")

    def test_real_project_card_extraction(self):
        """Test card extraction with first real project found"""
        project = Resource.objects.filter(
            uri__contains="projekt"
        ).first()

        if project:
            print(f"\nTesting real project: {project.uri}")

            # Test CardView
            card_data = get_card_view_data(project.uri)
            print(f"Card data: {card_data}")

            # Test ProjectView
            project_data = get_project_view_data(project.uri)
            print(f"Project data: {project_data}")

            # Check what triples exist for this project
            triples = Triple.objects.filter(subject=project)[:10]
            print(f"\nFirst 10 triples for this project:")
            for triple in triples:
                print(f"  {triple.predicate.uri} -> {triple.object.uri} ({triple.object.resource_type})")
                if triple.object.resource_type == ResourceType.LITERAL:
                    print(f"    Value: {getattr(triple.object, 'literal_value', 'NO VALUE')}")