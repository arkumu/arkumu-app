import uuid

import pytest
from django.urls import reverse

from arkumu.catalog.models import ProjectIndex
from arkumu.metadata.models import PublicAccessLevel, Resource, ResourceType
from arkumu.users.tests.factories import OrganizationFactory, UserFactory


def _create_indexed_project(org, title: str) -> None:
    resource = Resource.objects.create(
        id=uuid.uuid4(),
        uri=f"http://example.org/project/{title.lower().replace(' ', '-')}",
        resource_type=ResourceType.ENTITY,
        organization=org,
        public_access_level=PublicAccessLevel.PUBLIC,
        is_public_approved=True,
    )
    ProjectIndex.objects.create(
        project_resource=resource,
        uri=resource.uri,
        org_code=org.code,
        public_access_level=PublicAccessLevel.PUBLIC,
        is_public_approved=True,
        title=title,
        subtitle="Catalog Search",
        institution_codes=[org.code],
    )


@pytest.mark.django_db
def test_advanced_search_uses_paginated_results(client, settings):
    settings.PROJECT_INDEX_BACKEND = "db"

    org = OrganizationFactory(code="fuk")
    user = UserFactory()
    client.force_login(user)

    for i in range(25):
        _create_indexed_project(org, f"Alpha {i:02d}")

    response = client.get(reverse("catalog:advanced_search"), {"query": "Alpha", "page": 2})

    assert response.status_code == 200
    assert response.context["total_results"] == 25
    assert response.context["current_page"] == 2
    assert response.context["total_pages"] == 2
    assert response.context["has_previous"] is True
    assert response.context["has_next"] is False
    assert [project["title"] for project in response.context["results"]] == [f"Alpha {i:02d}" for i in range(15, 25)]


@pytest.mark.django_db
def test_advanced_search_first_page_has_navigation_when_more_results_exist(client, settings):
    settings.PROJECT_INDEX_BACKEND = "db"

    org = OrganizationFactory(code="fuk")
    user = UserFactory()
    client.force_login(user)

    for i in range(20):
        _create_indexed_project(org, f"Alpha {i:02d}")

    response = client.get(reverse("catalog:advanced_search"), {"query": "Alpha"})

    assert response.status_code == 200
    assert response.context["current_page"] == 1
    assert response.context["total_pages"] == 2
    assert response.context["has_next"] is True
    assert [project["title"] for project in response.context["results"]] == [f"Alpha {i:02d}" for i in range(15)]
