import json
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from urllib.parse import urlparse, parse_qs

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils.text import slugify

from arkumu.common.uri_utils import slugify_uri_part
from arkumu.metadata.models.mappings import Mapping
from arkumu.metadata.models.resource import Resource, ResourceType
from arkumu.metadata.models.triples import Triple
from arkumu.metadata.schema_workspace.forms import DatasetEntityForm
from arkumu.metadata.schema_workspace.services import SchemaWorkspaceService, RelationshipValues
from arkumu.metadata.views.schema_workspace_views import _apply_relationship_initials
from arkumu.users.models import Organization, User


pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _rdf_type_resource(db):
    Resource.objects.get_or_create(
        uri="http://www.w3.org/1999/02/22-rdf-syntax-ns#type",
        defaults={
            "resource_type": ResourceType.PROPERTY,
            "name": "rdf:type",
        },
    )


@dataclass
class FieldDefinition:
    name: str
    label: str
    column_type: str = "string"
    required: bool = False
    anchor: bool = False
    multi: bool = False
    separator: str = ";"
    fk_target: Optional[str] = None
    fk_column: Optional[str] = None
    external_uri_template: Optional[str] = None


@dataclass
class DatasetBlueprintConfig:
    name: str
    label: str
    fields: List[FieldDefinition]
    fk_relationships: List[Dict[str, str]] = field(default_factory=list)


class WorkspaceSchemaBuilder:
    def __init__(self, organization: Organization, base_uri: str = "http://arkumu.org/data"):
        from arkumu.importer.services.execution.resource_manager import ResourceManager
        from arkumu.importer.services.execution.statistics import ExecutionStatistics

        self.organization = organization
        self.base_uri = base_uri
        self.statistics = ExecutionStatistics()
        self.resource_manager = ResourceManager(
            organization=organization,
            base_uri=base_uri,
            statistics=self.statistics,
        )
        self.datasets: Dict[str, Dict[str, object]] = {}

    def _property_uri(self, dataset_name: str, field_name: str) -> str:
        return f"http://example.org/properties/{slugify(dataset_name)}/{slugify(field_name)}"

    def _class_uri(self, dataset_name: str) -> str:
        return f"http://example.org/classes/{slugify(dataset_name)}"

    def register_dataset(self, config: DatasetBlueprintConfig) -> None:
        entity_type = Resource.objects.create(
            uri=self._class_uri(config.name),
            resource_type=ResourceType.CLASS,
            name=config.label,
            organization=self.organization,
        )
        dataset_resource = self.resource_manager.create_dataset_resource(config.name)

        properties: Dict[str, Resource] = {}
        column_metadata: Dict[str, Dict[str, object]] = {}
        fk_relationships: List[Dict[str, object]] = []
        multi_value_schemas: Dict[str, Dict[str, object]] = {}
        external_ontology_schemas: Dict[str, Dict[str, object]] = {}

        for field_def in config.fields:
            property_resource = Resource.objects.create(
                uri=self._property_uri(config.name, field_def.name),
                resource_type=ResourceType.PROPERTY,
                name=field_def.label,
                organization=self.organization,
            )
            properties[field_def.name] = property_resource
            column_metadata[field_def.name] = {
                "column_name": field_def.name,
                "column_type": field_def.column_type,
                "property_label": field_def.label,
                "datatype": "http://www.w3.org/2001/XMLSchema#string",
                "is_required": field_def.required,
                "is_anchor": field_def.anchor,
                "is_multi_value": field_def.multi,
            }

            if field_def.multi:
                multi_value_schemas[field_def.name] = {
                    "separator": field_def.separator,
                }

            if field_def.external_uri_template:
                external_ontology_schemas[field_def.name] = {
                    "column_name": field_def.name,
                    "ontology_type": field_def.column_type,
                    "uri_template": field_def.external_uri_template,
                    "property_resource": property_resource,
                    "creates_external_reference": True,
                }

            if field_def.fk_target and field_def.fk_column:
                fk_relationships.append(
                    {
                        "source_column": field_def.name,
                        "target_dataset": field_def.fk_target,
                        "target_column": field_def.fk_column,
                        "source_property_uri": property_resource.uri,
                    }
                )

        blueprint = {
            "entity_type": entity_type,
            "entity_type_resource": entity_type,
            "dataset_resource": dataset_resource,
            "properties": properties,
            "column_metadata": column_metadata,
            "anchor_columns": [
                {"column_name": f.name}
                for f in config.fields
                if f.anchor
            ],
            "fk_relationships": fk_relationships,
            "multi_value_schemas": multi_value_schemas,
            "external_ontology_schemas": external_ontology_schemas,
        }
        self.datasets[config.name] = blueprint

    def as_schema_service(self):
        from types import SimpleNamespace

        datasets = self.datasets
        processor = SimpleNamespace(
            resource_manager=self.resource_manager,
            dataset_blueprints=datasets,
        )

        class StubSchemaService:
            def __init__(
                self,
                *,
                mapping_id: str,
                institution: str,
                base_uri: str,
                schema_variant_key: str | None = None,
            ) -> None:
                self.mapping_id = mapping_id
                self.institution = institution
                self.base_uri = base_uri
                self.schema_variant_key = schema_variant_key or "promoted_manifest"
                self._processor = processor

            def list_datasets(self):
                return list(datasets.keys())

            def get_dataset_schema(self, dataset_name):
                return datasets[dataset_name]

            def _ensure_schema_loaded(self):
                return None

        return StubSchemaService


@pytest.fixture
def organization(db):
    return Organization.objects.create(code="wrk", name="Workspace Org")


@pytest.fixture
def mapping(db, organization):
    return Mapping.objects.create(
        name="Workspace Mapping",
        organization_id=organization.code,
        is_active=True,
    )


@pytest.fixture
def user(db, organization):
    user = User.objects.create_user(username="workspace-user", password="pass1234")
    user.organization = organization
    user.save()
    return user


