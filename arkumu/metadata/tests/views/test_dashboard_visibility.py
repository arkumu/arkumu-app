from types import SimpleNamespace

import pytest
from django.urls import reverse

from arkumu.metadata.models.resource import PublicAccessLevel, Resource, ResourceType
from arkumu.projects.services import ProjectSnapshotService
from arkumu.users.models import Organization, User


@pytest.mark.django_db
def test_superuser_can_publish_projects(client, monkeypatch):
    organization = Organization.objects.create(name="Test Org", code="test")
    project = Resource.objects.create(
        uri="http://example.org/data/test/entities/projekt/1",
        resource_type=ResourceType.ENTITY,
        organization=organization,
        public_access_level=PublicAccessLevel.PRIVATE,
        is_public_approved=False,
    )

    snapshot = SimpleNamespace(
        projects=[
            SimpleNamespace(
                uri=project.uri,
                institution=SimpleNamespace(code=organization.code),
            )
        ]
    )
    monkeypatch.setattr(
        ProjectSnapshotService,
        "get_cross_institutional_snapshot",
        lambda self: snapshot,
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
def test_non_superuser_cannot_publish_projects(client, monkeypatch):
    organization = Organization.objects.create(name="Test Org", code="test")
    project = Resource.objects.create(
        uri="http://example.org/data/test/entities/projekt/1",
        resource_type=ResourceType.ENTITY,
        organization=organization,
        public_access_level=PublicAccessLevel.PRIVATE,
        is_public_approved=False,
    )

    snapshot = SimpleNamespace(projects=[])
    monkeypatch.setattr(
        ProjectSnapshotService,
        "get_cross_institutional_snapshot",
        lambda self: snapshot,
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
