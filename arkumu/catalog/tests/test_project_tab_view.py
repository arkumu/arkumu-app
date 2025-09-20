import pytest
from django.urls import reverse

from arkumu.catalog.services.project_views import ProjectData
from arkumu.catalog.views.project_view import ProjectView, ProjectTabView


@pytest.fixture
def logged_in_client(client, django_user_model):
    user = django_user_model.objects.create_user(username="test", password="pass")
    client.force_login(user)
    return client


@pytest.mark.django_db
def test_project_tab_overview_renders_partial(monkeypatch, logged_in_client):
    sample_data = ProjectData(
        uri="http://example.org/project/1",
        title="Sample Project",
        subtitle="Subtitle",
        description="Eine kurze Beschreibung",
        categories=["Kategorie"],
        actors=[{"name": "Akteur", "roles": ["Rolle"]}],
        catchphrases=["Schlagwort"],
        project_type="Projektart",
        digital_objects=["http://example.org/object"],
    )
    monkeypatch.setattr(ProjectView, "_load_project", lambda self, uri: ({'events': []}, sample_data))

    response = logged_in_client.get(
        reverse("catalog:projekt_tab"),
        {"projekt": sample_data.uri, "tab": "overview"},
        HTTP_HX_REQUEST="true",
    )

    assert response.status_code == 200
    content = response.content.decode()
    assert "Sample Project" in content
    assert "Eine kurze Beschreibung" in content


@pytest.mark.django_db
def test_project_tab_events_uses_event_payload(monkeypatch, logged_in_client):
    sample_data = ProjectData(uri="http://example.org/project/1")
    monkeypatch.setattr(ProjectView, "_load_project", lambda self, uri: ({'events': []}, sample_data))
    monkeypatch.setattr(
        ProjectTabView,
        "_build_event_payload",
        staticmethod(lambda uri: [
            {
                "id": "evt-1",
                "name": "Konzert",
                "start": "2020-01-01",
                "end": "2020-01-02",
                "location": "Leipzig",
                "actors": [{"name": "Dirigent", "roles": ["Leitung"]}],
            }
        ]),
    )

    response = logged_in_client.get(
        reverse("catalog:projekt_tab"),
        {"projekt": sample_data.uri, "tab": "events"},
        HTTP_HX_REQUEST="true",
    )

    assert response.status_code == 200
    content = response.content.decode()
    assert "Konzert" in content
    assert "Leitung" in content


@pytest.mark.django_db
def test_project_tab_metadata_renders_table(monkeypatch, logged_in_client):
    sample_data = ProjectData(
        uri="http://example.org/project/1",
        title="Sample Project",
        catchphrases=["Schlagwort"],
    )
    enriched = {'events': [{'id': 'evt-1'}]}
    monkeypatch.setattr(ProjectView, "_load_project", lambda self, uri: (enriched, sample_data))

    response = logged_in_client.get(
        reverse("catalog:projekt_tab"),
        {"projekt": sample_data.uri, "tab": "metadata"},
        HTTP_HX_REQUEST="true",
    )

    assert response.status_code == 200
    content = response.content.decode()
    assert "Projekt URI" in content
    assert "Schlagwort" in content
    assert "Anzahl Ereignisse" in content