@pytest.fixture
def workspace_service(monkeypatch, organization):
    builder = WorkspaceSchemaBuilder(organization)

    builder.register_dataset(
        DatasetBlueprintConfig(
            name="Projekt",
            label="Projekt",
            fields=[
                FieldDefinition(name="projekt_id", label="Projekt-ID", anchor=True, required=True),
                FieldDefinition(name="titel", label="Titel", required=True),
                FieldDefinition(
                    name="wikidata_id",
                    label="Wikidata-ID",
                    external_uri_template="https://www.wikidata.org/entity/{identifier}",
                ),
            ],
        )
    )
    builder.register_dataset(
        DatasetBlueprintConfig(
            name="Ereignis",
            label="Ereignis",
            fields=[
                FieldDefinition(name="ereignis_id", label="Ereignis-ID", anchor=True, required=True),
                FieldDefinition(name="bezeichnung", label="Bezeichnung", required=True),
                FieldDefinition(
                    name="projekt_fk",
                    label="Projekt",
                    column_type="entity",
                    required=True,
                    fk_target="Projekt",
                    fk_column="projekt_id",
                ),
                FieldDefinition(
                    name="digital_object_fk",
                    label="Digitales Objekt",
                    column_type="entity",
                    fk_target="Digitales Objekt",
                    fk_column="objekt_id",
                ),
                FieldDefinition(name="rolle", label="Rolle"),
            ],
        )
    )
    builder.register_dataset(
        DatasetBlueprintConfig(
            name="Digitales Objekt",
            label="Digitales Objekt",
            fields=[
                FieldDefinition(name="objekt_id", label="Objekt-ID", anchor=True, required=True),
                FieldDefinition(name="titel", label="Objektitel", required=True),
            ],
        )
    )
    builder.register_dataset(
        DatasetBlueprintConfig(
            name="Informationsträger",
            label="Informationsträger",
            fields=[
                FieldDefinition(name="traeger_id", label="Träger-ID", anchor=True, required=True),
                FieldDefinition(name="bezeichnung", label="Trägername"),
            ],
        )
    )
    builder.register_dataset(
        DatasetBlueprintConfig(
            name="Akteur",
            label="Akteur",
            fields=[
                FieldDefinition(name="akteur_id", label="Akteur-ID", anchor=True, required=True),
                FieldDefinition(name="name", label="Name", required=True),
            ],
        )
    )
    builder.register_dataset(
        DatasetBlueprintConfig(
            name="Projekt_Ereignis",
            label="Projekt-Ereignis",
            fields=[
                FieldDefinition(
                    name="project_fk",
                    label="Projekt",
                    column_type="entity",
                    fk_target="Projekt",
                    fk_column="projekt_id",
                    required=True,
                ),
                FieldDefinition(
                    name="event_fk",
                    label="Ereignis",
                    column_type="entity",
                    fk_target="Ereignis",
                    fk_column="ereignis_id",
                    required=True,
                ),
            ],
        )
    )
    builder.register_dataset(
        DatasetBlueprintConfig(
            name="Ereignis_Digitales Objekt",
            label="Ereignis-Digitales Objekt",
            fields=[
                FieldDefinition(
                    name="event_fk",
                    label="Ereignis",
                    column_type="entity",
                    fk_target="Ereignis",
                    fk_column="ereignis_id",
                    required=True,
                ),
                FieldDefinition(
                    name="object_fk",
                    label="Digitales Objekt",
                    column_type="entity",
                    fk_target="Digitales Objekt",
                    fk_column="objekt_id",
                    required=True,
                ),
            ],
        )
    )
    builder.register_dataset(
        DatasetBlueprintConfig(
            name="Ereignis_Informationsträger",
            label="Ereignis-Informationsträger",
            fields=[
                FieldDefinition(
                    name="event_fk",
                    label="Ereignis",
                    column_type="entity",
                    fk_target="Ereignis",
                    fk_column="ereignis_id",
                    required=True,
                ),
                FieldDefinition(
                    name="carrier_fk",
                    label="Informationsträger",
                    column_type="entity",
                    fk_target="Informationsträger",
                    fk_column="traeger_id",
                    required=True,
                ),
            ],
        )
    )
    builder.register_dataset(
        DatasetBlueprintConfig(
            name="Ereignis_Akteur",
            label="Ereignis-Akteur",
            fields=[
                FieldDefinition(
                    name="event_fk",
                    label="Ereignis",
                    column_type="entity",
                    fk_target="Ereignis",
                    fk_column="ereignis_id",
                    required=True,
                ),
                FieldDefinition(
                    name="actor_fk",
                    label="Akteur",
                    column_type="entity",
                    fk_target="Akteur",
                    fk_column="akteur_id",
                    required=True,
                ),
            ],
        )
    )

    schema_service_cls = builder.as_schema_service()
    monkeypatch.setattr(
        "arkumu.metadata.schema_workspace.services.SchemaService",
        schema_service_cls,
    )
    return builder


def test_project_title_field_is_enforced(monkeypatch, organization, mapping):
    builder = WorkspaceSchemaBuilder(organization)
    builder.register_dataset(
        DatasetBlueprintConfig(
            name="Projekt",
            label="Projekt",
            fields=[
                FieldDefinition(name="projekt_id", label="Projekt-ID", anchor=True, required=True),
                FieldDefinition(name="bevorzugter_titel", label="Bevorzugter Titel", required=False),
            ],
        )
    )
    schema_service_cls = builder.as_schema_service()
    monkeypatch.setattr(
        "arkumu.metadata.schema_workspace.services.SchemaService",
        schema_service_cls,
    )

    service = SchemaWorkspaceService(
        mapping=mapping,
        organization=organization,
        base_uri="http://arkumu.org/data",
    )
    metadata = service.get_field_metadata("Projekt")
    assert metadata["bevorzugter_titel"]["is_required"] is True

    form = DatasetEntityForm(
        data={"projekt_id": "P-001", "bevorzugter_titel": ""},
        field_metadata=metadata,
    )
    assert form.is_valid() is False
    assert "bevorzugter_titel" in form.errors


def _post_dataset(client, mapping, dataset, payload, hx=True):
    url = reverse("metadata:entity_workspace_dataset", args=[mapping.id])
    headers = {}
    if hx:
        headers["HTTP_HX_REQUEST"] = "true"
    return client.post(
        url,
        {
            "dataset": dataset,
            **payload,
        },
        **headers,
    )


