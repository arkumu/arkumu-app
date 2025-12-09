"""Tests for institution adapters."""

import uuid
from unittest.mock import MagicMock, patch

import pytest

from arkumu.projects.adapters import get_adapter, InstitutionAdapter
from arkumu.projects.adapters.base import CanonicalURIs, _is_truthy, _as_uuid, ActorData
from arkumu.projects.adapters.fuk import FukAdapter, RshAdapter, DetAdapter
from arkumu.projects.adapters.khm import KhmAdapter
from arkumu.projects.adapters.hmt import HmtAdapter


class TestUtilityFunctions:
    """Test utility functions in base module."""

    def test_is_truthy_with_true_values(self):
        assert _is_truthy("1") is True
        assert _is_truthy("true") is True
        assert _is_truthy("True") is True
        assert _is_truthy("TRUE") is True
        assert _is_truthy("yes") is True
        assert _is_truthy("Yes") is True
        assert _is_truthy("ja") is True
        assert _is_truthy("Ja") is True

    def test_is_truthy_with_false_values(self):
        assert _is_truthy("0") is False
        assert _is_truthy("false") is False
        assert _is_truthy("no") is False
        assert _is_truthy("nein") is False
        assert _is_truthy("") is False
        assert _is_truthy(None) is False

    def test_as_uuid_with_valid_uuid(self):
        test_uuid = uuid.uuid4()
        assert _as_uuid(str(test_uuid)) == test_uuid
        assert _as_uuid(test_uuid) == test_uuid

    def test_as_uuid_with_invalid_values(self):
        assert _as_uuid(None) is None
        assert _as_uuid("not-a-uuid") is None
        assert _as_uuid("") is None


class TestAdapterRegistry:
    """Test adapter registry and factory."""

    def test_get_adapter_returns_fuk_for_fuk(self):
        adapter = get_adapter("fuk")
        assert isinstance(adapter, FukAdapter)
        assert adapter.org_code == "fuk"

    def test_get_adapter_returns_rsh_adapter(self):
        adapter = get_adapter("rsh")
        assert isinstance(adapter, RshAdapter)
        assert adapter.org_code == "rsh"

    def test_get_adapter_returns_det_adapter(self):
        adapter = get_adapter("det")
        assert isinstance(adapter, DetAdapter)
        assert adapter.org_code == "det"

    def test_get_adapter_returns_khm_adapter(self):
        adapter = get_adapter("khm")
        assert isinstance(adapter, KhmAdapter)
        assert adapter.org_code == "khm"

    def test_get_adapter_returns_hmt_adapter(self):
        adapter = get_adapter("hmt")
        assert isinstance(adapter, HmtAdapter)
        assert adapter.org_code == "hmt"

    def test_get_adapter_defaults_to_fuk_for_unknown(self):
        adapter = get_adapter("unknown_org")
        assert isinstance(adapter, FukAdapter)

    def test_get_adapter_handles_none(self):
        adapter = get_adapter(None)
        assert isinstance(adapter, FukAdapter)

    def test_get_adapter_normalizes_case(self):
        adapter = get_adapter("FUK")
        assert isinstance(adapter, FukAdapter)
        assert adapter.org_code == "fuk"


class TestFukAdapter:
    """Test FUK adapter (canonical pattern)."""

    def test_junction_predicate_is_im_ereignis(self):
        adapter = FukAdapter()
        assert adapter.JUNCTION_PREDICATE == CanonicalURIs.IM_EREIGNIS

    def test_org_code_is_fuk(self):
        adapter = FukAdapter()
        assert adapter.ORG_CODE == "fuk"

    def test_normalize_predicate_passes_through(self):
        adapter = FukAdapter()
        uri = "http://arkumu.org/data/properties/some-property"
        assert adapter.normalize_predicate(uri) == uri


class TestKhmAdapter:
    """Test KHM adapter (projekt -> grundereignis pattern)."""

    def test_junction_predicate_is_projekt(self):
        adapter = KhmAdapter()
        assert adapter.JUNCTION_PREDICATE == CanonicalURIs.PROJEKT

    def test_org_code_is_khm(self):
        adapter = KhmAdapter()
        assert adapter.ORG_CODE == "khm"


