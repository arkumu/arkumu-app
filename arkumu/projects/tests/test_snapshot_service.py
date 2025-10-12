from collections import defaultdict
from datetime import datetime, timezone
from types import SimpleNamespace

from arkumu.catalog.services.schema_manifest_service import (
    CardProperty,
    CardSchema,
    CardSection,
    CanonicalPropertyBinding,
)
from arkumu.catalog.services.project_views import CardURIs, ProjectURIs
from arkumu.metadata.models.resource import ResourceType
from arkumu.projects import ProjectDigitalObject
from arkumu.projects.services.snapshot_service import ProjectSnapshotService


def make_schema(bindings_per_prop, fk_relationships=None) -> CardSchema:
    fk_relationships = fk_relationships or []
    project_section = CardSection(
        label="project",
        canonical_class_uri=CardURIs.PROJECT_TYPE,
        properties={
            name: CardProperty(
                name=name,
                canonical_uri=canonical,
                bindings=[
                    CanonicalPropertyBinding(
                        canonical_uri=canonical,
                        dataset=dataset,
                        column=column,
                    )
                    for dataset, column in binding_pairs
                ],
            )
            for name, (canonical, binding_pairs) in bindings_per_prop.items()
        },
        fk_relationships=list(fk_relationships),
    )
    return CardSchema(sections={"project": project_section})


def test_combine_card_schemas_merges_unique_bindings():
    schema_one = make_schema(
        {
            "title": (
                CardURIs.TITLE,
                [("dataset_a", "title")],
            ),
        },
        fk_relationships=[{"source_property": "event", "target_property": "foo"}],
    )

    schema_two = make_schema(
        {
            "title": (
                CardURIs.TITLE,
                [("dataset_b", "title_col"), ("dataset_b", "title_col")],
            ),
        },
        fk_relationships=[{"source_property": "event", "target_property": "foo"}],
    )

    combined = ProjectSnapshotService._combine_card_schemas([schema_one, schema_two])

    project_section = combined.sections["project"]
    title_bindings = project_section.properties["title"].bindings

    assert {b.dataset for b in title_bindings} == {"dataset_a", "dataset_b"}
    assert len(project_section.fk_relationships) == 1


class DummyTripleService:
    def get_project_description(self, *_, **__):
        return None

    def get_alternative_titles(self, *_, **__):
        return []

    def get_catchphrases(self, *_, **__):
        return []

    def get_project_type(self, *_, **__):
        return None

    def get_event_data(self, *_, **__):
        return {"event_ids": [], "event_details": {}}

    def get_detailed_event_data(self, *_, **__):
        return []

    def get_actor_relationships(self, *_, **__):
        return []

    def get_related_entities(self, *_, **__):
        return []

    def get_literal_map(self, *_, **__):
        return {}


