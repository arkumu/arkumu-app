"""
Tests for relationship search functionality in schema workspace views.

These tests focus on the Verküpfungen (relationships) search and selection workflow,
ensuring that search suggestions work correctly and selected values are properly stored.
"""

import json
from pathlib import Path

import pytest
from django.urls import reverse
from django.utils.text import slugify

from arkumu.metadata.models.mappings import Mapping
from arkumu.metadata.models.resource import Resource, ResourceType
from arkumu.metadata.models.triples import Triple
from arkumu.users.models import Organization, User
from arkumu.metadata.views import schema_workspace_views
from arkumu.metadata.views.schema_workspace_views import JoinRelationship


MAPPING_FIXTURE_PATH = (
    Path(__file__).resolve().parents[4] / "data/mappings/fuk_mapping_20250930.json"
)

PROJECT_DATASET = "Projekt"
EVENT_DATASET = "Ereignis"


@pytest.fixture
def organization(db):
    return Organization.objects.create(code="fuk", name="FUK Test Organization")


@pytest.fixture
def user(db, organization):
    user = User.objects.create_user(
        username="test-user",
        email="test@example.com",
        password="testpass123",
    )
    user.organization = organization
    user.save()
    return user


@pytest.fixture
def mapping(db, organization):
    """Create a mapping with a simple schema."""
    if not MAPPING_FIXTURE_PATH.exists():
        pytest.skip(f"Required mapping fixture missing: {MAPPING_FIXTURE_PATH}")

    with MAPPING_FIXTURE_PATH.open("r", encoding="utf-8") as mapping_file:
        mapping_config = json.load(mapping_file)

    return Mapping.objects.create(
        organization_id=organization.code,
        name="Test Mapping",
        mapping_config=mapping_config,
    )


class StubWorkspaceService:
    """Stub schema workspace service using minimal metadata for tests."""

    def __init__(self, mapping: Mapping, organization: Organization):
        self.mapping = mapping
        self.organization = organization

    def get_field_metadata(self, dataset_name: str):
        if dataset_name == "Projekt":
            return {
                "projekt_id": {
                    "column_name": "projekt_id",
                    "is_anchor": True,
                    "is_required": True,
                },
                "titel": {
                    "column_name": "titel",
                    "property_uri": "http://arkumu.org/properties/titel",
                },
                "sprache": {
                    "column_name": "sprache",
                    "property_label": "Sprache",
                    "fk_relationship": {
                        "target_dataset": "Sprache",
                    },
                },
            }
        if dataset_name == "Person":
            return {
                "person_id": {
                    "column_name": "person_id",
                    "is_anchor": True,
                    "is_required": True,
                },
                "name": {
                    "column_name": "name",
                    "property_uri": "http://arkumu.org/properties/name",
                },
            }
        if dataset_name == "Mitarbeit":
            return {
                "mitarbeit_id": {
                    "column_name": "mitarbeit_id",
                    "is_anchor": True,
                    "is_required": True,
                },
                "projekt_ref": {
                    "column_name": "projekt_ref",
                    "is_join": True,
                    "is_multi_value": True,
                    "join_key": "projekt_ref",
                },
                "person_ref": {
                    "column_name": "person_ref",
                    "is_join": True,
                    "is_multi_value": True,
                    "join_key": "person_ref",
                },
            }
        return {}

    def augment_field_metadata_with_joins(self, dataset_name, metadata):
        join_map = {}
        if dataset_name == "Mitarbeit":
            join_map["projekt_ref"] = JoinRelationship(
                join_dataset="Mitarbeit",
                join_dataset_schema={},
                self_column="projekt_ref",
                self_property_uri="http://arkumu.org/properties/projekt_ref",
                other_dataset="Projekt",
                other_column="projekt_id",
                other_property_uri="http://arkumu.org/properties/projekt-id",
                other_display_label="Projekt",
            )
            join_map["person_ref"] = JoinRelationship(
                join_dataset="Mitarbeit",
                join_dataset_schema={},
                self_column="person_ref",
                self_property_uri="http://arkumu.org/properties/person_ref",
                other_dataset="Person",
                other_column="person_id",
                other_property_uri="http://arkumu.org/properties/person-id",
                other_display_label="Person",
            )
        return metadata, join_map

    def get_dataset_schema(self, dataset_name: str):
        dataset_resource = self._ensure_dataset_resource(dataset_name)
        if dataset_name == "Projekt":
            return {
                "entity_type": type("EntityType", (), {"name": "Projekt"}),
                "properties": {
                    "titel": Resource.objects.filter(
                        uri="http://arkumu.org/properties/titel"
                    ).first(),
                    "sprache": Resource.objects.filter(
                        uri="http://arkumu.org/properties/sprache"
                    ).first(),
                },
                "fk_relationships": [],
                "dataset_resource": dataset_resource,
            }
        if dataset_name == "Person":
            return {
                "entity_type": type("EntityType", (), {"name": "Person"}),
                "properties": {
                    "name": Resource.objects.filter(
                        uri="http://arkumu.org/properties/name"
                    ).first(),
                },
                "fk_relationships": [],
                "dataset_resource": dataset_resource,
            }
        if dataset_name == "Sprache":
            return {
                "entity_type": type("EntityType", (), {"name": "Sprache"}),
                "properties": {
                    "label": Resource.objects.filter(
                        uri="http://arkumu.org/properties/sprache"
                    ).first(),
                },
                "fk_relationships": [],
                "dataset_resource": dataset_resource,
            }
        if dataset_name == "Mitarbeit":
            return {
                "entity_type": type("EntityType", (), {"name": "Mitarbeit"}),
                "properties": {},
                "fk_relationships": [],
                "dataset_resource": dataset_resource,
            }
        raise ValueError(f"Unknown dataset '{dataset_name}'")

    def _ensure_dataset_resource(self, dataset_name: str):
        dataset_slug = slugify(dataset_name) or dataset_name.lower()
        uri = f"http://arkumu.org/data/{self.organization.code}/datasets/{dataset_name}"
        defaults = {
            "resource_type": ResourceType.CLASS,
            "name": dataset_name,
            "organization": self.organization,
        }
        resource, _ = Resource.objects.get_or_create(uri=uri, defaults=defaults)
        return resource

    def _resolve_dataset_resource(self, dataset_name: str, schema):
        return self._ensure_dataset_resource(dataset_name)


