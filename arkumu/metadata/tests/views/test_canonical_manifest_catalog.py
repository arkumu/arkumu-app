import pytest
from django.urls import reverse

from arkumu.metadata.models.mappings import Mapping
from arkumu.metadata.models.resource import Resource
from arkumu.users.models import Organization, User


@pytest.fixture
def khm_org(db):
    return Organization.objects.create(name="KHM", code="khm")


@pytest.fixture
def hmt_org(db):
    return Organization.objects.create(name="HMT", code="hmt")


@pytest.fixture
def test_user(db, khm_org):
    user = User.objects.create_user(
        username="catalog-user",
        password="secret",
        organization=khm_org
    )
    return user


@pytest.fixture
def canonical_resources(db, khm_org):
    """Create Resource objects for label resolution."""
    resources = []

    resources.append(Resource.objects.create(
        uri="http://arkumu.org/data/types/projekt",
        name="Projekt Entity Type",
        organization=khm_org,
    ))

    resources.append(Resource.objects.create(
        uri="http://arkumu.org/data/properties/projekt-id",
        name="Projekt Identifier",
        organization=khm_org,
    ))

    resources.append(Resource.objects.create(
        uri="http://arkumu.org/data/properties/projekt-title",
        name="Projekt Title",
        organization=khm_org,
    ))

    resources.append(Resource.objects.create(
        uri="http://arkumu.org/data/types/akteur",
        name="Akteur Entity Type",
        organization=khm_org,
    ))

    resources.append(Resource.objects.create(
        uri="http://arkumu.org/data/properties/akteur-id",
        name="Akteur Identifier",
        organization=khm_org,
    ))

    return resources


@pytest.fixture
def khm_mapping(db, khm_org):
    manifest = {
        "Projects": {
            "label": "Projects Dataset",
            "entity_type": {
                "name": "Projekt",
                "uri": "http://example.org/types/projekt",
                "canonical_uri": "http://arkumu.org/data/types/projekt",
            },
            "properties": {
                "project_id": {
                    "name": "Projekt-ID",
                    "uri": "http://example.org/properties/project-id",
                    "canonical_uri": "http://arkumu.org/data/properties/projekt-id",
                },
                "title": {
                    "name": "Title",
                    "uri": "http://example.org/properties/title",
                    "canonical_uri": "http://arkumu.org/data/properties/projekt-title",
                },
                "unmapped_field": {
                    "name": "Unmapped Field",
                    "uri": "http://example.org/properties/unmapped",
                    "canonical_uri": None,
                },
            },
            "fk_relationships": [
                {
                    "source_property_uri": "http://example.org/properties/partner",
                    "source_property_canonical_uri": "http://arkumu.org/data/properties/partner",
                    "target_property_uri": "http://example.org/properties/actor-id",
                    "target_property_canonical_uri": "http://arkumu.org/data/properties/akteur-id",
                    "source_dataset": "Projects",
                    "target_dataset": "Actors",
                    "notes": "Partner relationship"
                }
            ],
            "relationship_contexts": [
                {
                    "context_property_uri": "http://example.org/properties/role",
                    "context_property_canonical_uri": "http://arkumu.org/data/properties/role",
                    "primary_property_uri": "http://example.org/properties/project",
                    "primary_property_canonical_uri": "http://arkumu.org/data/properties/projekt-id",
                    "secondary_property_uri": "http://example.org/properties/actor",
                    "secondary_property_canonical_uri": "http://arkumu.org/data/properties/akteur-id",
                }
            ],
        },
        "Actors": {
            "label": "Actors Dataset",
            "entity_type": {
                "name": "Akteur",
                "uri": "http://example.org/types/akteur",
                "canonical_uri": "http://arkumu.org/data/types/akteur",
            },
            "properties": {
                "actor_id": {
                    "name": "Actor-ID",
                    "uri": "http://example.org/properties/actor-id",
                    "canonical_uri": "http://arkumu.org/data/properties/akteur-id",
                },
            },
        }
    }
    return Mapping.objects.create(
        name="KHM Schema Manifest",
        organization_id=khm_org.code,
        mapping_config={"schema_manifest": manifest},
        is_active=True,
    )


@pytest.fixture
def hmt_mapping(db, hmt_org):
    manifest = {
        "Events": {
            "label": "Events Dataset",
            "entity_type": {
                "name": "Ereignis",
                "uri": "http://example.org/types/ereignis",
                "canonical_uri": "http://arkumu.org/data/types/ereignis",
            },
            "properties": {
                "event_id": {
                    "name": "Event-ID",
                    "uri": "http://example.org/properties/event-id",
                    "canonical_uri": "http://arkumu.org/data/properties/ereignis-id",
                },
            },
        }
    }
    return Mapping.objects.create(
        name="HMT Schema Manifest",
        organization_id=hmt_org.code,
        mapping_config={"schema_manifest": manifest},
        is_active=True,
    )


