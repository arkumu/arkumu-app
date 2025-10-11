import pytest

from arkumu.metadata.canonical import (
    ACTOR_DOMAIN,
    CANONICAL_DOMAINS,
    CANONICAL_PREDICATES,
    DIGITAL_DOMAIN,
    PROJECT_DOMAIN,
    canonical_uri,
    iter_domain,
    predicate_candidates,
)


def test_canonical_uri_returns_expected_values():
    assert canonical_uri("project") == PROJECT_DOMAIN.predicates["project"]
    assert canonical_uri("digital_object") == DIGITAL_DOMAIN.predicates["digital_object"]
    assert canonical_uri("actor_in_event") == ACTOR_DOMAIN.predicates["actor_in_event"]


def test_canonical_uri_unknown_key_raises_key_error():
    with pytest.raises(KeyError):
        canonical_uri("not-a-valid-key")


def test_iter_domain_yields_expected_predicates():
    actor_uris = set(iter_domain("actor"))
    assert ACTOR_DOMAIN.predicates["actor_in_event"] in actor_uris
    assert ACTOR_DOMAIN.predicates["actor"] in actor_uris


def test_can_enumerate_all_predicates():
    flattened = set(CANONICAL_PREDICATES.values())
    grouped = {uri for domain in CANONICAL_DOMAINS.values() for uri in domain}
    assert flattened == grouped


def test_predicate_candidates_adds_configured_fallback():
    requested = "http://example.org/custom/actor-link"
    expanded = predicate_candidates("project_actor", requested)
    assert expanded[0] == requested
    assert canonical_uri("actor") in expanded


def test_predicate_candidates_avoids_duplicates():
    canonical_actor = canonical_uri("actor")
    expanded = predicate_candidates("project_actor", canonical_actor)
    assert expanded == [canonical_actor]
