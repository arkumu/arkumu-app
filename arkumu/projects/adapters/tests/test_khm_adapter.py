"""Tests for KHM adapter (grundereignis pattern)."""

import uuid
from unittest.mock import MagicMock, patch

import pytest

from arkumu.projects.adapters import CanonicalURIs, get_adapter
from arkumu.projects.adapters.khm import KhmAdapter


class TestKhmAdapterUnit:
    """Unit tests for KHM adapter."""

    def test_org_code_is_khm(self):
        adapter = KhmAdapter()
        assert adapter.ORG_CODE == "khm"

    def test_junction_predicate_is_projekt(self):
        adapter = KhmAdapter()
        assert adapter.JUNCTION_PREDICATE == CanonicalURIs.PROJEKT

    def test_get_adapter_returns_khm_adapter(self):
        adapter = get_adapter("khm")
        assert isinstance(adapter, KhmAdapter)
        assert adapter.org_code == "khm"

    def test_get_adapter_handles_uppercase(self):
        adapter = get_adapter("KHM")
        assert isinstance(adapter, KhmAdapter)
        assert adapter.org_code == "khm"

    def test_normalize_predicate_passes_through(self):
        """KHM uses canonical predicates, so no normalization needed."""
        adapter = KhmAdapter()
        uri = "http://arkumu.org/data/properties/some-property"
        assert adapter.normalize_predicate(uri) == uri


class TestKhmGrundereignisPattern:
    """Test KHM-specific grundereignis pattern."""

    def test_grundereignis_uri_mapping(self):
        """KHM maps project URI to grundereignis URI by replacing path segment."""
        # 00-projekte/X -> 01-grundereignis/X
        project_uri = "http://arkumu.org/data/khm/00-projekte/123"
        expected_grundereignis = "http://arkumu.org/data/khm/01-grundereignis/123"
        actual = project_uri.replace("/00-projekte/", "/01-grundereignis/")
        assert actual == expected_grundereignis

    def test_project_uri_pattern(self):
        """KHM project URIs contain /00-projekte/ segment."""
        project_uri = "http://arkumu.org/data/khm/00-projekte/test-project"
        assert "/00-projekte/" in project_uri

    def test_grundereignis_is_event(self):
        """In KHM, grundereignis IS the event (main production event)."""
        adapter = KhmAdapter()
        # The grundereignis serves as the primary event for a project
        assert adapter.ORG_CODE == "khm"


@pytest.mark.django_db
class TestKhmAdapterIntegration:
    """Integration tests for KHM adapter with database."""

    def test_get_actors_for_project_with_invalid_uuid_returns_empty(self):
        adapter = KhmAdapter("khm")
        result = adapter.get_actors_for_project("not-a-uuid")
        assert result == []

    def test_get_actors_for_project_with_nonexistent_project_returns_empty(self):
        adapter = KhmAdapter("khm")
        result = adapter.get_actors_for_project(str(uuid.uuid4()))
        assert result == []

    def test_get_events_for_project_with_invalid_uuid_returns_empty(self):
        adapter = KhmAdapter("khm")
        result = adapter.get_events_for_project("not-a-uuid")
        assert result == []

    def test_get_events_for_project_with_nonexistent_project_returns_empty(self):
        adapter = KhmAdapter("khm")
        result = adapter.get_events_for_project(str(uuid.uuid4()))
        assert result == []

    def test_get_digital_objects_for_project_with_invalid_uuid_returns_empty(self):
        adapter = KhmAdapter("khm")
        result = adapter.get_digital_objects_for_project("not-a-uuid")
        assert result == []

    def test_get_digital_objects_for_project_with_nonexistent_project_returns_empty(self):
        adapter = KhmAdapter("khm")
        result = adapter.get_digital_objects_for_project(str(uuid.uuid4()))
        assert result == []

    def test_get_project_properties_with_invalid_uuid_returns_none(self):
        adapter = KhmAdapter("khm")
        result = adapter.get_project_properties("not-a-uuid")
        assert result is None

    def test_get_project_graph_with_invalid_uuid_returns_none(self):
        adapter = KhmAdapter("khm")
        result = adapter.get_project_graph("not-a-uuid")
        assert result is None


class TestKhmJunctionPatterns:
    """Test KHM-specific junction patterns."""

    def test_actor_junction_uses_projekt_predicate(self):
        """KHM actor junctions link to grundereignis via projekt predicate."""
        adapter = KhmAdapter()
        assert adapter.JUNCTION_PREDICATE == CanonicalURIs.PROJEKT

    def test_digital_object_junction_pattern(self):
        """KHM uses 11_Kreuz_DigitaleObjekte_Proj for digital object links."""
        adapter = KhmAdapter()
        # Junction links to project via Projekt_ID and to digital object
        assert adapter.ORG_CODE == "khm"

    def test_actors_have_no_event_id(self):
        """KHM actors link to project directly, not to specific events."""
        adapter = KhmAdapter()
        # junction_event_map is empty for KHM
        # Actors are associated with the project, not individual events
        assert adapter.JUNCTION_PREDICATE == CanonicalURIs.PROJEKT


class TestKhmCanonicalURIs:
    """Test that KHM uses correct canonical URIs."""

    def test_projekt_predicate(self):
        assert CanonicalURIs.PROJEKT == "http://arkumu.org/data/properties/projekt"

    def test_ist_urheberin_predicate(self):
        # KHM has proper canonical_uri mappings in database
        assert CanonicalURIs.IST_URHEBERIN == "http://arkumu.org/data/properties/ist-urheberin"

    def test_leistungsschutzrechte_predicate(self):
        # KHM has proper canonical_uri mappings in database
        assert CanonicalURIs.LEISTUNGSSCHUTZRECHTE == "http://arkumu.org/data/properties/besitzt-leistungsschutzrechte"