@pytest.fixture(autouse=True)
def stub_schema_service(monkeypatch, organization, mapping):
    """Use stub workspace service for all tests in this module."""

    def _stub(request, mapping_id: str):
        if str(mapping_id) != str(mapping.id):
            raise AssertionError("Unexpected mapping lookup in stub schema service")
        return StubWorkspaceService(mapping=mapping, organization=organization)

    monkeypatch.setattr(schema_workspace_views, "_get_schema_service", _stub)
    yield


@pytest.mark.django_db
def test_single_fk_suggestion_updates_hidden_input_name(client, user, mapping):
    client.force_login(user)
    url = reverse("metadata:entity_workspace_select_suggestion", args=[mapping.id])
    response = client.post(
        url,
        {
            "input_id": "id_sprache",
            "target_id": "suggestions-sprache",
            "dataset": PROJECT_DATASET,
            "column": "sprache",
            "value": "http://arkumu.org/data/fuk/sprache/de",
            "label": "Deutsch",
        },
        HTTP_HX_REQUEST="true",
    )
    assert response.status_code == 200
    content = response.content.decode()
    assert 'name="sprache"' in content
    assert 'name="sprache[]"' not in content


@pytest.mark.django_db
def test_multi_select_suggestion_adds_chip(client, user, mapping):
    client.force_login(user)
    url = reverse("metadata:entity_workspace_select_suggestion", args=[mapping.id])
    response = client.post(
        url,
        {
            "input_id": "multi-select-search-projekt_ref",
            "target_id": "multi-select-suggestions-projekt_ref",
            "dataset": "Mitarbeit",
            "column": "projekt_ref",
            "field_name": "projekt_ref",
            "chip_container_id": "multi-select-chips-projekt_ref",
            "widget": "multi_select",
            "value": "http://arkumu.org/data/fuk/projekt/p1",
            "label": "Projekt P1",
        },
        HTTP_HX_REQUEST="true",
    )

    assert response.status_code == 200
    content = response.content.decode()
    assert 'hx-swap-oob="beforeend:#multi-select-chips-projekt_ref"' in content
    assert 'name="projekt_ref[]"' in content
    assert 'value="http://arkumu.org/data/fuk/projekt/p1"' in content
    assert 'id="multi-select-suggestions-projekt_ref"' in content
    assert 'id="multi-select-search-projekt_ref"' in content
    assert 'value=""' in content  # input reset


