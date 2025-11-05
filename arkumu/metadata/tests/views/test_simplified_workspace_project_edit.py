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

    def augment_field_metadata_with_joins(self, dataset_name, metadata):
        return metadata, {}

    def collect_relationship_values(self, **kwargs):
        return []

    def save_entity(self, *, dataset_name: str, entity_data: dict, entity_uri: str):
        self.saved_entity_data = entity_data
        return entity_uri or self.entity_uri, False


class DummyProjektSchemaService(_BaseDummySchemaService):
    """Stub service focused on Projekt dataset interactions."""

    def __init__(self) -> None:
        super().__init__("projekt/PROJ-1")

    def get_field_metadata(self, dataset_name: str):
        return {
            "Projektart": {
                "column_name": "Projektart",
                "property_label": "Projektart",
                "is_multi_value": True,
                "is_external_ontology": True,
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

    def __init__(self) -> None:
        super().__init__("ereignis/EVT-1")

    def get_field_metadata(self, dataset_name: str):
        return {
            "Ereignistyp": {
                "column_name": "Ereignistyp",
                "property_label": "Ereignistyp",
                "is_multi_value": True,
                "is_external_ontology": True,
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
    assert 'name="Projektart"' in content
    assert 'data-multi-value="true"' in content
    assert "Suchen nach" not in content
    assert 'select id="relationship-property' not in content
    assert "property=http%3A//example.org/properties/code" in content
    assert 'name="relationship_property_Projektart"' in content
    assert 'value="http://example.org/properties/code"' in content


@pytest.mark.django_db
def test_post_preserves_multi_value_relationships(client, user, dummy_service):
    client.force_login(user)
    payload = [
        {"uri": "http://example.org/project-type/a"},
        {"uri": "http://example.org/project-type/c"},
    ]
    response = client.post(
        reverse("metadata:edit_project"),
        {
            "entity_uri": dummy_service.entity_uri,
            "Projektart": json.dumps(payload),
        },
    )
    assert response.status_code == 302
    assert dummy_service.saved_entity_data is not None
    assert dummy_service.saved_entity_data.get("Projektart") == json.dumps(payload)


@pytest.mark.django_db
def test_post_accepts_array_payloads(client, user, dummy_service):
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
    saved = dummy_service.saved_entity_data
    assert saved is not None
    parsed = json.loads(saved.get("Projektart"))
    uris = {entry["uri"] for entry in parsed}
    assert uris == {
        "http://example.org/project-type/a",
        "http://example.org/project-type/c",
    }


@pytest.mark.django_db
def test_get_renders_hidden_multi_value_field_for_ereignis(client, user, dummy_ereignis_service):
    client.force_login(user)
    response = client.get(
        reverse("metadata:edit_ereignis"),
        {"uri": dummy_ereignis_service.entity_uri},
    )
    assert response.status_code == 200
    content = response.content.decode()
    assert 'name="Ereignistyp"' in content
    assert 'data-multi-value="true"' in content
    assert "Suchen nach" not in content
    assert 'select id="relationship-property' not in content
    assert "property=http%3A//example.org/properties/code" in content
    assert 'name="relationship_property_Ereignistyp"' in content
    assert 'value="http://example.org/properties/code"' in content


@pytest.mark.django_db
def test_post_preserves_multi_value_relationships_for_ereignis(client, user, dummy_ereignis_service):
    client.force_login(user)
    payload = [
        {"uri": "http://example.org/event-type/a"},
        {"uri": "http://example.org/event-type/c"},
    ]
    response = client.post(
        reverse("metadata:edit_ereignis"),
        {
            "entity_uri": dummy_ereignis_service.entity_uri,
            "Ereignistyp": json.dumps(payload),
        },
    )
    assert response.status_code == 302
    assert dummy_ereignis_service.saved_entity_data is not None
    assert dummy_ereignis_service.saved_entity_data.get("Ereignistyp") == json.dumps(payload)


@pytest.mark.django_db
def test_post_accepts_array_payloads_for_ereignis(client, user, dummy_ereignis_service):
    client.force_login(user)
    response = client.post(
        reverse("metadata:edit_ereignis"),
        {
            "entity_uri": dummy_ereignis_service.entity_uri,
            "Ereignistyp": "",
            "Ereignistyp[]": [
                "http://example.org/event-type/a",
                "http://example.org/event-type/d",
            ],
        },
    )
    assert response.status_code == 302
    saved = dummy_ereignis_service.saved_entity_data
    assert saved is not None
    parsed = json.loads(saved.get("Ereignistyp"))
    uris = {entry["uri"] for entry in parsed}
    assert uris == {
        "http://example.org/event-type/a",
        "http://example.org/event-type/d",
    }