def minimal_card_schema() -> CardSchema:
    return CardSchema(
        sections={
            "project": CardSection(
                label="project",
                canonical_class_uri=CardURIs.PROJECT_TYPE,
                properties={
                    "title": CardProperty(name="title", canonical_uri=CardURIs.TITLE, bindings=[]),
                    "subtitle": CardProperty(name="subtitle", canonical_uri=CardURIs.SUBTITLE, bindings=[]),
                    "image": CardProperty(name="image", canonical_uri=CardURIs.IMAGE, bindings=[]),
                    "institution": CardProperty(name="institution", canonical_uri=CardURIs.INSTITUTION, bindings=[]),
                    "category": CardProperty(name="category", canonical_uri=CardURIs.CATEGORY, bindings=[]),
                },
                fk_relationships=[
                    {
                        "source_property": ProjectURIs.DIGITAL_OBJECT_LINK,
                        "target_property": ProjectURIs.DIGITAL_OBJECT_PATH,
                    }
                ],
            ),
            "digital_object": CardSection(
                label="digital_object",
                canonical_class_uri=ProjectURIs.DIGITAL_OBJECT_TYPE,
                properties={
                    "path": CardProperty(
                        name="path",
                        canonical_uri=ProjectURIs.DIGITAL_OBJECT_PATH,
                        bindings=[],
                    ),
                    "Pruefsumme_SHA256": CardProperty(
                        name="Pruefsumme_SHA256",
                        canonical_uri='http://arkumu.org/data/khm/properties/pruefsumme-sha256',
                        bindings=[],
                    ),
                },
                fk_relationships=[],
            ),
            "institution": CardSection(
                label="institution",
                canonical_class_uri=CardURIs.INSTITUTION_TYPE,
                properties={
                    "german_name": CardProperty(
                        name="german_name",
                        canonical_uri=CardURIs.INSTITUTION_GERMAN_NAME,
                        bindings=[],
                    )
                },
                fk_relationships=[],
            ),
            "project_category": CardSection(
                label="project_category",
                canonical_class_uri=CardURIs.CATEGORY_TYPE,
                properties={
                    "german_name": CardProperty(
                        name="german_name",
                        canonical_uri=CardURIs.CATEGORY_GERMAN_NAME,
                        bindings=[],
                    ),
                    "synonyms": CardProperty(
                        name="synonyms",
                        canonical_uri=CardURIs.CATEGORY_SYNONYMS,
                        bindings=[],
                    ),
                    "wikidata_id": CardProperty(
                        name="wikidata_id",
                        canonical_uri=CardURIs.CATEGORY_WIKIDATA_ID,
                        bindings=[],
                    ),
                },
                fk_relationships=[],
            ),
            "event": CardSection(
                label="event",
                canonical_class_uri=CardURIs.EVENT_TYPE,
                properties={
                    "start": CardProperty(name="start", canonical_uri=CardURIs.EVENT_START, bindings=[]),
                    "end": CardProperty(name="end", canonical_uri=CardURIs.EVENT_END, bindings=[]),
                },
                fk_relationships=[],
            ),
            "actor_event": CardSection(
                label="actor_event",
                canonical_class_uri=CardURIs.ACTOR_EVENT_TYPE,
                properties={
                    "actor_link": CardProperty(name="actor_link", canonical_uri=CardURIs.ACTOR_IN_EVENT, bindings=[]),
                    "role_link": CardProperty(name="role_link", canonical_uri=CardURIs.ACTOR_ROLE, bindings=[]),
                },
                fk_relationships=[],
            ),
            "actor": CardSection(
                label="actor",
                canonical_class_uri=CardURIs.ACTOR_TYPE,
                properties={
                    "name": CardProperty(name="name", canonical_uri=CardURIs.ACTOR_GERMAN_NAME, bindings=[]),
                },
                fk_relationships=[],
            ),
            "role": CardSection(
                label="role",
                canonical_class_uri=CardURIs.ROLE_TYPE,
                properties={
                    "name": CardProperty(name="name", canonical_uri=CardURIs.ROLE_GERMAN_NAME, bindings=[]),
                },
                fk_relationships=[],
            ),
            "digital_object": CardSection(
                label="digital_object",
                canonical_class_uri=CardURIs.DIGITAL_OBJECT_TYPE,
                properties={
                    "path": CardProperty(name="path", canonical_uri=CardURIs.DIGITAL_OBJECT_PATH, bindings=[]),
                },
                fk_relationships=[],
            ),
        }
    )


def test_build_project_record_collects_all_institution_codes():
    service = ProjectSnapshotService(relationship_org_code='khm')
    triple_service = DummyTripleService()
    card_schema = minimal_card_schema()

    subject_id = "proj-1"
    nodes = {
        subject_id: {"uri": "http://example.org/project/proj-1"},
        "inst-1": {"uri": "http://example.org/inst/fuk", "organization": "FUK"},
        "inst-2": {"uri": "http://example.org/inst/rsh", "organization": "RSH"},
        "cat-1": {"uri": "http://example.org/cat/performing-arts"},
    }

    edges_by_subject = {
        subject_id: [
            {"predicate_canonical": CardURIs.TITLE, "object_value": "Market Project"},
            {"predicate_canonical": CardURIs.SUBTITLE, "object_value": "Subtitle"},
            {"predicate_canonical": CardURIs.INSTITUTION, "object_id": "inst-1"},
            {"predicate_canonical": CardURIs.INSTITUTION, "object_id": "inst-2"},
            {"predicate_canonical": CardURIs.CATEGORY, "object_id": "cat-1"},
            {"predicate_canonical": CardURIs.CATEGORY, "object_id": "cat-1"},
        ],
        "inst-1": [
            {
                "predicate_canonical": CardURIs.INSTITUTION_GERMAN_NAME,
                "object_value": "FUK University",
            }
        ],
        "inst-2": [
            {
                "predicate_canonical": CardURIs.INSTITUTION_GERMAN_NAME,
                "object_value": "RSH Academy",
            }
        ],
        "cat-1": [
            {
                "predicate_canonical": CardURIs.CATEGORY_GERMAN_NAME,
                "object_value": "Performing Arts",
            },
            {
                "predicate_canonical": CardURIs.CATEGORY_WIKIDATA_ID,
                "object_value": "Q123",
            }
        ],
    }

    storage_files_map = defaultdict(list)

    record = service._build_project_record(
        subject_id=subject_id,
        nodes=nodes,
        edges_by_subject=edges_by_subject,
        card_schema=card_schema,
        triple_service=triple_service,
        storage_files_map=storage_files_map,
    )

    assert record is not None
    assert record.institution.code == "fuk"
    assert record.institution_codes == ["fuk", "rsh"]
    assert record.category_slugs == ["performing-arts"]
    assert [category.label for category in record.categories] == ["Q123"]


