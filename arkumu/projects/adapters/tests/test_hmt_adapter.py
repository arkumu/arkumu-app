"""Tests for HMT adapter (junction patterns + predicate mapping)."""

import uuid
from unittest.mock import MagicMock, patch

import pytest

from arkumu.projects.adapters import CanonicalURIs, get_adapter
from arkumu.projects.adapters.hmt import HmtAdapter


class TestHmtAdapterUnit:
    """Unit tests for HMT adapter."""

    def test_org_code_is_hmt(self):
        adapter = HmtAdapter()
        assert adapter.ORG_CODE == "hmt"

    def test_junction_predicate_is_hmt_ereignis(self):
        adapter = HmtAdapter()
        assert "hmt" in adapter.JUNCTION_PREDICATE
        assert "ereignis" in adapter.JUNCTION_PREDICATE

    def test_get_adapter_returns_hmt_adapter(self):
        adapter = get_adapter("hmt")
        assert isinstance(adapter, HmtAdapter)
        assert adapter.org_code == "hmt"

    def test_get_adapter_handles_uppercase(self):
        adapter = get_adapter("HMT")
        assert isinstance(adapter, HmtAdapter)
        assert adapter.org_code == "hmt"


class TestHmtPredicateNormalization:
    """Test HMT predicate normalization (maps institutional to canonical)."""

    def test_normalize_ist_urheberin(self):
        adapter = HmtAdapter()
        hmt_uri = "http://arkumu.org/data/hmt/properties/ist-urheberin"
        assert adapter.normalize_predicate(hmt_uri) == CanonicalURIs.IST_URHEBERIN

    def test_normalize_leistungsschutzrechte(self):
        adapter = HmtAdapter()
        hmt_uri = "http://arkumu.org/data/hmt/properties/besitzt-leistungsschutzrechte"
        assert adapter.normalize_predicate(hmt_uri) == CanonicalURIs.LEISTUNGSSCHUTZRECHTE

    def test_normalize_actor_link(self):
        adapter = HmtAdapter()
        hmt_uri = "http://arkumu.org/data/hmt/properties/akteurin-im-ereignis"
        assert adapter.normalize_predicate(hmt_uri) == CanonicalURIs.ACTOR_LINK

    def test_normalize_role_link(self):
        adapter = HmtAdapter()
        hmt_uri = "http://arkumu.org/data/hmt/properties/rollen-der-akteurin-im-ereignis"
        assert adapter.normalize_predicate(hmt_uri) == CanonicalURIs.ROLE_LINK

    def test_normalize_actor_name(self):
        adapter = HmtAdapter()
        hmt_uri = "http://arkumu.org/data/hmt/properties/deutscher-name"
        assert adapter.normalize_predicate(hmt_uri) == CanonicalURIs.ACTOR_NAME

    def test_normalize_unknown_predicate_passes_through(self):
        adapter = HmtAdapter()
        uri = "http://arkumu.org/data/hmt/properties/unknown-predicate"
        assert adapter.normalize_predicate(uri) == uri

    def test_normalize_empty_predicate(self):
        adapter = HmtAdapter()
        assert adapter.normalize_predicate("") == ""

    def test_normalize_none_predicate(self):
        adapter = HmtAdapter()
        # normalize_predicate expects string, but should handle None gracefully
        assert adapter.normalize_predicate(None) is None


class TestHmtPredicateCanonicalMap:
    """Test PREDICATE_CANONICAL_MAP has required mappings."""

    def test_has_ist_urheberin_mapping(self):
        adapter = HmtAdapter()
        assert "/ist-urheberin" in adapter.PREDICATE_CANONICAL_MAP

    def test_has_leistungsschutzrechte_mapping(self):
        adapter = HmtAdapter()
        assert "/besitzt-leistungsschutzrechte" in adapter.PREDICATE_CANONICAL_MAP

    def test_has_akteurin_mapping(self):
        adapter = HmtAdapter()
        assert "/akteurin-im-ereignis" in adapter.PREDICATE_CANONICAL_MAP

    def test_has_rollen_mapping(self):
        adapter = HmtAdapter()
        assert "/rollen-der-akteurin-im-ereignis" in adapter.PREDICATE_CANONICAL_MAP

    def test_has_deutscher_name_mapping(self):
        adapter = HmtAdapter()
        assert "/deutscher-name" in adapter.PREDICATE_CANONICAL_MAP


@pytest.mark.django_db
class TestHmtAdapterIntegration:
    """Integration tests for HMT adapter with database."""

    def test_get_actors_for_project_with_invalid_uuid_returns_empty(self):
        adapter = HmtAdapter("hmt")
        result = adapter.get_actors_for_project("not-a-uuid")
        assert result == []

    def test_get_actors_for_project_with_nonexistent_project_returns_empty(self):
        adapter = HmtAdapter("hmt")
        result = adapter.get_actors_for_project(str(uuid.uuid4()))
        assert result == []

    def test_get_events_for_project_with_invalid_uuid_returns_empty(self):
        adapter = HmtAdapter("hmt")
        result = adapter.get_events_for_project("not-a-uuid")
        assert result == []

    def test_get_events_for_project_with_nonexistent_project_returns_empty(self):
        adapter = HmtAdapter("hmt")
        result = adapter.get_events_for_project(str(uuid.uuid4()))
        assert result == []

    def test_get_digital_objects_for_project_with_invalid_uuid_returns_empty(self):
        adapter = HmtAdapter("hmt")
        result = adapter.get_digital_objects_for_project("not-a-uuid")
        assert result == []

    def test_get_digital_objects_for_project_with_nonexistent_project_returns_empty(self):
        adapter = HmtAdapter("hmt")
        result = adapter.get_digital_objects_for_project(str(uuid.uuid4()))
        assert result == []

    def test_get_project_properties_with_invalid_uuid_returns_none(self):
        adapter = HmtAdapter("hmt")
        result = adapter.get_project_properties("not-a-uuid")
        assert result is None

    def test_get_project_graph_with_invalid_uuid_returns_none(self):
        adapter = HmtAdapter("hmt")
        result = adapter.get_project_graph("not-a-uuid")
        assert result is None


class TestHmtJunctionPatterns:
    """Test HMT-specific junction patterns are documented correctly."""

    def test_project_event_junction_pattern(self):
        """HMT uses 01_hfm_Kreuz_Projekt_Ereignis for project-event links."""
        adapter = HmtAdapter()
        # Junction has: projekt -> project, ereignis -> event
        # This is an inverted pattern compared to FUK's direct links
        assert adapter.ORG_CODE == "hmt"

    def test_event_digital_object_junction_pattern(self):
        """HMT uses 07_hfm_Kreuz_Ereignis_DigitalesObjekt for event-DO links."""
        adapter = HmtAdapter()
        # Junction has: ereignis -> event, digitales-objekt -> DO
        assert adapter.ORG_CODE == "hmt"

    def test_actor_event_junction_pattern(self):
        """HMT uses 03_hfm_Kreuz_Ereignis_Akteure for actor-event links."""
        adapter = HmtAdapter()
        # Junction has: ereignis -> event, akteurin -> actor
        assert adapter.JUNCTION_PREDICATE == "http://arkumu.org/data/hmt/properties/ereignis"
