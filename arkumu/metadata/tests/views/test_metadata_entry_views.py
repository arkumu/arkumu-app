import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from arkumu.catalog.services.project_views import CardURIs
from arkumu.metadata.models.mappings import Mapping
from arkumu.metadata.models.resource import Resource, ResourceType
from arkumu.metadata.models.triples import Triple
from arkumu.metadata.services.canonical_graph_service import RDF_TYPE_URI
from arkumu.users.models import Organization


@pytest.fixture
@pytest.mark.django_db
def organization():
    return Organization.objects.create(name="Folkwang", code="fuk")


@pytest.fixture
@pytest.mark.django_db
def user(organization):
    User = get_user_model()
    return User.objects.create_user(
        username="archivist",
        password="test-pass",
        organization=organization,
        role="archivist",
    )


@pytest.fixture
@pytest.mark.django_db
def client_logged_in(client, user):
    client.force_login(user)
    return client


def _create_typed_option(*, organization, type_uri, resource_uri, label, label_predicate_uri):
    type_resource, _ = Resource.objects.get_or_create(
        uri=type_uri,
        defaults={
            "canonical_uri": type_uri,
            "resource_type": ResourceType.CLASS,
        },
    )
    rdf_type_resource, _ = Resource.objects.get_or_create(
        uri=RDF_TYPE_URI,
        defaults={
            "canonical_uri": RDF_TYPE_URI,
            "resource_type": ResourceType.PROPERTY,
        },
    )
    label_predicate, _ = Resource.objects.get_or_create(
        uri=label_predicate_uri,
        defaults={
            "canonical_uri": label_predicate_uri,
            "resource_type": ResourceType.PROPERTY,
        },
    )
    resource = Resource.objects.create(
        uri=resource_uri,
        resource_type=ResourceType.ENTITY,
        organization=organization,
        name=label,
    )
    literal = Resource.objects.create(
        resource_type=ResourceType.LITERAL,
        value=label,
        organization=organization,
    )
    Triple.objects.create(subject=resource, predicate=rdf_type_resource, object=type_resource, source=organization)
    Triple.objects.create(subject=resource, predicate=label_predicate, object=literal, source=organization)
    return resource


@pytest.mark.django_db
def test_dashboard_renders_sections(client_logged_in, organization):
    url = reverse("metadata:metadata_entry")
    response = client_logged_in.get(
        url,
        {
            "organization": organization.code,
            "legacy": "1",
        },
    )

    assert response.status_code == 200
    body = response.content.decode()
    assert "Metadata Workspace" in body
    assert "Projekte" in body


@pytest.mark.django_db
def test_section_form_returns_htmx_partial(client_logged_in, organization):
    url = reverse("metadata:metadata_entry_section")
    response = client_logged_in.get(
        url,
        {"organization": organization.code, "section": "overview"},
        HTTP_HX_REQUEST="true",
    )

    assert response.status_code == 200
    body = response.content.decode()
    assert "name=\"title\"" in body
    assert "Speichern" in body
    assert "metadata-entry-panel" in body


@pytest.mark.django_db
def test_submit_creates_resource(client_logged_in, organization):
    url = reverse("metadata:metadata_entry_submit")
    response = client_logged_in.post(
        url,
        {
            "organization": organization.code,
            "section": "overview",
            "title": "HTMX Record",
            "subtitle": "Ein Abend",
        },
        HTTP_HX_REQUEST="true",
    )

    assert response.status_code == 200
    body = response.content.decode()
    assert "Metadaten gespeichert" in body
    assert Resource.objects.filter(name="HTMX Record").exists()
    assert "metadata-entry-panel" in body


@pytest.mark.django_db
def test_submit_missing_required_field_shows_error(client_logged_in, organization):
    url = reverse("metadata:metadata_entry_submit")
    response = client_logged_in.post(
        url,
        {
            "organization": organization.code,
            "section": "overview",
            "subtitle": "Ohne Titel",
        },
        HTTP_HX_REQUEST="true",
    )

    assert response.status_code == 200
    body = response.content.decode()
    assert "Pflichtfeld" in body
    assert Resource.objects.filter(name="Ohne Titel").exists() is False
    assert "metadata-entry-panel" in body


@pytest.mark.django_db
def test_mask_entry_dashboard_renders_mask_and_binding_inspector(client_logged_in, organization):
    Mapping.objects.create(
        name="Folkwang Projekt Mapping",
        organization_id=organization.code,
        mapping_config={
            "workspace_columns": {
                "fuk::00_Projekte::Titel": {
                    "dataset": "00_Projekte",
                    "name": "Titel",
                    "canonical_mapping": {
                        "canonical_property_uri": CardURIs.TITLE,
                        "canonical_property_label": "Bevorzugter Titel",
                    },
                }
            }
        },
    )

    url = reverse("metadata:mask_entry")
    response = client_logged_in.get(
        url,
        {
            "organization": organization.code,
            "entity": "project",
            "phase": "create",
        },
    )

    assert response.status_code == 200
    body = response.content.decode()
    assert "Mask Schema Preview" in body
    assert "Anlegen" in body
    assert "Projektübersicht" in body
    assert "Binding Inspector" in body
    assert "Maskentextquelle" in body
    assert "Feldlabelquelle" in body
    assert "Pflichtbewertung aus" in body
    assert "Slotquelle" in body
    assert "Bindingquelle" in body
    assert "Frontend Grails" in body
    assert "Backend Grails" in body
    assert "ja" in body
    assert "Folkwang Projekt Mapping" in body
    assert "00_Projekte" in body
    assert "Titel" in body
    assert "Untertitel" not in body
    assert "Schlagworte" not in body