def _load_dataset(client, mapping, dataset, params, hx=True):
    url = reverse("metadata:entity_workspace_dataset", args=[mapping.id])
    headers = {}
    if hx:
        headers["HTTP_HX_REQUEST"] = "true"
    return client.get(
        url,
        {
            "dataset": dataset,
            **params,
        },
        **headers,
    )


def _get_dataset_table(client, mapping, dataset, params=None, hx=True):
    url = reverse("metadata:entity_workspace_table", args=[mapping.id])
    headers = {}
    if hx:
        headers["HTTP_HX_REQUEST"] = "true"
    return client.get(
        url,
        {
            "dataset": dataset,
            **(params or {}),
        },
        **headers,
    )


def _post_dataset_table_preference(client, mapping, payload, hx=True):
    url = reverse("metadata:entity_workspace_table_preference", args=[mapping.id])
    headers = {}
    if hx:
        headers["HTTP_HX_REQUEST"] = "true"
    return client.post(url, payload, **headers)


def _entity_uri(organization: Organization, dataset: str, identifier: str) -> str:
    org_slug = slugify_uri_part(str(organization.code))
    dataset_slug = slugify_uri_part(dataset)
    identifier_slug = slugify_uri_part(identifier)
    return f"http://arkumu.org/data/{org_slug}/entities/{dataset_slug}/{identifier_slug}"


def test_project_creation_persists_literals(client, user, mapping, organization, workspace_service):
    client.force_login(user)
    response = _post_dataset(
        client,
        mapping,
        "Projekt",
        {
            "projekt_id": "P-001",
            "titel": "Projekt Alpha",
        },
    )

    assert response.status_code == 200
    project_uri = _entity_uri(organization, "Projekt", "P-001")
    project_resource = Resource.objects.filter(uri=project_uri).first()
    assert project_resource is not None

    is_part_of = "http://purl.org/dc/terms/isPartOf"
    assert Triple.objects.filter(
        subject=project_resource,
        predicate__uri=is_part_of,
        source=organization,
    ).exists()

    titel_predicate = workspace_service.datasets["Projekt"]["properties"]["titel"]
    literal_values = Triple.objects.filter(
        subject=project_resource,
        predicate=titel_predicate,
    ).values_list("object__value", flat=True)
    assert list(literal_values) == ["Projekt Alpha"]

    reload_response = _load_dataset(
        client,
        mapping,
        "Projekt",
        {
            "mode": "load",
            "entity_uri": project_uri,
        },
    )
    assert reload_response.status_code == 200
    assert "Projekt Alpha" in reload_response.content.decode()


def test_dataset_table_uses_all_visible_fields_in_form_order(
    client,
    user,
    mapping,
    organization,
    workspace_service,
):
    client.force_login(user)

    project_uri = _entity_uri(organization, "Projekt", "P-001")
    object_uri = _entity_uri(organization, "Digitales Objekt", "O-001")

    assert _post_dataset(
        client,
        mapping,
        "Projekt",
        {
            "projekt_id": "P-001",
            "titel": "Projekt Alpha",
        },
    ).status_code == 200
    assert _post_dataset(
        client,
        mapping,
        "Digitales Objekt",
        {
            "objekt_id": "O-001",
            "titel": "Objekt Beta",
        },
    ).status_code == 200
    assert _post_dataset(
        client,
        mapping,
        "Ereignis",
        {
            "ereignis_id": "E-001",
            "bezeichnung": "Premiere",
            "projekt_fk": project_uri,
            "digital_object_fk": object_uri,
            "rolle": "Screening",
        },
    ).status_code == 200

    response = _get_dataset_table(client, mapping, "Ereignis")

    assert response.status_code == 200
    html = response.content.decode()
    assert "<th>Ereignis-ID</th>" not in html

    bezeichnung_pos = html.index("<th>Bezeichnung</th>")
    digital_pos = html.index("<th>Digitales Objekt</th>")
    projekt_pos = html.index("<th>Projekt</th>")
    rolle_pos = html.index("<th>Rolle</th>")

    assert bezeichnung_pos < digital_pos < projekt_pos < rolle_pos


def test_dataset_table_resolves_fk_values_to_labels(
    client,
    user,
    mapping,
    organization,
    workspace_service,
):
    client.force_login(user)

    project_uri = _entity_uri(organization, "Projekt", "P-020")
    object_uri = _entity_uri(organization, "Digitales Objekt", "O-020")

    assert _post_dataset(
        client,
        mapping,
        "Projekt",
        {
            "projekt_id": "P-020",
            "titel": "Projekt Table Label",
        },
    ).status_code == 200
    assert _post_dataset(
        client,
        mapping,
        "Digitales Objekt",
        {
            "objekt_id": "O-020",
            "titel": "Objekt Table Label",
        },
    ).status_code == 200
    assert _post_dataset(
        client,
        mapping,
        "Ereignis",
        {
            "ereignis_id": "E-020",
            "bezeichnung": "Event With Links",
            "projekt_fk": project_uri,
            "digital_object_fk": object_uri,
        },
    ).status_code == 200

    response = _get_dataset_table(client, mapping, "Ereignis")

    assert response.status_code == 200
    html = response.content.decode()
    assert "Projekt Table Label" in html
    assert "Objekt Table Label" in html
    assert project_uri not in html
    assert object_uri not in html


def test_dataset_table_preference_persists_and_can_reset(
    client,
    user,
    mapping,
    workspace_service,
):
    client.force_login(user)
    role_property_uri = workspace_service.datasets["Ereignis"]["properties"]["rolle"].uri
    project_property_uri = workspace_service.datasets["Ereignis"]["properties"]["projekt_fk"].uri

    response = _post_dataset_table_preference(
        client,
        mapping,
        {
            "dataset": "Ereignis",
            "columns": [role_property_uri, project_property_uri],
            "q": "alpha",
            "page": "2",
        },
    )

    assert response.status_code == 200
    mapping.refresh_from_db()
    assert (
        mapping.mapping_config["workspace_preferences"]["dataset_table_columns"]["Ereignis"]
        == [role_property_uri, project_property_uri]
    )

    hx_location = json.loads(response.headers["HX-Location"])
    assert "workspace" in hx_location["path"]
    assert "dataset=Ereignis" in hx_location["path"]
    assert "q=alpha" in hx_location["path"]
    assert "page=2" in hx_location["path"]

    clear_response = _post_dataset_table_preference(
        client,
        mapping,
        {
            "dataset": "Ereignis",
            "reset_columns": "1",
        },
    )

    assert clear_response.status_code == 200
    mapping.refresh_from_db()
    dataset_columns = (
        (mapping.mapping_config or {})
        .get("workspace_preferences", {})
        .get("dataset_table_columns", {})
    )
    assert "Ereignis" not in dataset_columns


