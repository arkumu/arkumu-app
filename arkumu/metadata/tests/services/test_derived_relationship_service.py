from __future__ import annotations

import pytest

from arkumu.metadata.canonical import canonical_uri
from arkumu.metadata.models import Resource, ResourceType, Triple, Mapping
from arkumu.metadata.derivations.kreuz_config import DCTERMS_IS_PART_OF
from arkumu.metadata.services.derived_relationship_service import DerivedRelationshipService
from arkumu.users.models import Organization

PROJECT = canonical_uri("project")
EVENT = canonical_uri("event")


@pytest.mark.django_db
def test_service_derives_from_mapping_config():
    org = Organization.objects.create(name="FUK", code="fuk")
    mapping = Mapping.objects.create(
        name="Test Mapping",
        organization_id=org.code,
        mapping_config={
            "junction_patterns": {
                "projekt_ereignis": {
                    "patterns": [
                        {
                            "name": "custom_project_event",
                            "required_properties": [PROJECT, EVENT],
                            "recipes": [
                                {
                                    "subject_property": PROJECT,
                                    "object_property": EVENT,
                                    "predicate_uri": EVENT,
                                }
                            ],
                        }
                    ]
                }
            }
        },
    )

    project = Resource.objects.create(
        uri="http://example.org/project/1",
        resource_type=ResourceType.ENTITY,
        organization=org,
    )
    event = Resource.objects.create(
        uri="http://example.org/event/1",
        resource_type=ResourceType.ENTITY,
        organization=org,
    )
    junction = Resource.objects.create(
        uri="http://example.org/junction/1",
        resource_type=ResourceType.ENTITY,
        organization=org,
    )
    predicate_project = Resource.objects.create(
        uri=PROJECT,
        resource_type=ResourceType.PROPERTY,
    )
    predicate_event = Resource.objects.create(
        uri=EVENT,
        resource_type=ResourceType.PROPERTY,
    )
    dataset_link = Resource.objects.create(
        uri="dataset/projekt_ereignis",
        resource_type=ResourceType.IRI,
        name="Projekt_Ereignis",
    )

    Triple.objects.create(
        subject=junction,
        predicate=predicate_project,
        object=project,
    )
    Triple.objects.create(
        subject=junction,
        predicate=predicate_event,
        object=event,
    )
    Triple.objects.create(
        subject=junction,
        predicate=Resource.objects.create(uri=DCTERMS_IS_PART_OF, resource_type=ResourceType.PROPERTY),
        object=dataset_link,
    )

    service = DerivedRelationshipService(mapping.organization_id, mapping_config=mapping.mapping_config)
    stats = service.derive(dry_run=False)

    assert stats.processed == 1
    assert stats.created >= 1
    assert Triple.objects.filter(
        subject=project,
        predicate__uri=EVENT,
        object=event,
        is_derived=True,
    ).exists()