def test_build_digital_object_license_resolves_related_rights_statement():
    service = ProjectSnapshotService()

    edges_for_digital = [
        {
            "predicate_canonical": service.DIGITAL_OBJECT_LICENSE_LINK_URI,
            "object_id": "license-1",
        }
    ]

    nodes = {
        "license-1": {"uri": "http://example.org/license/1"},
        "rights-1": {"name": "Rights Statement Text"},
    }

    edges_by_subject = {
        "license-1": [
            {
                "predicate_canonical": service.DIGITAL_OBJECT_LICENSE_URI_PROPERTIES[0],
                "object_value": "http://example.org/license/1",
            },
            {
                "predicate_canonical": service.DIGITAL_OBJECT_LICENSE_RIGHTS_STATEMENT_PROPERTIES[0],
                "object_id": "rights-1",
            },
            {
                "predicate_canonical": service.DIGITAL_OBJECT_LICENSE_IDENTIFIER_PROPERTIES[0],
                "object_value": "license-1",
            },
        ],
        "rights-1": [
            {
                "predicate_canonical": service.DIGITAL_OBJECT_LICENSE_LABEL_DE_PROPERTIES[0],
                "object_value": "Rights Statement Text",
            }
        ],
    }

    license_info = service._build_digital_object_license(
        edges_for_digital,
        nodes,
        edges_by_subject,
    )

    assert license_info is not None
    assert license_info.rights_statement == "Rights Statement Text"
    assert license_info.identifier == "license-1"


def test_build_digital_object_license_strips_numeric_labels_for_fuk():
    service = ProjectSnapshotService()

    edges_for_digital = [
        {
            "predicate_canonical": service.DIGITAL_OBJECT_LICENSE_LINK_URI,
            "object_id": "license-2",
        }
    ]

    nodes = {
        "license-2": {"uri": "http://arkumu.org/data/fuk/entities/digitales-objekt-lizenz/2"},
    }

    edges_by_subject = {
        "license-2": [
            {
                "predicate_canonical": service.DIGITAL_OBJECT_LICENSE_LABEL_DE_PROPERTIES[0],
                "object_value": "2",
            },
            {
                "predicate_canonical": service.DIGITAL_OBJECT_LICENSE_RIGHTS_STATEMENT_PROPERTIES[0],
                "object_value": "2",
            },
            {
                "predicate_canonical": service.DIGITAL_OBJECT_LICENSE_IDENTIFIER_PROPERTIES[0],
                "object_value": "2",
            },
        ]
    }

    license_info = service._build_digital_object_license(
        edges_for_digital,
        nodes,
        edges_by_subject,
    )

    assert license_info is not None
    assert license_info.uri == "http://arkumu.org/data/fuk/entities/digitales-objekt-lizenz/2"
    assert license_info.identifier == "2"
    assert license_info.label_de is None
    assert license_info.label_en is None
    assert license_info.rights_statement is None


def test_build_project_record_merges_event_storage_files():
    service = ProjectSnapshotService(relationship_org_code='khm')
    card_schema = minimal_card_schema()

    subject_id = "proj-1"
    event_id = "event-1"

    nodes = {
        subject_id: {"uri": "http://example.org/project/proj-1"},
        event_id: {"uri": "http://example.org/event/event-1"},
    }

    edges_by_subject = {
        subject_id: [
            {"predicate_canonical": CardURIs.TITLE, "object_value": "Event Project"},
        ],
    }

    class EventTripleService(DummyTripleService):
        def get_detailed_event_data(self, *_, **__):
            return [
                {
                    "id": event_id,
                    "name": "Event Name",
                    "description": None,
                    "location": None,
                    "location_id": None,
                    "type": None,
                    "start": None,
                    "end": None,
                }
            ]

    triple_service = EventTripleService()

    event_file = SimpleNamespace(
        s3_key="events/file.mov",
        original_path="/events/file.mov",
        file_name="file.mov",
        content_type="video/mp4",
        file_size_bytes=1234,
        sha256_checksum="checksum",
        s3_url="https://example.org/events/file.mov",
        status="available",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )

    storage_files_map = defaultdict(list)
    storage_files_map[event_id].append(event_file)

    record = service._build_project_record(
        subject_id=subject_id,
        nodes=nodes,
        edges_by_subject=edges_by_subject,
        card_schema=card_schema,
        triple_service=triple_service,
        storage_files_map=storage_files_map,
    )

    assert record is not None
    assert record.events and record.events[0].id == event_id
    assert record.digital_objects
    digital_object = record.digital_objects[0]
    assert digital_object.storage_key == "events/file.mov"
    assert digital_object.file_name == "file.mov"
    assert digital_object.checksum == "checksum"
    assert digital_object.checksum_algorithm is None
    assert digital_object.checksum_provenance == "s3"


