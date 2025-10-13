import copy
import io

import pytest
from django.core.management import call_command

from arkumu.metadata.models import Resource
from arkumu.metadata.models.mappings import Mapping
from arkumu.metadata.models.resource import ResourceType
from arkumu.users.models import Organization


def _create_property_resource(org, slug: str) -> Resource:
    """Helper for creating property resources with predictable canonical URIs."""
    return Resource.objects.create(
        uri=f"http://arkumu.org/data/khm/properties/{slug}",
        canonical_uri=f"http://arkumu.org/data/properties/{slug}-canonical",
        resource_type=ResourceType.PROPERTY,
        organization=org,
    )


@pytest.mark.django_db
def test_command_updates_schema_manifest_entries():
    org = Organization.objects.create(name="KHM", code="khm")
    entity_resource = Resource.objects.create(
        uri="http://arkumu.org/data/khm/entities/projekt",
        canonical_uri="http://arkumu.org/data/entities/projekt-canonical",
        resource_type=ResourceType.ENTITY,
        organization=org,
    )
    project_id_resource = _create_property_resource(org, "projekt-id")
    digital_object_resource = _create_property_resource(org, "digitales-objekt")
    context_resource = _create_property_resource(org, "context-prop")
    primary_resource = _create_property_resource(org, "primary-prop")
    secondary_resource = _create_property_resource(org, "secondary-prop")

    manifest = {
        "00_Projects": {
            "entity_type": {
                "uri": "/khm/entities/projekt",
                "canonical_uri": "/khm/entities/projekt",
            },
            "properties": {
                "project_id": {
                    "uri": "/khm/properties/projekt-id",
                    "canonical_uri": None,
                }
            },
            "fk_relationships": [
                {
                    "source_property_uri": "/khm/properties/projekt-id",
                    "source_canonical_property": None,
                    "target_property_uri": "/khm/properties/digitales-objekt",
                    "target_canonical_property": None,
                }
            ],
            "relationship_contexts": [
                {
                    "context_property_uri": "/khm/properties/context-prop",
                    "context_canonical_property": None,
                    "primary_property_uri": "/khm/properties/primary-prop",
                    "primary_canonical_property": None,
                    "secondary_property_uri": "/khm/properties/secondary-prop",
                    "secondary_canonical_property": None,
                }
            ],
        }
    }

    mapping = Mapping.objects.create(
        name="KHM Mapping",
        organization_id=org.code,
        mapping_config={"schema_manifest": manifest},
    )

    out = io.StringIO()
    call_command("canonicalize_schema_manifest", "--organization", org.code, stdout=out)
    mapping.refresh_from_db()

    updated_manifest = mapping.mapping_config["schema_manifest"]["00_Projects"]

    assert updated_manifest["entity_type"]["uri"] == entity_resource.uri
    assert updated_manifest["entity_type"]["canonical_uri"] == entity_resource.canonical_uri

    property_snapshot = updated_manifest["properties"]["project_id"]
    assert property_snapshot["uri"] == project_id_resource.uri
    assert property_snapshot["canonical_uri"] == project_id_resource.canonical_uri

    fk_snapshot = updated_manifest["fk_relationships"][0]
    assert fk_snapshot["source_property_uri"] == project_id_resource.uri
    assert fk_snapshot["source_canonical_property"] == project_id_resource.canonical_uri
    assert fk_snapshot["target_property_uri"] == digital_object_resource.uri
    assert fk_snapshot["target_canonical_property"] == digital_object_resource.canonical_uri

    relationship_context = updated_manifest["relationship_contexts"][0]
    assert relationship_context["context_property_uri"] == context_resource.uri
    assert relationship_context["context_canonical_property"] == context_resource.canonical_uri
    assert relationship_context["primary_property_uri"] == primary_resource.uri
    assert relationship_context["primary_canonical_property"] == primary_resource.canonical_uri
    assert relationship_context["secondary_property_uri"] == secondary_resource.uri
    assert relationship_context["secondary_canonical_property"] == secondary_resource.canonical_uri

    assert "Updated 1 mapping(s); skipped 0." in out.getvalue()


@pytest.mark.django_db
def test_command_respects_dry_run():
    org = Organization.objects.create(name="KHM", code="khm")
    Resource.objects.create(
        uri="http://arkumu.org/data/khm/entities/projekt",
        canonical_uri="http://arkumu.org/data/entities/projekt-canonical",
        resource_type=ResourceType.ENTITY,
        organization=org,
    )
    _create_property_resource(org, "projekt-id")

    manifest = {
        "00_Projects": {
            "entity_type": {
                "uri": "/khm/entities/projekt",
                "canonical_uri": "/khm/entities/projekt",
            },
            "properties": {
                "project_id": {
                    "uri": "/khm/properties/projekt-id",
                    "canonical_uri": None,
                }
            },
        }
    }

    mapping = Mapping.objects.create(
        name="KHM Mapping",
        organization_id=org.code,
        mapping_config={"schema_manifest": manifest},
    )

    original_manifest = copy.deepcopy(mapping.mapping_config["schema_manifest"])
    out = io.StringIO()

    call_command(
        "canonicalize_schema_manifest",
        "--organization",
        org.code,
        "--dry-run",
        stdout=out,
    )

    mapping.refresh_from_db()
    assert mapping.mapping_config["schema_manifest"] == original_manifest
    assert "Dry-run complete. 1 mapping(s) would be updated." in out.getvalue()
