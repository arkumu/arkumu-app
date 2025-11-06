"""
Tests for schema workspace form submission and relationship saving.

Ensures that:
1. "Entity erstellen & neues Formular" creates entity and shows fresh form
2. "Entity erstellen & weiter bearbeiten" creates entity and loads it for editing
3. Verküpfungen (relationships) are properly saved
4. Multi-value relationship fields work correctly
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
from arkumu.metadata.schema_workspace.services import DatasetSummary


MAPPING_FIXTURE_PATH = (
    Path(__file__).resolve().parents[4] / "data/mappings/fuk_mapping_20250930.json"
)


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
    """Create a mapping using the FUK fixture."""
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
            # Base metadata includes FK columns that will be replaced by join fields
            return {
                "mitarbeit_id": {
                    "column_name": "mitarbeit_id",
                    "is_anchor": True,
                    "is_required": True,
                },
                # Note: projekt_ref and person_ref FK columns are removed
                # during augment_field_metadata_with_joins() and replaced with
                # __join__ fields
            }
        return {}

    def augment_field_metadata_with_joins(self, dataset_name, metadata):
        """
        Augment metadata with join relationships, matching real implementation:
        - Remove source columns from metadata
        - Add join fields with __join__ prefix
        """
        metadata = dict(metadata)  # Copy to avoid mutating original
        join_map = {}

        if dataset_name == "Mitarbeit":
            # Remove source columns from metadata (like real implementation)
            metadata.pop("projekt_ref", None)
            metadata.pop("person_ref", None)

            # Create join field for Projekt with proper naming
            projekt_field_name = "__join__Mitarbeit__Projekt"
            join_map[projekt_field_name] = JoinRelationship(
                join_dataset="Mitarbeit",
                join_dataset_schema={},
                self_column="projekt_ref",
                self_property_uri="http://arkumu.org/properties/projekt_ref",
                other_dataset="Projekt",
                other_column="projekt_id",
                other_property_uri="http://arkumu.org/properties/projekt-id",
                other_display_label="Projekt",
            )
            metadata[projekt_field_name] = {
                "column_name": projekt_field_name,
                "column_type": "join",
                "property_label": "Projekt",
                "is_required": False,
                "is_multi_value": True,
                "is_join": True,
                "join_relationship": join_map[projekt_field_name],
                "join_other_dataset": "Projekt",
                "join_key": "Mitarbeit::Projekt",
                "widget": "JunctionRelationshipWidget",
            }

            # Create join field for Person with proper naming
            person_field_name = "__join__Mitarbeit__Person"
            join_map[person_field_name] = JoinRelationship(
                join_dataset="Mitarbeit",
                join_dataset_schema={},
                self_column="person_ref",
                self_property_uri="http://arkumu.org/properties/person_ref",
                other_dataset="Person",
                other_column="person_id",
                other_property_uri="http://arkumu.org/properties/person-id",
                other_display_label="Person",
            )
            metadata[person_field_name] = {
                "column_name": person_field_name,
                "column_type": "join",
                "property_label": "Person",
                "is_required": False,
                "is_multi_value": True,
                "is_join": True,
                "join_relationship": join_map[person_field_name],
                "join_other_dataset": "Person",
                "join_key": "Mitarbeit::Person",
                "widget": "JunctionRelationshipWidget",
            }

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
        if dataset_name == "Mitarbeit":
            return {
                "entity_type": type("EntityType", (), {"name": "Mitarbeit"}),
                "properties": {},
                "fk_relationships": [],
                "dataset_resource": dataset_resource,
            }
        raise ValueError(f"Unknown dataset '{dataset_name}'")

    def _ensure_dataset_resource(self, dataset_name: str):
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

    def save_entity(self, dataset_name: str, entity_data: dict, entity_uri: str = None):
        """Stub save that creates minimal resources."""
        if entity_uri:
            # Update existing
            entity = Resource.objects.get(uri=entity_uri)
            return entity_uri, False
        else:
            # Create new
            anchor_field = next((k for k, v in self.get_field_metadata(dataset_name).items() if v.get("is_anchor")), None)
            if not anchor_field:
                raise ValueError("No anchor field found")

            anchor_value = entity_data.get(anchor_field)
            if not anchor_value:
                raise ValueError("Anchor value required")

            new_uri = f"http://arkumu.org/data/{self.organization.code}/{dataset_name.lower()}/{anchor_value}"

            # Create entity resource
            entity, created = Resource.objects.get_or_create(
                uri=new_uri,
                defaults={
                    "resource_type": ResourceType.ENTITY,
                    "name": anchor_value,
                    "organization": self.organization,
                }
            )

            # Link to dataset
            dataset_resource = self._ensure_dataset_resource(dataset_name)
            is_part_of, _ = Resource.objects.get_or_create(
                uri="http://purl.org/dc/terms/isPartOf",
                defaults={"resource_type": ResourceType.PROPERTY, "name": "isPartOf"}
            )
            Triple.objects.get_or_create(
                subject=entity,
                predicate=is_part_of,
                object=dataset_resource,
                defaults={"source": self.organization}
            )

            return new_uri, created

    def sync_join_relationship(self, entity_uri: str, relationship: JoinRelationship, related_items: list):
        """Stub sync for join relationships."""
        entity = Resource.objects.get(uri=entity_uri)
        predicate, _ = Resource.objects.get_or_create(
            uri=relationship.self_property_uri,
            defaults={"resource_type": ResourceType.PROPERTY, "name": relationship.self_column}
        )

        # Clear existing relationships
        Triple.objects.filter(subject=entity, predicate=predicate).delete()

        # Create new relationships
        for item in related_items:
            related_uri = item if isinstance(item, str) else item.get("uri")
            if not related_uri:
                continue
            related_resource, _ = Resource.objects.get_or_create(
                uri=related_uri,
                defaults={"resource_type": ResourceType.ENTITY, "name": related_uri.split("/")[-1]}
            )
            Triple.objects.create(
                subject=entity,
                predicate=predicate,
                object=related_resource,
                source=self.organization
            )

    def save_multi_fk_relationship(self, entity_uri: str, property_uri: str, related_uris: list):
        """Stub save for multi-FK relationships."""
        entity = Resource.objects.get(uri=entity_uri)
        predicate, _ = Resource.objects.get_or_create(
            uri=property_uri,
            defaults={"resource_type": ResourceType.PROPERTY, "name": property_uri.split("/")[-1]}
        )

        # Clear existing
        Triple.objects.filter(subject=entity, predicate=predicate).delete()

        # Create new
        for related_uri in related_uris:
            related_resource, _ = Resource.objects.get_or_create(
                uri=related_uri,
                defaults={"resource_type": ResourceType.ENTITY, "name": related_uri.split("/")[-1]}
            )
            Triple.objects.create(
                subject=entity,
                predicate=predicate,
                object=related_resource,
                source=self.organization
            )

    def collect_relationship_values(self, dataset_name: str, entity_uri: str, field_metadata: dict, join_field_map: dict):
        """Stub collect relationships."""
        return {}

    def load_entity_by_uri(self, dataset_name: str, entity_uri: str):
        """Stub load entity."""
        return None

    def get_dataset_summary(self, dataset_name: str) -> DatasetSummary:
        """Stub dataset summary."""
        field_meta = self.get_field_metadata(dataset_name)
        return DatasetSummary(
            dataset_name=dataset_name,
            display_label=dataset_name,
            anchor_columns=[k for k, v in field_meta.items() if v.get("is_anchor")],
            property_count=len(field_meta),
            relationship_count=0,
            is_controlled_vocab=False,
            entity_count=0,
        )


@pytest.fixture(autouse=True)
def stub_schema_service(monkeypatch, organization, mapping):
    """Use stub workspace service for all tests in this module."""

    def _stub(request, mapping_id: str):
        if str(mapping_id) != str(mapping.id):
            raise AssertionError("Unexpected mapping lookup in stub schema service")
        return StubWorkspaceService(mapping=mapping, organization=organization)

    monkeypatch.setattr(schema_workspace_views, "_get_schema_service", _stub)
    yield


@pytest.fixture
def person_entities(db, organization):
    """Create sample person entities for relationship testing."""
    is_part_of_predicate = Resource.objects.create(
        uri="http://purl.org/dc/terms/isPartOf",
        resource_type=ResourceType.PROPERTY,
        name="isPartOf",
    )

    person_dataset = Resource.objects.create(
        uri=f"http://arkumu.org/data/{organization.code}/datasets/Person",
        resource_type=ResourceType.CLASS,
        name="Person",
    )

    name_predicate = Resource.objects.create(
        uri="http://arkumu.org/properties/name",
        resource_type=ResourceType.PROPERTY,
        name="name",
    )

    persons = []
    for i, name in enumerate(["Anna Schmidt", "Klaus Müller"], start=1):
        person = Resource.objects.create(
            uri=f"http://arkumu.org/data/{organization.code}/person/PER00{i}",
            resource_type=ResourceType.ENTITY,
            name=f"PER00{i}",
        )

        # Link to dataset
        Triple.objects.create(
            subject=person,
            predicate=is_part_of_predicate,
            object=person_dataset,
            source=organization,
        )

        # Add name
        name_literal = Resource.objects.create(
            value=name,
            resource_type=ResourceType.LITERAL,
            uri=f"http://example.org/literals/name-{i}",
        )
        Triple.objects.create(
            subject=person,
            predicate=name_predicate,
            object=name_literal,
            source=organization,
        )

        persons.append(person)

    return persons


@pytest.mark.django_db
class TestFormSubmissionModes:
    """Test the two submission modes: create new vs continue editing."""

    def test_create_and_new_form_mode(self, client, user, mapping):
        """Test 'Entity erstellen & neues Formular' mode."""
        client.force_login(user)
        url = reverse("metadata:entity_workspace_dataset", args=[mapping.id])

        response = client.post(
            url,
            {
                "dataset": "Projekt",
                "projekt_id": "P001",
                "titel": "Test Project",
                "submission_mode": "create_new",
            },
            HTTP_HX_REQUEST="true",
        )

        assert response.status_code == 200
        content = response.content.decode()

        # Should show success message
        assert "Entity erfolgreich erstellt" in content

        # Should show empty form (no entity_uri hidden input with value)
        assert 'name="entity_uri"' not in content or 'name="entity_uri" value=""' in content

        # Form fields should be empty for next entry
        # Note: form is reset, so values from previous submission should not appear
        # The test validates that we see a fresh form

    def test_create_and_continue_editing_mode(self, client, user, mapping):
        """Test 'Entity erstellen & weiter bearbeiten' mode."""
        client.force_login(user)
        url = reverse("metadata:entity_workspace_dataset", args=[mapping.id])

        response = client.post(
            url,
            {
                "dataset": "Projekt",
                "projekt_id": "P002",
                "titel": "Project Two",
                "submission_mode": "stay_on_entity",
            },
            HTTP_HX_REQUEST="true",
        )

        assert response.status_code == 200
        content = response.content.decode()

        # Should show success message
        assert "Entity erfolgreich erstellt" in content
        assert "weiter bearbeiten" in content

        # Should have entity_uri hidden input with the created URI
        assert 'name="entity_uri"' in content
        assert "http://arkumu.org/data/fuk/projekt/" in content

        # Form fields should still contain the values
        assert 'value="P002"' in content
        assert 'value="Project Two"' in content

        # Should show "Änderungen speichern" button instead of create buttons
        assert "Änderungen speichern" in content


@pytest.mark.django_db
class TestFormRendering:
    """Test that the form renders relationship fields correctly."""

    def test_join_field_names_in_rendered_html(self, client, user, mapping):
        """
        Test that join fields are rendered with correct __join__ naming in HTML.
        This verifies the UI sends the correct field names to the backend.
        """
        client.force_login(user)
        url = reverse("metadata:entity_workspace_dataset", args=[mapping.id])

        # GET the form for Mitarbeit dataset which has join fields
        response = client.get(url, {"dataset": "Mitarbeit"}, HTTP_HX_REQUEST="true")

        assert response.status_code == 200
        content = response.content.decode()

        # Check that join fields are rendered with __join__ naming
        # The hidden input for the join field should have data-multi-value="true"
        assert '__join__Mitarbeit__Person' in content, "Join field for Person should be present"
        assert '__join__Mitarbeit__Projekt' in content, "Join field for Projekt should be present"

        # Check that the hidden inputs have data-multi-value attribute
        assert 'data-multi-value="true"' in content, "Hidden inputs should have data-multi-value attribute"
        assert 'data-widget="JunctionRelationshipWidget"' in content, "Join widgets should identify themselves for front-end handling"

        # Check that the relationship rows use the correct name pattern (field_name + [])
        # The dynamic rows should have name="__join__Mitarbeit__Person[]"
        assert 'name="__join__Mitarbeit__Person[]"' in content or \
               'name="__join__Mitarbeit__Projekt[]"' in content, \
               "Relationship rows should use __join__ field names with [] suffix"

        # Verify the JavaScript looks for the correct pattern
        assert 'data-multi-value="true"' in content, "Form should have multi-value markers for JavaScript"


@pytest.mark.django_db
class TestRelationshipSaving:
    """Test that Verküpfungen (relationships) are properly saved."""

    def test_save_multi_value_relationships(self, client, user, mapping, person_entities):
        """Test saving relationships with multiple values using join field."""
        client.force_login(user)
        url = reverse("metadata:entity_workspace_dataset", args=[mapping.id])

        # Create sample projects first
        project_entities = []
        for i in range(2):
            proj_uri = f"http://arkumu.org/data/{user.organization.code}/projekt/PROJ00{i+1}"
            proj_resource = Resource.objects.create(
                uri=proj_uri,
                resource_type=ResourceType.ENTITY,
                name=f"PROJ00{i+1}",
            )
            project_entities.append(proj_resource)

        # Create a Mitarbeit with relationship to both persons
        person_uris = [p.uri for p in person_entities]

        response = client.post(
            url,
            {
                "dataset": "Mitarbeit",
                "mitarbeit_id": "M001",
                "__join__Mitarbeit__Person": json.dumps(person_uris),  # JSON array of URIs
                "submission_mode": "stay_on_entity",
            },
            HTTP_HX_REQUEST="true",
        )

        assert response.status_code == 200

        # Verify the relationships were created
        mitarbeit_uri = f"http://arkumu.org/data/{user.organization.code}/mitarbeit/M001"
        mitarbeit_resource = Resource.objects.get(uri=mitarbeit_uri)

        person_ref_predicate = Resource.objects.get(
            uri="http://arkumu.org/properties/person_ref"
        )

        # Should have two relationship triples
        relationships = Triple.objects.filter(
            subject=mitarbeit_resource,
            predicate=person_ref_predicate,
        )
        assert relationships.count() == 2

        # Verify both persons are linked
        linked_person_uris = {rel.object.uri for rel in relationships}
        assert linked_person_uris == set(person_uris)

    def test_empty_relationships_allowed(self, client, user, mapping):
        """Test that creating entity without relationships works."""
        client.force_login(user)
        url = reverse("metadata:entity_workspace_dataset", args=[mapping.id])

        response = client.post(
            url,
            {
                "dataset": "Mitarbeit",
                "mitarbeit_id": "M002",
                "__join__Mitarbeit__Person": json.dumps([]),  # Empty array
                "submission_mode": "create_new",
            },
            HTTP_HX_REQUEST="true",
        )

        assert response.status_code == 200
        content = response.content.decode()
        assert "Entity erfolgreich erstellt" in content

    def test_update_relationships_on_edit(self, client, user, mapping, person_entities):
        """Test updating relationships when editing an existing entity."""
        client.force_login(user)
        url = reverse("metadata:entity_workspace_dataset", args=[mapping.id])

        # First create Mitarbeit with one person
        first_person_uri = person_entities[0].uri

        response = client.post(
            url,
            {
                "dataset": "Mitarbeit",
                "mitarbeit_id": "M003",
                "__join__Mitarbeit__Person": json.dumps([first_person_uri]),
                "submission_mode": "stay_on_entity",
            },
            HTTP_HX_REQUEST="true",
        )

        assert response.status_code == 200

        # Now update to link both persons
        both_person_uris = [p.uri for p in person_entities]

        # Extract created entity URI
        mitarbeit_uri = f"http://arkumu.org/data/{user.organization.code}/mitarbeit/M003"

        response = client.post(
            url,
            {
                "dataset": "Mitarbeit",
                "entity_uri": mitarbeit_uri,
                "mitarbeit_id": "M003",
                "__join__Mitarbeit__Person": json.dumps(both_person_uris),
            },
            HTTP_HX_REQUEST="true",
        )

        assert response.status_code == 200

        # Verify both persons are now linked
        mitarbeit_resource = Resource.objects.get(uri=mitarbeit_uri)
        person_ref_predicate = Resource.objects.get(
            uri="http://arkumu.org/properties/person_ref"
        )

        relationships = Triple.objects.filter(
            subject=mitarbeit_resource,
            predicate=person_ref_predicate,
        )
        assert relationships.count() == 2

        linked_uris = {rel.object.uri for rel in relationships}
        assert linked_uris == set(both_person_uris)
