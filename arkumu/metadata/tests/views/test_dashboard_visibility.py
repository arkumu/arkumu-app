import pytest
from django.urls import reverse

from arkumu.metadata.models.resource import PublicAccessLevel, Resource, ResourceType
from arkumu.metadata.models.triples import Triple
from arkumu.users.models import Organization, User


@pytest.mark.django_db
def test_superuser_can_publish_projects(client):
    """Test that superuser can publish projects using canonical URI identification."""
    organization = Organization.objects.create(name="Test Org", code="test")

    # Create project resource
    project = Resource.objects.create(
        uri="http://example.org/data/test/entities/projekt/1",
        resource_type=ResourceType.IRI,
        organization=organization,
        public_access_level=PublicAccessLevel.PRIVATE,
        is_public_approved=False,
        is_public=False,
    )

    # Create rdf:type predicate
    rdf_type_predicate = Resource.objects.create(
        uri="http://www.w3.org/1999/02/22-rdf-syntax-ns#type",
        resource_type=ResourceType.PROPERTY,
        organization=organization,
    )

    # Create Project type resource with canonical URI
    project_type = Resource.objects.create(
        uri="http://arkumu.org/data/types/projekt",
        canonical_uri="http://arkumu.org/data/types/projekt",
        resource_type=ResourceType.IRI,
        organization=organization,
    )

    # Create the type triple that identifies this as a project
    Triple.objects.create(
        subject=project,
        predicate=rdf_type_predicate,
        object=project_type,
        source=organization,
    )

    superuser = User.objects.create_superuser(
        username="admin",
        email="admin@example.com",
        password="password",
    )
    client.force_login(superuser)

    response = client.post(
        reverse("metadata:metadata_dashboard_publish_projects"),
        {"organization_id": str(organization.id)},
    )

    assert response.status_code == 302
    project.refresh_from_db()
    assert project.public_access_level == PublicAccessLevel.PUBLIC
    assert project.is_public_approved is True
    assert project.is_public is True
    assert project.public_approved_by == superuser
    assert project.public_approved_at is not None


@pytest.mark.django_db
def test_non_superuser_cannot_publish_projects(client):
    """Test that non-superuser staff cannot publish projects."""
    organization = Organization.objects.create(name="Test Org", code="test")

    # Create project resource
    project = Resource.objects.create(
        uri="http://example.org/data/test/entities/projekt/1",
        resource_type=ResourceType.IRI,
        organization=organization,
        public_access_level=PublicAccessLevel.PRIVATE,
        is_public_approved=False,
        is_public=False,
    )

    # Create rdf:type predicate
    rdf_type_predicate = Resource.objects.create(
        uri="http://www.w3.org/1999/02/22-rdf-syntax-ns#type",
        resource_type=ResourceType.PROPERTY,
        organization=organization,
    )

    # Create Project type resource with canonical URI
    project_type = Resource.objects.create(
        uri="http://arkumu.org/data/types/projekt",
        canonical_uri="http://arkumu.org/data/types/projekt",
        resource_type=ResourceType.IRI,
        organization=organization,
    )

    # Create the type triple that identifies this as a project
    Triple.objects.create(
        subject=project,
        predicate=rdf_type_predicate,
        object=project_type,
        source=organization,
    )

    staff_user = User.objects.create_user(
        username="staff",
        email="staff@example.com",
        password="password",
        is_staff=True,
        is_superuser=False,
    )
    client.force_login(staff_user)

    response = client.post(
        reverse("metadata:metadata_dashboard_publish_projects"),
        {"organization_id": str(organization.id)},
    )

    assert response.status_code == 302
    project.refresh_from_db()
    assert project.public_access_level == PublicAccessLevel.PRIVATE
    assert project.is_public_approved is False
    assert project.is_public is False


@pytest.mark.django_db
def test_publish_projects_with_no_projects_found(client):
    """Test publishing when organization has no projects."""
    organization = Organization.objects.create(name="Empty Org", code="empty")

    superuser = User.objects.create_superuser(
        username="admin",
        email="admin@example.com",
        password="password",
    )
    client.force_login(superuser)

    response = client.post(
        reverse("metadata:metadata_dashboard_publish_projects"),
        {"organization_id": str(organization.id)},
    )

    assert response.status_code == 302


