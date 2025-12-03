"""Registry for institution adapters."""

from __future__ import annotations

from typing import Dict, Optional, Type

from arkumu.projects.adapters.base import InstitutionAdapter


# Registry of adapter classes by org code
_ADAPTER_REGISTRY: Dict[str, Type[InstitutionAdapter]] = {}


def register_adapter(org_code: str, adapter_class: Type[InstitutionAdapter]) -> None:
    """Register an adapter class for an organization code."""
    _ADAPTER_REGISTRY[org_code.lower().strip()] = adapter_class


def get_adapter(org_code: Optional[str] = None) -> InstitutionAdapter:
    """Get the appropriate adapter for an organization code.

    Args:
        org_code: Organization code (fuk, rsh, det, khm, hmt, etc.)

    Returns:
        An InstitutionAdapter instance for the organization.
        Falls back to FukAdapter for unknown organizations.
    """
    # Lazy import to avoid circular dependencies
    from arkumu.projects.adapters.fuk import FukAdapter, RshAdapter, DetAdapter
    from arkumu.projects.adapters.khm import KhmAdapter
    from arkumu.projects.adapters.hmt import HmtAdapter

    # Register adapters if not already done
    if not _ADAPTER_REGISTRY:
        register_adapter("fuk", FukAdapter)
        register_adapter("rsh", RshAdapter)
        register_adapter("det", DetAdapter)
        register_adapter("khm", KhmAdapter)
        register_adapter("hmt", HmtAdapter)

    normalized = (org_code or "").lower().strip()
    adapter_class = _ADAPTER_REGISTRY.get(normalized, FukAdapter)
    return adapter_class(org_code=normalized)
