"""Tests for create_promoted_schema_manifest command."""

from django.core.management import call_command
from django.test import TestCase

from arkumu.metadata.models import Mapping, Resource, ResourceType
from arkumu.users.models import Organization


BASE_URI = "http://arkumu.org/data"


class CreatePromotedSchemaManifestTests(TestCase):
    def setUp(self):
        super().setUp()
        self.org = Organization.objects.create(code="test", name="Test Org")
        self._seed_property_resources()
        self.mapping = Mapping.objects.create(
            name="Test Mapping",
            organization_id=self.org.code,
            mapping_config=self._build_mapping_config(),
        )

    def test_promoted_manifest_created(self):
        call_command("create_promoted_schema_manifest", "--organization", "test")
        self.mapping.refresh_from_db()
        promoted_config = self.mapping.mapping_config.get("promoted_manifest")
        self.assertIsNotNone(promoted_config)

        workspace_columns = promoted_config["workspace_columns"]
        self.assertIn("promoted::Projekt::projekt-hat-teil", workspace_columns)
        self.assertIn("promoted::Ereignis::ereignis-hat-akteurin", workspace_columns)

        schema_manifest = promoted_config["schema_manifest"]
        projekt_fk = schema_manifest["Projekt"]["fk_relationships"]
        self.assertTrue(any(entry["source_column"] == "Projekt hat Teil" for entry in projekt_fk))

    def test_idempotent(self):
        call_command("create_promoted_schema_manifest", "--organization", "test")
        self.mapping.refresh_from_db()
        first = self.mapping.mapping_config["promoted_manifest"]

        call_command("create_promoted_schema_manifest", "--organization", "test")
        self.mapping.refresh_from_db()
        second = self.mapping.mapping_config["promoted_manifest"]

        self.assertEqual(first["workspace_columns"].keys(), second["workspace_columns"].keys())

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _seed_property_resources(self):
        # Existing ID properties
        for canonical in [
            "http://arkumu.org/data/properties/projekt-id",
            "http://arkumu.org/data/properties/akteurin-id",
            "http://arkumu.org/data/properties/ereignis-id",
            "http://arkumu.org/data/properties/rolle-id",
        ]:
            slug = canonical.split("/")[-1]
            Resource.objects.create(
                uri=f"{BASE_URI}/test/properties/{slug}",
                canonical_uri=canonical,
                resource_type=ResourceType.PROPERTY,
                organization=self.org,
                name=slug,
            )

        # Promoted predicates
        for slug, label in [
            ("projekt-hat-teil", "Projekt hat Teil"),
            ("projekt-ist-teil-von", "Projekt ist Teil von"),
            ("projekt-hat-bezug-zu", "Projekt hat Bezug zu"),
            ("projekt-basiert-auf", "Projekt basiert auf"),
            ("projekt-ist-vorbereitend-fuer", "Projekt ist vorbereitend für"),
            ("ereignis-hat-akteurin", "Ereignis hat AkteurIn"),
            ("akteurin-im-ereignis", "AkteurIn wirkt in Ereignis"),
            ("akteurin-hat-rolle-im-ereignis", "Rolle im Ereignis"),
        ]:
            Resource.objects.create(
                uri=f"{BASE_URI}/test/properties/{slug}",
                canonical_uri=f"{BASE_URI}/properties/{slug}",
                resource_type=ResourceType.PROPERTY,
                organization=self.org,
                name=label,
            )

    def _build_mapping_config(self):
        workspace_columns = {
            "fuk::Projekt::Projekt-ID": {
                "id": "fuk::Projekt::Projekt-ID",
                "name": "Projekt-ID",
                "type": "string",
                "is_fk": False,
                "source": "Projekt",
                "dataset": "Projekt",
                "added_at": "2025-01-01T00:00:00",
                "is_anchor": True,
                "is_multi_value": False,
            }
        }

        schema_manifest = {
            "Projekt": {
                "properties": {
                    "Projekt-ID": {
                        "uri": f"{BASE_URI}/test/properties/projekt-id",
                        "name": "Projekt-ID",
                        "canonical_uri": "http://arkumu.org/data/properties/projekt-id",
                    }
                },
                "entity_type": {
                    "uri": f"{BASE_URI}/test/types/projekt",
                    "name": "Projekt",
                    "canonical_uri": "http://arkumu.org/data/types/projekt",
                },
                "fk_relationships": [],
                "relationship_contexts": [],
            },
            "Ereignis": {
                "properties": {},
                "entity_type": {
                    "uri": f"{BASE_URI}/test/types/ereignis",
                    "name": "Ereignis",
                    "canonical_uri": "http://arkumu.org/data/types/ereignis",
                },
                "fk_relationships": [],
                "relationship_contexts": [],
            },
            "AkteurIn": {
                "properties": {},
                "entity_type": {
                    "uri": f"{BASE_URI}/test/types/akteurin",
                    "name": "AkteurIn",
                    "canonical_uri": "http://arkumu.org/data/types/akteurin",
                },
                "fk_relationships": [],
                "relationship_contexts": [],
            },
            "AkteurIn_Ereignis_Kreuztabelle": {
                "properties": {},
                "entity_type": {
                    "uri": f"{BASE_URI}/test/types/akteurin-ereignis-kreuztabelle",
                    "name": "AkteurIn_Ereignis_Kreuztabelle",
                    "canonical_uri": "http://arkumu.org/data/types/akteurin-ereignis-kreuztabelle",
                },
                "fk_relationships": [],
                "relationship_contexts": [],
            },
        }

        return {
            "workspace_columns": workspace_columns,
            "schema_manifest": schema_manifest,
            "fk_relationships": {},
        }
