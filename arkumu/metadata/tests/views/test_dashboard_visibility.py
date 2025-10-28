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
                subject_id=str(project.id),
                uri=project.uri,
                institution=SimpleNamespace(code=organization.code, label=organization.name),
                institution_codes=[organization.code],
            )
        ]
    )
    monkeypatch.setattr(
        ProjectSnapshotService,
        "get_cross_institutional_snapshot",
        lambda self, **kwargs: snapshot,
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
        lambda self, **kwargs: snapshot,
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
def test_publish_projects_resolves_alias_codes(client, monkeypatch, settings):
    settings.OAI_INSTITUTION_CODE_ALIASES = {'ff8f3b0306bebf6d': 'hmt'}
    organization = Organization.objects.create(name="HMT", code="hmt")
    project = Resource.objects.create(
        uri="http://example.org/data/hmt/projekte/1",
        resource_type=ResourceType.ENTITY,
        organization=organization,
        public_access_level=PublicAccessLevel.RESTRICTED,
        is_public_approved=False,
    )

    snapshot = SimpleNamespace(
        projects=[
            SimpleNamespace(
                subject_id=str(project.id),
                uri=project.uri,
                institution=SimpleNamespace(code='ff8f3b0306bebf6d', label=organization.name),
                institution_codes=['ff8f3b0306bebf6d'],
            )
        ]
    )
    monkeypatch.setattr(
        ProjectSnapshotService,
        "get_cross_institutional_snapshot",
        lambda self, **kwargs: snapshot,
    )

    superuser = User.objects.create_superuser(
        username="admin",
        email="admin@example.com",
        password="password",
    )
    client.force_login(superuser)

    client.post(
        reverse("metadata:metadata_dashboard_publish_projects"),
        {"organization_id": str(organization.id)},
    )

    project.refresh_from_db()
    assert project.public_access_level == PublicAccessLevel.PUBLIC
    assert project.is_public_approved is True