def test_dataset_table_uses_configured_column_subset(
    client,
    user,
    mapping,
    organization,
    workspace_service,
):
    client.force_login(user)

    project_uri = _entity_uri(organization, "Projekt", "P-030")
    object_uri = _entity_uri(organization, "Digitales Objekt", "O-030")

    assert _post_dataset(
        client,
        mapping,
        "Projekt",
        {
            "projekt_id": "P-030",
            "titel": "Projekt Config Label",
        },
    ).status_code == 200
    assert _post_dataset(
        client,
        mapping,
        "Digitales Objekt",
        {
            "objekt_id": "O-030",
            "titel": "Objekt Config Label",
        },
    ).status_code == 200
    assert _post_dataset(
        client,
        mapping,
        "Ereignis",
        {
            "ereignis_id": "E-030",
            "bezeichnung": "Premiere",
            "projekt_fk": project_uri,
            "digital_object_fk": object_uri,
            "rolle": "Screening",
        },
    ).status_code == 200

    mapping.mapping_config = {
        "workspace_preferences": {
            "dataset_table_columns": {
                "Ereignis": [
                    workspace_service.datasets["Ereignis"]["properties"]["bezeichnung"].uri,
                    workspace_service.datasets["Ereignis"]["properties"]["rolle"].uri,
                ],
            }
        }
    }
    mapping.save(update_fields=["mapping_config"])

    response = _get_dataset_table(client, mapping, "Ereignis")

    assert response.status_code == 200
    html = response.content.decode()
    assert "<th>Bezeichnung</th>" in html
    assert "<th>Rolle</th>" in html
    assert "<th>Projekt</th>" not in html
    assert "<th>Digitales Objekt</th>" not in html


def test_read_only_relationship_items_include_workspace_edit_link(
    organization,
    mapping,
    workspace_service,
):
    service = SchemaWorkspaceService(
        mapping=mapping,
        organization=organization,
        base_uri="http://arkumu.org/data",
    )
    form = DatasetEntityForm(field_metadata={})

    event_uri, _ = service.save_entity(
        "Ereignis",
        {
            "ereignis_id": "E-900",
            "bezeichnung": "Bearbeitbares Ereignis",
        },
    )

    read_only = _apply_relationship_initials(
        service=service,
        form=form,
        relationships=[
            RelationshipValues(
                field_name="__reverse__Ereignis",
                display_label="Ereignis",
                uris=[event_uri],
                is_join=False,
                target_dataset="Ereignis",
                editable=False,
            )
        ],
    )

    assert len(read_only) == 1
    item = read_only[0]["items"][0]
    assert item["label"]
    assert "workspace" in item["load_url"]
    query = parse_qs(urlparse(item["load_url"]).query)
    assert query["dataset"] == ["Ereignis"]
    assert query["mode"] == ["load"]
    assert query["entity_uri"] == [event_uri]


def test_read_only_relationship_edit_button_scrolls_panel_to_top(
    client,
    user,
    mapping,
    organization,
    workspace_service,
):
    client.force_login(user)

    project_uri = _entity_uri(organization, "Projekt", "P-700")
    assert _post_dataset(
        client,
        mapping,
        "Projekt",
        {
            "projekt_id": "P-700",
            "titel": "Projekt Mit Beziehung",
        },
    ).status_code == 200
    assert _post_dataset(
        client,
        mapping,
        "Ereignis",
        {
            "ereignis_id": "E-700",
            "bezeichnung": "Ereignis Zum Bearbeiten",
            "projekt_fk": project_uri,
        },
    ).status_code == 200

    response = _load_dataset(
        client,
        mapping,
        "Projekt",
        {
            "mode": "load",
            "entity_uri": project_uri,
        },
    )

    assert response.status_code == 200
    html = response.content.decode()
    assert "Bearbeiten" in html
    assert 'hx-swap="innerHTML show:top"' in html


def test_dataset_table_uses_explicit_pagination_controls(
    client,
    user,
    mapping,
    organization,
    workspace_service,
):
    client.force_login(user)
    service = SchemaWorkspaceService(
        mapping=mapping,
        organization=organization,
        base_uri="http://arkumu.org/data",
    )

    for index in range(1, 53):
        service.save_entity(
            "Projekt",
            {
                "projekt_id": f"P-{index:03d}",
                "titel": f"Projekt {index:03d}",
            },
        )

    response = _get_dataset_table(client, mapping, "Projekt")

    assert response.status_code == 200
    html = response.content.decode()
    assert "Mehr laden" not in html
    assert "Seite 1" in html
    assert "page=2" in html


def test_dataset_table_batches_label_queries_for_large_result_sets(
    client,
    user,
    mapping,
    organization,
    workspace_service,
):
    client.force_login(user)
    service = SchemaWorkspaceService(
        mapping=mapping,
        organization=organization,
        base_uri="http://arkumu.org/data",
    )

    for index in range(1, 51):
        service.save_entity(
            "Projekt",
            {
                "projekt_id": f"P-{index:03d}",
                "titel": f"Projekt {index:03d}",
            },
        )

    with CaptureQueriesContext(connection) as ctx:
        response = _get_dataset_table(client, mapping, "Projekt")

    assert response.status_code == 200
    assert len(ctx.captured_queries) <= 20


