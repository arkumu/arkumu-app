import json
from types import SimpleNamespace

import pytest
from django.urls import reverse

from arkumu.metadata.schema_workspace.services import JoinRelationship
from arkumu.metadata.views import schema_workspace_views
from arkumu.metadata.models.resource import Resource, ResourceType
from arkumu.metadata.models.triples import Triple
from arkumu.metadata.models.mappings import Mapping
from arkumu.users.models import Organization, User


@pytest.fixture
def organization(db):
    return Organization.objects.create(code="joinorg", name="Join Org")


@pytest.fixture
def mapping(db, organization):
    return Mapping.objects.create(name="Join Mapping", organization_id=organization.code)


@pytest.mark.django_db
def test_dataset_field_value_options_returns_literals(client, monkeypatch):
    organization = Organization.objects.create(code="optorg", name="Options Org")
    mapping = Mapping.objects.create(name="Options Mapping", organization_id=organization.code)

    property_resource = Resource.objects.create(
        uri="http://arkumu.org/data/optorg/properties/titel",
        resource_type=ResourceType.PROPERTY,
        name="Titel",
        organization=organization,
    )
    literal_resource = Resource.objects.create(
        resource_type=ResourceType.LITERAL,
        value="Beispielwert",
    )
    subject_resource = Resource.objects.create(
        uri="http://arkumu.org/data/optorg/entities/projekt/1",
        resource_type=ResourceType.ENTITY,
        organization=organization,
    )
    Triple.objects.create(
        subject=subject_resource,
        predicate=property_resource,
        object=literal_resource,
        source=organization,
    )

    class StubService:
        def __init__(self):
            self.mapping = mapping
            self.organization = organization

        def get_field_metadata(self, dataset_name):
            return {
                "titel": {
                    "property_uri": property_resource.uri,
                }
            }

        def get_dataset_schema(self, dataset_name):
            return {
                "properties": {
                    "titel": property_resource,
                }
            }

        def list_join_relationships(self, dataset_name):
            return []

        def get_join_values(self, relationship, entity_uri):
            return []

        def sync_join_relationship(self, *, entity_uri, relationship, related_uris):
            return None

    monkeypatch.setattr(
        schema_workspace_views,
        "_get_schema_service",
        lambda request, mapping_id: StubService(),
    )

    user = User.objects.create_user(username="options-user", password="pass1234")
    user.organization = organization
    user.save()
    client.force_login(user)

    url = reverse("metadata:entity_workspace_field_values", args=[mapping.id])
    response = client.get(
        url,
        {
            "dataset": "00_hfm_Projekte",
            "column": "titel",
            "input_id": "id_titel",
            "target_id": "field-suggestions-titel",
        },
        HTTP_HX_REQUEST="true",
    )

    assert response.status_code == 200
    assert "Beispielwert" in response.content.decode()


@pytest.mark.django_db
def test_entity_search_view_matches_literals(client, monkeypatch):
    organization = Organization.objects.create(code="searchorg", name="Search Org")
    mapping = Mapping.objects.create(name="Search Mapping", organization_id=organization.code)

    dataset_resource = Resource.objects.create(
        uri="http://arkumu.org/data/searchorg/datasets/projekte",
        resource_type=ResourceType.IRI,
        organization=organization,
        name="Projekte",
    )
    project_entity = Resource.objects.create(
        uri="http://arkumu.org/data/searchorg/entities/projekt/p1",
        resource_type=ResourceType.ENTITY,
        organization=organization,
    )
    title_property = Resource.objects.create(
        uri="http://arkumu.org/data/searchorg/properties/titel",
        resource_type=ResourceType.PROPERTY,
        name="Titel",
        organization=organization,
    )
    literal_resource = Resource.objects.create(
        resource_type=ResourceType.LITERAL,
        value="Suchbarer Titel",
    )
    is_part_of = Resource.objects.get_or_create(
        uri="http://purl.org/dc/terms/isPartOf",
        defaults={
            "resource_type": ResourceType.PROPERTY,
            "name": "isPartOf",
        },
    )[0]

    Triple.objects.create(
        subject=project_entity,
        predicate=is_part_of,
        object=dataset_resource,
        source=organization,
    )
    Triple.objects.create(
        subject=project_entity,
        predicate=title_property,
        object=literal_resource,
        source=organization,
    )

    class StubService:
        def __init__(self):
            self.mapping = mapping
            self.organization = organization

        def get_dataset_schema(self, dataset_name):
            return {
                "dataset_resource": dataset_resource,
                "properties": {
                    "titel": title_property,
                },
            }

        def _resolve_dataset_resource(self, dataset_name, schema):
            return dataset_resource

    monkeypatch.setattr(
        schema_workspace_views,
        "_get_schema_service",
        lambda request, mapping_id: StubService(),
    )

    user = User.objects.create_user(username="search-user", password="pass1234")
    user.organization = organization
    user.save()
    client.force_login(user)

    url = reverse("metadata:entity_workspace_search", args=[mapping.id])
    response = client.get(
        url,
        {
            "dataset": "00_hfm_Projekte",
            "q": "Suchbarer",
        },
        HTTP_HX_REQUEST="true",
    )

    assert response.status_code == 200
    assert "Suchbarer Titel" in response.content.decode()


