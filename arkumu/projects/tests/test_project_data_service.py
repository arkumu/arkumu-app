"""Tests for ProjectDataService."""

import uuid
from unittest.mock import MagicMock, patch

import pytest

from arkumu.projects.services.project_data_service import (
    ProjectDataService,
    get_project_data_service,
)
from arkumu.projects.adapters import (
    get_adapter,
    ProjectGraph,
    ProjectPropertiesData,
    EventData,
    ActorData,
    DigitalObjectData,
)
from arkumu.projects.adapters.fuk import FukAdapter
from arkumu.projects.adapters.hmt import HmtAdapter
from arkumu.projects.adapters.khm import KhmAdapter
from arkumu.projects.models import ProjectRecord, ProjectEvent, ProjectDigitalObject


class TestProjectDataServiceFactory:
    """Test factory function."""

    def test_get_project_data_service_returns_service(self):
        service = get_project_data_service("fuk")
        assert isinstance(service, ProjectDataService)
        assert service.org_code == "fuk"

    def test_get_project_data_service_with_different_orgs(self):
        for org_code in ["fuk", "hmt", "khm", "rsh", "det"]:
            service = get_project_data_service(org_code)
            assert service.org_code == org_code


class TestProjectDataServiceInit:
    """Test service initialization."""

    def test_init_with_fuk(self):
        service = ProjectDataService("fuk")
        assert service.org_code == "fuk"
        assert isinstance(service.adapter, FukAdapter)

    def test_init_with_hmt(self):
        service = ProjectDataService("hmt")
        assert service.org_code == "hmt"
        assert isinstance(service.adapter, HmtAdapter)

    def test_init_with_khm(self):
        service = ProjectDataService("khm")
        assert service.org_code == "khm"
        assert isinstance(service.adapter, KhmAdapter)

    def test_init_normalizes_case(self):
        service = ProjectDataService("FUK")
        assert service.org_code == "FUK"
        # Adapter should still work
        assert isinstance(service.adapter, FukAdapter)


class TestProjectDataServiceGetProjectGraph:
    """Test get_project_graph method."""

    def test_get_project_graph_delegates_to_adapter(self):
        service = ProjectDataService("fuk")
        mock_graph = MagicMock(spec=ProjectGraph)

        with patch.object(service.adapter, "get_project_graph", return_value=mock_graph):
            result = service.get_project_graph("test-id")
            service.adapter.get_project_graph.assert_called_once_with("test-id")
            assert result == mock_graph

    def test_get_project_graph_returns_none_for_missing(self):
        service = ProjectDataService("fuk")

        with patch.object(service.adapter, "get_project_graph", return_value=None):
            result = service.get_project_graph("nonexistent")
            assert result is None


