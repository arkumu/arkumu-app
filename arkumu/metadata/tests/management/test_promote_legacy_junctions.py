"""Tests for the ``promote_legacy_junctions`` management command."""

from pathlib import Path
import json

from django.core.management import call_command
from django.test import TestCase

from arkumu.metadata.management.commands.promote_legacy_junctions import JUNCTION_SPECS
from arkumu.metadata.models import Resource, ResourceType, Triple
from arkumu.users.models import Organization


BASE_URI = "http://arkumu.org/data"
FIXTURE_PATH = Path(__file__).resolve().parents[4] / "data" / "mappings" / "fuk_mapping_20250930.json"


class PromoteLegacyJunctionsCommandTests(TestCase):
    def setUp(self):
        super().setUp()
        self.org = Organization.objects.create(code="test", name="Test Org")

    # ------------------------------------------------------------------
    # Helper builders
    # ------------------------------------------------------------------

    def _create_property(self, slug: str, canonical_slug: str | None = None) -> Resource:
        canonical_slug = canonical_slug or slug
        return Resource.objects.create(
            uri=f"{BASE_URI}/test/properties/{slug}",
            canonical_uri=f"{BASE_URI}/properties/{canonical_slug}",
            resource_type=ResourceType.PROPERTY,
            organization=self.org,
        )

    def _create_entity(self, path: str, name: str) -> Resource:
        return Resource.objects.create(
            uri=f"{BASE_URI}/test/entities/{path}",
            resource_type=ResourceType.ENTITY,
            organization=self.org,
            name=name,
        )

    def _create_literal(self, value: str) -> Resource:
        return Resource.objects.create(
            resource_type=ResourceType.LITERAL,
            value=value,
            name=value,
        )

    # ------------------------------------------------------------------
    # Tests
    # ------------------------------------------------------------------

    def test_promotes_project_relationship(self):
        ausgangs = self._create_property("ausgangsprojekt")
        verknuepft = self._create_property("verknuepftes-projekt")
        beziehung = self._create_property("beziehung")

        project_a = self._create_entity("projekt/projekt-a", "Projekt A")
        project_b = self._create_entity("projekt/projekt-b", "Projekt B")

        junction = self._create_entity("projekt-projekt-kreuztabelle/row-1", "Junction Row")
        relation_label = self._create_literal("hat Teil")

        Triple.objects.create(subject=junction, predicate=ausgangs, object=project_a)
        Triple.objects.create(subject=junction, predicate=verknuepft, object=project_b)
        Triple.objects.create(subject=junction, predicate=beziehung, object=relation_label)

        call_command("promote_legacy_junctions", "--organization", "test")

        predicate = Resource.objects.get(uri=f"{BASE_URI}/test/properties/projekt-hat-teil")
        self.assertEqual(predicate.canonical_uri, f"{BASE_URI}/properties/projekt-hat-teil")
        self.assertEqual(predicate.organization, self.org)

        triple = Triple.objects.get(subject=project_a, predicate=predicate, object=project_b)
        self.assertTrue(triple.is_derived)
        self.assertIsNone(triple.source_id)

    def test_promotes_actor_relationship(self):
        ausgangs = self._create_property("ausgangsakteurin")
        verknuepft = self._create_property("verknuepfter-akteurin")
        beziehung = self._create_property("beziehung")

        actor_a = self._create_entity("akteurin/actor-a", "Actor A")
        actor_b = self._create_entity("akteurin/actor-b", "Actor B")

        junction = self._create_entity("akteurin-akteurin-kreuztabelle/row-2", "Junction Row")
        relation_label = self._create_literal("hat Vater")

        Triple.objects.create(subject=junction, predicate=ausgangs, object=actor_a)
        Triple.objects.create(subject=junction, predicate=verknuepft, object=actor_b)
        Triple.objects.create(subject=junction, predicate=beziehung, object=relation_label)

        call_command("promote_legacy_junctions")

        predicate = Resource.objects.get(uri=f"{BASE_URI}/test/properties/akteurin-hat-vater")
        self.assertEqual(predicate.canonical_uri, f"{BASE_URI}/properties/akteurin-hat-vater")

        triple = Triple.objects.get(subject=actor_a, predicate=predicate, object=actor_b)
        self.assertTrue(triple.is_derived)

    def test_idempotent_execution(self):
        ausgangs = self._create_property("ausgangsprojekt")
        verknuepft = self._create_property("verknuepftes-projekt")
        beziehung = self._create_property("beziehung")

        project_a = self._create_entity("projekt/projekt-a", "Projekt A")
        project_b = self._create_entity("projekt/projekt-b", "Projekt B")

        junction = self._create_entity("projekt-projekt-kreuztabelle/row-3", "Junction Row")
        relation_label = self._create_literal("ist Teil von")

        Triple.objects.create(subject=junction, predicate=ausgangs, object=project_a)
        Triple.objects.create(subject=junction, predicate=verknuepft, object=project_b)
        Triple.objects.create(subject=junction, predicate=beziehung, object=relation_label)

        call_command("promote_legacy_junctions")
        call_command("promote_legacy_junctions")

        predicate = Resource.objects.get(uri=f"{BASE_URI}/test/properties/projekt-ist-teil-von")
        triples = Triple.objects.filter(subject=project_a, predicate=predicate, object=project_b)
        self.assertEqual(triples.count(), 1)
        self.assertTrue(triples.first().is_derived)

    def test_promotes_actor_event_relationship(self):
        actor_fk = self._create_property("akteurin-im-ereignis")
        event_fk = self._create_property("im-ereignis")
        role_pred = self._create_property("rollen-der-akteurin-im-ereignis")
        urheber_pred = self._create_property("ist-urheberin")

        actor = self._create_entity("akteurin/actor-a", "Actor A")
        event = self._create_entity("ereignis/event-a", "Event A")
        role = self._create_entity("rolle/role-a", "Role A")

        junction = self._create_entity(
            "akteurin-ereignis-kreuztabelle/row-actor-event",
            "Junction Row",
        )

        Triple.objects.create(subject=junction, predicate=actor_fk, object=actor)
        Triple.objects.create(subject=junction, predicate=event_fk, object=event)
        Triple.objects.create(subject=junction, predicate=role_pred, object=role)

        literal_one = self._create_literal("1")
        Triple.objects.create(subject=junction, predicate=urheber_pred, object=literal_one)

        call_command("promote_legacy_junctions", "--organization", "test")

        actor_event_pred = Resource.objects.get(uri=f"{BASE_URI}/test/properties/akteurin-im-ereignis")
        actor_event_triple = Triple.objects.get(subject=actor, predicate=actor_event_pred, object=event)
        self.assertTrue(actor_event_triple.is_derived)

        event_actor_pred = Resource.objects.get(uri=f"{BASE_URI}/test/properties/ereignis-hat-akteurin")
        event_actor_triple = Triple.objects.get(subject=event, predicate=event_actor_pred, object=actor)
        self.assertTrue(event_actor_triple.is_derived)

    def test_all_hat_beziehung_junctions_in_mapping_are_covered(self):
        with FIXTURE_PATH.open("r", encoding="utf-8") as handle:
            mapping = json.load(handle)

        contexts = mapping["relationship_contexts"]
        expected = {
            ctx["primary_fk_dataset"]
            for ctx in contexts.values()
            if ctx.get("context_predicate") == "hatBeziehung"
        }

        spec_datasets = {spec.dataset_name for spec in JUNCTION_SPECS}

        self.assertSetEqual(
            expected,
            spec_datasets,
            "Command specs should cover every hatBeziehung junction in mapping",
        )