@pytest.mark.django_db
def test_multi_select_suggestion_deduplicates_existing(client, user, mapping):
    client.force_login(user)
    url = reverse("metadata:entity_workspace_select_suggestion", args=[mapping.id])
    response = client.post(
        url,
        {
            "input_id": "multi-select-search-projekt_ref",
            "target_id": "multi-select-suggestions-projekt_ref",
            "dataset": "Mitarbeit",
            "column": "projekt_ref",
            "field_name": "projekt_ref",
            "chip_container_id": "multi-select-chips-projekt_ref",
            "widget": "multi_select",
            "value": "http://arkumu.org/data/fuk/projekt/p1",
            "label": "Projekt P1",
            "projekt_ref[]": ["http://arkumu.org/data/fuk/projekt/p1"],
        },
        HTTP_HX_REQUEST="true",
    )

    assert response.status_code == 200
    content = response.content.decode()
    assert 'hx-swap-oob="beforeend:#multi-select-chips-projekt_ref"' not in content
    assert 'id="multi-select-search-projekt_ref"' in content
    assert 'id="multi-select-suggestions-projekt_ref"' in content
    assert 'hx-swap-oob="innerHTML"' in content


@pytest.fixture
def dataset_resource(db, organization):
    """Create a dataset resource."""
    return Resource.objects.create(
        uri=f"http://arkumu.org/data/{organization.code}/datasets/Projekt",
        resource_type=ResourceType.CLASS,
        name="Projekt",
    )


@pytest.fixture
def person_dataset_resource(db, organization):
    """Create a person dataset resource."""
    return Resource.objects.create(
        uri=f"http://arkumu.org/data/{organization.code}/datasets/Person",
        resource_type=ResourceType.CLASS,
        name="Person",
    )


@pytest.fixture
def is_part_of_predicate(db):
    """Create the dcterms:isPartOf predicate."""
    return Resource.objects.create(
        uri="http://purl.org/dc/terms/isPartOf",
        resource_type=ResourceType.PROPERTY,
        name="isPartOf",
    )


@pytest.fixture
def sample_project_entities(db, organization, dataset_resource, is_part_of_predicate):
    """Create sample project entities in the database."""
    entities = []
    for i, title in enumerate(["Projekt Alpha", "Projekt Beta", "Projekt Gamma"], start=1):
        # Create project entity
        project = Resource.objects.create(
            uri=f"http://arkumu.org/data/{organization.code}/projekt/P00{i}",
            resource_type=ResourceType.ENTITY,
            name=f"P00{i}",
        )

        # Link to dataset
        Triple.objects.create(
            subject=project,
            predicate=is_part_of_predicate,
            object=dataset_resource,
            source=organization,
        )

        # Add title triple
        title_predicate, _ = Resource.objects.get_or_create(
            uri="http://arkumu.org/properties/titel",
            defaults={"resource_type": ResourceType.PROPERTY, "name": "titel"},
        )
        title_literal, _ = Resource.objects.get_or_create(
            value=title,
            resource_type=ResourceType.LITERAL,
            defaults={"uri": f"http://example.org/literals/title-{i}"},
        )
        Triple.objects.create(
            subject=project,
            predicate=title_predicate,
            object=title_literal,
            source=organization,
        )

        entities.append(project)

    return entities


@pytest.fixture
def sample_person_entities(db, organization, person_dataset_resource, is_part_of_predicate):
    """Create sample person entities in the database."""
    entities = []
    for i, name in enumerate(["Anna Schmidt", "Klaus Müller", "Maria Weber"], start=1):
        # Create person entity
        person = Resource.objects.create(
            uri=f"http://arkumu.org/data/{organization.code}/person/PER00{i}",
            resource_type=ResourceType.ENTITY,
            name=f"PER00{i}",
        )

        # Link to dataset
        Triple.objects.create(
            subject=person,
            predicate=is_part_of_predicate,
            object=person_dataset_resource,
            source=organization,
        )

        # Add name triple
        name_predicate, _ = Resource.objects.get_or_create(
            uri="http://arkumu.org/properties/name",
            defaults={"resource_type": ResourceType.PROPERTY, "name": "name"},
        )
        name_literal, _ = Resource.objects.get_or_create(
            value=name,
            resource_type=ResourceType.LITERAL,
            defaults={"uri": f"http://example.org/literals/name-{i}"},
        )
        Triple.objects.create(
            subject=person,
            predicate=name_predicate,
            object=name_literal,
            source=organization,
        )

        entities.append(person)

    return entities


