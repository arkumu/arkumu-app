from __future__ import annotations

import pytest

from django.core.management import call_command

from arkumu.metadata.models import Resource, ResourceType, Triple
from arkumu.users.models import Organization


@pytest.mark.django_db
def test_prune_derived_triples_removes_only_specified_org():
    org_khm = Organization.objects.create(code="khm", name="KHM", is_active=True)
    org_fuk = Organization.objects.create(code="fuk", name="FUK", is_active=True)

    pred = Resource.objects.create(
        uri="http://arkumu.org/data/properties/test-derived",
        resource_type=ResourceType.PROPERTY,
    )

    project_khm = Resource.objects.create(
        uri="http://arkumu.org/data/khm/entities/projekt/1",
        organization=org_khm,
        resource_type=ResourceType.ENTITY,
    )
    project_fuk = Resource.objects.create(
        uri="http://arkumu.org/data/fuk/entities/projekt/1",
        organization=org_fuk,
        resource_type=ResourceType.ENTITY,
    )

    target = Resource.objects.create(
        uri="http://arkumu.org/data/test/entities/target/1",
        resource_type=ResourceType.ENTITY,
    )

    # Non-derived KHM triple (should remain)
    Triple.objects.create(
        subject=project_khm,
        predicate=pred,
        object=target,
        is_derived=False,
    )
    # Derived KHM triple (use different object so unique constraint is not violated)
    other_target = Resource.objects.create(
        uri="http://arkumu.org/data/test/entities/target/2",
        resource_type=ResourceType.ENTITY,
    )
    Triple.objects.create(
        subject=project_khm,
        predicate=pred,
        object=other_target,
        is_derived=True,
    )

    # Derived FUK triple (should remain)
    Triple.objects.create(
        subject=project_fuk,
        predicate=pred,
        object=target,
        is_derived=True,
    )

    assert Triple.objects.filter(subject__organization__code__iexact="khm").count() == 2
    assert Triple.objects.filter(subject__organization__code__iexact="fuk").count() == 1

    call_command("prune_derived_triples", "--organization", "khm")

    # Only one KHM triple (non-derived) should remain
    assert Triple.objects.filter(subject__organization__code__iexact="khm").count() == 1
    assert (
        Triple.objects.filter(
            subject__organization__code__iexact="khm",
            is_derived=True,
        ).count()
        == 0
    )

    # FUK derived triple must still exist
    assert (
        Triple.objects.filter(
            subject__organization__code__iexact="fuk",
            is_derived=True,
        ).count()
        == 1
    )
