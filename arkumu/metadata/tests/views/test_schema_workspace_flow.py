import pytest
from django.urls import reverse
from types import SimpleNamespace

from arkumu.metadata.schema_workspace.flow import SchemaWorkspaceCoordinator
from arkumu.metadata.views import schema_workspace_views
from arkumu.metadata.models.mappings import Mapping
from arkumu.users.models import Organization, User


PROJECT_DATASET = "Projekt"
EVENT_DATASET = "Ereignis"


class StubSchemaWorkspaceService:
    def __init__(self, mapping, organization):
        self.mapping = mapping
        self.organization = organization
        self.saved_payloads = {}
        self._processor = SimpleNamespace(
            resource_manager=SimpleNamespace(
                generate_entity_uri=lambda dataset, value: f"http://example.org/{dataset}/{value}",
            )
        )

    # Dataset metadata ---------------------------------------------------
    def list_datasets(self):
        return [
            SimpleNamespace(
                dataset_name=PROJECT_DATASET,
                display_label="Projekt",
                anchor_columns=["projekt_id"],
                property_count=1,
                relationship_count=0,
            ),
            SimpleNamespace(
                dataset_name=EVENT_DATASET,
                display_label="Ereignis",
                anchor_columns=["ereignis_id"],
                property_count=2,
                relationship_count=1,
            ),
        ]

    def get_field_metadata(self, dataset_name):
        if dataset_name == PROJECT_DATASET:
            return {
                "projekt_id": {
                    "column_name": "projekt_id",
                    "is_anchor": True,
                    "is_required": True,
                    "column_type": "string",
                    "property_label": "Projekt-ID",
                },
                "projekt_name": {
                    "column_name": "projekt_name",
                    "is_required": True,
                    "column_type": "string",
                    "property_label": "Projektname",
                },
            }
        if dataset_name == EVENT_DATASET:
            return {
                "ereignis_id": {
                    "column_name": "ereignis_id",
                    "is_anchor": True,
                    "is_required": True,
                    "column_type": "string",
                    "property_label": "Ereignis-ID",
                },
                "ereignisname": {
                    "column_name": "ereignisname",
                    "is_required": True,
                    "column_type": "string",
                    "property_label": "Ereignisname",
                },
                "project_uri": {
                    "column_name": "project_uri",
                    "has_fk": True,
                    "is_required": True,
                    "column_type": "string",
                    "property_label": "Projekt",
                },
            }
        raise ValueError(f"Unsupported dataset '{dataset_name}'")

    def get_dataset_schema(self, dataset_name):
        if dataset_name == PROJECT_DATASET:
            return {
                "fk_relationships": [],
                "anchor_columns": [{"column_name": "projekt_id"}],
                "column_metadata": self.get_field_metadata(dataset_name),
            }
        if dataset_name == EVENT_DATASET:
            return {
                "fk_relationships": [
                    {
                        "source_column": "project_uri",
                        "target_dataset": PROJECT_DATASET,
                    }
                ],
                "anchor_columns": [{"column_name": "ereignis_id"}],
                "column_metadata": self.get_field_metadata(dataset_name),
            }
        raise ValueError(f"Unsupported dataset '{dataset_name}'")

    # Persistence --------------------------------------------------------
    def save_entity(self, dataset_name, entity_data, entity_uri=None):
        self.saved_payloads.setdefault(dataset_name, []).append(entity_data)
        if dataset_name == PROJECT_DATASET:
            uri = f"http://example.org/project/{entity_data['projekt_id']}"
        elif dataset_name == EVENT_DATASET:
            uri = f"http://example.org/event/{entity_data['ereignis_id']}"
        else:
            uri = f"http://example.org/{dataset_name}/placeholder"
        return uri, True

    # Joins --------------------------------------------------------------
    def list_join_relationships(self, dataset_name):
        return []

    def get_join_values(self, relationship, entity_uri):
        return []

    def sync_join_relationship(self, *, entity_uri, relationship, related_items):
        return None


