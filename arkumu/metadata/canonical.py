"""Shared canonical predicate registry for Arkumu metadata domains.

This module centralises the URI constants that describe how core domain
objects (projects, events, actors, digital objects, etc.) are related.
Keeping them here prevents the same literal URIs from being redefined in
multiple commands/services and makes the overall mapping logic easier to
maintain.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, Mapping


@dataclass(frozen=True)
class CanonicalDomain:
    """Logical grouping of canonical predicates for a domain area."""

    name: str
    predicates: Mapping[str, str]

    def __iter__(self) -> Iterable[str]:  # pragma: no cover - container convenience
        return iter(self.predicates.values())


PROJECT_DOMAIN = CanonicalDomain(
    name="project",
    predicates={
        "project": "http://arkumu.org/data/properties/projekt",
        "project_membership": "http://arkumu.org/data/properties/im-ereignis",
        "project_category": "http://arkumu.org/data/properties/projektkategorie",
    },
)

EVENT_DOMAIN = CanonicalDomain(
    name="event",
    predicates={
        "event": "http://arkumu.org/data/properties/ereignis",
        "event_membership": "http://arkumu.org/data/properties/im-ereignis",
        "in_event": "http://arkumu.org/data/properties/im-ereignis",
    },
)

ACTOR_DOMAIN = CanonicalDomain(
    name="actor",
    predicates={
        "actor": "http://arkumu.org/data/properties/akteurin",
        "actor_in_event": "http://arkumu.org/data/properties/akteurin-im-ereignis",
        "role_in_event": "http://arkumu.org/data/properties/rollen-der-akteurin-im-ereignis",
    },
)

DIGITAL_DOMAIN = CanonicalDomain(
    name="digital",
    predicates={
        "digital_object": "http://arkumu.org/data/properties/digitales-objekt",
        "information_carrier": "http://arkumu.org/data/properties/informationstraeger",
    },
)

THEMATIC_DOMAIN = CanonicalDomain(
    name="thematic",
    predicates={
        "keyword": "http://arkumu.org/data/properties/schlagwort",
        "equipment": "http://arkumu.org/data/properties/equipment-und-software",
    },
)


CANONICAL_DOMAINS: Dict[str, CanonicalDomain] = {
    PROJECT_DOMAIN.name: PROJECT_DOMAIN,
    EVENT_DOMAIN.name: EVENT_DOMAIN,
    ACTOR_DOMAIN.name: ACTOR_DOMAIN,
    DIGITAL_DOMAIN.name: DIGITAL_DOMAIN,
    THEMATIC_DOMAIN.name: THEMATIC_DOMAIN,
}

CANONICAL_PREDICATES: Dict[str, str] = {
    key: uri for domain in CANONICAL_DOMAINS.values() for key, uri in domain.predicates.items()
}


def canonical_uri(key: str) -> str:
    """Return the canonical predicate URI for a logical key."""

    try:
        return CANONICAL_PREDICATES[key]
    except KeyError as exc:  # pragma: no cover - defensive branch
        raise KeyError(f"Unknown canonical predicate key '{key}'.") from exc


def iter_domain(name: str) -> Iterable[str]:
    """Yield all canonical URIs for the requested domain."""

    domain = CANONICAL_DOMAINS.get(name)
    if not domain:
        raise KeyError(f"Unknown canonical domain '{name}'.")
    return domain.predicates.values()


RELATIONSHIP_FALLBACKS: Dict[str, tuple[str, ...]] = {
    # project_actor: allow direct project→actor edges to resolve via canonical actor predicate
    "project_actor": ("actor",),
}


def predicate_candidates(key: str, requested_uri: str) -> list[str]:
    """Return unique predicate URIs including any configured fallbacks."""

    candidates = [requested_uri]
    for canonical_key in RELATIONSHIP_FALLBACKS.get(key, ()):
        fallback_uri = canonical_uri(canonical_key)
        if fallback_uri not in candidates:
            candidates.append(fallback_uri)
    return candidates


__all__ = [
    "ACTOR_DOMAIN",
    "CANONICAL_DOMAINS",
    "CANONICAL_PREDICATES",
    "CanonicalDomain",
    "DIGITAL_DOMAIN",
    "EVENT_DOMAIN",
    "PROJECT_DOMAIN",
    "THEMATIC_DOMAIN",
    "canonical_uri",
    "iter_domain",
    "predicate_candidates",
    "RELATIONSHIP_FALLBACKS",
]
