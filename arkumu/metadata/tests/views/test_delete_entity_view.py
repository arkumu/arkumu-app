"""
Tests for DeleteEntityView in schema workspace.

Ensures that:
1. Entity deletion removes the entity resource
2. Entity deletion removes triples where entity is subject
3. Entity deletion removes triples where entity is object (dangling refs)
4. Other resources are NOT deleted
5. Organization ownership is enforced
6. Missing parameters return errors
"""

import pytest
from django.urls import reverse

from arkumu.metadata.models.mappings import Mapping
from arkumu.metadata.models.resource import Resource, ResourceType
from arkumu.metadata.models.triples import Triple
from arkumu.users.models import Organization, User


@pytest.fixture
def organization(db):
    return Organization.objects.create(code="rsh", name="RSH Test Organization")


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
    """Create a minimal mapping for tests."""
    return Mapping.objects.create(
        organization_id=organization.code,
        name="Test Mapping",
        mapping_config={
            "datasets": {
                "digitales-objekt": {
                    "entity_type": "http://arkumu.org/data/types/digitales-objekt",
                    "columns": {},
                }
            }
        },
    )


@pytest.fixture
def entity_to_delete(db, organization):
    """Create an entity resource that will be deleted."""
    return Resource.objects.create(
        uri="http://arkumu.org/data/rsh/entities/digitales-objekt/196",
        resource_type=ResourceType.ENTITY,
        organization=organization,
    )


@pytest.fixture
def related_entity(db, organization):
    """Create a related entity that should NOT be deleted."""
    return Resource.objects.create(
        uri="http://arkumu.org/data/rsh/entities/projekt/100",
        resource_type=ResourceType.ENTITY,
        organization=organization,
    )


@pytest.fixture
def property_resource(db, organization):
    """Create a property resource for triples."""
    return Resource.objects.create(
        uri="http://arkumu.org/properties/hat-digitales-objekt",
        resource_type=ResourceType.PROPERTY,
        organization=organization,
    )


@pytest.fixture
def value_resource(db, organization):
    """Create a value resource for entity's own data."""
    return Resource.objects.create(
        uri="http://arkumu.org/data/rsh/values/filename-123",
        resource_type=ResourceType.ENTITY,
        organization=organization,
    )


@pytest.fixture
def name_property(db, organization):
    """Property for entity's own data."""
    return Resource.objects.create(
        uri="http://arkumu.org/properties/dateiname",
        resource_type=ResourceType.PROPERTY,
        organization=organization,
    )