@pytest.fixture
def organization(db):
    return Organization.objects.create(code="testorg", name="Test Org")


@pytest.fixture
def mapping(db, organization):
    return Mapping.objects.create(name="Test Mapping", organization_id=organization.code)


@pytest.fixture
def user(db, organization):
    user = User.objects.create_user(username="flow-user", password="pass1234")
    user.organization = organization
    user.save()
    return user


@pytest.fixture
def stub_service(monkeypatch, mapping, organization):
    service = StubSchemaWorkspaceService(mapping=mapping, organization=organization)

    def _stub(request, mapping_id):
        return service

    monkeypatch.setattr(schema_workspace_views, "_get_schema_service", _stub)
    return service


@pytest.mark.django_db
def test_project_post_updates_flow_state(client, user, mapping, organization, stub_service):
    client.force_login(user)
    coordinator = SchemaWorkspaceCoordinator()
    dummy_request = SimpleNamespace(session=client.session)
    coordinator.set_current_organization(dummy_request, organization.id)
    coordinator.set_current_mapping(
        dummy_request,
        str(mapping.id),
        mapping_name=mapping.name,
        organization_id=organization.id,
    )
    flow_state = coordinator.get_or_create_flow_state(
        dummy_request,
        mapping=mapping,
        organization=organization,
    )
    client.session.save()

    url = reverse("metadata:entity_workspace_flow", args=[mapping.id]) + "?step=project"
    response = client.post(
        url,
        {
            "flow_id": flow_state.flow_id,
            "step": "project",
            "projekt_id": "P-001",
            "projekt_name": "Projekt Alpha",
        },
        follow=True,
    )

    assert response.status_code == 200
    dummy_request = SimpleNamespace(session=client.session)
    states = coordinator.list_flow_states(dummy_request, mapping, organization)
    assert flow_state.flow_id in states
    updated_state = states[flow_state.flow_id]
    assert updated_state.project is not None
    assert updated_state.project.uri == "http://example.org/project/P-001"
    assert "Projekt erfolgreich erstellt" in response.content.decode()


@pytest.mark.django_db
def test_event_post_links_to_project(client, user, mapping, organization, stub_service):
    client.force_login(user)
    coordinator = SchemaWorkspaceCoordinator()
    dummy_request = SimpleNamespace(session=client.session)
    coordinator.set_current_organization(dummy_request, organization.id)
    coordinator.set_current_mapping(
        dummy_request,
        str(mapping.id),
        mapping_name=mapping.name,
        organization_id=organization.id,
    )
    flow_state = coordinator.get_or_create_flow_state(
        dummy_request,
        mapping=mapping,
        organization=organization,
    )
    client.session.save()

    project_url = reverse("metadata:entity_workspace_flow", args=[mapping.id]) + "?step=project"
    client.post(
        project_url,
        {
            "flow_id": flow_state.flow_id,
            "step": "project",
            "projekt_id": "P-100",
            "projekt_name": "Projekt Beta",
        },
    )

    event_url = reverse("metadata:entity_workspace_flow", args=[mapping.id]) + "?step=events"
    response = client.post(
        event_url,
        {
            "flow_id": flow_state.flow_id,
            "step": "events",
            "ereignis_id": "E-200",
            "ereignisname": "Kickoff",
            "project_uri": "http://example.org/project/P-100",
        },
        follow=True,
    )

    assert response.status_code == 200
    dummy_request = SimpleNamespace(session=client.session)
    states = coordinator.list_flow_states(dummy_request, mapping, organization)
    updated_state = states[flow_state.flow_id]
    assert len(updated_state.events) == 1
    event = next(iter(updated_state.events.values()))
    assert event.uri == "http://example.org/event/E-200"
    assert "Ereignis gespeichert" in response.content.decode()
    # ensure FK propagated to service payload
    saved_event = stub_service.saved_payloads[EVENT_DATASET][0]
    assert saved_event["project_uri"] == "http://example.org/project/P-100"
