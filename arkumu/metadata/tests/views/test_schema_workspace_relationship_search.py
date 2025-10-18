"""
Tests for relationship search functionality in schema workspace views.

These tests focus on the Verküpfungen (relationships) search and selection workflow,
ensuring that search suggestions work correctly and selected values are properly stored.
"""

import json
import pytest
from django.urls import reverse

from arkumu.metadata.models.mappings import Mapping
from arkumu.metadata.models.resource import Resource, ResourceType
from arkumu.metadata.models.triples import Triple
from arkumu.users.models import Organization, User


@pytest.fixture
def organization(db):
    return Organization.objects.create(code="testorg", name="Test Organization")


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
    mapping_config = {
        "datasets": [
            {
                "name": "Projekt",
                "columns": {
                    "projekt_id": {
                        "name": "projekt_id",
                        "property_uri": "http://arkumu.org/properties/projekt-id",
                    },
                    "titel": {
                        "name": "titel",
                        "property_uri": "http://arkumu.org/properties/titel",
                    },
                },
                "anchor_columns": ["projekt_id"],
                "fk_relationships": [],
            },
            {
                "name": "Person",
                "columns": {
                    "person_id": {
                        "name": "person_id",
                        "property_uri": "http://arkumu.org/properties/person-id",
                    },
                    "name": {
                        "name": "name",
                        "property_uri": "http://arkumu.org/properties/name",
                    },
                },
                "anchor_columns": ["person_id"],
                "fk_relationships": [],
            },
            {
                "name": "Mitarbeit",
                "columns": {
                    "mitarbeit_id": {"name": "mitarbeit_id"},
                    "projekt_ref": {"name": "projekt_ref"},
                    "person_ref": {"name": "person_ref"},
                },
                "anchor_columns": ["mitarbeit_id"],
                "join_relationships": [
                    {
                        "self_column": "projekt_ref",
                        "other_dataset": "Projekt",
                        "other_column": "projekt_id",
                    },
                    {
                        "self_column": "person_ref",
                        "other_dataset": "Person",
                        "other_column": "person_id",
                    },
                ],
            },
        ]
    }

    return Mapping.objects.create(
        organization_id=organization.code,
        name="Test Mapping",
        mapping_config=mapping_config,
    )


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

        # Should only show Alpha
        assert "Alpha" in content
        assert "Beta" not in content

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

    def test_post_requires_htmx(self, client, user, mapping):
        """Test that non-HTMX requests are rejected."""
        client.force_login(user)
        url = reverse("metadata:entity_workspace_relationship_row", args=[mapping.id])

        response = client.post(f"{url}?dataset=Mitarbeit&field_name=projekt_ref")
        assert response.status_code == 400

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

        response = client.post(url, {
            "input_id": "test-input",
            "target_id": "test-suggestions",
            "value": test_uri,
            "label": test_label,
        })

        assert response.status_code == 200
        content = response.content.decode()

        # Should contain OOB swaps for both inputs
        assert "test-input" in content
        assert "test-input-hidden" in content
        assert test_uri in content
        assert test_label in content
        assert "hx-swap-oob" in content

    def test_select_suggestion_clears_dropdown(self, client, user, mapping):
        """Test that selecting clears the suggestions dropdown."""
        client.force_login(user)
        url = reverse("metadata:entity_workspace_select_suggestion", args=[mapping.id])

        response = client.post(url, {
            "input_id": "test-input",
            "target_id": "test-suggestions",
            "value": "http://example.org/project/1",
            "label": "Test Project",
        })

        assert response.status_code == 200
        content = response.content.decode()

        # Should contain empty target div
        assert "test-suggestions" in content

    def test_requires_input_id(self, client, user, mapping):
        """Test that missing input_id returns 400."""
        client.force_login(user)
        url = reverse("metadata:entity_workspace_select_suggestion", args=[mapping.id])

        response = client.post(url, {
            "target_id": "test-suggestions",
            "value": "http://example.org/project/1",
            "label": "Test Project",
        })

        assert response.status_code == 400

    def test_handles_special_characters(self, client, user, mapping):
        """Test handling of special characters in labels."""
        client.force_login(user)
        url = reverse("metadata:entity_workspace_select_suggestion", args=[mapping.id])

        response = client.post(url, {
            "input_id": "input-relationship-row-test_field-abc12345",  # Proper format
            "target_id": "test-suggestions",
            "value": "http://example.org/project/1",
            "label": 'Project "Special" <Characters> & Stuff',
        })

        assert response.status_code == 200
        content = response.content.decode()

        # Verify values are properly escaped in HTML attributes
        assert "&quot;" in content  # Quotes escaped in HTML
        assert "&lt;" in content  # < escaped in HTML
        assert "&amp;" in content  # & escaped in HTML

        # Verify the script tag is present (we use inline JS for updates)
        assert "<script>" in content

        # Verify JSON escaping in JavaScript (no raw HTML injection)
        # The label should be JSON-encoded in the script
        assert '\\"' in content or "\\\"" in content  # Quotes are escaped in JSON


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
