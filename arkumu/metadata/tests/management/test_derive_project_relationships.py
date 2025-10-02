"""Tests for derive_project_relationships management command."""

from django.core.management import call_command
from django.test import TestCase

from arkumu.metadata.models import Resource, ResourceType, Triple
from arkumu.users.models import Organization


class DeriveProjectRelationshipsCommandTests(TestCase):
    def setUp(self):
        super().setUp()
        # Organization and predicate resources
        self.org = Organization.objects.create(code="test", name="Test Org")

        self.projekt_pred = Resource.objects.create(
            uri="http://arkumu.org/data/properties/projekt",
            resource_type=ResourceType.PROPERTY,
        )
        self.ereignis_pred = Resource.objects.create(
            uri="http://arkumu.org/data/properties/ereignis",
            resource_type=ResourceType.PROPERTY,
        )

        # Project and related entities
        self.project = Resource.objects.create(
            uri="http://example.org/projects/1",
            resource_type=ResourceType.ENTITY,
            organization=self.org,
        )
        self.event = Resource.objects.create(
            uri="http://example.org/events/1",
            resource_type=ResourceType.ENTITY,
            organization=self.org,
        )

        # Junction resource
        self.junction = Resource.objects.create(
            uri="http://example.org/test_junction/1",
            resource_type=ResourceType.ENTITY,
            organization=self.org,
        )

        # Local predicates with canonical URIs
        projekt_local = Resource.objects.create(
            uri="http://local/projekt",
            resource_type=ResourceType.PROPERTY,
            canonical_uri="http://arkumu.org/data/properties/projekt",
        )
        ereignis_local = Resource.objects.create(
            uri="http://local/ereignis",
            resource_type=ResourceType.PROPERTY,
            canonical_uri="http://arkumu.org/data/properties/ereignis",
        )

        Triple.objects.create(
            subject=self.junction,
            predicate=projekt_local,
            object=self.project,
        )

        Triple.objects.create(
            subject=self.junction,
            predicate=ereignis_local,
            object=self.event,
        )

    def test_derive_relationships_creates_project_triple(self):
        self.assertFalse(
            Triple.objects.filter(
                subject=self.project,
                predicate=self.ereignis_pred,
                object=self.event,
            ).exists()
        )

        call_command("derive_project_relationships", "--organization", "test")

        triple = Triple.objects.get(
            subject=self.project,
            predicate=self.ereignis_pred,
            object=self.event,
        )
        self.assertTrue(triple.is_derived)

    def test_dry_run_does_not_create_triples(self):
        call_command("derive_project_relationships", "--organization", "test", "--dry-run")
        self.assertFalse(
            Triple.objects.filter(
                subject=self.project,
                predicate=self.ereignis_pred,
                object=self.event,
            ).exists()
        )
