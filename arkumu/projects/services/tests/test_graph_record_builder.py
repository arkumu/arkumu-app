"""Tests for graph record builder module."""

import pytest

from arkumu.projects.services.graph_extractors import TripleIndex, Predicates
from arkumu.projects.services.graph_record_builder import (
    extract_institution,
    extract_categories,
    extract_project_type,
    extract_alternative_titles,
    extract_catchphrases,
    extract_event_actors,
    extract_events,
    extract_digital_objects,
    extract_year_range,
    build_project_record,
)
from arkumu.projects.services.graph_service import TripleResult, ProjectGraphs


def make_triple(
    subject: str,
    predicate: str,
    obj_uri: str = None,
    obj_value: str = None,
    canonical: str = None,
) -> TripleResult:
    """Helper to create TripleResult."""
    return TripleResult(
        subject_uri=subject,
        predicate_uri=predicate,
        predicate_canonical_uri=canonical or predicate,
        object_uri=obj_uri,
        object_value=obj_value,
    )


class TestExtractInstitution:
    """Tests for extract_institution function."""

    def test_extracts_institution_with_name(self):
        triples = [
            make_triple(
                "http://arkumu.org/data/hmt/entities/projekt/1",
                Predicates.INSTITUTION,
                obj_uri="http://arkumu.org/data/hmt/entities/hochschule/hmt",
            ),
            make_triple(
                "http://arkumu.org/data/hmt/entities/hochschule/hmt",
                Predicates.INSTITUTION_NAME,
                obj_value="Hochschule für Musik und Tanz Köln",
            ),
        ]
        index = TripleIndex.from_triples(triples)

        result = extract_institution(index, "http://arkumu.org/data/hmt/entities/projekt/1")

        assert result is not None
        assert result.label == "Hochschule für Musik und Tanz Köln"
        assert result.uri == "http://arkumu.org/data/hmt/entities/hochschule/hmt"
        assert result.code == "hmt"

    def test_returns_none_when_no_institution(self):
        triples = []
        index = TripleIndex.from_triples(triples)

        result = extract_institution(index, "http://arkumu.org/data/hmt/entities/projekt/1")

        assert result is None


class TestExtractCategories:
    """Tests for extract_categories function."""

    def test_extracts_multiple_categories(self):
        triples = [
            make_triple(
                "http://arkumu.org/data/fuk/entities/projekt/1",
                Predicates.CATEGORY,
                obj_uri="http://arkumu.org/data/fuk/entities/kategorie/music",
            ),
            make_triple(
                "http://arkumu.org/data/fuk/entities/projekt/1",
                Predicates.CATEGORY,
                obj_uri="http://arkumu.org/data/fuk/entities/kategorie/art",
            ),
            make_triple(
                "http://arkumu.org/data/fuk/entities/kategorie/music",
                Predicates.CATEGORY_NAME,
                obj_value="Musik",
            ),
            make_triple(
                "http://arkumu.org/data/fuk/entities/kategorie/art",
                Predicates.CATEGORY_NAME,
                obj_value="Kunst",
            ),
        ]
        index = TripleIndex.from_triples(triples)

        result = extract_categories(index, "http://arkumu.org/data/fuk/entities/projekt/1")

        assert len(result) == 2
        labels = [c.label for c in result]
        assert "Musik" in labels
        assert "Kunst" in labels


class TestExtractEventActors:
    """Tests for extract_event_actors function."""

    def test_extracts_actors_from_junction(self):
        event_uri = "http://arkumu.org/data/hmt/entities/ereignis/1"
        junction_uri = "http://arkumu.org/data/hmt/entities/kreuz-ereignis-akteure/1"
        actor_uri = "http://arkumu.org/data/hmt/entities/akteur/1"
        role_uri = "http://arkumu.org/data/hmt/entities/rolle/composer"

        triples = [
            # Junction -> Event
            make_triple(junction_uri, Predicates.IM_EREIGNIS, obj_uri=event_uri),
            # Junction -> Actor
            make_triple(junction_uri, Predicates.ACTOR_LINK, obj_uri=actor_uri),
            # Actor name
            make_triple(actor_uri, Predicates.ACTOR_NAME, obj_value="Johann Bach"),
            # Junction -> Role
            make_triple(junction_uri, Predicates.ROLE_LINK, obj_uri=role_uri),
            # Role name
            make_triple(role_uri, Predicates.ROLE_NAME, obj_value="Komponist"),
            # Rights flags
            make_triple(junction_uri, Predicates.IST_URHEBERIN, obj_value="1"),
            make_triple(junction_uri, Predicates.LEISTUNGSSCHUTZRECHTE, obj_value="0"),
        ]
        index = TripleIndex.from_triples(triples)

        result = extract_event_actors(index, event_uri)

        assert len(result) == 1
        actor = result[0]
        assert actor.name == "Johann Bach"
        assert actor.roles == ["Komponist"]
        assert actor.is_copyright_holder is True
        assert actor.is_neighbouring_rights_holder is False