@pytest.mark.django_db
def test_join_relationship_render_and_save(client, monkeypatch, organization, mapping):
    project_uri = "http://example.org/project/1"
    event_uri = "http://example.org/event/1"
    event_uri_two = "http://example.org/event/2"

    name_property = Resource.objects.create(
        uri="http://example.org/name",
        resource_type=ResourceType.PROPERTY,
        name="name",
        organization=organization,
    )
    event_resource = Resource.objects.create(
        uri=event_uri,
        resource_type=ResourceType.ENTITY,
        organization=organization,
    )
    literal_resource = Resource.objects.create(
        resource_type=ResourceType.LITERAL,
        value="Event Alpha",
    )
    Triple.objects.create(
        subject=event_resource,
        predicate=name_property,
        object=literal_resource,
        source=organization,
    )

    project_property_resource = Resource.objects.create(
        uri="http://example.org/prop/project",
        resource_type=ResourceType.PROPERTY,
        name="project_fk",
        organization=organization,
    )
    event_property_resource = Resource.objects.create(
        uri="http://example.org/prop/event",
        resource_type=ResourceType.PROPERTY,
        name="event_fk",
        organization=organization,
    )

    join_relationship = JoinRelationship(
        join_dataset="Projekt_Ereignis",
        join_dataset_schema={
            "entity_type": Resource.objects.create(
                uri="http://example.org/types/join",
                resource_type=ResourceType.CLASS,
                name="Join",
                organization=organization,
            ),
            "properties": {
                "project_fk": project_property_resource,
                "event_fk": event_property_resource,
            },
        },
        self_column="project_fk",
        self_property_uri=project_property_resource.uri,
        other_dataset="Ereignis",
        other_column="event_fk",
        other_property_uri=event_property_resource.uri,
        other_display_label="Ereignis",
    )

    class JoinStubService:
        def __init__(self):
            self.mapping = mapping
            self.organization = organization
            self.synced = []

        def get_field_metadata(self, dataset_name):
            return {}

        def get_dataset_schema(self, dataset_name):
            if dataset_name == join_relationship.join_dataset:
                return join_relationship.join_dataset_schema
            return {
                "properties": {},
                "column_metadata": {},
                "anchor_columns": [],
                "fk_relationships": [],
            }

        def get_dataset_summary(self, dataset_name):
            return SimpleNamespace(
                dataset_name=dataset_name,
                display_label=dataset_name,
                anchor_columns=[],
                property_count=0,
                relationship_count=0,
            )

        def list_join_relationships(self, dataset_name):
            if dataset_name == "Projekt":
                return [join_relationship]
            return []

        def get_join_values(self, relationship, entity_uri):
            if entity_uri == project_uri:
                return [event_uri]
            return []

        def sync_join_relationship(self, *, entity_uri, relationship, related_uris):
            self.synced.append((entity_uri, tuple(related_uris)))

        def save_entity(self, dataset_name, entity_data, entity_uri=None):
            return project_uri, False

        def load_entity_by_uri(self, dataset_name, entity_uri):
            return {}

    stub_service = JoinStubService()

    monkeypatch.setattr(
        schema_workspace_views,
        "_get_schema_service",
        lambda request, mapping_id: stub_service,
    )

    user = User.objects.create_user(username="join-user", password="pass1234")
    user.organization = organization
    user.save()
    client.force_login(user)

    # Load form with existing join
    get_url = reverse("metadata:entity_workspace_dataset", args=[mapping.id])
    response = client.get(
        get_url,
        {
            "dataset": "Projekt",
            "mode": "load",
            "entity_uri": project_uri,
        },
        HTTP_HX_REQUEST="true",
    )
    assert response.status_code == 200
    body = response.content.decode()
    assert "Event Alpha" in body

    # Submit updated join selection
    payload = {
        "dataset": "Projekt",
        "entity_uri": project_uri,
        "__join__Projekt_Ereignis__Ereignis": json.dumps([event_uri, event_uri_two]),
    }
    response = client.post(
        get_url,
        payload,
        HTTP_HX_REQUEST="true",
    )
    assert response.status_code == 200
    assert stub_service.synced[-1] == (project_uri, (event_uri, event_uri_two))