@pytest.mark.django_db
class TestDatasetFieldValueOptionsView:
    """Tests for the field value options/suggestions endpoint."""

    def test_requires_authentication(self, client, mapping):
        """Unauthenticated requests should be redirected."""
        url = reverse("metadata:entity_workspace_field_values", args=[mapping.id])
        response = client.get(url, {
            "dataset": "Mitarbeit",
            "column": "projekt_ref",
            "input_id": "test-input",
            "target_id": "test-target",
        })
        assert response.status_code == 302  # Redirect to login

    def test_requires_all_parameters(self, client, user, mapping):
        """Missing required parameters should return 400."""
        client.force_login(user)
        url = reverse("metadata:entity_workspace_field_values", args=[mapping.id])

        # Missing dataset
        response = client.get(url, {
            "column": "projekt_ref",
            "input_id": "test-input",
            "target_id": "test-target",
        })
        assert response.status_code == 400

        # Missing column
        response = client.get(url, {
            "dataset": "Mitarbeit",
            "input_id": "test-input",
            "target_id": "test-target",
        })
        assert response.status_code == 400

        # Missing input_id
        response = client.get(url, {
            "dataset": "Mitarbeit",
            "column": "projekt_ref",
            "target_id": "test-target",
        })
        assert response.status_code == 400

    def test_join_field_suggestions_no_query(
        self, client, user, mapping, sample_project_entities
    ):
        """Test getting suggestions for a join field without search query."""
        client.force_login(user)
        url = reverse("metadata:entity_workspace_field_values", args=[mapping.id])

        response = client.get(url, {
            "dataset": "Mitarbeit",
            "column": "projekt_ref",
            "input_id": "test-input",
            "target_id": "test-target",
        })

        assert response.status_code == 200
        content = response.content.decode()

        # Should show all 3 projects
        assert "Projekt Alpha" in content or "P001" in content
        assert "Projekt Beta" in content or "P002" in content

    def test_join_field_suggestions_with_query(
        self, client, user, mapping, sample_project_entities
    ):
        """Test filtering suggestions with a search query."""
        client.force_login(user)
        url = reverse("metadata:entity_workspace_field_values", args=[mapping.id])

        response = client.get(url, {
            "dataset": "Mitarbeit",
            "column": "projekt_ref",
            "input_id": "test-input",
            "target_id": "test-target",
            "q": "Alpha",
        })

        assert response.status_code == 200
        content = response.content.decode()

        # Should contain Alpha and prioritise it ahead of other suggestions
        assert "Alpha" in content
        if "Beta" in content:
            assert content.index("Alpha") < content.index("Beta")

    def test_join_field_suggestions_case_insensitive(
        self, client, user, mapping, sample_project_entities
    ):
        """Test that search is case-insensitive."""
        client.force_login(user)
        url = reverse("metadata:entity_workspace_field_values", args=[mapping.id])

        response = client.get(url, {
            "dataset": "Mitarbeit",
            "column": "projekt_ref",
            "input_id": "test-input",
            "target_id": "test-target",
            "q": "alpha",  # lowercase
        })

        assert response.status_code == 200
        content = response.content.decode()
        assert "Alpha" in content or "P001" in content

    def test_person_suggestions(
        self, client, user, mapping, sample_person_entities
    ):
        """Test getting suggestions for person references."""
        client.force_login(user)
        url = reverse("metadata:entity_workspace_field_values", args=[mapping.id])

        response = client.get(url, {
            "dataset": "Mitarbeit",
            "column": "person_ref",
            "input_id": "test-input",
            "target_id": "test-target",
        })

        assert response.status_code == 200
        content = response.content.decode()

        # Should show persons
        assert "Anna Schmidt" in content or "PER001" in content

    def test_property_filtering(
        self, client, user, mapping, sample_project_entities
    ):
        """Test filtering by specific property URI."""
        client.force_login(user)
        url = reverse("metadata:entity_workspace_field_values", args=[mapping.id])

        response = client.get(url, {
            "dataset": "Mitarbeit",
            "column": "projekt_ref",
            "input_id": "test-input",
            "target_id": "test-target",
            "q": "Projekt",
            "property": "http://arkumu.org/properties/titel",
        })

        assert response.status_code == 200
        # Should still work and return results


