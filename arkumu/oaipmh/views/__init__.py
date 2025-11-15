"""Public OAI view exports."""

from __future__ import annotations

import sys
import types

from . import base as _base_module
from . import tailored as _tailored_module

__all__ = sorted(
    {
        name for name in dir(_base_module) if not name.startswith("__")
    }
    | {
        name for name in dir(_tailored_module) if not name.startswith("__")
    }
)


class _ViewsModule(types.ModuleType):
    """Proxy module that delegates attribute access to submodules."""

    def __getattr__(self, name: str):  # type: ignore[override]
        if hasattr(_base_module, name):
            return getattr(_base_module, name)
        if hasattr(_tailored_module, name):
            return getattr(_tailored_module, name)
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    def __setattr__(self, name: str, value):  # type: ignore[override]
        if hasattr(_base_module, name):
            setattr(_base_module, name, value)
        if hasattr(_tailored_module, name):
            setattr(_tailored_module, name, value)
        super().__setattr__(name, value)

    def __dir__(self):  # type: ignore[override]
        return sorted(set(super().__dir__()) | set(__all__))


_module = sys.modules[__name__]
_module.__class__ = _ViewsModule
_module.__dict__.update(
    {
        "_base_module": _base_module,
        "_tailored_module": _tailored_module,
        "__all__": __all__,
    }
)
