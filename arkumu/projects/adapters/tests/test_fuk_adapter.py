"""Tests for FUK adapter (canonical pattern)."""

import uuid
from unittest.mock import MagicMock, patch

import pytest

from arkumu.projects.adapters import CanonicalURIs, get_adapter
from arkumu.projects.adapters.fuk import FukAdapter


class TestFukAdapterUnit:
    """Unit tests for FUK adapter."""

    def test_org_code_is_fuk(self):
        adapter = FukAdapter()
        assert adapter.ORG_CODE == "fuk"

    def test_junction_predicate_is_im_ereignis(self):
        adapter = FukAdapter()
        assert adapter.JUNCTION_PREDICATE == CanonicalURIs.IM_EREIGNIS

    def test_normalize_predicate_passes_through(self):
        """FUK uses canonical predicates, so no normalization needed."""
        adapter = FukAdapter()
        uri = "http://arkumu.org/data/properties/some-property"
        assert adapter.normalize_predicate(uri) == uri

    def test_get_adapter_returns_fuk_adapter(self):
        adapter = get_adapter("fuk")
        assert isinstance(adapter, FukAdapter)
        assert adapter.org_code == "fuk"

    def test_get_adapter_handles_uppercase(self):
        adapter = get_adapter("FUK")
        assert isinstance(adapter, FukAdapter)
        assert adapter.org_code == "fuk"


@pytest.mark.django_db
class TestFukAdapterIntegration:
    """Integration tests for FUK adapter with database."""

    def test_get_actors_for_project_with_invalid_uuid_returns_empty(self):
        adapter = FukAdapter("fuk")
        result = adapter.get_actors_for_project("not-a-uuid")
        assert result == []

    def test_get_actors_for_project_with_nonexistent_project_returns_empty(self):
        adapter = FukAdapter("fuk")
        result = adapter.get_actors_for_project(str(uuid.uuid4()))
        assert result == []

    def test_get_events_for_project_with_invalid_uuid_returns_empty(self):
        adapter = FukAdapter("fuk")
        result = adapter.get_events_for_project("not-a-uuid")
        assert result == []

    def test_get_events_for_project_with_nonexistent_project_returns_empty(self):
        adapter = FukAdapter("fuk")
        result = adapter.get_events_for_project(str(uuid.uuid4()))
        assert result == []

    def test_get_digital_objects_for_project_with_invalid_uuid_returns_empty(self):
        adapter = FukAdapter("fuk")
        result = adapter.get_digital_objects_for_project("not-a-uuid")
        assert result == []

    def test_get_digital_objects_for_project_with_nonexistent_project_returns_empty(self):
        adapter = FukAdapter("fuk")
        result = adapter.get_digital_objects_for_project(str(uuid.uuid4()))
        assert result == []

    def test_get_project_properties_with_invalid_uuid_returns_none(self):
        adapter = FukAdapter("fuk")
        result = adapter.get_project_properties("not-a-uuid")
        assert result is None

    def test_get_project_properties_with_nonexistent_project_returns_none(self):
        adapter = FukAdapter("fuk")
        result = adapter.get_project_properties(str(uuid.uuid4()))
        assert result is None

    def test_get_project_graph_with_invalid_uuid_returns_none(self):
        adapter = FukAdapter("fuk")
        result = adapter.get_project_graph("not-a-uuid")
        assert result is None

    def test_get_project_graph_with_nonexistent_project_returns_none(self):
        adapter = FukAdapter("fuk")
        result = adapter.get_project_graph(str(uuid.uuid4()))
        assert result is None


class TestFukAdapterCanonicalURIs:
    """Test that FUK adapter uses canonical URIs correctly."""

    def test_event_predicate_is_canonical(self):
        assert CanonicalURIs.EVENT == "http://arkumu.org/data/properties/ereignis"

    def test_im_ereignis_predicate_is_canonical(self):
        assert CanonicalURIs.IM_EREIGNIS == "http://arkumu.org/data/properties/im-ereignis"

    def test_actor_link_predicate_is_canonical(self):
        assert CanonicalURIs.ACTOR_LINK == "http://arkumu.org/data/properties/akteurin-im-ereignis"

    def test_digital_object_predicate_is_canonical(self):
        assert CanonicalURIs.DIGITAL_OBJECT == "http://arkumu.org/data/properties/digitales-objekt"
