from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from arkumu.metadata.canonical import canonical_uri
from arkumu.metadata.models.mappings import Mapping
from arkumu.users.models import Organization

PROJECT = canonical_uri("project")
EVENT = canonical_uri("event")


@pytest.fixture
def superuser(db):
    User = get_user_model()
    return User.objects.create_superuser(username="admin", password="pw", email="admin@example.com")


@pytest.fixture
def mapping(db):
    org = Organization.objects.create(name="FUK", code="fuk")
    manifest = {
        "Projekt_Ereignis": {
            "properties": {
                "projekt_ref": {"canonical_uri": PROJECT},
                "ereignis_ref": {"canonical_uri": EVENT},
            },
            "fk_relationships": [],
        }
    }
    return Mapping.objects.create(
        name="Test Mapping",
        organization_id=org.code,
        mapping_config={
            "schema_manifest": manifest,
        },
    )


@pytest.mark.django_db
def test_admin_view_lists_proposals(client, superuser, mapping):
    client.force_login(superuser)
    url = reverse("admin:metadata_mapping_junction_patterns", args=[mapping.pk])
    response = client.get(url)
    assert response.status_code == 200
    assert b"Projekt_Ereignis" in response.content
    assert b"project_event" in response.content


@pytest.mark.django_db
def test_admin_view_adopts_and_removes_pattern(client, superuser, mapping):
    client.force_login(superuser)
    url = reverse("admin:metadata_mapping_junction_patterns", args=[mapping.pk])

    # Adopt suggested pattern
    response = client.post(
        url,
        {
            "action": "adopt_pattern",
            "dataset_name": "Projekt_Ereignis",
            "pattern_name": "project_event",
        },
        follow=True,
    )
    mapping.refresh_from_db()
    assert response.status_code == 200
    junction_patterns = mapping.mapping_config.get("junction_patterns", {})
    assert "Projekt_Ereignis" in junction_patterns
    stored_patterns = junction_patterns["Projekt_Ereignis"].get("patterns", [])
    assert any(pat.get("name") == "project_event" for pat in stored_patterns)

    # Remove it again
    response = client.post(
        url,
        {
            "action": "remove_pattern",
            "dataset_name": "Projekt_Ereignis",
            "pattern_name": "project_event",
        },
        follow=True,
    )
    mapping.refresh_from_db()
    junction_patterns = mapping.mapping_config.get("junction_patterns", {})
    stored_patterns = junction_patterns.get("Projekt_Ereignis", {}).get("patterns", [])
    assert all(pat.get("name") != "project_event" for pat in stored_patterns)
