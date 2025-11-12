"""Tests for the curated OAI media links dashboard."""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from arkumu.metadata.models.resource import PublicAccessLevel, Resource, ResourceType
from arkumu.oaipmh.models import OAIProjectMediaLink
from arkumu.users.models import Organization


User = get_user_model()


def _make_project(org: Organization, uri: str) -> Resource:
    return Resource.objects.create(
        uri=uri,
        organization=org,
        resource_type=ResourceType.ENTITY,
        public_access_level=PublicAccessLevel.PUBLIC,
        is_public_approved=True,
    )


@pytest.mark.django_db
def test_dashboard_allows_manual_addition(client):
    org = Organization.objects.create(name="Org", code="org", domain="org", is_active=True)
    project = _make_project(org, "http://arkumu.test/entities/projekt/1")
    digital = _make_project(org, "http://arkumu.test/entities/digital/1")

    user = User.objects.create_user(username="staff", password="pwd", is_staff=True)
    client.force_login(user)

    url = reverse('metadata:oai_media_links_dashboard')
    response = client.post(
        url,
        {
            'action': 'add',
            'organization': org.code,
            'project_uri': project.uri,
            'digital_uri': digital.uri,
            'status': OAIProjectMediaLink.STATUS_APPROVED,
            'page': '1',
        },
        follow=False,
    )

    assert response.status_code == 302
    assert OAIProjectMediaLink.objects.filter(project=project, digital_object=digital).exists()


@pytest.mark.django_db
def test_dashboard_allows_removal(client):
    org = Organization.objects.create(name="Org", code="org", domain="org", is_active=True)
    project = _make_project(org, "http://arkumu.test/entities/projekt/2")
    digital = _make_project(org, "http://arkumu.test/entities/digital/2")
    link = OAIProjectMediaLink.objects.create(
        project=project,
        digital_object=digital,
        status=OAIProjectMediaLink.STATUS_PENDING,
    )

    user = User.objects.create_user(username="staff2", password="pwd", is_staff=True)
    client.force_login(user)

    url = reverse('metadata:oai_media_links_dashboard')
    response = client.post(
        url,
        {
            'action': 'delete',
            'organization': org.code,
            'link_id': link.id,
            'page': '1',
        },
        follow=False,
    )

    assert response.status_code == 302
    assert not OAIProjectMediaLink.objects.filter(id=link.id).exists()