def test_build_project_record_uses_rosetta_checksum():
    class RosettaTripleService(DummyTripleService):
        def get_related_entities(self, *_, **__):
            return [
                {
                    'id': 'obj-1',
                    'uri': 'http://arkumu.org/data/khm/entities/digital-object/1',
                    'resource_type': ResourceType.ENTITY,
                }
            ]

        def get_literal_map(self, subject_ids, predicate_uri, *, organization_code=None):
            if predicate_uri == ProjectURIs.DIGITAL_OBJECT_PATH:
                return {'obj-1': '/rosetta/khm/test/input/object_master.tif'}
            if predicate_uri == 'http://arkumu.org/data/khm/properties/pruefsumme-sha256':
                return {'obj-1': 'a' * 64}
            return {}

    service = ProjectSnapshotService(relationship_org_code='khm')
    card_schema = minimal_card_schema()
    triple_service = RosettaTripleService()

    edges = defaultdict(list)
    edges['proj-1'].append({"predicate_canonical": CardURIs.TITLE, "object_value": "Rosetta Project"})

    record = service._build_project_record(
        subject_id='proj-1',
        nodes={'proj-1': {'uri': 'http://example.org/project/1'}},
        edges_by_subject=edges,
        card_schema=card_schema,
        triple_service=triple_service,
        storage_files_map=defaultdict(list),
    )

    assert record is not None
    assert record.digital_objects
    obj = record.digital_objects[0]
    assert obj.checksum == 'a' * 64
    assert obj.checksum_algorithm == 'sha256'
    assert obj.checksum_provenance == 'metadata'


def test_build_project_record_infers_checksum_org_from_uri():
    class ChecksumTripleService(DummyTripleService):
        def get_related_entities(self, subject_id, predicate_uri, *, organization_code=None):
            if predicate_uri == ProjectURIs.DIGITAL_OBJECT_LINK:
                return [
                    {
                        'id': 'obj-1',
                        'uri': 'http://arkumu.org/data/khm/entities/digital-object/1',
                        'canonical_uri': None,
                        'name': 'digital-object',
                        'value': None,
                        'resource_type': ResourceType.ENTITY,
                    }
                ]
            return []

        def get_literal_map(self, subject_ids, predicate_uri, *, organization_code=None):
            if predicate_uri == ProjectURIs.DIGITAL_OBJECT_PATH:
                return {'obj-1': '/rosetta/khm/test/input/object_master.tif'}
            if predicate_uri == ProjectSnapshotService.ROSETTA_CHECKSUM_PREDICATES['khm']:
                return {'obj-1': 'b' * 64}
            return {}

    service = ProjectSnapshotService()
    card_schema = minimal_card_schema()
    triple_service = ChecksumTripleService()

    subject_id = 'proj-1'
    institution_id = 'inst-1'

    nodes = {
        subject_id: {'uri': 'http://arkumu.org/data/khm/entities/00-projekte/200'},
        institution_id: {
            'uri': 'http://arkumu.org/data/literals/aa5f824e167db5e1',
            'name': 'KHM',
        },
    }

    edges_by_subject = defaultdict(list)
    edges_by_subject[subject_id].append({
        'predicate_canonical': CardURIs.TITLE,
        'object_value': 'Rosetta Project',
    })
    edges_by_subject[subject_id].append({
        'predicate_canonical': CardURIs.INSTITUTION,
        'object_id': institution_id,
    })
    edges_by_subject[institution_id].append({
        'predicate_canonical': CardURIs.INSTITUTION_GERMAN_NAME,
        'object_value': 'Kunsthochschule für Medien Köln',
    })

    record = service._build_project_record(
        subject_id=subject_id,
        nodes=nodes,
        edges_by_subject=edges_by_subject,
        card_schema=card_schema,
        triple_service=triple_service,
        storage_files_map=defaultdict(list),
    )

    assert record is not None
    assert record.digital_objects
    obj = record.digital_objects[0]
    assert obj.checksum == 'b' * 64
    assert obj.checksum_algorithm == 'sha256'
    assert obj.checksum_provenance == 'metadata'
