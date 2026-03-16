import pytest

from arkumu.metadata.models.resource import Resource, ResourceType
from arkumu.metadata.models.triples import Triple
from arkumu.metadata.services.canonical_graph_service import RDF_TYPE_URI
from arkumu.metadata.services.vocabulary_options_service import (
    build_metadata_option_map,
    get_default_metadata_option_map,
)
from arkumu.users.models import Organization


@pytest.mark.django_db
def test_get_default_metadata_option_map_returns_choice_tuples():
    organization = Organization.objects.create(name="Org", code="org")

    type_uri = "http://arkumu.org/data/types/projekt"
    type_resource, _ = Resource.objects.get_or_create(
        uri=type_uri,
        defaults={
            "canonical_uri": type_uri,
            "resource_type": ResourceType.CLASS,
        },
    )

    rdf_type_resource, _ = Resource.objects.get_or_create(
        uri=RDF_TYPE_URI,
        defaults={
            "resource_type": ResourceType.PROPERTY,
            "canonical_uri": RDF_TYPE_URI,
        },
    )

    label_predicate_uri = "http://arkumu.org/data/properties/bevorzugter-titel"
    label_predicate_resource, _ = Resource.objects.get_or_create(
        uri=label_predicate_uri,
        defaults={
            "resource_type": ResourceType.PROPERTY,
            "canonical_uri": label_predicate_uri,
        },
    )

    project = Resource.objects.create(
        uri="http://arkumu.org/data/project/1",
        resource_type=ResourceType.ENTITY,
        organization=organization,
    )

    label_resource = Resource.objects.create(
        resource_type=ResourceType.LITERAL,
        value="Projekt Alpha",
    )

    Triple.objects.create(
        subject=project,
        predicate=rdf_type_resource,
        object=type_resource,
        source=organization,
    )

    Triple.objects.create(
        subject=project,
        predicate=label_predicate_resource,
        object=label_resource,
        source=organization,
    )

    options = get_default_metadata_option_map(organization=organization)

    assert options["project"] == [(project.uri, "Projekt Alpha")]
    assert options["institution"] == []


@pytest.mark.django_db
def test_build_metadata_option_map_fallback_label_and_sorting():
    organization = Organization.objects.create(name="Org", code="org")

    type_uri = "http://arkumu.org/data/types/projekt"
    type_resource, _ = Resource.objects.get_or_create(
        uri=type_uri,
        defaults={
            "canonical_uri": type_uri,
            "resource_type": ResourceType.CLASS,
        },
    )

    rdf_type_resource, _ = Resource.objects.get_or_create(
        uri=RDF_TYPE_URI,
        defaults={
            "resource_type": ResourceType.PROPERTY,
            "canonical_uri": RDF_TYPE_URI,
        },
    )

    project_predicate_uri = "http://arkumu.org/data/properties/bevorzugter-titel"
    project_predicate_resource, _ = Resource.objects.get_or_create(
        uri=project_predicate_uri,
        defaults={
            "resource_type": ResourceType.PROPERTY,
            "canonical_uri": project_predicate_uri,
        },
    )

    project = Resource.objects.create(
        uri="http://arkumu.org/data/project/a",
        resource_type=ResourceType.ENTITY,
        organization=organization,
    )

    unlabeled_project = Resource.objects.create(
        uri="http://arkumu.org/data/project/b",
        resource_type=ResourceType.ENTITY,
        organization=organization,
    )

    label_resource = Resource.objects.create(
        resource_type=ResourceType.LITERAL,
        value="Projekt Alpha",
    )

    Triple.objects.create(
        subject=project,
        predicate=rdf_type_resource,
        object=type_resource,
        source=organization,
    )
    Triple.objects.create(
        subject=unlabeled_project,
        predicate=rdf_type_resource,
        object=type_resource,
        source=organization,
    )

    Triple.objects.create(
        subject=project,
        predicate=project_predicate_resource,
        object=label_resource,
        source=organization,
    )

    options = build_metadata_option_map(
        {"project": type_uri},
        organization=organization,
    )

    assert options["project"] == [
        (project.uri, "Projekt Alpha"),
        (unlabeled_project.uri, f"Unbekannter Eintrag ({unlabeled_project.uri})"),
    ]


@pytest.mark.django_db
def test_build_metadata_option_map_resolves_event_type_german_label():
    organization = Organization.objects.create(name="Org", code="org")

    type_uri = "http://arkumu.org/data/types/ereignistyp"
    type_resource, _ = Resource.objects.get_or_create(
        uri=type_uri,
        defaults={
            "canonical_uri": type_uri,
            "resource_type": ResourceType.CLASS,
        },
    )

    rdf_type_resource, _ = Resource.objects.get_or_create(
        uri=RDF_TYPE_URI,
        defaults={
            "resource_type": ResourceType.PROPERTY,
            "canonical_uri": RDF_TYPE_URI,
        },
    )

    label_predicate_uri = "http://arkumu.org/data/properties/deutscher-name-des-ereignistyps"
    label_predicate_resource, _ = Resource.objects.get_or_create(
        uri=label_predicate_uri,
        defaults={
            "resource_type": ResourceType.PROPERTY,
            "canonical_uri": label_predicate_uri,
        },
    )

    event_type = Resource.objects.create(
        uri="http://arkumu.org/data/org/entities/ereignistyp/1",
        resource_type=ResourceType.ENTITY,
        organization=organization,
    )

    label_resource = Resource.objects.create(
        resource_type=ResourceType.LITERAL,
        value="Ankauf",
        organization=organization,
    )

    Triple.objects.create(
        subject=event_type,
        predicate=rdf_type_resource,
        object=type_resource,
        source=organization,
    )
    Triple.objects.create(
        subject=event_type,
        predicate=label_predicate_resource,
        object=label_resource,
        source=organization,
    )

    options = build_metadata_option_map(
        {"event_type": type_uri},
        organization=organization,
    )

    assert options["event_type"] == [(event_type.uri, "Ankauf")]