@pytest.mark.django_db
class TestRelationshipRowView:
    """Tests for adding/removing relationship rows."""

    def test_post_creates_new_row(self, client, user, mapping):
        """Test creating a new relationship row."""
        client.force_login(user)
        url = reverse("metadata:entity_workspace_relationship_row", args=[mapping.id])

        response = client.post(f"{url}?dataset=Mitarbeit&field_name=projekt_ref", HTTP_HX_REQUEST="true")

        assert response.status_code == 200
        content = response.content.decode()

        # Should contain row structure
        assert "relationship-row-projekt_ref" in content
        assert "input-relationship-row" in content
        assert "suggestions-relationship-row" in content

    def test_post_handles_non_htmx(self, client, user, mapping):
        """Test that non-HTMX requests still return a rendered row."""
        client.force_login(user)
        url = reverse("metadata:entity_workspace_relationship_row", args=[mapping.id])

        response = client.post(f"{url}?dataset=Mitarbeit&field_name=projekt_ref")
        assert response.status_code == 200
        content = response.content.decode()
        assert "relationship-row-projekt_ref" in content

    def test_get_normalizes_placeholder_values(self, client, user, mapping):
        """Existing placeholder URIs should render using canonical URIs and readable labels."""
        client.force_login(user)
        url = reverse("metadata:entity_workspace_relationship_rows", args=[mapping.id])

        placeholder = "uri-http-arkumu-org-data-fuk-entities-schlagwort-q13716-label-Schlagwort-Alpha"
        canonical = "http://arkumu.org/data/fuk/entities/schlagwort/q13716"

        response = client.get(
            url,
            {
                "dataset": "Mitarbeit",
                "field_name": "projekt_ref",
                "projekt_ref[]": placeholder,
            },
        )

        assert response.status_code == 200
        content = response.content.decode()
        assert canonical in content
        assert "Schlagwort Alpha" in content
        assert placeholder not in content

    def test_delete_removes_row(self, client, user, mapping):
        """Test deleting a relationship row returns empty response."""
        client.force_login(user)
        url = reverse("metadata:entity_workspace_relationship_row", args=[mapping.id])

        response = client.delete(url, HTTP_HX_REQUEST="true")

        assert response.status_code == 200
        assert response.content == b""


