"""Public OAI view exports."""

from __future__ import annotations

import sys
import types

from . import base as _base_module
from . import config as _config_module
from . import harvest as _harvest_module
from . import metadata as _metadata_module
from . import projects as _projects_module
from . import router as _router_module
from . import tailored as _tailored_module

_MODULES = (
    _base_module,
    _harvest_module,
    _metadata_module,
    _projects_module,
    _config_module,
    _router_module,
    _tailored_module,
)

__all__ = sorted({name for module in _MODULES for name in dir(module) if not name.startswith("__")})


class _ViewsModule(types.ModuleType):
    """Proxy module that delegates attribute access to submodules."""

    def __getattr__(self, name: str):  # type: ignore[override]
        for module in _MODULES:
            if hasattr(module, name):
                return getattr(module, name)
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    def __setattr__(self, name: str, value):  # type: ignore[override]
        for module in _MODULES:
            if hasattr(module, name):
                setattr(module, name, value)
        super().__setattr__(name, value)

    def __dir__(self):  # type: ignore[override]
        return sorted(set(super().__dir__()) | set(__all__))


_module = sys.modules[__name__]
_module.__class__ = _ViewsModule
_module.__dict__.update(
    {
        "_base_module": _base_module,
        "_harvest_module": _harvest_module,
        "_metadata_module": _metadata_module,
        "_projects_module": _projects_module,
        "_config_module": _config_module,
        "_router_module": _router_module,
        "_tailored_module": _tailored_module,
        "_MODULES": _MODULES,
        "__all__": __all__,
    }
)
