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


class DummyProjektSchemaService(_BaseDummySchemaService):
    """Stub service focused on Projekt dataset interactions."""

    PROJECT_TYPE_PROPERTY_URI = "http://example.org/properties/project-type"
    PROJECT_LINK_PROPERTY_URI = "http://example.org/properties/verknuepftes-projekt"

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
            "Verknüpftes Projekt": {
                "column_name": "Verknüpftes Projekt",
                "property_label": "Verknüpftes Projekt",
                "is_multi_value": True,
                "property_uri": self.PROJECT_LINK_PROPERTY_URI,
                "fk_relationship": {
                    "target_dataset": "Projekt",
                },
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
            "Verknüpftes Projekt": json.dumps(
                [
                    {"uri": "http://example.org/project/linked-1"},
                    {"uri": "http://example.org/project/linked-2"},
                ]
            ),
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


from arkumu.metadata.schema_workspace.services import JoinRelationship


class DummyJoinSchemaService(_BaseDummySchemaService):
    """Stub service that surfaces a join relationship for Projekt dataset."""

    PROPERTY_URI = "http://example.org/properties/verknuepftes-projekt"
    CONTEXT_PROPERTY_URI = "http://example.org/properties/beziehung"
    FIELD_NAME = "__join__Projekt_Projekt_Kreuztabelle__Projekt"

    def __init__(self) -> None:
        super().__init__("projekt/PROJ-2")
        self.relationship = JoinRelationship(
            join_dataset="Projekt_Projekt_Kreuztabelle",
            join_dataset_schema={
                "junction_schema": {"context_columns": ["Beziehung"]},
            },
            self_column="Ausgangsprojekt",
            self_property_uri=self.PROPERTY_URI,
            other_dataset="Projekt",
            other_column="Verknüpftes Projekt",
            other_property_uri=self.PROPERTY_URI,
            other_display_label="Projekt",
            context_columns=[
                {
                    "column": "Beziehung",
                    "property_uri": self.CONTEXT_PROPERTY_URI,
                    "slug": "beziehung",
                }
            ],
        )

    def get_field_metadata(self, dataset_name: str):
        return {
            self.FIELD_NAME: {
                "column_name": self.FIELD_NAME,
                "column_type": "join",
                "property_label": "Projekt",
                "is_multi_value": True,
                "is_join": True,
                "join_relationship": self.relationship,
                "join_other_dataset": "Projekt",
                "property_uri": self.PROPERTY_URI,
                "help_text": "Verknüpfte Projekte",
                "context_columns": [
                    {
                        "column": "Beziehung",
                        "property_uri": self.CONTEXT_PROPERTY_URI,
                        "slug": "beziehung",
                    }
                ],
                "context_options": {
                    "Beziehung": ["ist Teil von", "hat Teil"],
                },
            }
        }

    def get_dataset_schema(self, dataset_name: str):
        return {"properties": {}}

    def augment_field_metadata_with_joins(self, dataset_name, metadata):
        # Return a fresh copy so tests can mutate without side-effects
        meta = self.get_field_metadata(dataset_name)
        return meta, {self.FIELD_NAME: self.relationship}

    def load_entity_by_uri(self, dataset_name: str, entity_uri: str):
        return {}

    def get_context_value_options(self, property_uri, limit=200):
        return ["ist Teil von", "hat Teil"]


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
    assert 'Normdaten und Links' in content
    assert 'name="Projektart"' in content
    assert 'data-multi-value="true"' in content
    assert 'data-htmx-multi-select' not in content
    assert 'id="relationship-container-Projektart"' in content
    assert 'name="Projektart[]"' in content
    assert 'name="Wikidata-ID"' in content
    assert 'name="Andere Normdaten"' in content
    assert 'name="Externe Projektwebseite"' in content
    assert 'name="Verknüpftes Projekt[]"' in content


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
    assert calls[DummyProjektSchemaService.PROJECT_LINK_PROPERTY_URI] == []


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
    assert calls[DummyProjektSchemaService.PROJECT_LINK_PROPERTY_URI] == []


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
    assert calls[DummyProjektSchemaService.PROJECT_LINK_PROPERTY_URI] == []


@pytest.mark.django_db
def test_post_filters_self_from_linked_projects(client, user, dummy_service):
    client.force_login(user)
    response = client.post(
        reverse("metadata:edit_project"),
        {
            "entity_uri": dummy_service.entity_uri,
            "Verknüpftes Projekt": "",
            "Verknüpftes Projekt[]": [
                "http://example.org/project/linked-1",
                dummy_service.entity_uri,
                "http://example.org/project/linked-3",
            ],
        },
    )
    assert response.status_code == 302
    calls = {
        property_uri: related
        for _, property_uri, related in dummy_service.multi_fk_calls
    }
    assert calls[DummyProjektSchemaService.PROJECT_LINK_PROPERTY_URI] == [
        "http://example.org/project/linked-1",
        "http://example.org/project/linked-3",
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


@pytest.mark.django_db
def test_get_renders_project_link_join_field(client, user, dummy_join_service):
    client.force_login(user)
    response = client.get(
        reverse("metadata:edit_project"),
        {"uri": dummy_join_service.entity_uri},
    )
    assert response.status_code == 200
    fields = response.context["fields_with_metadata"]
    field_names = [item["field"].name for item in fields]
    assert DummyJoinSchemaService.FIELD_NAME in field_names
    content = response.content.decode()
    assert "Verknüpfte Projekte" in content
    assert "__context__" in content
    assert "ist Teil von" in content


@pytest.mark.django_db
def test_post_syncs_join_relationships(client, user, dummy_join_service):
    client.force_login(user)
    response = client.post(
        reverse("metadata:edit_project"),
        {
            "entity_uri": dummy_join_service.entity_uri,
            DummyJoinSchemaService.FIELD_NAME: "",
            f"{DummyJoinSchemaService.FIELD_NAME}[]": [
                "http://example.org/project/alpha",
                dummy_join_service.entity_uri,
                "http://example.org/project/beta",
            ],
            f"{DummyJoinSchemaService.FIELD_NAME}__context__beziehung[]": [
                "ist Teil von",
                "hat Teil",
                "hat Teil",
            ],
        },
    )
    assert response.status_code == 302
    assert dummy_join_service.join_sync_calls == [
        (
            dummy_join_service.entity_uri,
            dummy_join_service.relationship,
            [
                {"uri": "http://example.org/project/alpha", "context": {"Beziehung": "ist Teil von"}},
                {"uri": "http://example.org/project/beta", "context": {"Beziehung": "hat Teil"}},
            ],
        )
    ]
    assert dummy_join_service.multi_fk_calls == []
