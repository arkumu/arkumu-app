import pytest
from django.urls import reverse

from arkumu.metadata.entity_creation import EntityCreationService
from arkumu.metadata.entity_creation.forms import ProjectForm
from arkumu.metadata.models.resource import Resource, ResourceType
from arkumu.users.models import Organization, User


@pytest.fixture(autouse=True)
def rdf_type_resource(db):
    Resource.objects.get_or_create(
        uri="http://www.w3.org/1999/02/22-rdf-syntax-ns#type",
        defaults={
            "resource_type": ResourceType.PROPERTY,
            "name": "rdf:type",
        },
    )


def _project_options():
    return {
        "project": [],
        "institution": [("http://example.org/institution/1", "Institution 1")],
        "project_category": [("http://example.org/category/1", "Category 1")],
        "catchphrase": [("http://example.org/catchphrase/1", "Catchphrase 1")],
        "project_type": [("http://example.org/type/1", "Type 1")],
        "digital_object": [("http://example.org/object/1", "Object 1")],
    }


@pytest.fixture
def organization(db):
    return Organization.objects.create(code="fragorg", name="Fragment Org")


@pytest.fixture
def user(db, organization):
    user = User.objects.create_user(
        username="fragment-user",
        email="fragment@example.com",
        password="pass1234",
    )
    user.organization = organization
    user.save()
    return user


@pytest.mark.django_db
def test_project_fragment_disables_fields_for_existing(client, user, organization):
    client.force_login(user)

    metadata_options = _project_options()
    form = ProjectForm(
        data={
            "uri": "",
            "bevorzugter_titel": "Existing Project",
            "bevorzugter_untertitel": "Subtitle",
            "einliefernde_hochschule_uri": "http://example.org/institution/1",
            "projektkategorie_uri": "http://example.org/category/1",
            "beschreibung": "Existing project description",
            "schlagwort_uris": ["http://example.org/catchphrase/1"],
            "projektart_uri": "http://example.org/type/1",
            "vorschaubild_uri": "http://example.org/object/1",
        },
        metadata_options=metadata_options,
    )
    assert form.is_valid()

    service = EntityCreationService.for_key("project", organization)
    entity, _ = service.create_or_update_from_form(form)

    url = reverse("metadata:entity_creation_fragment", args=["project"])
    response = client.get(
        url,
        {"uri": entity._resource.uri},
        HTTP_HX_REQUEST="true",
    )

    assert response.status_code == 200
    content = response.content.decode()
    assert "Existing Project" in content


@pytest.mark.django_db
def test_project_fragment_requires_htmx_header(client, user):
    client.force_login(user)
    url = reverse("metadata:entity_creation_fragment", args=["project"])
    response = client.get(url)
    assert response.status_code == 400


@pytest.mark.django_db
def test_entity_field_options_match_uri(monkeypatch, client, user, organization):
    client.force_login(user)

    def fake_option_map(organization=None, **_kwargs):
        return {
            "project": [],
            "institution": [],
            "project_category": [
                ("http://example.org/category/1", "Fête Alpha"),
                ("http://example.org/category/2", "Category Beta"),
            ],
            "project_type": [],
            "catchphrase": [],
            "digital_object": [],
        }

    monkeypatch.setattr(
        "arkumu.metadata.views.entity_creation_views.get_default_metadata_option_map",
        fake_option_map,
    )

    def render(query: str):
        url = reverse(
            "metadata:entity_field_options",
            args=["project", "projektkategorie_uri"],
        )
        response = client.get(
            url,
            {"q": query},
            HTTP_HX_REQUEST="true",
        )
        assert response.status_code == 200
        return response.content.decode()

    content = render("category/2")
    assert "http://example.org/category/2" in content
    assert "http://example.org/category/1" not in content

    content = render("Fete")
    assert "http://example.org/category/1" in content

    content = render("category beta")
    assert "http://example.org/category/2" in content
