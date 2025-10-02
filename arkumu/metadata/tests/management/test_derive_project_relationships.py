"""Tests for derive_project_relationships management command."""

from uuid import uuid4
from typing import Mapping, Sequence

from django.core.management import call_command
from django.test import TestCase

from arkumu.metadata.derivations import kreuz_config
from arkumu.metadata.models import Resource, ResourceType, Triple
from arkumu.users.models import Organization


class DeriveProjectRelationshipsCommandTests(TestCase):
    def setUp(self):
        super().setUp()
        self.org = Organization.objects.create(code="test", name="Test Org")

        # Canonical predicate resources reused across junctions
        self.project_pred = Resource.objects.create(
            uri=kreuz_config.PROJECT,
            resource_type=ResourceType.PROPERTY,
        )
        self.event_pred = Resource.objects.create(
            uri=kreuz_config.EVENT,
            resource_type=ResourceType.PROPERTY,
        )
        self.digital_pred = Resource.objects.create(
            uri=kreuz_config.DIGITAL_OBJECT,
            resource_type=ResourceType.PROPERTY,
        )
        self.is_part_of_pred = Resource.objects.create(
            uri=kreuz_config.DCTERMS_IS_PART_OF,
            resource_type=ResourceType.PROPERTY,
        )

        # Entity resources used by tests
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
        self.digital_object = Resource.objects.create(
            uri="http://example.org/digital/1",
            resource_type=ResourceType.ENTITY,
            organization=self.org,
        )

    # ------------------------------------------------------------------
    # Helper utilities
    # ------------------------------------------------------------------

    def _create_junction(self, dataset_name: str, property_map: Mapping[str, Sequence[Resource]]):
        """Create a junction entity with dataset membership and canonical triples."""

        junction = Resource.objects.create(
            uri=f"http://example.org/junction/{uuid4()}",
            resource_type=ResourceType.ENTITY,
            organization=self.org,
        )

        dataset = Resource.objects.create(
            uri=f"http://example.org/datasets/{uuid4()}",
            resource_type=ResourceType.IRI,
            organization=self.org,
            name=dataset_name,
        )

        Triple.objects.create(subject=junction, predicate=self.is_part_of_pred, object=dataset)

        for canonical_uri, targets in property_map.items():
            predicate = Resource.objects.create(
                uri=f"http://local/{uuid4()}",
                resource_type=ResourceType.PROPERTY,
                canonical_uri=canonical_uri,
            )
            for target in targets:
                Triple.objects.create(subject=junction, predicate=predicate, object=target)

        return junction

    def test_derive_relationships_creates_project_triple(self):
        self._create_junction(
            dataset_name="Projekt_Ereignis",
            property_map={
                kreuz_config.PROJECT: [self.project],
                kreuz_config.EVENT: [self.event],
            },
        )

        call_command("derive_project_relationships", "--organization", "test")

        triple = Triple.objects.get(
            subject=self.project,
            predicate=self.event_pred,
            object=self.event,
        )
        self.assertTrue(triple.is_derived)

    def test_dry_run_does_not_create_triples(self):
        self._create_junction(
            dataset_name="Projekt_Ereignis",
            property_map={
                kreuz_config.PROJECT: [self.project],
                kreuz_config.EVENT: [self.event],
            },
        )

        call_command("derive_project_relationships", "--organization", "test", "--dry-run")
        self.assertFalse(
            Triple.objects.filter(
                subject=self.project,
                predicate=self.event_pred,
                object=self.event,
            ).exists()
        )

    def test_project_event_digital_object_derivations(self):
        self._create_junction(
            dataset_name="Ereignis_Digitales_Objekt",
            property_map={
                kreuz_config.PROJECT: [self.project],
                kreuz_config.EVENT: [self.event],
                kreuz_config.DIGITAL_OBJECT: [self.digital_object],
            },
        )

        call_command("derive_project_relationships", "--organization", "test")

        project_event = Triple.objects.get(
            subject=self.project,
            predicate=self.event_pred,
            object=self.event,
        )
        event_digital = Triple.objects.get(
            subject=self.event,
            predicate=self.digital_pred,
            object=self.digital_object,
        )
        project_digital = Triple.objects.get(
            subject=self.project,
            predicate=self.digital_pred,
            object=self.digital_object,
        )

        self.assertTrue(project_event.is_derived)
        self.assertTrue(event_digital.is_derived)
        self.assertTrue(project_digital.is_derived)
