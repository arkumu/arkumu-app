"""HTMX dashboard tests for curated OAI media links."""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from arkumu.metadata.models.resource import PublicAccessLevel, Resource, ResourceType
from arkumu.oaipmh.models import OAIProjectMediaLink
from arkumu.users.models import Organization


User = get_user_model()


def _make_project(org: Organization, uri: str, name: str = "Project") -> Resource:
    return Resource.objects.create(
        uri=uri,
        organization=org,
        resource_type=ResourceType.ENTITY,
        public_access_level=PublicAccessLevel.PUBLIC,
        is_public_approved=True,
        name=name,
    )


@pytest.mark.django_db
def test_panel_renders_for_staff(client):
    org = Organization.objects.create(name="Org", code="org", domain="org", is_active=True)
    project = _make_project(org, "http://arkumu.test/entities/projekt/1", name="Demo")
    digital = _make_project(org, "http://arkumu.test/entities/digital/1", name="Asset")
    OAIProjectMediaLink.objects.create(project=project, digital_object=digital, status=OAIProjectMediaLink.STATUS_APPROVED)

    user = User.objects.create_user(username="staff", password="pwd", is_staff=True)
    client.force_login(user)

    url = reverse('metadata:oai_media_links_panel')
    response = client.get(url, {'organization': org.code})

    assert response.status_code == 200
    assert b"Demo" in response.content
    assert b"Asset" in response.content


@pytest.mark.django_db
def test_htmx_add_link_creates_entry(client):
    org = Organization.objects.create(name="Org", code="org", domain="org", is_active=True)
    project = _make_project(org, "http://arkumu.test/entities/projekt/2")
    digital = _make_project(org, "http://arkumu.test/entities/digital/2")

    user = User.objects.create_user(username="staff2", password="pwd", is_staff=True)
    client.force_login(user)

    url = reverse('metadata:oai_media_link_add')
    response = client.post(
        url,
        {
            'organization': org.code,
            'project_uri': project.uri,
            'digital_uri': digital.uri,
            'status': OAIProjectMediaLink.STATUS_APPROVED,
            'status_filter': 'all',
            'page': '1',
        },
        follow=False,
    )

    assert response.status_code == 200
    assert OAIProjectMediaLink.objects.filter(project=project, digital_object=digital, status=OAIProjectMediaLink.STATUS_APPROVED).exists()


@pytest.mark.django_db
def test_htmx_delete_link_removes_entry(client):
    org = Organization.objects.create(name="Org", code="org", domain="org", is_active=True)
    project = _make_project(org, "http://arkumu.test/entities/projekt/3")
    digital = _make_project(org, "http://arkumu.test/entities/digital/3")
    link = OAIProjectMediaLink.objects.create(project=project, digital_object=digital, status=OAIProjectMediaLink.STATUS_PENDING)

    user = User.objects.create_user(username="staff3", password="pwd", is_staff=True)
    client.force_login(user)

    url = reverse('metadata:oai_media_link_delete', args=[link.id])
    response = client.post(
        url,
        {
            'organization': org.code,
            'status_filter': 'all',
            'page': '1',
        },
        follow=False,
    )

    assert response.status_code == 200
    assert not OAIProjectMediaLink.objects.filter(id=link.id).exists()


@pytest.mark.django_db
def test_htmx_update_changes_status(client):
    org = Organization.objects.create(name="Org", code="org", domain="org", is_active=True)
    project = _make_project(org, "http://arkumu.test/entities/projekt/4")
    digital = _make_project(org, "http://arkumu.test/entities/digital/4")
    link = OAIProjectMediaLink.objects.create(project=project, digital_object=digital, status=OAIProjectMediaLink.STATUS_PENDING)

    user = User.objects.create_user(username="staff4", password="pwd", is_staff=True)
    client.force_login(user)

    url = reverse('metadata:oai_media_link_update', args=[link.id])
    response = client.post(
        url,
        {
            'organization': org.code,
            'status_filter': 'all',
            'page': '1',
            'status': OAIProjectMediaLink.STATUS_APPROVED,
            'current_status': link.status,
        },
        follow=False,
    )

    assert response.status_code == 200
    link.refresh_from_db()
    assert link.status == OAIProjectMediaLink.STATUS_APPROVED
