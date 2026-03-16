import pytest

from arkumu.catalog.services.project_views import CardURIs
from arkumu.metadata.models.mappings import Mapping
from arkumu.metadata.services.mapping_set_resolver import MappingSetResolver
from arkumu.users.models import Organization


@pytest.mark.django_db
def test_list_datasets_for_entity_collects_multiple_mappings_for_same_org():
    Organization.objects.create(name="HMT", code="hmt")

    Mapping.objects.create(
        name="HMT Produktionen",
        organization_id="hmt",
        mapping_config={
            "schema_manifest": {
                "Produktionen": {
                    "entity_type": {
                        "canonical_uri": CardURIs.PROJECT_TYPE,
                    }
                }
            }
        },
    )
    Mapping.objects.create(
        name="HMT Auffuehrungen",
        organization_id="hmt",
        mapping_config={
            "promoted_manifest": {
                "schema_manifest": {
                    "Auffuehrungen": {
                        "entity_type": {
                            "canonical_uri": CardURIs.PROJECT_TYPE,
                        }
                    }
                }
            }
        },
    )

    resolver = MappingSetResolver()

    bindings = resolver.list_datasets_for_entity(
        organization_code="hmt",
        entity_type="project",
    )

    assert [(binding.mapping_name, binding.dataset_name) for binding in bindings] == [
        ("HMT Auffuehrungen", "Auffuehrungen"),
        ("HMT Produktionen", "Produktionen"),
    ]


@pytest.mark.django_db
def test_list_datasets_for_entity_ignores_other_orgs_and_entity_types():
    Organization.objects.create(name="HMT", code="hmt")
    Organization.objects.create(name="KHM", code="khm")

    Mapping.objects.create(
        name="HMT Events",
        organization_id="hmt",
        mapping_config={
            "schema_manifest": {
                "Ereignisse": {
                    "entity_type": {
                        "canonical_uri": CardURIs.EVENT_TYPE,
                    }
                }
            }
        },
    )
    Mapping.objects.create(
        name="KHM Projects",
        organization_id="khm",
        mapping_config={
            "schema_manifest": {
                "Werke": {
                    "entity_type": {
                        "canonical_uri": CardURIs.PROJECT_TYPE,
                    }
                }
            }
        },
    )

    resolver = MappingSetResolver()

    bindings = resolver.list_datasets_for_entity(
        organization_code="hmt",
        entity_type="project",
    )

    assert bindings == []