@pytest.mark.django_db
def test_publish_projects_with_multiple_projects(client):
    """Test publishing multiple projects at once."""
    organization = Organization.objects.create(name="Test Org", code="test")

    # Create rdf:type predicate
    rdf_type_predicate = Resource.objects.create(
        uri="http://www.w3.org/1999/02/22-rdf-syntax-ns#type",
        resource_type=ResourceType.PROPERTY,
        organization=organization,
    )

    # Create Project type resource with canonical URI
    project_type = Resource.objects.create(
        uri="http://arkumu.org/data/types/projekt",
        canonical_uri="http://arkumu.org/data/types/projekt",
        resource_type=ResourceType.IRI,
        organization=organization,
    )

    # Create multiple projects
    projects = []
    for i in range(3):
        project = Resource.objects.create(
            uri=f"http://example.org/data/test/entities/projekt/{i}",
            resource_type=ResourceType.IRI,
            organization=organization,
            public_access_level=PublicAccessLevel.PRIVATE,
            is_public_approved=False,
            is_public=False,
        )
        Triple.objects.create(
            subject=project,
            predicate=rdf_type_predicate,
            object=project_type,
            source=organization,
        )
        projects.append(project)

    superuser = User.objects.create_superuser(
        username="admin",
        email="admin@example.com",
        password="password",
    )
    client.force_login(superuser)

    response = client.post(
        reverse("metadata:metadata_dashboard_publish_projects"),
        {"organization_id": str(organization.id)},
    )

    assert response.status_code == 302

    # Verify all projects were published
    for project in projects:
        project.refresh_from_db()
        assert project.public_access_level == PublicAccessLevel.PUBLIC
        assert project.is_public_approved is True
        assert project.is_public is True


@pytest.mark.django_db
def test_publish_projects_htmx_request_returns_inline_html(client):
    """Test HTMX request returns inline HTML instead of redirect."""
    organization = Organization.objects.create(name="Test Org", code="test")

    # Create project with canonical type
    project = Resource.objects.create(
        uri="http://example.org/data/test/entities/projekt/1",
        resource_type=ResourceType.IRI,
        organization=organization,
        public_access_level=PublicAccessLevel.PRIVATE,
        is_public_approved=False,
        is_public=False,
    )

    rdf_type_predicate = Resource.objects.create(
        uri="http://www.w3.org/1999/02/22-rdf-syntax-ns#type",
        resource_type=ResourceType.PROPERTY,
        organization=organization,
    )

    project_type = Resource.objects.create(
        uri="http://arkumu.org/data/types/projekt",
        canonical_uri="http://arkumu.org/data/types/projekt",
        resource_type=ResourceType.IRI,
        organization=organization,
    )

    Triple.objects.create(
        subject=project,
        predicate=rdf_type_predicate,
        object=project_type,
        source=organization,
    )

    superuser = User.objects.create_superuser(
        username="admin",
        email="admin@example.com",
        password="password",
    )
    client.force_login(superuser)

    # Make HTMX request
    response = client.post(
        reverse("metadata:metadata_dashboard_publish_projects"),
        {"organization_id": str(organization.id)},
        HTTP_HX_REQUEST="true",
    )

    assert response.status_code == 200
    assert b'alert' in response.content
    assert b'success' in response.content

    project.refresh_from_db()
    assert project.public_access_level == PublicAccessLevel.PUBLIC


@pytest.mark.django_db
def test_publish_projects_htmx_no_projects_warning(client):
    """Test HTMX request returns warning when no projects found."""
    organization = Organization.objects.create(name="Empty Org", code="empty")

    superuser = User.objects.create_superuser(
        username="admin",
        email="admin@example.com",
        password="password",
    )
    client.force_login(superuser)

    response = client.post(
        reverse("metadata:metadata_dashboard_publish_projects"),
        {"organization_id": str(organization.id)},
        HTTP_HX_REQUEST="true",
    )

    assert response.status_code == 200
    assert b'alert' in response.content
    assert b'warning' in response.content
    assert b'No projects were found' in response.content


@pytest.mark.django_db
def test_publish_projects_htmx_non_superuser_forbidden(client):
    """Test HTMX request returns error for non-superuser."""
    organization = Organization.objects.create(name="Test Org", code="test")

    staff_user = User.objects.create_user(
        username="staff",
        email="staff@example.com",
        password="password",
        is_staff=True,
        is_superuser=False,
    )
    client.force_login(staff_user)

    response = client.post(
        reverse("metadata:metadata_dashboard_publish_projects"),
        {"organization_id": str(organization.id)},
        HTTP_HX_REQUEST="true",
    )

    assert response.status_code == 403
    assert b'alert' in response.content
    assert b'error' in response.content
    assert b'Only superusers' in response.content