class TestProjectDataServiceGetProjectRecord:
    """Test get_project_record method."""

    def test_get_project_record_returns_none_for_missing(self):
        service = ProjectDataService("fuk")

        with patch.object(service.adapter, "get_project_graph", return_value=None):
            result = service.get_project_record("nonexistent")
            assert result is None

    def test_get_project_record_builds_from_graph(self):
        service = ProjectDataService("fuk")

        # Create mock graph data
        mock_properties = ProjectPropertiesData(
            title="Test Project",
            subtitle="Subtitle",
            description="Description",
            image="http://example.com/image.jpg",
            institution_uri="http://example.com/institution",
            institution_label="Test Institution",
            category_uris=["http://example.com/cat1"],
            category_labels=["Category 1"],
        )
        mock_event = EventData(
            event_id="event-1",
            event_uri="http://example.com/event/1",
            name="Main Event",
            description="Event description",
            location="Location",
            start="2020-01-01",
            end="2020-12-31",
            event_type="performance",
            actors=[],
        )
        mock_actor = ActorData(
            actor_id="actor-1",
            actor_name="Test Actor",
            event_id="event-1",
            roles=["Director"],
            is_copyright_holder=True,
            is_neighbouring_rights_holder=False,
        )
        mock_digital_object = DigitalObjectData(
            object_id="do-1",
            object_uri="http://example.com/do/1",
            path="/path/to/file.jpg",
            file_name="file.jpg",
            content_type="image/jpeg",
            license_uri="http://example.com/license",
            license_label="CC BY",
            source_event_ids=["event-1"],
        )
        mock_graph = ProjectGraph(
            project_uri="http://example.com/project/1",
            properties=mock_properties,
            events=[mock_event],
            actors=[mock_actor],
            digital_objects=[mock_digital_object],
        )

        with patch.object(service.adapter, "get_project_graph", return_value=mock_graph):
            result = service.get_project_record("proj-1")

            assert result is not None
            assert isinstance(result, ProjectRecord)
            assert result.subject_id == "proj-1"
            assert result.uri == "http://example.com/project/1"
            assert result.title == "Test Project"
            assert result.subtitle == "Subtitle"
            assert result.description == "Description"
            assert result.image == "http://example.com/image.jpg"

    def test_get_project_record_includes_institution(self):
        service = ProjectDataService("fuk")

        mock_properties = ProjectPropertiesData(
            title="Test",
            institution_uri="http://example.com/inst",
            institution_label="FUK",
        )
        mock_graph = ProjectGraph(
            project_uri="http://example.com/project/1",
            properties=mock_properties,
            events=[],
            actors=[],
            digital_objects=[],
        )

        with patch.object(service.adapter, "get_project_graph", return_value=mock_graph):
            result = service.get_project_record("proj-1")

            assert result.institution is not None
            assert result.institution.label == "FUK"
            assert result.institution.uri == "http://example.com/inst"
            assert result.institution.code == "fuk"

    def test_get_project_record_includes_categories(self):
        service = ProjectDataService("fuk")

        mock_properties = ProjectPropertiesData(
            title="Test",
            category_uris=["http://example.com/cat1", "http://example.com/cat2"],
            category_labels=["Category 1", "Category 2"],
        )
        mock_graph = ProjectGraph(
            project_uri="http://example.com/project/1",
            properties=mock_properties,
            events=[],
            actors=[],
            digital_objects=[],
        )

        with patch.object(service.adapter, "get_project_graph", return_value=mock_graph):
            result = service.get_project_record("proj-1")

            assert len(result.categories) == 2
            assert result.categories[0].label == "Category 1"
            assert result.categories[0].uri == "http://example.com/cat1"


class TestProjectDataServiceGetProjectRecords:
    """Test get_project_records method for multiple projects."""

    def test_get_project_records_returns_list(self):
        service = ProjectDataService("fuk")

        mock_properties = ProjectPropertiesData(title="Test")
        mock_graph = ProjectGraph(
            project_uri="http://example.com/project/1",
            properties=mock_properties,
            events=[],
            actors=[],
            digital_objects=[],
        )

        with patch.object(service.adapter, "get_project_graph", return_value=mock_graph):
            result = service.get_project_records(["proj-1", "proj-2"])

            # Should return 2 records (same mock for both)
            assert len(result) == 2

    def test_get_project_records_filters_none(self):
        service = ProjectDataService("fuk")

        call_count = [0]

        def mock_get_graph(project_id):
            call_count[0] += 1
            if project_id == "exists":
                return ProjectGraph(
                    project_uri="http://example.com/exists",
                    properties=ProjectPropertiesData(title="Exists"),
                    events=[],
                    actors=[],
                    digital_objects=[],
                )
            return None

        with patch.object(service.adapter, "get_project_graph", side_effect=mock_get_graph):
            result = service.get_project_records(["exists", "missing", "also-missing"])

            assert len(result) == 1
            assert result[0].subject_id == "exists"