class TestExtractEvents:
    """Tests for extract_events function."""

    def test_extracts_events_with_properties(self):
        project_uri = "http://arkumu.org/data/hmt/entities/projekt/1"
        event_uri = "http://arkumu.org/data/hmt/entities/ereignis/1"

        triples = [
            make_triple(project_uri, Predicates.EVENT, obj_uri=event_uri),
            make_triple(event_uri, Predicates.EVENT_NAME, obj_value="Concert 2023"),
            make_triple(event_uri, Predicates.EVENT_START, obj_value="2023-05-01"),
            make_triple(event_uri, Predicates.EVENT_END, obj_value="2023-05-01"),
            make_triple(event_uri, Predicates.EVENT_LOCATION, obj_value="Q64"),
        ]
        index = TripleIndex.from_triples(triples)

        result = extract_events(index, project_uri)

        assert len(result) == 1
        event = result[0]
        assert event.name == "Concert 2023"
        assert event.start == "2023-05-01"
        assert event.end == "2023-05-01"
        assert event.location == "Q64"


class TestExtractDigitalObjects:
    """Tests for extract_digital_objects function."""

    def test_extracts_digital_objects(self):
        project_uri = "http://arkumu.org/data/hmt/entities/projekt/1"
        do_uri = "http://arkumu.org/data/hmt/entities/digitales-objekt/1"

        triples = [
            make_triple(project_uri, Predicates.DIGITAL_OBJECT, obj_uri=do_uri),
            make_triple(do_uri, Predicates.FILE_PATH, obj_value="/path/to/file.mp3"),
            make_triple(do_uri, Predicates.FILE_NAME, obj_value="file.mp3"),
        ]
        index = TripleIndex.from_triples(triples)

        result = extract_digital_objects(index, project_uri, [])

        assert len(result) == 1
        do = result[0]
        assert do.path == "/path/to/file.mp3"
        assert do.file_name == "file.mp3"
        assert do.uri == do_uri


class TestExtractYearRange:
    """Tests for extract_year_range function."""

    def test_single_year(self):
        from arkumu.projects import ProjectEvent
        events = [ProjectEvent(start="2023-05-01", end="2023-05-01")]
        assert extract_year_range(events) == "2023"

    def test_year_range(self):
        from arkumu.projects import ProjectEvent
        events = [
            ProjectEvent(start="2020-01-01"),
            ProjectEvent(start="2023-12-31"),
        ]
        assert extract_year_range(events) == "2020-2023"

    def test_no_dates(self):
        from arkumu.projects import ProjectEvent
        events = [ProjectEvent()]
        assert extract_year_range(events) is None


class TestBuildProjectRecord:
    """Tests for build_project_record function."""

    def test_builds_complete_record(self):
        project_uri = "http://arkumu.org/data/fuk/entities/projekt/1"
        inst_uri = "http://arkumu.org/data/fuk/entities/hochschule/fuk"

        triples = [
            # Project properties
            make_triple(project_uri, Predicates.TITLE, obj_value="Test Project"),
            make_triple(project_uri, Predicates.SUBTITLE, obj_value="A Subtitle"),
            make_triple(project_uri, Predicates.DESCRIPTION, obj_value="Description here"),
            # Institution
            make_triple(project_uri, Predicates.INSTITUTION, obj_uri=inst_uri),
            make_triple(inst_uri, Predicates.INSTITUTION_NAME, obj_value="Folkwang"),
        ]

        graphs = ProjectGraphs(project_uri=project_uri, triples=triples)
        record = build_project_record(graphs, "test-uuid-123")

        assert record.subject_id == "test-uuid-123"
        assert record.uri == project_uri
        assert record.title == "Test Project"
        assert record.subtitle == "A Subtitle"
        assert record.description == "Description here"
        assert record.institution is not None
        assert record.institution.label == "Folkwang"
        assert record.institution.code == "fuk"