def test_dataset_table_search_can_be_scoped_to_a_field(
    client,
    user,
    mapping,
    organization,
    workspace_service,
):
    client.force_login(user)

    project_uri = _entity_uri(organization, "Projekt", "P-101")
    object_uri = _entity_uri(organization, "Digitales Objekt", "O-101")

    assert _post_dataset(
        client,
        mapping,
        "Projekt",
        {
            "projekt_id": "P-101",
            "titel": "Search Host Project",
        },
    ).status_code == 200
    assert _post_dataset(
        client,
        mapping,
        "Digitales Objekt",
        {
            "objekt_id": "O-101",
            "titel": "Search Host Object",
        },
    ).status_code == 200

    assert _post_dataset(
        client,
        mapping,
        "Ereignis",
        {
            "ereignis_id": "E-101",
            "bezeichnung": "Alpha Event",
            "projekt_fk": project_uri,
            "digital_object_fk": object_uri,
            "rolle": "Screening",
        },
    ).status_code == 200
    assert _post_dataset(
        client,
        mapping,
        "Ereignis",
        {
            "ereignis_id": "E-102",
            "bezeichnung": "Beta Event",
            "projekt_fk": project_uri,
            "digital_object_fk": object_uri,
            "rolle": "Alpha Role",
        },
    ).status_code == 200

    role_property_uri = workspace_service.datasets["Ereignis"]["properties"]["rolle"].uri
    title_property_uri = workspace_service.datasets["Ereignis"]["properties"]["bezeichnung"].uri

    role_response = _get_dataset_table(
        client,
        mapping,
        "Ereignis",
        {"q": "Alpha", "property": role_property_uri},
    )
    assert role_response.status_code == 200
    role_html = role_response.content.decode()
    assert "Alpha Role" in role_html
    assert "Alpha Event" not in role_html

    title_response = _get_dataset_table(
        client,
        mapping,
        "Ereignis",
        {"q": "Alpha", "property": title_property_uri},
    )
    assert title_response.status_code == 200
    title_html = title_response.content.decode()
    assert "Alpha Event" in title_html
    assert "Alpha Role" not in title_html


def test_project_external_reference_uses_identifier_placeholder(
    client,
    user,
    mapping,
    organization,
    workspace_service,
):
    client.force_login(user)
    response = _post_dataset(
        client,
        mapping,
        "Projekt",
        {
            "projekt_id": "P-010",
            "titel": "Projekt Wikidata",
            "wikidata_id": "Q3939",
        },
    )
    assert response.status_code == 200

    project_uri = _entity_uri(organization, "Projekt", "P-010")
    wikidata_uri = "https://www.wikidata.org/entity/Q3939"
    wikidata_resource = Resource.objects.filter(uri=wikidata_uri).first()
    assert wikidata_resource is not None
    assert wikidata_resource.is_placeholder is False

    wikidata_property = workspace_service.datasets["Projekt"]["properties"]["wikidata_id"]
    assert Triple.objects.filter(
        subject__uri=project_uri,
        predicate=wikidata_property,
        object=wikidata_resource,
    ).exists()

    reload_response = _load_dataset(
        client,
        mapping,
        "Projekt",
        {
            "mode": "load",
            "entity_uri": project_uri,
        },
    )
    assert reload_response.status_code == 200
    html = reload_response.content.decode()
    assert 'value="Q3939"' in html
    assert "https://www.wikidata.org/entity/Q3939" not in html


def test_project_external_reference_can_be_updated(
    client,
    user,
    mapping,
    organization,
    workspace_service,
):
    client.force_login(user)
    create_response = _post_dataset(
        client,
        mapping,
        "Projekt",
        {
            "projekt_id": "P-011",
            "titel": "Projekt Delta",
            "wikidata_id": "Q3939",
        },
    )
    assert create_response.status_code == 200

    project_uri = _entity_uri(organization, "Projekt", "P-011")
    wikidata_property = workspace_service.datasets["Projekt"]["properties"]["wikidata_id"]

    # Update to a different identifier
    update_response = _post_dataset(
        client,
        mapping,
        "Projekt",
        {
            "entity_uri": project_uri,
            "projekt_id": "P-011",
            "titel": "Projekt Delta",
            "wikidata_id": "Q42",
        },
    )
    assert update_response.status_code == 200

    triples = Triple.objects.filter(
        subject__uri=project_uri,
        predicate=wikidata_property,
    )
    assert triples.count() == 1
    assert triples.first().object.uri == "https://www.wikidata.org/entity/Q42"

    reload_response = _load_dataset(
        client,
        mapping,
        "Projekt",
        {
            "mode": "load",
            "entity_uri": project_uri,
        },
    )
    assert reload_response.status_code == 200
    html = reload_response.content.decode()
    assert 'value="Q42"' in html


def test_project_creation_continue_editing_keeps_context(
    client,
    user,
    mapping,
    organization,
    workspace_service,
):
    client.force_login(user)
    response = _post_dataset(
        client,
        mapping,
        "Projekt",
        {
            "projekt_id": "P-003",
            "titel": "Projekt Gamma",
            "submission_mode": "stay_on_entity",
        },
    )
    assert response.status_code == 200
    project_uri = _entity_uri(organization, "Projekt", "P-003")
    content = response.content.decode()
    assert project_uri in content
    assert "weiter bearbeiten" in content

    update_response = _post_dataset(
        client,
        mapping,
        "Projekt",
        {
            "entity_uri": project_uri,
            "projekt_id": "P-003",
            "titel": "Projekt Gamma aktualisiert",
        },
    )
    assert update_response.status_code == 200
    assert "Änderungen gespeichert." in update_response.content.decode()

    titel_predicate = workspace_service.datasets["Projekt"]["properties"]["titel"]
    literal_values = Triple.objects.filter(
        subject__uri=project_uri,
        predicate=titel_predicate,
    ).values_list("object__value", flat=True)
    assert list(literal_values) == ["Projekt Gamma aktualisiert"]


