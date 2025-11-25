from __future__ import annotations

import pytest

from django.core.management import call_command

from arkumu.catalog.services.project_views import ProjectURIs
from arkumu.metadata.models import Resource, ResourceType, Triple
from arkumu.users.models import Organization


@pytest.mark.django_db
def test_prune_derived_project_digital_links_removes_only_derived_for_org():
    org_khm = Organization.objects.create(code="khm", name="KHM", is_active=True)
    org_fuk = Organization.objects.create(code="fuk", name="FUK", is_active=True)

    pred_digital = Resource.objects.create(
        uri=ProjectURIs.DIGITAL_OBJECT,
        resource_type=ResourceType.PROPERTY,
    )

    # KHM project / digital resources
    project_khm = Resource.objects.create(
        uri="http://arkumu.org/data/khm/entities/projekt/1",
        organization=org_khm,
        resource_type=ResourceType.ENTITY,
    )
    digital_khm = Resource.objects.create(
        uri="http://arkumu.org/data/khm/entities/digitales-objekt/1",
        organization=org_khm,
        resource_type=ResourceType.ENTITY,
    )

    # FUK project / digital resources
    project_fuk = Resource.objects.create(
        uri="http://arkumu.org/data/fuk/entities/projekt/1",
        organization=org_fuk,
        resource_type=ResourceType.ENTITY,
    )
    digital_fuk = Resource.objects.create(
        uri="http://arkumu.org/data/fuk/entities/digitales-objekt/1",
        organization=org_fuk,
        resource_type=ResourceType.ENTITY,
    )

    # Non-derived KHM triple (should remain)
    Triple.objects.create(
        subject=project_khm,
        predicate=pred_digital,
        object=digital_khm,
        is_derived=False,
    )
    # Derived KHM triple (should be pruned)
    Triple.objects.create(
        subject=project_khm,
        predicate=pred_digital,
        object=digital_khm,
        is_derived=True,
    )

    # Derived FUK triple (should remain; other org)
    Triple.objects.create(
        subject=project_fuk,
        predicate=pred_digital,
        object=digital_fuk,
        is_derived=True,
    )

    assert (
        Triple.objects.filter(
            predicate__canonical_uri=ProjectURIs.DIGITAL_OBJECT,
            subject__organization__code__iexact="khm",
            subject__uri__contains="/entities/projekt/",
        ).count()
        == 2
    )

    call_command("prune_derived_project_digital_links", "--organization", "khm")

    # Only one KHM triple (non-derived) should remain
    remaining_khm = Triple.objects.filter(
        predicate__canonical_uri=ProjectURIs.DIGITAL_OBJECT,
        subject__organization__code__iexact="khm",
        subject__uri__contains="/entities/projekt/",
    )
    assert remaining_khm.count() == 1
    assert remaining_khm.filter(is_derived=True).count() == 0

    # FUK derived triple must still exist
    assert Triple.objects.filter(
        predicate__canonical_uri=ProjectURIs.DIGITAL_OBJECT,
        subject__organization__code__iexact="fuk",
        subject__uri__contains="/entities/projekt/",
        is_derived=True,
    ).count() == 1