@pytest.fixture
def org_without_manifest(db):
    org = Organization.objects.create(name="Test Org", code="test")
    return org


@pytest.mark.django_db
def test_canonical_manifest_catalog_page_loads(client, test_user, khm_mapping):
    """Test that the catalog page loads successfully."""
    client.force_login(test_user)
    response = client.get(reverse("metadata:canonical_manifest_catalog"))
    assert response.status_code == 200
    assert b"Canonical Schema Manifest Catalog" in response.content


@pytest.mark.django_db
def test_catalog_displays_two_organizations(client, test_user, khm_mapping, hmt_mapping):
    """Test that the catalog displays data from multiple organizations."""
    client.force_login(test_user)
    response = client.get(reverse("metadata:canonical_manifest_catalog"))

    assert response.status_code == 200
    content = response.content.decode("utf-8")

    assert "KHM" in content
    assert "HMT" in content

    assert "Projects Dataset" in content or "Projects" in content
    assert "Events Dataset" in content or "Events" in content


@pytest.mark.django_db
def test_catalog_resolves_labels_from_resources(client, test_user, khm_mapping, canonical_resources):
    """Test that labels are resolved from Resource objects."""
    client.force_login(test_user)
    response = client.get(reverse("metadata:canonical_manifest_catalog"))

    assert response.status_code == 200
    content = response.content.decode("utf-8")

    assert "Projekt Entity Type" in content
    assert "Projekt Identifier" in content
    assert "Projekt Title" in content
    assert "Akteur Entity Type" in content
    assert "Akteur Identifier" in content


@pytest.mark.django_db
def test_catalog_handles_missing_manifest(client, test_user, org_without_manifest):
    """Test that the catalog handles organizations without manifests gracefully."""
    client.force_login(test_user)
    response = client.get(reverse("metadata:canonical_manifest_catalog"))

    assert response.status_code == 200
    content = response.content.decode("utf-8")

    assert "Test Org" in content or "test" in content


@pytest.mark.django_db
def test_catalog_displays_summary_stats(client, test_user, khm_mapping, hmt_mapping):
    """Test that summary statistics are displayed correctly."""
    client.force_login(test_user)
    response = client.get(reverse("metadata:canonical_manifest_catalog"))

    assert response.status_code == 200
    content = response.content.decode("utf-8")

    assert "Organizations" in content
    assert "Datasets" in content
    assert "Properties" in content


@pytest.mark.django_db
def test_catalog_displays_fk_relationships(client, test_user, khm_mapping):
    """Test that FK relationships are displayed."""
    client.force_login(test_user)
    response = client.get(reverse("metadata:canonical_manifest_catalog"))

    assert response.status_code == 200
    content = response.content.decode("utf-8")

    assert "FK Relationships" in content
    assert "Actors" in content


@pytest.mark.django_db
def test_catalog_displays_relationship_contexts(client, test_user, khm_mapping):
    """Test that relationship contexts are displayed."""
    client.force_login(test_user)
    response = client.get(reverse("metadata:canonical_manifest_catalog"))

    assert response.status_code == 200
    content = response.content.decode("utf-8")

    assert "Relationship Contexts" in content


@pytest.mark.django_db
def test_catalog_filters_by_organization(client, test_user, khm_mapping, hmt_mapping):
    """Test that the catalog can filter by organization code."""
    client.force_login(test_user)
    response = client.get(reverse("metadata:canonical_manifest_catalog"), {"org": "khm"})

    assert response.status_code == 200
    content = response.content.decode("utf-8")

    assert "KHM" in content
    assert "Projects" in content


@pytest.mark.django_db
def test_catalog_handles_malformed_manifest(client, test_user, khm_org):
    """Test that the catalog handles malformed manifests gracefully."""
    malformed_mapping = Mapping.objects.create(
        name="Malformed Manifest",
        organization_id=khm_org.code,
        mapping_config={"schema_manifest": "not a dict"},
        is_active=True,
    )

    client.force_login(test_user)
    response = client.get(reverse("metadata:canonical_manifest_catalog"))

    assert response.status_code == 200
    content = response.content.decode("utf-8")

    assert "KHM" in content


@pytest.mark.django_db
def test_catalog_shows_unmapped_properties(client, test_user, khm_mapping):
    """Test that unmapped properties (missing canonical URIs) are shown."""
    client.force_login(test_user)
    response = client.get(reverse("metadata:canonical_manifest_catalog"))

    assert response.status_code == 200
    content = response.content.decode("utf-8")

    assert "Unmapped Field" in content
    assert "missing canonical" in content or "unmapped" in content
