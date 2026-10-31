"""Fixtures and probes, one module per area: each registers its own steps when it is imported.

Every module in this package is imported here, so a new ``steps/<area>.py`` registers itself without
touching a shared list. ``core`` holds the built-ins every spec uses.
"""

from __future__ import annotations

import importlib
import pkgutil

for _module in sorted(pkgutil.iter_modules(__path__), key=lambda info: info.name):
    importlib.import_module(f"{__name__}.{_module.name}")
