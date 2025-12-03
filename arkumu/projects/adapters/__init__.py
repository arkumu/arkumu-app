"""Institution adapters for building ProjectRecord data.

Each institution (FUK, KHM, HMT) has different data patterns for:
- Junction entities linking actors to events
- Predicate URIs (some lack canonical mappings)
- Event/project relationships

The adapters abstract these differences, providing a unified interface
for building ProjectRecord data regardless of institution.
"""

from arkumu.projects.adapters.base import InstitutionAdapter
from arkumu.projects.adapters.registry import get_adapter, register_adapter

__all__ = [
    "InstitutionAdapter",
    "get_adapter",
    "register_adapter",
]
