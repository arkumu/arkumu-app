import pytest
from django.urls import reverse

from arkumu.metadata.models.mappings import Mapping
from arkumu.users.models import Organization, User


@pytest.fixture
def khm_org(db):
    return Organization.objects.create(name="KHM", code="khm")


@pytest.fixture
def test_user(db, khm_org):
    user = User.objects.create_user(username="graph-user", password="secret", organization=khm_org)
    return user


@pytest.fixture
def khm_mapping(db, khm_org):
    manifest = {
        "Projects": {
            "entity_type": {
                "name": "Projekt",
                "canonical_uri": "http://arkumu.org/data/types/projekt",
            },
            "properties": {
                "project_id": {
                    "name": "Projekt-ID",
                    "uri": "http://example.org/properties/project-id",
                    "canonical_uri": "http://arkumu.org/data/properties/projekt-id",
                },
                "partner": {
                    "name": "Partner",
                    "uri": "http://example.org/properties/partner",
                    "canonical_uri": None,
                },
            },
            "column_metadata": {
                "project_id": {"is_anchor": True},
                "partner": {"has_fk": True, "is_multi_value": True},
            },
            "fk_relationships": [
                {
                    "source_column": "partner",
                    "target_dataset": "Actors",
                    "target_column": "Actor-ID",
                    "relationship_type": "hat Beteiligte",
                }
            ],
        }
    }
    return Mapping.objects.create(
        name="KHM Schema Manifest",
        organization_id=khm_org.code,
        mapping_config={"schema_manifest": manifest},
    )


@pytest.mark.django_db
def test_canonical_graph_page_loads(client, test_user, khm_mapping):
    client.force_login(test_user)
    response = client.get(reverse("metadata:canonical_graph_view"))
    assert response.status_code == 200
    assert b"Canonical Manifest Graph" in response.content


@pytest.mark.django_db
def test_selectors_partial_lists_mappings(client, test_user, khm_mapping):
    client.force_login(test_user)
    response = client.get(
        reverse("metadata:canonical_graph_selectors"),
        {"organization": "khm"},
    )
    assert response.status_code == 200
    assert b"KHM Schema Manifest" in response.content


@pytest.mark.django_db
def test_graph_render_tree_view(client, test_user, khm_mapping):
    client.force_login(test_user)
    response = client.get(
        reverse("metadata:canonical_graph_render"),
        {
            "organization": "khm",
            "mapping_id": str(khm_mapping.id),
            "view_mode": "tree",
        },
        HTTP_HX_REQUEST="true",
    )
    assert response.status_code == 200
    body = response.content.decode("utf-8").lower()
    assert "canonical schema overview" in body
    assert "organization schema overview" in body


@pytest.mark.django_db
def test_tree_canonical_partial(client, test_user, khm_mapping):
    client.force_login(test_user)
    response = client.get(
        reverse("metadata:canonical_graph_tree_canonical"),
        {
            "organization": "khm",
            "mapping_id": str(khm_mapping.id),
            "class_uri": "http://arkumu.org/data/types/projekt",
        },
        HTTP_HX_REQUEST="true",
    )
    assert response.status_code == 200
    assert b"mapped" in response.content.lower()


@pytest.mark.django_db
def test_tree_dataset_partial(client, test_user, khm_mapping):
    client.force_login(test_user)
    response = client.get(
        reverse("metadata:canonical_graph_tree_dataset"),
        {
            "organization": "khm",
            "mapping_id": str(khm_mapping.id),
            "dataset_name": "Projects",
            "target_id": "dataset-node-projects",
        },
        HTTP_HX_REQUEST="true",
    )
    assert response.status_code == 200
    body = response.content.decode("utf-8").lower()
    assert "canonical property" in body or "missing canonical" in body


@pytest.mark.django_db
def test_tree_edit_column_get(client, test_user, khm_mapping):
    client.force_login(test_user)
    response = client.get(
        reverse("metadata:canonical_graph_tree_edit_column"),
        {
            "organization": "khm",
            "mapping_id": str(khm_mapping.id),
            "dataset_name": "Projects",
            "column_slug": "project_id",
            "target_id": "dataset-node-projects",
        },
        HTTP_HX_REQUEST="true",
    )
    assert response.status_code == 200
    assert b"Canonical property" in response.content
    assert b"<select" in response.content


@pytest.mark.django_db
def test_tree_update_column_persists_change(client, test_user, khm_mapping):
    client.force_login(test_user)
    new_uri = "http://arkumu.org/data/properties/test-prop"
    response = client.post(
        reverse("metadata:canonical_graph_tree_update_column"),
        {
            "organization": "khm",
            "mapping_id": str(khm_mapping.id),
            "dataset_name": "Projects",
            "column_slug": "partner",
            "target_id": "dataset-node-projects",
            "canonical_uri": new_uri,
        },
        HTTP_HX_REQUEST="true",
    )
    assert response.status_code == 200
    assert new_uri.encode() in response.content
    khm_mapping.refresh_from_db()
    manifest = khm_mapping.mapping_config["schema_manifest"]
    assert manifest["Projects"]["properties"]["partner"]["canonical_uri"] == new_uri