def test_project_event_join_create_and_remove(
    client,
    user,
    mapping,
    organization,
    workspace_service,
):
    client.force_login(user)
    _post_dataset(
        client,
        mapping,
        "Projekt",
        {
            "projekt_id": "P-002",
            "titel": "Projekt Beta",
        },
    )
    project_uri = _entity_uri(organization, "Projekt", "P-002")

    _post_dataset(
        client,
        mapping,
        "Ereignis",
        {
            "ereignis_id": "E-100",
            "bezeichnung": "Eröffnung",
            "projekt_fk": project_uri,
        },
    )
    event_uri = _entity_uri(organization, "Ereignis", "E-100")

    join_payload = json.dumps([event_uri])
    response = _post_dataset(
        client,
        mapping,
        "Projekt",
        {
            "entity_uri": project_uri,
            "projekt_id": "P-002",
            "titel": "Projekt Beta",
            "__join__Projekt_Ereignis__Ereignis": join_payload,
        },
    )
    assert response.status_code == 200

    project_property = workspace_service.datasets["Projekt_Ereignis"]["properties"]["project_fk"]
    event_property = workspace_service.datasets["Projekt_Ereignis"]["properties"]["event_fk"]
    join_subject_ids = Triple.objects.filter(
        predicate=project_property,
        object__uri=project_uri,
    ).values_list("subject_id", flat=True)
    assert join_subject_ids
    join_subject_id = join_subject_ids[0]
    assert Triple.objects.filter(
        subject_id=join_subject_id,
        predicate=event_property,
        object__uri=event_uri,
    ).exists()

    response = _post_dataset(
        client,
        mapping,
        "Projekt",
        {
            "entity_uri": project_uri,
            "projekt_id": "P-002",
            "titel": "Projekt Beta",
            "__join__Projekt_Ereignis__Ereignis": json.dumps([]),
        },
    )
    assert response.status_code == 200
    assert not Triple.objects.filter(
        predicate=project_property,
        object__uri=project_uri,
    ).exists()


def test_event_form_hides_direct_digital_object_field(
    client,
    user,
    mapping,
    organization,
    workspace_service,
):
    client.force_login(user)
    _post_dataset(
        client,
        mapping,
        "Projekt",
        {
            "projekt_id": "P-010",
            "titel": "Projekt Gamma",
        },
    )
    load_response = _load_dataset(
        client,
        mapping,
        "Ereignis",
        {},
    )
    body = load_response.content.decode()
    assert 'name="digital_object_fk"' not in body
    assert "__join__Ereignis_Digitales Objekt__Digitales Objekt" in body


def test_event_informationstraeger_join_persists_relationship(
    client,
    user,
    mapping,
    organization,
    workspace_service,
):
    client.force_login(user)
    _post_dataset(
        client,
        mapping,
        "Projekt",
        {
            "projekt_id": "P-900",
            "titel": "Projekt Delta",
        },
    )
    project_uri = _entity_uri(organization, "Projekt", "P-900")

    _post_dataset(
        client,
        mapping,
        "Ereignis",
        {
            "ereignis_id": "E-900",
            "bezeichnung": "Workshop",
            "projekt_fk": project_uri,
        },
    )
    event_uri = _entity_uri(organization, "Ereignis", "E-900")

    _post_dataset(
        client,
        mapping,
        "Informationsträger",
        {
            "traeger_id": "T-1",
            "bezeichnung": "Audio Kassette",
        },
    )
    carrier_uri = _entity_uri(organization, "Informationsträger", "T-1")

    response = _post_dataset(
        client,
        mapping,
        "Ereignis",
        {
            "entity_uri": event_uri,
            "ereignis_id": "E-900",
            "bezeichnung": "Workshop",
            "projekt_fk": project_uri,
            "__join__Ereignis_Informationsträger__Informationsträger": json.dumps([carrier_uri]),
        },
    )
    assert response.status_code == 200

    service = SchemaWorkspaceService(
        mapping=mapping,
        organization=organization,
    )
    info_relationship = next(
        rel
        for rel in service.list_join_relationships("Ereignis")
        if rel.other_dataset == "Informationsträger"
    )
    carrier_property = info_relationship.other_property_uri
    assert Triple.objects.filter(
        predicate__uri=carrier_property,
        object__uri=carrier_uri,
    ).exists()


def test_event_digital_object_join_merges_existing_and_new_targets(
    client,
    user,
    mapping,
    organization,
    workspace_service,
):
    client.force_login(user)
    _post_dataset(
        client,
        mapping,
        "Projekt",
        {
            "projekt_id": "P-310",
            "titel": "Projekt Theta",
        },
    )
    project_uri = _entity_uri(organization, "Projekt", "P-310")

    _post_dataset(
        client,
        mapping,
        "Digitales Objekt",
        {
            "objekt_id": "DO-1",
            "titel": "Digital Alt",
        },
    )
    digital_old_uri = _entity_uri(organization, "Digitales Objekt", "DO-1")

    _post_dataset(
        client,
        mapping,
        "Ereignis",
        {
            "ereignis_id": "E-310",
            "bezeichnung": "Seminar",
            "projekt_fk": project_uri,
            "__join__Ereignis_Digitales Objekt__Digitales Objekt": json.dumps([digital_old_uri]),
        },
    )
    event_uri = _entity_uri(organization, "Ereignis", "E-310")

    _post_dataset(
        client,
        mapping,
        "Digitales Objekt",
        {
            "objekt_id": "DO-2",
            "titel": "Digital Neu",
        },
    )
    digital_new_uri = _entity_uri(organization, "Digitales Objekt", "DO-2")

    response = _post_dataset(
        client,
        mapping,
        "Ereignis",
        {
            "entity_uri": event_uri,
            "ereignis_id": "E-310",
            "bezeichnung": "Seminar",
            "projekt_fk": project_uri,
            "__join__Ereignis_Digitales Objekt__Digitales Objekt": json.dumps(
                [digital_old_uri, digital_new_uri]
            ),
        },
    )
    assert response.status_code == 200

    service = SchemaWorkspaceService(
        mapping=mapping,
        organization=organization,
    )
    join_schema = service.get_dataset_schema("Ereignis_Digitales Objekt")
    event_prop = join_schema["properties"]["event_fk"]
    object_prop = join_schema["properties"]["object_fk"]

    join_subject_ids = list(
        Triple.objects.filter(
            predicate=event_prop,
            object__uri=event_uri,
        ).values_list("subject_id", flat=True)
    )
    assert len(join_subject_ids) == 2
    related = set(
        Triple.objects.filter(
            predicate=object_prop,
            subject_id__in=join_subject_ids,
        ).values_list("object__uri", flat=True)
    )
    assert related == {digital_old_uri, digital_new_uri}

    response = _post_dataset(
        client,
        mapping,
        "Ereignis",
        {
            "entity_uri": event_uri,
            "ereignis_id": "E-310",
            "bezeichnung": "Seminar",
            "projekt_fk": project_uri,
            "__join__Ereignis_Digitales Objekt__Digitales Objekt": json.dumps(
                [digital_old_uri, digital_new_uri]
            ),
        },
    )
    assert response.status_code == 200
    join_subject_ids_repeat = list(
        Triple.objects.filter(
            predicate=event_prop,
            object__uri=event_uri,
        ).values_list("subject_id", flat=True)
    )
    assert len(join_subject_ids_repeat) == 2
    related_repeat = set(
        Triple.objects.filter(
            predicate=object_prop,
            subject_id__in=join_subject_ids_repeat,
        ).values_list("object__uri", flat=True)
    )
    assert related_repeat == {digital_old_uri, digital_new_uri}


