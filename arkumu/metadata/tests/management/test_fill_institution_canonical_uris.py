import pytest
from django.core.management import call_command

from arkumu.metadata.models.resource import Resource, ResourceType


@pytest.mark.django_db
def test_fill_institution_canonical_uris_updates_missing_values():
    res = Resource.objects.create(
        uri="http://arkumu.org/data/fuk/properties/digitales-objekt",
        resource_type=ResourceType.PROPERTY,
        canonical_uri=None,
    )
    res_other = Resource.objects.create(
        uri="http://arkumu.org/data/fuk/entities/digitales-objekt/1",
        resource_type=ResourceType.ENTITY,
        canonical_uri=None,
    )

    # resource outside target institution should remain untouched
    untouched = Resource.objects.create(
        uri="http://arkumu.org/data/khm/properties/digitales-objekt",
        resource_type=ResourceType.PROPERTY,
        canonical_uri=None,
    )

    call_command("fill_institution_canonical_uris", "--institutions", "fuk")

    res.refresh_from_db()
    res_other.refresh_from_db()
    untouched.refresh_from_db()

    assert res.canonical_uri == "http://arkumu.org/data/properties/digitales-objekt"
    assert res_other.canonical_uri == "http://arkumu.org/data/entities/digitales-objekt/1"
    assert untouched.canonical_uri is None


@pytest.mark.django_db
def test_fill_institution_canonical_uris_dry_run_does_not_persist():
    res = Resource.objects.create(
        uri="http://arkumu.org/data/fuk/properties/ereignis",
        resource_type=ResourceType.PROPERTY,
        canonical_uri=None,
    )

    call_command("fill_institution_canonical_uris", "--institutions", "fuk", "--dry-run")

    res.refresh_from_db()
    assert res.canonical_uri is None