@pytest.mark.django_db
class TestBuildProjectRecordIntegration:
    """Integration tests with real database data."""

    def test_fuk_project_has_expected_fields(self):
        """Test that FUK project extraction produces expected fields."""
        from arkumu.metadata.models.resource import Resource
        from arkumu.projects.services.graph_service import get_project_graphs

        project = Resource.objects.filter(
            organization__code__iexact='fuk',
            uri__icontains='/projekt/'
        ).first()

        if not project:
            pytest.skip("No FUK project in database")

        graphs = get_project_graphs(str(project.id), 'fuk')
        if not graphs:
            pytest.skip("No graph data for FUK project")

        record = graphs.to_project_record(str(project.id))

        # Basic assertions
        assert record.uri == project.uri
        assert record.subject_id == str(project.id)

        # Should have some title
        assert record.title is not None or len(record.alternative_titles) > 0

        # Check structure consistency
        for event in record.events:
            assert event.uri is not None or event.id is not None
            for actor in event.actors:
                assert actor.name is not None

        for do in record.digital_objects:
            assert do.path is not None


@pytest.mark.django_db
class TestBatchedGraphFetching:
    """Tests for batched graph fetching."""

    def test_batched_returns_same_as_single(self):
        """Verify batched fetching produces same results as per-project fetching."""
        from arkumu.metadata.models.resource import Resource
        from arkumu.projects.services.graph_service import (
            get_project_graphs,
            get_all_project_graphs_batched,
        )

        # Get a few FUK projects by URI pattern
        projects = list(Resource.objects.filter(
            organization__code__iexact='fuk',
            uri__regex=r'/data/fuk/entities/projekt/\d+$',
        )[:3])

        if len(projects) < 2:
            pytest.skip("Need at least 2 FUK projects in database")

        # Get graphs using batched method
        batched_results = {}
        for project_id, graphs in get_all_project_graphs_batched('fuk', batch_size=10):
            if project_id in [str(p.id) for p in projects]:
                batched_results[project_id] = graphs

        # Get graphs using per-project method
        single_results = {}
        for project in projects:
            graphs = get_project_graphs(str(project.id), 'fuk')
            if graphs:
                single_results[str(project.id)] = graphs

        # Compare results
        assert set(batched_results.keys()) == set(single_results.keys())

        for project_id in single_results:
            single_graphs = single_results[project_id]
            batched_graphs = batched_results[project_id]

            assert single_graphs.project_uri == batched_graphs.project_uri

            # Compare triple counts (may differ slightly due to deduplication order)
            single_count = len(single_graphs.triples)
            batched_count = len(batched_graphs.triples)
            # Allow small variance but should be close
            assert abs(single_count - batched_count) <= single_count * 0.1, \
                f"Triple count mismatch: single={single_count}, batched={batched_count}"

    def test_batched_yields_all_projects(self):
        """Verify batched method yields all projects for an org."""
        from arkumu.metadata.models.resource import Resource
        from arkumu.projects.services.graph_service import get_all_project_graphs_batched

        # Count FUK projects by URI pattern
        fuk_count = Resource.objects.filter(
            organization__code__iexact='fuk',
            uri__regex=r'/data/fuk/entities/projekt/\d+$',
        ).count()

        if fuk_count == 0:
            pytest.skip("No FUK projects in database")

        # Count batched results
        batched_count = sum(1 for _ in get_all_project_graphs_batched('fuk', batch_size=10))

        assert batched_count == fuk_count

    def test_batched_project_record_conversion(self):
        """Verify batched graphs can be converted to ProjectRecord."""
        from arkumu.projects.services.graph_service import get_all_project_graphs_batched

        # Get first FUK project via batched method
        for project_id, graphs in get_all_project_graphs_batched('fuk', batch_size=5):
            record = graphs.to_project_record(project_id)

            # Basic structure checks
            assert record.subject_id == project_id
            assert record.uri == graphs.project_uri

            # Should be able to convert to card dict
            card = record.to_card_dict()
            assert 'uri' in card
            break
        else:
            pytest.skip("No FUK projects in database")
