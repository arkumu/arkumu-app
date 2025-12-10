"""
Tests for TabularDeleteEntityView.

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
def entity_to_delete(db, organization):
    """Create an entity resource that will be deleted."""
    return Resource.objects.create(
        uri="http://arkumu.org/data/rsh/entities/projekt/999",
        resource_type=ResourceType.ENTITY,
        organization=organization,
    )


@pytest.fixture
def related_entity(db, organization):
    """Create a related entity that should NOT be deleted."""
    return Resource.objects.create(
        uri="http://arkumu.org/data/rsh/entities/ereignis/100",
        resource_type=ResourceType.ENTITY,
        organization=organization,
    )


@pytest.fixture
def property_resource(db, organization):
    """Create a property resource for triples."""
    return Resource.objects.create(
        uri="http://arkumu.org/properties/hat-projekt",
        resource_type=ResourceType.PROPERTY,
        organization=organization,
    )


@pytest.fixture
def value_resource(db, organization):
    """Create a value resource for entity's own data."""
    return Resource.objects.create(
        uri="http://arkumu.org/data/rsh/entities/titel/123",
        resource_type=ResourceType.ENTITY,
        organization=organization,
    )


@pytest.fixture
def name_property(db, organization):
    """Property for entity's own data."""
    return Resource.objects.create(
        uri="http://arkumu.org/properties/titel",
        resource_type=ResourceType.PROPERTY,
        organization=organization,
    )


@pytest.mark.django_db
class TestTabularDeleteEntityView:
    """Tests for the TabularDeleteEntityView."""

    def test_delete_entity_removes_resource(self, client, user, entity_to_delete):
        """Deleting an entity should remove the Resource."""
        client.force_login(user)
        url = reverse("metadata:tabular_delete_entity")

        response = client.post(url, {
            "entity_uri": entity_to_delete.uri,
            "dataset": "Projekt",
            "organization": user.organization.code,
        })

        assert response.status_code == 200
        assert not Resource.objects.filter(uri=entity_to_delete.uri).exists()

    def test_delete_entity_removes_subject_triples(
        self, client, user, entity_to_delete, name_property, value_resource
    ):
        """Deleting an entity should remove triples where it's the subject."""
        triple = Triple.objects.create(
            subject=entity_to_delete,
            predicate=name_property,
            object=value_resource,
            source=user.organization,
        )

        client.force_login(user)
        url = reverse("metadata:tabular_delete_entity")

        response = client.post(url, {
            "entity_uri": entity_to_delete.uri,
            "dataset": "Projekt",
            "organization": user.organization.code,
        })

        assert response.status_code == 200
        assert not Triple.objects.filter(id=triple.id).exists()

    def test_delete_entity_removes_object_triples(
        self, client, user, entity_to_delete, related_entity, property_resource
    ):
        """Deleting an entity should remove triples where it's the object."""
        triple = Triple.objects.create(
            subject=related_entity,
            predicate=property_resource,
            object=entity_to_delete,
            source=user.organization,
        )

        client.force_login(user)
        url = reverse("metadata:tabular_delete_entity")

        response = client.post(url, {
            "entity_uri": entity_to_delete.uri,
            "dataset": "Projekt",
            "organization": user.organization.code,
        })

        assert response.status_code == 200
        assert not Triple.objects.filter(id=triple.id).exists()

    def test_delete_entity_preserves_other_resources(
        self, client, user, entity_to_delete, related_entity, property_resource
    ):
        """Deleting an entity should NOT delete other resources."""
        Triple.objects.create(
            subject=related_entity,
            predicate=property_resource,
            object=entity_to_delete,
            source=user.organization,
        )

        client.force_login(user)
        url = reverse("metadata:tabular_delete_entity")

        response = client.post(url, {
            "entity_uri": entity_to_delete.uri,
            "dataset": "Projekt",
            "organization": user.organization.code,
        })

        assert response.status_code == 200
        assert Resource.objects.filter(uri=related_entity.uri).exists()
        assert Resource.objects.filter(uri=property_resource.uri).exists()

    def test_delete_entity_requires_entity_uri(self, client, user):
        """Missing entity_uri should return 400."""
        client.force_login(user)
        url = reverse("metadata:tabular_delete_entity")

        response = client.post(url, {
            "dataset": "Projekt",
            "organization": user.organization.code,
        })

        assert response.status_code == 400
        assert b"Missing entity_uri" in response.content

    def test_delete_entity_requires_dataset(self, client, user, entity_to_delete):
        """Missing dataset should return 400."""
        client.force_login(user)
        url = reverse("metadata:tabular_delete_entity")

        response = client.post(url, {
            "entity_uri": entity_to_delete.uri,
            "organization": user.organization.code,
        })

        assert response.status_code == 400
        assert b"Missing dataset" in response.content

    def test_delete_nonexistent_entity_returns_error(self, client, user):
        """Deleting a non-existent entity should return 400."""
        client.force_login(user)
        url = reverse("metadata:tabular_delete_entity")

        response = client.post(url, {
            "entity_uri": "http://arkumu.org/data/rsh/entities/fake/999",
            "dataset": "Projekt",
            "organization": user.organization.code,
        })

        assert response.status_code == 400
        assert b"Entity not found" in response.content

    def test_delete_entity_from_other_org_forbidden(self, client, user, db):
        """Cannot delete entity from another organization."""
        other_org = Organization.objects.create(code="khm", name="KHM Organization")
        other_entity = Resource.objects.create(
            uri="http://arkumu.org/data/khm/entities/projekt/1",
            resource_type=ResourceType.ENTITY,
            organization=other_org,
        )

        client.force_login(user)
        url = reverse("metadata:tabular_delete_entity")

        response = client.post(url, {
            "entity_uri": other_entity.uri,
            "dataset": "Projekt",
            "organization": user.organization.code,
        })

        assert response.status_code == 400
        assert b"Cannot delete entity from another organization" in response.content
        assert Resource.objects.filter(uri=other_entity.uri).exists()

    def test_delete_entity_requires_authentication(self, client, entity_to_delete):
        """Unauthenticated requests should redirect to login."""
        url = reverse("metadata:tabular_delete_entity")

        response = client.post(url, {
            "entity_uri": entity_to_delete.uri,
            "dataset": "Projekt",
            "organization": "rsh",
        })

        assert response.status_code == 302
        assert "/login/" in response.url or "/accounts/login/" in response.url
