from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from arkumu.metadata.canonical import canonical_uri
from arkumu.metadata.derivations.kreuz_config import DCTERMS_IS_PART_OF
from arkumu.metadata.models import Resource, ResourceType, Triple, Mapping
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


@pytest.mark.django_db
def test_admin_run_derivation_action(client, superuser, mapping):
    client.force_login(superuser)
    url = reverse("admin:metadata_mapping_junction_patterns", args=[mapping.pk])

    client.post(
        url,
        {
            "action": "adopt_pattern",
            "dataset_name": "Projekt_Ereignis",
            "pattern_name": "project_event",
        },
        follow=True,
    )
    mapping.refresh_from_db()

    org = Organization.objects.get(code=mapping.organization_id)
    project = Resource.objects.create(
        uri="http://example.org/project/1",
        resource_type=ResourceType.ENTITY,
        organization=org,
    )
    event = Resource.objects.create(
        uri="http://example.org/event/1",
        resource_type=ResourceType.ENTITY,
        organization=org,
    )
    junction = Resource.objects.create(
        uri="http://example.org/junction/1",
        resource_type=ResourceType.ENTITY,
        organization=org,
    )
    predicate_project = Resource.objects.create(uri=PROJECT, resource_type=ResourceType.PROPERTY)
    predicate_event = Resource.objects.create(uri=EVENT, resource_type=ResourceType.PROPERTY)
    dataset_link = Resource.objects.create(
        uri="dataset/projekt_ereignis",
        resource_type=ResourceType.IRI,
        name="Projekt_Ereignis",
    )
    Triple.objects.create(subject=junction, predicate=predicate_project, object=project)
    Triple.objects.create(subject=junction, predicate=predicate_event, object=event)
    Triple.objects.create(
        subject=junction,
        predicate=Resource.objects.create(uri=DCTERMS_IS_PART_OF, resource_type=ResourceType.PROPERTY),
        object=dataset_link,
    )

    response = client.post(
        url,
        {
            "action": "run_derivation",
            "dry_run": "0",
        },
        follow=True,
    )
    assert response.status_code == 200
    assert Triple.objects.filter(
        subject=project,
        predicate__uri=EVENT,
        object=event,
        is_derived=True,
    ).exists()