def test_event_actor_join_and_role_literal(
    client,
    user,
    mapping,
    organization,
    workspace_service,
):
    client.force_login(user)
    _post_dataset(
        client,
        mapping,
        "Projekt",
        {
            "projekt_id": "P-500",
            "titel": "Projekt Epsilon",
        },
    )
    project_uri = _entity_uri(organization, "Projekt", "P-500")
    _post_dataset(
        client,
        mapping,
        "Ereignis",
        {
            "ereignis_id": "E-500",
            "bezeichnung": "Lesung",
            "projekt_fk": project_uri,
        },
    )
    event_uri = _entity_uri(organization, "Ereignis", "E-500")

    _post_dataset(
        client,
        mapping,
        "Akteur",
        {
            "akteur_id": "A-1",
            "name": "K. Person",
        },
    )
    actor_uri = _entity_uri(organization, "Akteur", "A-1")

    response = _post_dataset(
        client,
        mapping,
        "Ereignis",
        {
            "entity_uri": event_uri,
            "ereignis_id": "E-500",
            "bezeichnung": "Lesung",
            "projekt_fk": project_uri,
            "rolle": "Kurator",
            "__join__Ereignis_Akteur__Akteur": json.dumps([actor_uri]),
        },
    )
    assert response.status_code == 200

    service = SchemaWorkspaceService(
        mapping=mapping,
        organization=organization,
    )
    rolle_predicate = service.get_dataset_schema("Ereignis")["properties"]["rolle"]
    assert Triple.objects.filter(
        subject__uri=event_uri,
        predicate=rolle_predicate,
        object__value="Kurator",
    ).exists()

    actor_relationship = next(
        rel
        for rel in service.list_join_relationships("Ereignis")
        if rel.other_dataset == "Akteur"
    )
    actor_predicate = actor_relationship.other_property_uri
    assert Triple.objects.filter(
        predicate__uri=actor_predicate,
        object__uri=actor_uri,
    ).exists()


def test_literal_suggestions_include_recent_entry(
    client,
    user,
    mapping,
    organization,
    workspace_service,
):
    client.force_login(user)
    project_uri = _entity_uri(organization, "Projekt", "P-777")
    _post_dataset(
        client,
        mapping,
        "Projekt",
        {
            "projekt_id": "P-777",
            "titel": "Projekt Vorschlag",
        },
    )
    _post_dataset(
        client,
        mapping,
        "Ereignis",
        {
            "ereignis_id": "E-777",
            "bezeichnung": "Vortrag",
            "projekt_fk": project_uri,
            "rolle": "Kuratorischer Beitrag",
        },
    )

    url = reverse("metadata:entity_workspace_field_values", args=[mapping.id])
    response = client.get(
        url,
        {
            "dataset": "Ereignis",
            "column": "rolle",
            "input_id": "id_rolle",
            "target_id": "field-suggestions-rolle",
            "q": "Kur",
        },
        HTTP_HX_REQUEST="true",
    )
    assert response.status_code == 200
    assert "Kuratorischer Beitrag" in response.content.decode()