class TestProjectDataServiceYearRange:
    """Test year range derivation from events."""

    def test_derive_year_range_single_year(self):
        service = ProjectDataService("fuk")

        mock_event = EventData(
            event_id="e1",
            event_uri=None,
            name=None,
            description=None,
            location=None,
            start="2020-06-15",
            end="2020-08-20",
            actors=[],
        )
        mock_graph = ProjectGraph(
            project_uri="http://example.com/project/1",
            properties=ProjectPropertiesData(title="Test"),
            events=[mock_event],
            actors=[],
            digital_objects=[],
        )

        with patch.object(service.adapter, "get_project_graph", return_value=mock_graph):
            result = service.get_project_record("proj-1")
            assert result.year_range == "2020"

    def test_derive_year_range_multiple_years(self):
        service = ProjectDataService("fuk")

        mock_events = [
            EventData(event_id="e1", event_uri=None, name=None, description=None, location=None, start="2018-01-01", end="2018-12-31", actors=[]),
            EventData(event_id="e2", event_uri=None, name=None, description=None, location=None, start="2020-01-01", end="2021-06-30", actors=[]),
        ]
        mock_graph = ProjectGraph(
            project_uri="http://example.com/project/1",
            properties=ProjectPropertiesData(title="Test"),
            events=mock_events,
            actors=[],
            digital_objects=[],
        )

        with patch.object(service.adapter, "get_project_graph", return_value=mock_graph):
            result = service.get_project_record("proj-1")
            assert result.year_range == "2018-2021"

    def test_derive_year_range_no_events(self):
        service = ProjectDataService("fuk")

        mock_graph = ProjectGraph(
            project_uri="http://example.com/project/1",
            properties=ProjectPropertiesData(title="Test"),
            events=[],
            actors=[],
            digital_objects=[],
        )

        with patch.object(service.adapter, "get_project_graph", return_value=mock_graph):
            result = service.get_project_record("proj-1")
            assert result.year_range is None

    def test_derive_year_range_handles_invalid_dates(self):
        service = ProjectDataService("fuk")

        mock_event = EventData(
            event_id="e1",
            event_uri=None,
            name=None,
            description=None,
            location=None,
            start="not-a-date",
            end=None,
            actors=[],
        )
        mock_graph = ProjectGraph(
            project_uri="http://example.com/project/1",
            properties=ProjectPropertiesData(title="Test"),
            events=[mock_event],
            actors=[],
            digital_objects=[],
        )

        with patch.object(service.adapter, "get_project_graph", return_value=mock_graph):
            result = service.get_project_record("proj-1")
            assert result.year_range is None


class TestProjectDataServiceDigitalObjects:
    """Test digital object handling."""

    def test_digital_objects_include_license(self):
        service = ProjectDataService("fuk")

        mock_do = DigitalObjectData(
            object_id="do-1",
            object_uri="http://example.com/do/1",
            path="/files/image.jpg",
            file_name="image.jpg",
            content_type="image/jpeg",
            license_uri="http://creativecommons.org/licenses/by/4.0/",
            license_label="CC BY 4.0",
            source_event_ids=[],
        )
        mock_graph = ProjectGraph(
            project_uri="http://example.com/project/1",
            properties=ProjectPropertiesData(title="Test"),
            events=[],
            actors=[],
            digital_objects=[mock_do],
        )

        with patch.object(service.adapter, "get_project_graph", return_value=mock_graph):
            result = service.get_project_record("proj-1")

            assert len(result.digital_objects) == 1
            do = result.digital_objects[0]
            assert do.path == "/files/image.jpg"
            assert do.license is not None
            assert do.license.uri == "http://creativecommons.org/licenses/by/4.0/"

    def test_digital_objects_without_license(self):
        service = ProjectDataService("fuk")

        mock_do = DigitalObjectData(
            object_id="do-1",
            object_uri=None,
            path="/files/image.jpg",
            source_event_ids=[],
        )
        mock_graph = ProjectGraph(
            project_uri="http://example.com/project/1",
            properties=ProjectPropertiesData(title="Test"),
            events=[],
            actors=[],
            digital_objects=[mock_do],
        )

        with patch.object(service.adapter, "get_project_graph", return_value=mock_graph):
            result = service.get_project_record("proj-1")

            assert len(result.digital_objects) == 1
            do = result.digital_objects[0]
            assert do.license is None


@pytest.mark.django_db
class TestProjectDataServiceIntegration:
    """Integration tests with database."""

    def test_get_project_record_with_invalid_uuid_returns_none(self):
        service = ProjectDataService("fuk")
        result = service.get_project_record("not-a-uuid")
        assert result is None

    def test_get_project_record_with_nonexistent_project_returns_none(self):
        service = ProjectDataService("fuk")
        result = service.get_project_record(str(uuid.uuid4()))
        assert result is None

    def test_get_project_graph_with_invalid_uuid_returns_none(self):
        service = ProjectDataService("fuk")
        result = service.get_project_graph("not-a-uuid")
        assert result is None

    def test_get_project_records_with_empty_list(self):
        service = ProjectDataService("fuk")
        result = service.get_project_records([])
        assert result == []
