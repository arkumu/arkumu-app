import json
import uuid
from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from arkumu.metadata.views import simplified_workspace_views
from arkumu.users.models import Organization


class _BaseDummySchemaService:
    """Shared scaffolding for dummy schema services used in simplified workspace tests."""

    def __init__(self, entity_uri_suffix: str) -> None:
        self.mapping = SimpleNamespace(id=uuid.uuid4())
        self.organization = SimpleNamespace(code="test-org")
        self.entity_uri = f"http://example.org/data/{self.organization.code}/{entity_uri_suffix}"
        self.saved_entity_data = None
        self.multi_fk_calls = []
        self.join_sync_calls = []

    def augment_field_metadata_with_joins(self, dataset_name, metadata):
        return metadata, {}

    def collect_relationship_values(self, **kwargs):
        return []

    def save_entity(self, *, dataset_name: str, entity_data: dict, entity_uri: str):
        self.saved_entity_data = dict(entity_data)
        return entity_uri or self.entity_uri, False

    def save_multi_fk_relationship(self, *, entity_uri: str, property_uri: str, related_uris):
        self.multi_fk_calls.append((entity_uri, property_uri, list(related_uris)))

    def sync_join_relationship(self, *, entity_uri: str, relationship, related_uris):
        self.join_sync_calls.append((entity_uri, relationship, list(related_uris)))


class DummyProjektSchemaService(_BaseDummySchemaService):
    """Stub service focused on Projekt dataset interactions."""

    PROPERTY_URI = "http://example.org/properties/project-type"

    def __init__(self) -> None:
        super().__init__("projekt/PROJ-1")

    def get_field_metadata(self, dataset_name: str):
        return {
            "Projektart": {
                "column_name": "Projektart",
                "property_label": "Projektart",
                "is_multi_value": True,
                "is_external_ontology": True,
                "property_uri": self.PROPERTY_URI,
                "fk_relationship": {
                    "target_dataset": "Projektart",
                    "target_property_uri": "http://example.org/properties/code",
                },
            }
        }

    def get_dataset_schema(self, dataset_name: str):
        if dataset_name == "Projektart":
            return {
                "properties": {
                    "label": SimpleNamespace(uri="http://example.org/properties/label", name="Label"),
                    "code": SimpleNamespace(uri="http://example.org/properties/code", name="Code"),
                }
            }
        return {"properties": {}}

    def load_entity_by_uri(self, dataset_name: str, entity_uri: str):
        return {
            "Projektart": json.dumps(
                [
                    {"uri": "http://example.org/project-type/a"},
                    {"uri": "http://example.org/project-type/b"},
                ]
            )
        }


class DummyEreignisSchemaService(_BaseDummySchemaService):
    """Stub service focused on Ereignis dataset interactions."""

    PROPERTY_URI = "http://example.org/properties/event-type"

    def __init__(self) -> None:
        super().__init__("ereignis/EVT-1")

    def get_field_metadata(self, dataset_name: str):
        return {
            "Ereignistyp": {
                "column_name": "Ereignistyp",
                "property_label": "Ereignistyp",
                "is_multi_value": True,
                "is_external_ontology": True,
                "property_uri": self.PROPERTY_URI,
                "fk_relationship": {
                    "target_dataset": "Ereignistyp",
                    "target_property_uri": "http://example.org/properties/code",
                },
            }
        }

    def get_dataset_schema(self, dataset_name: str):
        if dataset_name == "Ereignistyp":
            return {
                "properties": {
                    "label": SimpleNamespace(uri="http://example.org/properties/label", name="Label"),
                    "code": SimpleNamespace(uri="http://example.org/properties/code", name="Code"),
                }
            }
        return {"properties": {}}

    def load_entity_by_uri(self, dataset_name: str, entity_uri: str):
        return {
            "Ereignistyp": json.dumps(
                [
                    {"uri": "http://example.org/event-type/a"},
                    {"uri": "http://example.org/event-type/b"},
                ]
            )
        }


