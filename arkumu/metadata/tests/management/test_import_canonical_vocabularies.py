import pathlib

import pytest
from django.core.management import call_command

from arkumu.metadata.models.resource import Resource, ResourceType
from arkumu.metadata.models.triples import Triple
from arkumu.metadata.services.canonical_graph_service import RDF_TYPE_URI


FIXTURE_VOCAB_DIR = (
    pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "canonical_vocabularies"
)

SKOS_ALT_LABEL_URI = "http://www.w3.org/2004/02/skos/core#altLabel"
SKOS_BROADER_URI = "http://www.w3.org/2004/02/skos/core#broader"
SYNONYMS_URI = "http://arkumu.org/data/properties/synonyme"
XSD_BOOLEAN_URI = "http://www.w3.org/2001/XMLSchema#boolean"


@pytest.fixture
def vocab_dir():
    return FIXTURE_VOCAB_DIR


@pytest.mark.django_db
def test_import_roles_creates_entities_and_updates_links(vocab_dir):
    role_uri = "http://arkumu.org/data/types/rolle/role-1"
    stale_synonym_literal = Resource.objects.create(
        resource_type=ResourceType.LITERAL,
        value="veraltete Rolle",
        language="de",
    )
    synonyms_predicate = Resource.objects.create(
        uri=SYNONYMS_URI,
        resource_type=ResourceType.PROPERTY,
    )
    existing_role = Resource.objects.create(
        uri=role_uri,
        resource_type=ResourceType.ENTITY,
        name="Alte Rolle",
        canonical_uri=role_uri,
    )
    Triple.objects.create(
        subject=existing_role,
        predicate=synonyms_predicate,
        object=stale_synonym_literal,
        source=None,
        is_derived=True,
    )

    call_command(
        "import_canonical_vocabularies",
        "--directory",
        str(vocab_dir),
        "--vocabulary",
        "roles",
    )

    role = Resource.objects.get(uri=role_uri)
    assert role.name == "1. Kameraassistenz"
    assert role.canonical_uri == role_uri

    assert Triple.objects.filter(
        subject=role,
        predicate__uri=RDF_TYPE_URI,
        object__uri="http://arkumu.org/data/types/rolle",
    ).exists()

    german_synonyms = {
        triple.object.value
        for triple in Triple.objects.filter(subject=role, predicate__uri=SYNONYMS_URI)
    }
    assert german_synonyms == {"1. Kameraassistentin", "1. Kameraassistent"}

    english_synonyms = {
        triple.object.value
        for triple in Triple.objects.filter(subject=role, predicate__uri=SKOS_ALT_LABEL_URI)
    }
    assert english_synonyms == {"camera operator", "focus puller"}

    assert not Triple.objects.filter(
        subject=role,
        predicate=synonyms_predicate,
        object=stale_synonym_literal,
    ).exists()

    successor_role = Resource.objects.get(uri="http://arkumu.org/data/types/rolle/role-2")
    parent_triple = Triple.objects.get(
        subject=successor_role,
        predicate__uri=SKOS_BROADER_URI,
    )
    assert parent_triple.object == role

    flag_triple = Triple.objects.get(
        subject=successor_role,
        predicate__uri="http://arkumu.org/data/properties/waehlt-ist-urheber-in-automatisch-aus",
    )
    assert flag_triple.object.value == "true"
    assert flag_triple.object.datatype == XSD_BOOLEAN_URI


@pytest.mark.django_db
def test_import_event_types_handles_identifiers_and_synonyms(vocab_dir):
    call_command(
        "import_canonical_vocabularies",
        "--directory",
        str(vocab_dir),
        "--vocabulary",
        "event_types",
    )

    event_type = Resource.objects.get(uri="http://arkumu.org/data/types/ereignistyp/event-type-2")

    assert event_type.name == "Konzert"

    identifier_values = {
        (triple.predicate.uri, triple.object.value or triple.object.uri)
        for triple in Triple.objects.filter(subject=event_type)
        if triple.predicate.uri
        in {
            "http://arkumu.org/data/properties/wikidata-id",
            "http://arkumu.org/data/properties/aat-id",
            "http://arkumu.org/data/properties/lido-terminologie-id",
        }
    }
    assert identifier_values == {
        ("http://arkumu.org/data/properties/wikidata-id", "Q132241"),
        ("http://arkumu.org/data/properties/aat-id", "300054731"),
        ("http://arkumu.org/data/properties/lido-terminologie-id", "lido00030"),
    }

    english_synonyms = {
        triple.object.value
        for triple in Triple.objects.filter(
            subject=event_type,
            predicate__uri=SKOS_ALT_LABEL_URI,
        )
    }
    assert english_synonyms == {"Live Performance"}


@pytest.mark.django_db
def test_import_information_storage_medium_types_creates_parent_and_pbcore_iri(vocab_dir):
    call_command(
        "import_canonical_vocabularies",
        "--directory",
        str(vocab_dir),
        "--vocabulary",
        "information_storage_medium_types",
    )

    base_medium = Resource.objects.get(
        uri="http://arkumu.org/data/types/informationstraegertyp/information-storage-medium-type-1"
    )
    child_medium = Resource.objects.get(
        uri="http://arkumu.org/data/types/informationstraegertyp/information-storage-medium-type-2"
    )

    hierarchy = Triple.objects.get(
        subject=child_medium,
        predicate__uri=SKOS_BROADER_URI,
    )
    assert hierarchy.object == base_medium

    pbcore_triple = Triple.objects.get(
        subject=base_medium,
        predicate__uri="http://arkumu.org/data/properties/pbcore-link",
    )
    assert pbcore_triple.object.resource_type == ResourceType.IRI
    assert pbcore_triple.object.uri.startswith("http://pbcore.org/pbcore-controlled-vocabularies/")

    breadcrumb_values = {
        (triple.predicate.uri, triple.object.value, triple.object.language)
        for triple in Triple.objects.filter(
            subject=child_medium,
            predicate__uri__in={
                "http://arkumu.org/data/properties/deutscher-name-des-informationstraegertyps-breadcrumb",
                "http://arkumu.org/data/properties/englischer-name-des-informationstraegertyps-breadcrumb",
            },
        )
    }
    assert breadcrumb_values == {
        (
            "http://arkumu.org/data/properties/deutscher-name-des-informationstraegertyps-breadcrumb",
            "Videokassette > VHS",
            "de",
        ),
        (
            "http://arkumu.org/data/properties/englischer-name-des-informationstraegertyps-breadcrumb",
            "Videocassette > VHS",
            "en",
        ),
    }


@pytest.mark.django_db
def test_import_project_categories_handles_filmportal_identifier(vocab_dir):
    call_command(
        "import_canonical_vocabularies",
        "--directory",
        str(vocab_dir),
        "--vocabulary",
        "project_categories",
    )

    category = Resource.objects.get(
        uri="http://arkumu.org/data/types/projektkategorie/project-category-1"
    )
    triple = Triple.objects.get(
        subject=category,
        predicate__uri="http://arkumu.org/data/properties/filmportal-kategorie-id",
    )
    assert triple.object.value == "fp-001"
