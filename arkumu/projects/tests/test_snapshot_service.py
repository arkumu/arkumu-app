from arkumu.catalog.services.schema_manifest_service import (
    CardProperty,
    CardSchema,
    CardSection,
    CanonicalPropertyBinding,
)
from arkumu.catalog.services.project_views import CardURIs
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

    def get_digital_object_paths(self, *_, **__):
        return []


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
    service = ProjectSnapshotService()
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

    record = service._build_project_record(
        subject_id=subject_id,
        nodes=nodes,
        edges_by_subject=edges_by_subject,
        card_schema=card_schema,
        triple_service=triple_service,
        storage_files=[],
    )

    assert record is not None
    assert record.institution.code == "fuk"
    assert record.institution_codes == ["fuk", "rsh"]
    assert record.category_slugs == ["performing-arts"]
    assert [category.label for category in record.categories] == ["Q123"]