@pytest.mark.django_db
class TestDeleteEntityView:
    """Tests for the DeleteEntityView."""

    def test_delete_entity_removes_resource(self, client, user, mapping, entity_to_delete):
        """Deleting an entity should remove the Resource."""
        client.force_login(user)
        url = reverse("metadata:entity_workspace_delete", args=[mapping.id])

        response = client.post(url, {
            "entity_uri": entity_to_delete.uri,
            "dataset": "digitales-objekt",
        })

        assert response.status_code == 200
        assert not Resource.objects.filter(uri=entity_to_delete.uri).exists()

    def test_delete_entity_removes_subject_triples(
        self, client, user, mapping, entity_to_delete, name_property, value_resource
    ):
        """Deleting an entity should remove triples where it's the subject."""
        # Create a triple where entity_to_delete is the subject
        triple = Triple.objects.create(
            subject=entity_to_delete,
            predicate=name_property,
            object=value_resource,
            source=user.organization,
        )

        client.force_login(user)
        url = reverse("metadata:entity_workspace_delete", args=[mapping.id])

        response = client.post(url, {
            "entity_uri": entity_to_delete.uri,
            "dataset": "digitales-objekt",
        })

        assert response.status_code == 200
        assert not Triple.objects.filter(id=triple.id).exists()

    def test_delete_entity_removes_object_triples(
        self, client, user, mapping, entity_to_delete, related_entity, property_resource
    ):
        """Deleting an entity should remove triples where it's the object (dangling refs)."""
        # Create a triple where another entity points to entity_to_delete
        triple = Triple.objects.create(
            subject=related_entity,
            predicate=property_resource,
            object=entity_to_delete,
            source=user.organization,
        )

        client.force_login(user)
        url = reverse("metadata:entity_workspace_delete", args=[mapping.id])

        response = client.post(url, {
            "entity_uri": entity_to_delete.uri,
            "dataset": "digitales-objekt",
        })

        assert response.status_code == 200
        # Triple should be deleted to avoid dangling reference
        assert not Triple.objects.filter(id=triple.id).exists()

    def test_delete_entity_preserves_other_resources(
        self, client, user, mapping, entity_to_delete, related_entity, property_resource
    ):
        """Deleting an entity should NOT delete other resources."""
        # Create a triple where another entity points to entity_to_delete
        Triple.objects.create(
            subject=related_entity,
            predicate=property_resource,
            object=entity_to_delete,
            source=user.organization,
        )

        client.force_login(user)
        url = reverse("metadata:entity_workspace_delete", args=[mapping.id])

        response = client.post(url, {
            "entity_uri": entity_to_delete.uri,
            "dataset": "digitales-objekt",
        })

        assert response.status_code == 200
        # Related entity should still exist
        assert Resource.objects.filter(uri=related_entity.uri).exists()
        # Property should still exist
        assert Resource.objects.filter(uri=property_resource.uri).exists()

    def test_delete_entity_requires_entity_uri(self, client, user, mapping):
        """Missing entity_uri should return 400."""
        client.force_login(user)
        url = reverse("metadata:entity_workspace_delete", args=[mapping.id])

        response = client.post(url, {
            "dataset": "digitales-objekt",
        })

        assert response.status_code == 400
        assert b"Missing entity_uri" in response.content

    def test_delete_entity_requires_dataset(self, client, user, mapping, entity_to_delete):
        """Missing dataset should return 400."""
        client.force_login(user)
        url = reverse("metadata:entity_workspace_delete", args=[mapping.id])

        response = client.post(url, {
            "entity_uri": entity_to_delete.uri,
        })

        assert response.status_code == 400
        assert b"Missing dataset" in response.content

    def test_delete_nonexistent_entity_returns_error(self, client, user, mapping):
        """Deleting a non-existent entity should return 400."""
        client.force_login(user)
        url = reverse("metadata:entity_workspace_delete", args=[mapping.id])

        response = client.post(url, {
            "entity_uri": "http://arkumu.org/data/rsh/entities/fake/999",
            "dataset": "digitales-objekt",
        })

        assert response.status_code == 400
        assert b"Entity not found" in response.content

    def test_delete_entity_from_other_org_forbidden(self, client, user, mapping, db):
        """Cannot delete entity from another organization."""
        # Create entity for different org
        other_org = Organization.objects.create(code="khm", name="KHM Organization")
        other_entity = Resource.objects.create(
            uri="http://arkumu.org/data/khm/entities/digitales-objekt/1",
            resource_type=ResourceType.ENTITY,
            organization=other_org,
        )

        client.force_login(user)
        url = reverse("metadata:entity_workspace_delete", args=[mapping.id])

        response = client.post(url, {
            "entity_uri": other_entity.uri,
            "dataset": "digitales-objekt",
        })

        assert response.status_code == 400
        assert b"Cannot delete entity from another organization" in response.content
        # Entity should still exist
        assert Resource.objects.filter(uri=other_entity.uri).exists()

    def test_delete_entity_requires_authentication(self, client, mapping, entity_to_delete):
        """Unauthenticated requests should redirect to login."""
        url = reverse("metadata:entity_workspace_delete", args=[mapping.id])

        response = client.post(url, {
            "entity_uri": entity_to_delete.uri,
            "dataset": "digitales-objekt",
        })

        # Should redirect to login
        assert response.status_code == 302
        assert "/login/" in response.url or "/accounts/login/" in response.url