class TestHmtAdapter:
    """Test HMT adapter (ereignis predicate, lacks canonical URIs)."""

    def test_junction_predicate_is_hmt_ereignis(self):
        adapter = HmtAdapter()
        assert "hmt" in adapter.JUNCTION_PREDICATE
        assert "ereignis" in adapter.JUNCTION_PREDICATE

    def test_org_code_is_hmt(self):
        adapter = HmtAdapter()
        assert adapter.ORG_CODE == "hmt"

    def test_normalize_predicate_maps_ist_urheberin(self):
        adapter = HmtAdapter()
        hmt_uri = "http://arkumu.org/data/hmt/properties/ist-urheberin"
        assert adapter.normalize_predicate(hmt_uri) == CanonicalURIs.IST_URHEBERIN

    def test_normalize_predicate_maps_leistungsschutzrechte(self):
        adapter = HmtAdapter()
        hmt_uri = "http://arkumu.org/data/hmt/properties/besitzt-leistungsschutzrechte"
        assert adapter.normalize_predicate(hmt_uri) == CanonicalURIs.LEISTUNGSSCHUTZRECHTE

    def test_normalize_predicate_maps_actor_link(self):
        adapter = HmtAdapter()
        hmt_uri = "http://arkumu.org/data/hmt/properties/akteurin-im-ereignis"
        assert adapter.normalize_predicate(hmt_uri) == CanonicalURIs.ACTOR_LINK

    def test_normalize_predicate_passes_unknown(self):
        adapter = HmtAdapter()
        uri = "http://arkumu.org/data/hmt/properties/unknown"
        assert adapter.normalize_predicate(uri) == uri

    def test_predicate_canonical_map_has_required_mappings(self):
        adapter = HmtAdapter()
        assert "/ist-urheberin" in adapter.PREDICATE_CANONICAL_MAP
        assert "/besitzt-leistungsschutzrechte" in adapter.PREDICATE_CANONICAL_MAP
        assert "/akteurin-im-ereignis" in adapter.PREDICATE_CANONICAL_MAP


class TestActorData:
    """Test ActorData dataclass."""

    def test_actor_data_creation(self):
        actor = ActorData(
            actor_id="test-id",
            actor_name="Test Actor",
            event_id="event-123",
            roles=["Director", "Producer"],
            is_copyright_holder=True,
            is_neighbouring_rights_holder=False,
        )
        assert actor.actor_id == "test-id"
        assert actor.actor_name == "Test Actor"
        assert actor.event_id == "event-123"
        assert actor.roles == ["Director", "Producer"]
        assert actor.is_copyright_holder is True
        assert actor.is_neighbouring_rights_holder is False

    def test_actor_data_with_none_event(self):
        actor = ActorData(
            actor_id="test-id",
            actor_name="Test Actor",
            event_id=None,
            roles=[],
            is_copyright_holder=False,
            is_neighbouring_rights_holder=False,
        )
        assert actor.event_id is None


@pytest.mark.django_db
class TestFukAdapterIntegration:
    """Integration tests for FUK adapter with database."""

    def test_get_actors_for_project_with_no_events_returns_empty(self):
        adapter = FukAdapter("fuk")
        # Random UUID that doesn't exist
        result = adapter.get_actors_for_project(str(uuid.uuid4()))
        assert result == []

    def test_get_actors_for_project_with_invalid_uuid_returns_empty(self):
        adapter = FukAdapter("fuk")
        result = adapter.get_actors_for_project("not-a-uuid")
        assert result == []


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


@pytest.mark.django_db
class TestHmtAdapterIntegration:
    """Integration tests for HMT adapter with database."""

    def test_get_actors_for_project_with_invalid_uuid_returns_empty(self):
        adapter = HmtAdapter("hmt")
        result = adapter.get_actors_for_project("not-a-uuid")
        assert result == []

    def test_get_actors_for_project_with_no_events_returns_empty(self):
        adapter = HmtAdapter("hmt")
        result = adapter.get_actors_for_project(str(uuid.uuid4()))
        assert result == []
