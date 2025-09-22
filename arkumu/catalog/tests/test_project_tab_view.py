import pytest
from django.urls import reverse

from arkumu.catalog.views.project_view import ProjectTabView, ProjectView
from arkumu.projects import (
    ProjectActor,
    ProjectAlternateTitle,
    ProjectCatchphrase,
    ProjectCategory,
    ProjectDigitalObject,
    ProjectEvent,
    ProjectEventActor,
    ProjectInstitution,
    ProjectRecord,
    ProjectType,
)


@pytest.fixture
def logged_in_client(client, django_user_model):
    user = django_user_model.objects.create_user(username="test", password="pass")
    client.force_login(user)
    return client


@pytest.fixture
def sample_record():
    return ProjectRecord(
        subject_id="proj-1",
        uri="http://example.org/project/1",
        title="Sample Project",
        subtitle="Subtitle",
        description="Eine kurze Beschreibung",
        institution=ProjectInstitution(label="Institution"),
        project_type=ProjectType(label="Projektart"),
        alternative_titles=[ProjectAlternateTitle(value="Alternativer Titel")],
        catchphrases=[ProjectCatchphrase(label="Schlagwort")],
        categories=[ProjectCategory(label="Kategorie")],
        digital_objects=[ProjectDigitalObject(path="http://example.org/object")],
        actors=[ProjectActor(name="Akteur", roles=["Rolle"])],
        events=[
            ProjectEvent(
                id="evt-1",
                name="Konzert",
                description="Konzertbeschreibung",
                start="2020-01-01",
                end="2020-01-02",
                location="Leipzig",
                type="Konzert",
                latitude=51.34,
                longitude=12.37,
                actors=[ProjectEventActor(name="Dirigent", roles=["Leitung"])],
            )
        ],
    )


def _patch_record(monkeypatch, record):
    def fake_load_record(cls, uri):
        if uri != record.uri:
            raise LookupError(uri)
        return record

    monkeypatch.setattr(ProjectView, "_load_record", classmethod(fake_load_record))


@pytest.mark.django_db
def test_project_tab_overview_renders_partial(monkeypatch, logged_in_client, sample_record):
    _patch_record(monkeypatch, sample_record)

    response = logged_in_client.get(
        reverse("catalog:projekt_tab"),
        {"projekt": sample_record.uri, "tab": "overview"},
        HTTP_HX_REQUEST="true",
    )

    assert response.status_code == 200
    content = response.content.decode()
    assert "Sample Project" in content
    assert "Eine kurze Beschreibung" in content
    assert "Institution" in content


@pytest.mark.django_db
def test_project_tab_events_renders_event_details(monkeypatch, logged_in_client, sample_record):
    _patch_record(monkeypatch, sample_record)

    response = logged_in_client.get(
        reverse("catalog:projekt_tab"),
        {"projekt": sample_record.uri, "tab": "events"},
        HTTP_HX_REQUEST="true",
    )

    assert response.status_code == 200
    content = response.content.decode()
    assert "Konzert" in content
    assert "Leipzig" in content
    assert "Dirigent" in content
    assert "Leitung" in content


@pytest.mark.django_db
def test_project_tab_metadata_renders_table(monkeypatch, logged_in_client, sample_record):
    _patch_record(monkeypatch, sample_record)

    response = logged_in_client.get(
        reverse("catalog:projekt_tab"),
        {"projekt": sample_record.uri, "tab": "metadata"},
        HTTP_HX_REQUEST="true",
    )

    assert response.status_code == 200
    content = response.content.decode()
    assert "Projekt URI" in content
    assert "Schlagwort" in content
    assert "Anzahl Ereignisse" in content
