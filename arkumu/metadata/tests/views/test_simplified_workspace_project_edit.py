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

    def sync_join_relationship(self, *, entity_uri: str, relationship, related_items):
        serialized = []
        for item in related_items:
            if isinstance(item, dict):
                serialized.append(
                    {
                        "uri": item.get("uri"),
                        "context": item.get("context") or {},
                    }
                )
            else:
                serialized.append({"uri": item, "context": {}})
        self.join_sync_calls.append((entity_uri, relationship, serialized))

    def list_triple_relationships(self, **kwargs):
        return []

    def suggest_triple_targets(self, **kwargs):
        return []

    def create_triple_relationship(self, **kwargs):
        return True, SimpleNamespace(id=uuid.uuid4())

    def delete_triple_relationship(self, **kwargs):
        return 1


class DummyProjektSchemaService(_BaseDummySchemaService):
    """Stub service focused on Projekt dataset interactions."""

    PROJECT_TYPE_PROPERTY_URI = "http://example.org/properties/project-type"
    PROJECT_RELATION_FIELDS = {
        "Projekt hat Teil": ("projekt-hat-teil", "http://example.org/properties/projekt-hat-teil", "child"),
        "Projekt ist Teil von": ("projekt-ist-teil-von", "http://example.org/properties/projekt-ist-teil-von", "parent"),
        "Projekt hat Bezug zu": ("projekt-hat-bezug-zu", "http://example.org/properties/projekt-hat-bezug-zu", "related"),
        "Projekt basiert auf": ("projekt-basiert-auf", "http://example.org/properties/projekt-basiert-auf", "source"),
        "Projekt ist vorbereitend für": ("projekt-ist-vorbereitend-fuer", "http://example.org/properties/projekt-ist-vorbereitend-fuer", "followup"),
    }

    def __init__(self) -> None:
        super().__init__("projekt/PROJ-1")

    def get_field_metadata(self, dataset_name: str):
        return {
            "Projektart": {
                "column_name": "Projektart",
                "property_label": "Projektart",
                "is_multi_value": True,
                "is_external_ontology": True,
                "property_uri": self.PROJECT_TYPE_PROPERTY_URI,
                "fk_relationship": {
                    "target_dataset": "Projektart",
                    "target_property_uri": "http://example.org/properties/code",
                },
            },
            "Wikidata-ID": {
                "column_name": "Wikidata-ID",
                "property_label": "Wikidata-ID",
                "is_multi_value": False,
            },
            "GND-Nummer": {
                "column_name": "GND-Nummer",
                "property_label": "GND-Nummer",
                "is_multi_value": False,
            },
            "Andere Normdaten": {
                "column_name": "Andere Normdaten",
                "property_label": "Andere Normdaten",
                "is_multi_value": True,
            },
            "Externe Projektwebseite": {
                "column_name": "Externe Projektwebseite",
                "property_label": "Externe Projektwebseite",
                "is_multi_value": True,
            },
            **{
                slug: {
                    "column_name": slug,
                    "property_label": label,
                    "is_multi_value": True,
                    "property_uri": uri,
                    "fk_relationship": {"target_dataset": "Projekt"},
                    "widget": "TripleCreatorWidget",
                }
                for label, (slug, uri, _) in self.PROJECT_RELATION_FIELDS.items()
            },
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
            ),
            **{
                slug: json.dumps(
                    [
                        {"uri": f"http://example.org/project/{sample}-1"},
                        {"uri": f"http://example.org/project/{sample}-2"},
                    ]
                )
                for label, (slug, _, sample) in self.PROJECT_RELATION_FIELDS.items()
            },
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
    assert 'tabs tabs-bordered' in content
    assert 'role="tab"' in content
    assert 'role="tabpanel"' in content
    assert 'Normdaten und Links' in content
    assert 'name="Projektart"' in content
    assert 'data-multi-value="true"' in content
    assert 'data-htmx-multi-select' not in content
    assert 'id="relationship-container-Projektart"' in content
    assert 'name="Projektart[]"' in content
    assert 'name="Wikidata-ID"' in content
    assert 'name="Andere Normdaten"' in content
    assert 'name="Externe Projektwebseite"' in content
    assert 'id="triple-component-projekt-hat-teil"' in content


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
    calls = {
        property_uri: related
        for _, property_uri, related in dummy_service.multi_fk_calls
    }
    assert calls[DummyProjektSchemaService.PROJECT_TYPE_PROPERTY_URI] == [
        "http://example.org/project-type/a",
        "http://example.org/project-type/c",
    ]
    for _, uri, _ in DummyProjektSchemaService.PROJECT_RELATION_FIELDS.values():
        assert calls.get(uri, []) == []


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
    calls = {
        property_uri: related
        for _, property_uri, related in dummy_service.multi_fk_calls
    }
    assert calls[DummyProjektSchemaService.PROJECT_TYPE_PROPERTY_URI] == [
        "http://example.org/project-type/a",
        "http://example.org/project-type/c",
    ]
    for _, uri, _ in DummyProjektSchemaService.PROJECT_RELATION_FIELDS.values():
        assert calls.get(uri, []) == []


@pytest.mark.django_db
def test_post_clears_multi_value_relationships(client, user, dummy_service):
    client.force_login(user)
    response = client.post(
        reverse("metadata:edit_project"),
        {"entity_uri": dummy_service.entity_uri},
    )
    assert response.status_code == 302
    calls = {
        property_uri: related
        for _, property_uri, related in dummy_service.multi_fk_calls
    }
    assert calls[DummyProjektSchemaService.PROJECT_TYPE_PROPERTY_URI] == []
    for _, uri, _ in DummyProjektSchemaService.PROJECT_RELATION_FIELDS.values():
        assert calls.get(uri, []) == []


@pytest.mark.django_db
def test_post_filters_self_from_linked_projects(client, user, dummy_service):
    client.force_login(user)
    response = client.post(
        reverse("metadata:edit_project"),
        {
            "entity_uri": dummy_service.entity_uri,
            "projekt-hat-teil": "",
            "projekt-hat-teil[]": [
                "http://example.org/project/child-1",
                dummy_service.entity_uri,
                "http://example.org/project/child-3",
            ],
        },
    )
    assert response.status_code == 302
    calls = {
        property_uri: related
        for _, property_uri, related in dummy_service.multi_fk_calls
    }
    relation_uri = DummyProjektSchemaService.PROJECT_RELATION_FIELDS["Projekt hat Teil"][1]
    assert calls[relation_uri] == [
        "http://example.org/project/child-1",
        "http://example.org/project/child-3",
    ]
    assert calls[DummyProjektSchemaService.PROJECT_TYPE_PROPERTY_URI] == []


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