class DummyJoinSchemaService(_BaseDummySchemaService):
    """Stub service that surfaces a join relationship for Projekt dataset."""

    PROPERTY_URI = "http://example.org/properties/org-unit"

    def __init__(self) -> None:
        super().__init__("projekt/PROJ-2")
        self.relationship = SimpleNamespace(
            join_dataset="projekt__organisationseinheit",
            join_dataset_schema={},
            self_column="Organisationseinheit",
            self_property_uri=self.PROPERTY_URI,
            other_dataset="Organisationseinheit",
            other_column="Organisationseinheit",
            other_property_uri=self.PROPERTY_URI,
            other_display_label="Organisationseinheit",
        )

    def get_field_metadata(self, dataset_name: str):
        return {
            "Organisationseinheit": {
                "column_name": "Organisationseinheit",
                "property_label": "Organisationseinheit",
                "is_multi_value": True,
                "fk_relationship": {
                    "target_dataset": "Organisationseinheit",
                },
                "property_uri": self.PROPERTY_URI,
            }
        }

    def get_dataset_schema(self, dataset_name: str):
        return {"properties": {}}

    def augment_field_metadata_with_joins(self, dataset_name, metadata):
        return metadata, {"Organisationseinheit": self.relationship}

    def load_entity_by_uri(self, dataset_name: str, entity_uri: str):
        return {}


@pytest.fixture
def user(db):
    organization = Organization.objects.create(code="test-org", name="Test Org")
    User = get_user_model()
    user = User.objects.create_user(
        username="simplified-tester",
        email="simplified@example.com",
        password="simplified-pass",
    )
    user.organization = organization
    user.save()
    return user


@pytest.fixture
def dummy_service(monkeypatch):
    service = DummyProjektSchemaService()
    monkeypatch.setattr(
        simplified_workspace_views,
        "_get_schema_service",
        lambda request: service,
    )
    monkeypatch.setattr(
        simplified_workspace_views,
        "_infer_entity_label",
        lambda *args, **kwargs: "Dummy Label",
    )
    return service


@pytest.fixture
def dummy_join_service(monkeypatch):
    service = DummyJoinSchemaService()
    monkeypatch.setattr(
        simplified_workspace_views,
        "_get_schema_service",
        lambda request: service,
    )
    monkeypatch.setattr(
        simplified_workspace_views,
        "_infer_entity_label",
        lambda *args, **kwargs: "Dummy Join",
    )
    return service


@pytest.fixture
def dummy_ereignis_service(monkeypatch):
    service = DummyEreignisSchemaService()
    monkeypatch.setattr(
        simplified_workspace_views,
        "_get_schema_service",
        lambda request: service,
    )
    monkeypatch.setattr(
        simplified_workspace_views,
        "_infer_entity_label",
        lambda *args, **kwargs: "Dummy Ereignis",
    )
    return service


@pytest.mark.django_db
def test_get_renders_hidden_multi_value_field(client, user, dummy_service):
    client.force_login(user)
    response = client.get(
        reverse("metadata:edit_project"),
        {"uri": dummy_service.entity_uri},
    )
    assert response.status_code == 200
    content = response.content.decode()
    assert 'tabs tabs-bordered' in content
    assert 'role="tab"' in content
    assert 'role="tabpanel"' in content
    assert 'name="Projektart"' in content
    assert 'data-multi-value="true"' in content
    assert 'data-htmx-multi-select' not in content
    assert 'id="relationship-container-Projektart"' in content
    assert 'name="Projektart[]"' in content


@pytest.mark.django_db
def test_post_preserves_multi_value_relationships(client, user, dummy_service):
    client.force_login(user)
    response = client.post(
        reverse("metadata:edit_project"),
        {
            "entity_uri": dummy_service.entity_uri,
            "Projektart": "",
            "Projektart[]": [
                "http://example.org/project-type/a",
                "http://example.org/project-type/c",
            ],
        },
    )
    assert response.status_code == 302
    assert dummy_service.saved_entity_data is not None
    assert "Projektart" not in dummy_service.saved_entity_data
    assert dummy_service.multi_fk_calls == [
        (
            dummy_service.entity_uri,
            DummyProjektSchemaService.PROPERTY_URI,
            [
                "http://example.org/project-type/a",
                "http://example.org/project-type/c",
            ],
        )
    ]


