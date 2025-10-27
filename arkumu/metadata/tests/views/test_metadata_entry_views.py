import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from arkumu.metadata.models.resource import Resource
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
    assert "Projekt-Metadaten erfassen" in body
    assert "Sektionen" in body


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
    assert "hx-swap-oob=\"outerHTML\"" in body


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
    assert "hx-swap-oob=\"outerHTML\"" in body


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
    assert "hx-swap-oob=\"outerHTML\"" in body