@pytest.mark.django_db
class TestRelationshipSelectSuggestionView:
    """Tests for selecting a suggestion from the dropdown."""

    def test_select_suggestion_updates_inputs(self, client, user, mapping):
        """Test that selecting a suggestion returns proper OOB updates."""
        client.force_login(user)
        url = reverse("metadata:entity_workspace_select_suggestion", args=[mapping.id])

        test_uri = "http://example.org/project/1"
        test_label = "Test Project"
        row_suffix = "relationship-row-projekt_ref-abc12345"
        input_id = f"input-{row_suffix}"
        hidden_input_id = f"{input_id}-hidden"
        target_id = f"suggestions-{row_suffix}"

        response = client.post(
            url,
            {
                "input_id": input_id,
                "target_id": target_id,
                "dataset": "Mitarbeit",
                "column": "projekt_ref",
                "value": test_uri,
                "label": test_label,
            },
        )

        assert response.status_code == 200
        content = response.content.decode()
        # Normalize whitespace for comparison
        content_normalized = ' '.join(content.split())

        # Should contain OOB swaps for individual inputs (more targeted approach)
        # 1. Hidden input with OOB swap
        assert f'id="{hidden_input_id}"' in content
        assert 'hx-swap-oob="outerHTML"' in content
        assert f'value="{test_uri}"' in content
        assert f'data-uri="{test_uri}"' in content
        assert f'data-label="{test_label}"' in content

        # 2. Visible input with OOB swap
        assert f'id="{input_id}"' in content
        assert f'value="{test_label}"' in content

        # 3. Dropdown cleared with OOB swap
        assert f'id="{target_id}"' in content
        assert 'hx-swap-oob="innerHTML"' in content

    def test_select_suggestion_clears_dropdown(self, client, user, mapping):
        """Test that selecting clears the suggestions dropdown."""
        client.force_login(user)
        url = reverse("metadata:entity_workspace_select_suggestion", args=[mapping.id])

        row_suffix = "relationship-row-projekt_ref-abc12345"
        input_id = f"input-{row_suffix}"
        target_id = f"suggestions-{row_suffix}"

        response = client.post(
            url,
            {
                "input_id": input_id,
                "target_id": target_id,
                "dataset": "Mitarbeit",
                "column": "projekt_ref",
                "value": "http://example.org/project/1",
                "label": "Test Project",
            },
        )

        assert response.status_code == 200
        content = response.content.decode()

        # Should contain empty target div
        assert f'<div id="{target_id}" hx-swap-oob="innerHTML"></div>' in content

    def test_select_suggestion_normalizes_placeholder(self, client, user, mapping):
        """Placeholder URIs should be converted to canonical values when selected."""
        client.force_login(user)
        url = reverse("metadata:entity_workspace_select_suggestion", args=[mapping.id])

        placeholder = "uri-http-arkumu-org-data-fuk-entities-schlagwort-q555-label-Schlagwort-Beta"
        canonical = "http://arkumu.org/data/fuk/entities/schlagwort/q555"
        label_hint = "Schlagwort Beta"
        row_suffix = "relationship-row-projekt_ref-xyz123"
        input_id = f"input-{row_suffix}"
        hidden_input_id = f"{input_id}-hidden"
        target_id = f"suggestions-{row_suffix}"

        response = client.post(
            url,
            {
                "input_id": input_id,
                "target_id": target_id,
                "dataset": "Mitarbeit",
                "column": "projekt_ref",
                "value": placeholder,
                "label": placeholder,
            },
        )

        assert response.status_code == 200
        content = response.content.decode()
        assert canonical in content
        assert placeholder not in content
        assert label_hint in content
        assert f'id="{hidden_input_id}"' in content

    def test_requires_input_id(self, client, user, mapping):
        """Test that missing input_id returns 400."""
        client.force_login(user)
        url = reverse("metadata:entity_workspace_select_suggestion", args=[mapping.id])

        response = client.post(
            url,
            {
                "target_id": "test-suggestions",
                "dataset": "Mitarbeit",
                "column": "projekt_ref",
                "value": "http://example.org/project/1",
                "label": "Test Project",
            },
        )

        assert response.status_code == 400

    def test_requires_dataset_and_column(self, client, user, mapping):
        """Test that missing dataset/column returns 400."""
        client.force_login(user)
        url = reverse("metadata:entity_workspace_select_suggestion", args=[mapping.id])

        response = client.post(
            url,
            {
                "input_id": "input-relationship-row-projekt_ref-abc12345",
                "target_id": "suggestions-relationship-row-projekt_ref-abc12345",
                "value": "http://example.org/project/1",
                "label": "Test Project",
            },
        )

        assert response.status_code == 400

    def test_handles_special_characters(self, client, user, mapping):
        """Test handling of special characters in labels."""
        client.force_login(user)
        url = reverse("metadata:entity_workspace_select_suggestion", args=[mapping.id])

        row_suffix = "relationship-row-projekt_ref-abc12345"
        response = client.post(
            url,
            {
                "input_id": f"input-{row_suffix}",
                "target_id": f"suggestions-{row_suffix}",
                "dataset": "Mitarbeit",
                "column": "projekt_ref",
                "value": "http://example.org/project/1",
                "label": 'Project "Special" <Characters> & Stuff',
            },
        )

        assert response.status_code == 200
        content = response.content.decode()

        # Verify values are properly escaped in HTML attributes
        assert "&quot;" in content  # Quotes escaped in HTML
        assert "&lt;" in content  # < escaped in HTML
        assert "&amp;" in content  # & escaped in HTML

        # New implementation should not inject inline script tags
        assert "<script>" not in content


@pytest.mark.django_db
class TestRelationshipRowsView:
    """Tests for re-rendering all relationship rows."""

    def test_rerender_with_property_change(self, client, user, mapping):
        """Test re-rendering rows when property selection changes."""
        client.force_login(user)
        url = reverse("metadata:entity_workspace_relationship_rows", args=[mapping.id])

        # Simulate existing values
        response = client.get(url, {
            "dataset": "Mitarbeit",
            "field_name": "projekt_ref",
            "relationship_property_projekt_ref": "http://arkumu.org/properties/titel",
            "projekt_ref[]": ["http://arkumu.org/data/testorg/projekt/P001"],
        })

        assert response.status_code == 200
        content = response.content.decode()

        # Should contain the row
        assert "relationship-row-projekt_ref" in content

    def test_creates_empty_row_when_no_values(self, client, user, mapping):
        """Test that an empty row is created when no existing values."""
        client.force_login(user)
        url = reverse("metadata:entity_workspace_relationship_rows", args=[mapping.id])

        response = client.get(url, {
            "dataset": "Mitarbeit",
            "field_name": "projekt_ref",
        })

        assert response.status_code == 200
        content = response.content.decode()

        # Should still create one row
        assert "relationship-row-projekt_ref" in content