def test_workspace_triple_snapshot_matches_expected(
    client,
    user,
    mapping,
    organization,
    workspace_service,
):
    client.force_login(user)

    project_uri = _entity_uri(organization, "Projekt", "P-990")
    event_uri = _entity_uri(organization, "Ereignis", "E-990")
    digital_uri = _entity_uri(organization, "Digitales Objekt", "D-990")
    carrier_uri = _entity_uri(organization, "Informationsträger", "T-990")
    actor_uri = _entity_uri(organization, "Akteur", "A-990")

    _post_dataset(
        client,
        mapping,
        "Projekt",
        {
            "projekt_id": "P-990",
            "titel": "Projekt Zeta",
        },
    )
    _post_dataset(
        client,
        mapping,
        "Ereignis",
        {
            "ereignis_id": "E-990",
            "bezeichnung": "Performance",
            "projekt_fk": project_uri,
        },
    )
    _post_dataset(
        client,
        mapping,
        "Digitales Objekt",
        {
            "objekt_id": "D-990",
            "titel": "Digital Objekt",
        },
    )
    _post_dataset(
        client,
        mapping,
        "Informationsträger",
        {
            "traeger_id": "T-990",
            "bezeichnung": "Audio Tape",
        },
    )
    _post_dataset(
        client,
        mapping,
        "Akteur",
        {
            "akteur_id": "A-990",
            "name": "Team Member",
        },
    )

    _post_dataset(
        client,
        mapping,
        "Projekt",
        {
            "entity_uri": project_uri,
            "projekt_id": "P-990",
            "titel": "Projekt Zeta",
            "__join__Projekt_Ereignis__Ereignis": json.dumps([event_uri]),
        },
    )
    _post_dataset(
        client,
        mapping,
        "Ereignis",
        {
            "entity_uri": event_uri,
            "ereignis_id": "E-990",
            "bezeichnung": "Performance",
            "projekt_fk": project_uri,
            "rolle": "Kurator",
            "__join__Projekt_Ereignis__Projekt": json.dumps([project_uri]),
            "__join__Ereignis_Digitales Objekt__Digitales Objekt": json.dumps([digital_uri]),
            "__join__Ereignis_Informationsträger__Informationsträger": json.dumps([carrier_uri]),
            "__join__Ereignis_Akteur__Akteur": json.dumps([actor_uri]),
        },
    )

    service = SchemaWorkspaceService(
        mapping=mapping,
        organization=organization,
    )
    project_schema = service.get_dataset_schema("Projekt")
    event_schema = service.get_dataset_schema("Ereignis")
    digital_schema = service.get_dataset_schema("Digitales Objekt")
    carrier_schema = service.get_dataset_schema("Informationsträger")
    actor_schema = service.get_dataset_schema("Akteur")
    project_join_schema = service.get_dataset_schema("Projekt_Ereignis")
    event_digital_schema = service.get_dataset_schema("Ereignis_Digitales Objekt")
    event_carrier_schema = service.get_dataset_schema("Ereignis_Informationsträger")
    event_actor_schema = service.get_dataset_schema("Ereignis_Akteur")

    def _join_subject(schema, predicate_key, target_uri):
        predicate = schema["properties"][predicate_key]
        matches = list(
            Triple.objects.filter(
            predicate=predicate,
            object__uri=target_uri,
        ).values_list("subject__uri", flat=True)
        )
        assert matches, f"Expected join entity for {predicate.uri} -> {target_uri}"
        return matches[0]

    project_event_join_uri = _join_subject(project_join_schema, "project_fk", project_uri)
    event_digital_join_uri = _join_subject(event_digital_schema, "event_fk", event_uri)
    event_carrier_join_uri = _join_subject(event_carrier_schema, "event_fk", event_uri)
    event_actor_join_uri = _join_subject(event_actor_schema, "event_fk", event_uri)

    rdf_type = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
    is_part_of = "http://purl.org/dc/terms/isPartOf"

    def capture(subject_uri: str) -> set[tuple[str, tuple[str, str]]]:
        records = []
        for triple in Triple.objects.filter(subject__uri=subject_uri).select_related("predicate", "object"):
            obj = triple.object
            if obj.resource_type == ResourceType.LITERAL:
                records.append((triple.predicate.uri, ("literal", obj.value)))
            else:
                records.append((triple.predicate.uri, ("uri", obj.uri)))
        return set(records)

    def literal(value: str) -> tuple[str, str]:
        return ("literal", value)

    def uri(value: str) -> tuple[str, str]:
        return ("uri", value)

    expected = {
        project_uri: {
            (rdf_type, uri(project_schema["entity_type"].uri)),
            (is_part_of, uri(project_schema["dataset_resource"].uri)),
            (project_schema["properties"]["projekt_id"].uri, literal("P-990")),
            (project_schema["properties"]["titel"].uri, literal("Projekt Zeta")),
        },
        event_uri: {
            (rdf_type, uri(event_schema["entity_type"].uri)),
            (is_part_of, uri(event_schema["dataset_resource"].uri)),
            (event_schema["properties"]["ereignis_id"].uri, literal("E-990")),
            (event_schema["properties"]["bezeichnung"].uri, literal("Performance")),
            (event_schema["properties"]["rolle"].uri, literal("Kurator")),
        },
        digital_uri: {
            (rdf_type, uri(digital_schema["entity_type"].uri)),
            (is_part_of, uri(digital_schema["dataset_resource"].uri)),
            (digital_schema["properties"]["objekt_id"].uri, literal("D-990")),
            (digital_schema["properties"]["titel"].uri, literal("Digital Objekt")),
        },
        carrier_uri: {
            (rdf_type, uri(carrier_schema["entity_type"].uri)),
            (is_part_of, uri(carrier_schema["dataset_resource"].uri)),
            (carrier_schema["properties"]["traeger_id"].uri, literal("T-990")),
            (carrier_schema["properties"]["bezeichnung"].uri, literal("Audio Tape")),
        },
        actor_uri: {
            (rdf_type, uri(actor_schema["entity_type"].uri)),
            (is_part_of, uri(actor_schema["dataset_resource"].uri)),
            (actor_schema["properties"]["akteur_id"].uri, literal("A-990")),
            (actor_schema["properties"]["name"].uri, literal("Team Member")),
        },
        project_event_join_uri: {
            (rdf_type, uri(project_join_schema["entity_type"].uri)),
            (is_part_of, uri(project_join_schema["dataset_resource"].uri)),
            (project_join_schema["properties"]["project_fk"].uri, uri(project_uri)),
            (project_join_schema["properties"]["event_fk"].uri, uri(event_uri)),
        },
        event_digital_join_uri: {
            (rdf_type, uri(event_digital_schema["entity_type"].uri)),
            (is_part_of, uri(event_digital_schema["dataset_resource"].uri)),
            (event_digital_schema["properties"]["event_fk"].uri, uri(event_uri)),
            (event_digital_schema["properties"]["object_fk"].uri, uri(digital_uri)),
        },
        event_carrier_join_uri: {
            (rdf_type, uri(event_carrier_schema["entity_type"].uri)),
            (is_part_of, uri(event_carrier_schema["dataset_resource"].uri)),
            (event_carrier_schema["properties"]["event_fk"].uri, uri(event_uri)),
            (event_carrier_schema["properties"]["carrier_fk"].uri, uri(carrier_uri)),
        },
        event_actor_join_uri: {
            (rdf_type, uri(event_actor_schema["entity_type"].uri)),
            (is_part_of, uri(event_actor_schema["dataset_resource"].uri)),
            (event_actor_schema["properties"]["event_fk"].uri, uri(event_uri)),
            (event_actor_schema["properties"]["actor_fk"].uri, uri(actor_uri)),
        },
    }

    actual = {subject_uri: capture(subject_uri) for subject_uri in expected}
    assert set(actual) == set(expected)
    for uri in expected:
        assert actual[uri] == expected[uri]


def test_invalid_suggestion_column_returns_error_without_side_effects(
    client,
    user,
    mapping,
    organization,
    workspace_service,
):
    client.force_login(user)
    project_uri = _entity_uri(organization, "Projekt", "P-321")
    Resource.objects.create(
        uri=project_uri,
        resource_type=ResourceType.ENTITY,
        organization=organization,
        name="Existing Projekt",
    )

    url = reverse("metadata:entity_workspace_field_values", args=[mapping.id])
    response = client.get(
        url,
        {
            "dataset": "Projekt",
            "column": "unknown_column",
            "input_id": "id_missing",
            "target_id": "field-suggestions-missing",
        },
        HTTP_HX_REQUEST="true",
    )
    assert response.status_code == 400
    assert Triple.objects.filter(subject__uri=project_uri).count() == 0
