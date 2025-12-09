"""Institution adapters for building ProjectRecord data.

Each institution (FUK, KHM, HMT) has different data patterns for:
- Junction entities linking actors to events
- Predicate URIs (some lack canonical mappings)
- Event/project relationships
- Digital object links

The adapters abstract these differences, providing a unified interface
for building ProjectRecord data and RDF graphs regardless of institution.
"""

from arkumu.projects.adapters.base import (
    InstitutionAdapter,
    ActorData,
    EventData,
    DigitalObjectData,
    ProjectPropertiesData,
    ProjectGraph,
    TripleData,
    CanonicalURIs,
)
from arkumu.projects.adapters.registry import get_adapter, register_adapter

__all__ = [
    "InstitutionAdapter",
    "ActorData",
    "EventData",
    "DigitalObjectData",
    "ProjectPropertiesData",
    "ProjectGraph",
    "TripleData",
    "CanonicalURIs",
    "get_adapter",
    "register_adapter",
]
