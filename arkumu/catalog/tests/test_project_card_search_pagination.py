import uuid

import pytest

from arkumu.catalog.models import ProjectIndex
from arkumu.catalog.services.project_card_search_service import ProjectCardSearchService
from arkumu.catalog.services.project_index_service import ProjectIndexService
from arkumu.metadata.models import PublicAccessLevel, Resource, ResourceType
from arkumu.users.tests.factories import OrganizationFactory


def _create_indexed_project(org, title: str) -> ProjectIndex:
    resource = Resource.objects.create(
        id=uuid.uuid4(),
        uri=f"http://example.org/project/{title.lower().replace(' ', '-')}",
        resource_type=ResourceType.ENTITY,
        organization=org,
        public_access_level=PublicAccessLevel.PUBLIC,
        is_public_approved=True,
    )
    return ProjectIndex.objects.create(
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
def test_project_index_service_paginates_before_card_materialization(monkeypatch):
    org = OrganizationFactory(code="fuk")
    entries = [_create_indexed_project(org, f"Alpha {i:02d}") for i in range(25)]

    rendered_titles = []

    def fake_to_card_dict(self, valid_preview_paths=None):
        rendered_titles.append(self.title)
        return {"uri": self.uri, "title": self.title}

    monkeypatch.setattr(ProjectIndex, "to_card_dict", fake_to_card_dict)

    service = ProjectIndexService(backend="db")
    cards, total = service.get_cards_page(query="Alpha", org_codes=None, page=2, page_size=10)

    assert total == 25
    assert len(cards) == 10
    assert len(rendered_titles) == 10
    assert cards[0]["title"] == "Alpha 10"
    assert cards[-1]["title"] == "Alpha 19"
    assert rendered_titles == [f"Alpha {i:02d}" for i in range(10, 20)]


@pytest.mark.django_db
def test_project_card_search_service_returns_total_and_requested_page(settings):
    settings.PROJECT_INDEX_BACKEND = "db"

    org = OrganizationFactory(code="fuk")
    for i in range(25):
        _create_indexed_project(org, f"Alpha {i:02d}")

    service = ProjectCardSearchService()
    cards, total = service.search_cards("Alpha", org_code="fuk", page=3, page_size=10)

    assert total == 25
    assert [card["title"] for card in cards] == [f"Alpha {i:02d}" for i in range(20, 25)]


@pytest.mark.django_db
def test_project_index_service_returns_empty_page_beyond_result_range():
    org = OrganizationFactory(code="fuk")
    for i in range(5):
        _create_indexed_project(org, f"Alpha {i:02d}")

    service = ProjectIndexService(backend="db")
    cards, total = service.get_cards_page(query="Alpha", org_codes=None, page=3, page_size=10)

    assert total == 5
    assert cards == []


@pytest.mark.django_db
def test_project_index_service_random_sample_materializes_only_requested_limit(monkeypatch):
    org = OrganizationFactory(code="fuk")
    entries = [_create_indexed_project(org, f"Alpha {i:02d}") for i in range(25)]

    rendered_titles = []

    def fake_to_card_dict(self, valid_preview_paths=None):
        rendered_titles.append(self.title)
        return {"uri": self.uri, "title": self.title}

    monkeypatch.setattr(ProjectIndex, "to_card_dict", fake_to_card_dict)

    service = ProjectIndexService(backend="db")
    cards, total = service.get_random_cards_sample(limit=7)

    assert total == 25
    assert len(cards) == 7
    assert len(rendered_titles) == 7