@pytest.mark.django_db
def test_post_accepts_array_payloads(client, user, dummy_service):
    client.force_login(user)
    response = client.post(
        reverse("metadata:edit_project"),
        {
            "entity_uri": dummy_service.entity_uri,
            "Projektart[]": [
                "http://example.org/project-type/a",
                "http://example.org/project-type/c",
            ],
        },
    )
    assert response.status_code == 302
    saved = dummy_service.saved_entity_data
    assert saved is not None
    assert "Projektart" not in saved
    assert dummy_service.multi_fk_calls == [
        (
            dummy_service.entity_uri,
            DummyProjektSchemaService.PROPERTY_URI,
            [
                "http://example.org/project-type/a",
                "http://example.org/project-type/c",
            ],
        )
    ]


@pytest.mark.django_db
def test_post_clears_multi_value_relationships(client, user, dummy_service):
    client.force_login(user)
    response = client.post(
        reverse("metadata:edit_project"),
        {"entity_uri": dummy_service.entity_uri},
    )
    assert response.status_code == 302
    assert dummy_service.multi_fk_calls == [
        (
            dummy_service.entity_uri,
            DummyProjektSchemaService.PROPERTY_URI,
            [],
        )
    ]


@pytest.mark.django_db
def test_get_renders_hidden_multi_value_field_for_ereignis(client, user, dummy_ereignis_service):
    client.force_login(user)
    response = client.get(
        reverse("metadata:edit_ereignis"),
        {"uri": dummy_ereignis_service.entity_uri},
    )
    assert response.status_code == 200
    content = response.content.decode()
    assert 'tabs tabs-bordered' in content
    assert 'role="tab"' in content
    assert 'role="tabpanel"' in content
    assert 'name="Ereignistyp"' in content
    assert 'data-multi-value="true"' in content
    assert 'data-htmx-multi-select' not in content
    assert 'id="relationship-container-Ereignistyp"' in content
    assert 'name="Ereignistyp[]"' in content


@pytest.mark.django_db
def test_post_preserves_multi_value_relationships_for_ereignis(client, user, dummy_ereignis_service):
    client.force_login(user)
    response = client.post(
        reverse("metadata:edit_ereignis"),
        {
            "entity_uri": dummy_ereignis_service.entity_uri,
            "Ereignistyp": "",
            "Ereignistyp[]": [
                "http://example.org/event-type/a",
                "http://example.org/event-type/c",
            ],
        },
    )
    assert response.status_code == 302
    assert dummy_ereignis_service.saved_entity_data is not None
    assert "Ereignistyp" not in dummy_ereignis_service.saved_entity_data
    assert dummy_ereignis_service.multi_fk_calls == [
        (
            dummy_ereignis_service.entity_uri,
            DummyEreignisSchemaService.PROPERTY_URI,
            [
                "http://example.org/event-type/a",
                "http://example.org/event-type/c",
            ],
        )
    ]


@pytest.mark.django_db
def test_post_accepts_array_payloads_for_ereignis(client, user, dummy_ereignis_service):
    client.force_login(user)
    response = client.post(
        reverse("metadata:edit_ereignis"),
        {
            "entity_uri": dummy_ereignis_service.entity_uri,
            "Ereignistyp[]": [
                "http://example.org/event-type/a",
                "http://example.org/event-type/d",
            ],
        },
    )
    assert response.status_code == 302
    saved = dummy_ereignis_service.saved_entity_data
    assert saved is not None
    assert "Ereignistyp" not in saved
    assert dummy_ereignis_service.multi_fk_calls == [
        (
            dummy_ereignis_service.entity_uri,
            DummyEreignisSchemaService.PROPERTY_URI,
            [
                "http://example.org/event-type/a",
                "http://example.org/event-type/d",
            ],
        )
    ]


@pytest.mark.django_db
def test_post_syncs_join_relationships(client, user, dummy_join_service):
    client.force_login(user)
    response = client.post(
        reverse("metadata:edit_project"),
        {
            "entity_uri": dummy_join_service.entity_uri,
            "Organisationseinheit": "",
            "Organisationseinheit[]": [
                "http://example.org/org-unit/1",
                "http://example.org/org-unit/2",
            ],
        },
    )
    assert response.status_code == 302
    assert dummy_join_service.join_sync_calls == [
        (
            dummy_join_service.entity_uri,
            dummy_join_service.relationship,
            [
                "http://example.org/org-unit/1",
                "http://example.org/org-unit/2",
            ],
        )
    ]
    assert dummy_join_service.multi_fk_calls == []