@pytest.mark.django_db
def test_mask_entry_dashboard_returns_partial_for_htmx(client_logged_in, organization):
    url = reverse("metadata:mask_entry")
    response = client_logged_in.get(
        url,
        {
            "organization": organization.code,
            "entity": "project",
            "phase": "create",
        },
        HTTP_HX_REQUEST="true",
    )

    assert response.status_code == 200
    body = response.content.decode()
    assert "Mask Schema Preview" in body
    assert '<div id="mask-entry-root">' not in body
    assert "Maske laden" in body


@pytest.mark.django_db
def test_mask_entry_dashboard_renders_event_mask_with_binding_inspector(client_logged_in, organization):
    Mapping.objects.create(
        name="Folkwang Ereignis Mapping",
        organization_id=organization.code,
        mapping_config={
            "workspace_columns": {
                "fuk::01_Grundereignis::Ereignistyp": {
                    "dataset": "01_Grundereignis",
                    "name": "Ereignistyp",
                    "canonical_mapping": {
                        "canonical_property_uri": "http://arkumu.org/data/properties/ereignistyp",
                        "canonical_property_label": "Ereignistyp",
                    },
                }
            }
        },
    )

    url = reverse("metadata:mask_entry")
    response = client_logged_in.get(
        url,
        {
            "organization": organization.code,
            "entity": "event",
            "phase": "create",
        },
    )

    assert response.status_code == 200
    body = response.content.decode()
    assert "Ereignis" in body
    assert "Ereignisübersicht" in body
    assert "Ereignistyp" in body
    assert "Beginn" not in body
    assert "Digikunst-Notiz aus Grails-Analyse" in body
    assert "Arkumu Canonical Model" in body
    assert "Frontend Grails" in body
    assert "Backend Grails" in body
    assert "Folkwang Ereignis Mapping" in body
    assert "01_Grundereignis" in body


@pytest.mark.django_db
def test_mask_entry_dashboard_renders_enrichment_fields_for_event(client_logged_in, organization):
    url = reverse("metadata:mask_entry")
    response = client_logged_in.get(
        url,
        {
            "organization": organization.code,
            "entity": "event",
            "phase": "enrichment",
        },
    )

    assert response.status_code == 200
    body = response.content.decode()
    assert "Erweitern" in body
    assert "Beginn" in body
    assert "Ende" in body
    assert "Ereignistyp" not in body


@pytest.mark.django_db
def test_mask_create_page_renders_project_create_fields(client_logged_in, organization):
    _create_typed_option(
        organization=organization,
        type_uri="http://arkumu.org/data/types/einliefernde-hochschule",
        resource_uri="http://arkumu.org/data/fuk/entities/institution/1",
        label="Folkwang Universität",
        label_predicate_uri="http://arkumu.org/data/properties/deutscher-name-der-einliefernden-hochschule",
    )
    _create_typed_option(
        organization=organization,
        type_uri="http://arkumu.org/data/types/projektart",
        resource_uri="http://arkumu.org/data/fuk/entities/project-type/1",
        label="Konzert",
        label_predicate_uri="http://arkumu.org/data/properties/deutscher-name-der-projektart",
    )

    response = client_logged_in.get(
        reverse("metadata:mask_create"),
        {"organization": organization.code, "entity": "project"},
    )

    assert response.status_code == 200
    body = response.content.decode()
    assert "Objekt anlegen" in body
    assert "Entitaet wechseln" in body
    assert "Sektionen" in body
    assert "Titel" in body
    assert "Institution" in body
    assert "Projektart" in body
    assert "Folkwang Universität" in body
    assert "Untertitel" not in body


@pytest.mark.django_db
def test_mask_create_post_creates_project_and_redirects_to_edit(client_logged_in, organization):
    institution = _create_typed_option(
        organization=organization,
        type_uri="http://arkumu.org/data/types/einliefernde-hochschule",
        resource_uri="http://arkumu.org/data/fuk/entities/institution/1",
        label="Folkwang Universität",
        label_predicate_uri="http://arkumu.org/data/properties/deutscher-name-der-einliefernden-hochschule",
    )
    project_type = _create_typed_option(
        organization=organization,
        type_uri="http://arkumu.org/data/types/projektart",
        resource_uri="http://arkumu.org/data/fuk/entities/project-type/1",
        label="Konzert",
        label_predicate_uri="http://arkumu.org/data/properties/deutscher-name-der-projektart",
    )

    response = client_logged_in.post(
        reverse("metadata:mask_create"),
        {
            "organization": organization.code,
            "entity": "project",
            "title": "Neues Projekt",
            "institution__label": institution.uri,
            "project_type": project_type.uri,
        },
    )

    assert response.status_code == 302
    assert reverse("metadata:edit_project") in response["Location"]
    assert "uri=" in response["Location"]
    assert Resource.objects.filter(name="Neues Projekt").exists()


@pytest.mark.django_db
def test_mask_create_post_creates_event_and_redirects_to_edit(client_logged_in, organization):
    event_type = _create_typed_option(
        organization=organization,
        type_uri="http://arkumu.org/data/types/ereignistyp",
        resource_uri="http://arkumu.org/data/fuk/entities/event-type/1",
        label="Aufführung",
        label_predicate_uri="http://arkumu.org/data/properties/deutscher-name-des-ereignistyps",
    )

    response = client_logged_in.post(
        reverse("metadata:mask_create"),
        {
            "organization": organization.code,
            "entity": "event",
            "event_type": event_type.uri,
        },
    )

    assert response.status_code == 302
    assert reverse("metadata:edit_ereignis") in response["Location"]
    assert "uri=" in response["Location"]
