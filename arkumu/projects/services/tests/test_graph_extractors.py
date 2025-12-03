"""Tests for graph extractors module."""

import pytest

from arkumu.projects.services.graph_extractors import (
    TripleIndex,
    Predicates,
    get_literal,
    get_all_literals,
    get_object_uri,
    get_all_object_uris,
    extract_code_from_uri,
    is_truthy,
    is_junction_uri,
)
from arkumu.projects.services.graph_service import TripleResult


class TestTripleIndex:
    """Tests for TripleIndex class."""

    def test_from_triples_empty(self):
        index = TripleIndex.from_triples([])
        assert index.by_subject == {}
        assert index.by_predicate == {}
        assert index.all_subjects == set()

    def test_from_triples_indexes_by_subject(self):
        triples = [
            TripleResult(
                subject_uri="http://example.org/project/1",
                predicate_uri="http://example.org/title",
                predicate_canonical_uri="http://arkumu.org/data/properties/bevorzugter-titel",
                object_uri=None,
                object_value="Test Title",
            )
        ]
        index = TripleIndex.from_triples(triples)

        assert "http://example.org/project/1" in index.by_subject
        assert len(index.by_subject["http://example.org/project/1"]) == 1

    def test_from_triples_indexes_by_canonical_predicate(self):
        triples = [
            TripleResult(
                subject_uri="http://example.org/project/1",
                predicate_uri="http://example.org/inst/title",
                predicate_canonical_uri="http://arkumu.org/data/properties/bevorzugter-titel",
                object_uri=None,
                object_value="Test Title",
            )
        ]
        index = TripleIndex.from_triples(triples)

        # Should be indexed by canonical URI
        assert Predicates.TITLE in index.by_predicate
        assert len(index.by_predicate[Predicates.TITLE]) == 1

    def test_from_triples_indexes_by_object_uri(self):
        triples = [
            TripleResult(
                subject_uri="http://example.org/project/1",
                predicate_uri="http://example.org/category",
                predicate_canonical_uri=None,
                object_uri="http://example.org/category/5",
                object_value=None,
            )
        ]
        index = TripleIndex.from_triples(triples)

        assert "http://example.org/category/5" in index.by_object


class TestGetLiteral:
    """Tests for get_literal function."""

    def test_get_literal_returns_value(self):
        triples = [
            TripleResult(
                subject_uri="http://example.org/project/1",
                predicate_uri="http://example.org/title",
                predicate_canonical_uri=Predicates.TITLE,
                object_uri=None,
                object_value="My Project",
            )
        ]
        index = TripleIndex.from_triples(triples)

        result = get_literal(index, "http://example.org/project/1", Predicates.TITLE)
        assert result == "My Project"

    def test_get_literal_returns_none_for_missing(self):
        triples = []
        index = TripleIndex.from_triples(triples)

        result = get_literal(index, "http://example.org/project/1", Predicates.TITLE)
        assert result is None

    def test_get_literal_ignores_object_uri(self):
        triples = [
            TripleResult(
                subject_uri="http://example.org/project/1",
                predicate_uri="http://example.org/category",
                predicate_canonical_uri=Predicates.CATEGORY,
                object_uri="http://example.org/category/5",
                object_value=None,
            )
        ]
        index = TripleIndex.from_triples(triples)

        result = get_literal(index, "http://example.org/project/1", Predicates.CATEGORY)
        assert result is None


class TestGetAllLiterals:
    """Tests for get_all_literals function."""

    def test_get_all_literals_returns_multiple(self):
        triples = [
            TripleResult(
                subject_uri="http://example.org/project/1",
                predicate_uri="http://example.org/alt",
                predicate_canonical_uri=Predicates.ALT_TITLE,
                object_uri=None,
                object_value="Alt 1",
            ),
            TripleResult(
                subject_uri="http://example.org/project/1",
                predicate_uri="http://example.org/alt",
                predicate_canonical_uri=Predicates.ALT_TITLE,
                object_uri=None,
                object_value="Alt 2",
            ),
        ]
        index = TripleIndex.from_triples(triples)

        result = get_all_literals(index, "http://example.org/project/1", Predicates.ALT_TITLE)
        assert result == ["Alt 1", "Alt 2"]


class TestGetObjectUri:
    """Tests for get_object_uri function."""

    def test_get_object_uri_returns_uri(self):
        triples = [
            TripleResult(
                subject_uri="http://example.org/project/1",
                predicate_uri="http://example.org/inst",
                predicate_canonical_uri=Predicates.INSTITUTION,
                object_uri="http://example.org/institution/hmt",
                object_value=None,
            )
        ]
        index = TripleIndex.from_triples(triples)

        result = get_object_uri(index, "http://example.org/project/1", Predicates.INSTITUTION)
        assert result == "http://example.org/institution/hmt"


class TestGetAllObjectUris:
    """Tests for get_all_object_uris function."""

    def test_get_all_object_uris_returns_multiple(self):
        triples = [
            TripleResult(
                subject_uri="http://example.org/project/1",
                predicate_uri="http://example.org/cat",
                predicate_canonical_uri=Predicates.CATEGORY,
                object_uri="http://example.org/category/1",
                object_value=None,
            ),
            TripleResult(
                subject_uri="http://example.org/project/1",
                predicate_uri="http://example.org/cat",
                predicate_canonical_uri=Predicates.CATEGORY,
                object_uri="http://example.org/category/2",
                object_value=None,
            ),
        ]
        index = TripleIndex.from_triples(triples)

        result = get_all_object_uris(index, "http://example.org/project/1", Predicates.CATEGORY)
        assert result == ["http://example.org/category/1", "http://example.org/category/2"]


class TestExtractCodeFromUri:
    """Tests for extract_code_from_uri function."""

    def test_extracts_hmt_code(self):
        uri = "http://arkumu.org/data/hmt/entities/projekt/123"
        assert extract_code_from_uri(uri) == "hmt"

    def test_extracts_fuk_code(self):
        uri = "http://arkumu.org/data/fuk/entities/projekt/456"
        assert extract_code_from_uri(uri) == "fuk"

    def test_returns_none_for_invalid_uri(self):
        uri = "http://example.org/something"
        assert extract_code_from_uri(uri) is None

    def test_ignores_properties_path(self):
        uri = "http://arkumu.org/data/properties/title"
        assert extract_code_from_uri(uri) is None


class TestIsTruthy:
    """Tests for is_truthy function."""

    def test_truthy_values(self):
        assert is_truthy("1") is True
        assert is_truthy("true") is True
        assert is_truthy("True") is True
        assert is_truthy("yes") is True
        assert is_truthy("ja") is True

    def test_falsy_values(self):
        assert is_truthy("0") is False
        assert is_truthy("false") is False
        assert is_truthy("no") is False
        assert is_truthy("nein") is False
        assert is_truthy(None) is False
        assert is_truthy("") is False


class TestIsJunctionUri:
    """Tests for is_junction_uri function."""

    def test_kreuz_uri_is_junction(self):
        uri = "http://arkumu.org/data/hmt/entities/03-hfm-kreuz-ereignis-akteure/123"
        assert is_junction_uri(uri) is True

    def test_junction_in_uri(self):
        uri = "http://example.org/junction/actor-event/1"
        assert is_junction_uri(uri) is True

    def test_regular_entity_not_junction(self):
        uri = "http://arkumu.org/data/hmt/entities/projekt/123"
        assert is_junction_uri(uri) is False

    def test_empty_uri_not_junction(self):
        assert is_junction_uri("") is False
        assert is_junction_uri(None) is False
