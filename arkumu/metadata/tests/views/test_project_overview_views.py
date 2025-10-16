import pytest
from unittest.mock import patch
from django.urls import reverse

from arkumu.metadata.canonical import canonical_uri
from arkumu.metadata.models.resource import PublicAccessLevel, Resource, ResourceType
from arkumu.metadata.models.triples import Triple
from arkumu.metadata.services.project_workspace_listing_service import IS_PART_OF_URI
from arkumu.users.models import Organization, User


@pytest.mark.django_db
def test_manage_view_renders(client):
    organization = Organization.objects.create(code="demo", name="Demo")
    manager = User.objects.create_user("manager", password="pass", role="manager", organization=organization)
    client.force_login(manager)

    response = client.get(reverse("metadata:project_overview_manage"))
    assert response.status_code == 200
    assert "Projektübersicht" in response.content.decode()
    content = response.content.decode()
    assert 'name="dataset"' in content
    assert "Projekte" in content


@pytest.mark.django_db
def test_table_view_lists_projects(client):
    organization = Organization.objects.create(code="demo", name="Demo")
    manager = User.objects.create_user("manager", password="pass", role="manager", organization=organization)
    client.force_login(manager)

    dataset = Resource.objects.create(
        uri="http://arkumu.org/data/demo/datasets/projekt",
        resource_type=ResourceType.IRI,
        name="Projekt",
        organization=organization,
    )
    is_part_of = Resource.objects.create(
        uri=IS_PART_OF_URI,
        resource_type=ResourceType.PROPERTY,
        name="isPartOf",
        organization=organization,
    )
    project = Resource.objects.create(
        uri="http://arkumu.org/data/demo/projects/1",
        resource_type=ResourceType.ENTITY,
        name="Listenprojekt",
        organization=organization,
        public_access_level=PublicAccessLevel.RESTRICTED,
    )
    Triple.objects.create(subject=project, predicate=is_part_of, object=dataset, source=organization)

    response = client.get(
        reverse("metadata:project_overview_table"),
        {"organization": organization.code, "dataset": "Projekt"},
        HTTP_HX_REQUEST="true",
    )
    assert response.status_code == 200
    assert "Listenprojekt" in response.content.decode()


@pytest.mark.django_db
def test_publish_action_updates_status(client):
    organization = Organization.objects.create(code="demo", name="Demo")
    manager = User.objects.create_user("manager", password="pass", role="manager", organization=organization)
    client.force_login(manager)

    dataset = Resource.objects.create(
        uri="http://arkumu.org/data/demo/datasets/projekt",
        resource_type=ResourceType.IRI,
        name="Projekt",
        organization=organization,
    )
    is_part_of = Resource.objects.create(
        uri=IS_PART_OF_URI,
        resource_type=ResourceType.PROPERTY,
        name="isPartOf",
        organization=organization,
    )
    project = Resource.objects.create(
        uri="http://arkumu.org/data/demo/projects/1",
        resource_type=ResourceType.ENTITY,
        name="Freigabeprojekt",
        organization=organization,
        public_access_level=PublicAccessLevel.RESTRICTED,
        is_public_approved=False,
    )
    Triple.objects.create(subject=project, predicate=is_part_of, object=dataset, source=organization)

    event_pred = Resource.objects.create(
        uri=canonical_uri("event"),
        resource_type=ResourceType.PROPERTY,
        name="event",
        organization=organization,
        canonical_uri=canonical_uri("event"),
    )
    event = Resource.objects.create(
        uri="http://arkumu.org/data/demo/events/1",
        resource_type=ResourceType.ENTITY,
        name="Event",
        organization=organization,
    )
    Triple.objects.create(subject=project, predicate=event_pred, object=event, source=organization)

    with patch("arkumu.cache.tasks.warm_cross_institutional_projects_cache") as mock_task:
        mock_task.schedule.return_value = None
        response = client.post(
            reverse("metadata:project_overview_publish", args=[project.id]),
            {"organization": organization.code, "dataset": "Projekt"},
            HTTP_HX_REQUEST="true",
        )

    assert response.status_code == 200
    assert response["HX-Trigger"] == "project-status-updated"
    project.refresh_from_db()
    assert project.public_access_level == PublicAccessLevel.PUBLIC
    assert project.is_public_approved is True
