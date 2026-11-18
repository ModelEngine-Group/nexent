# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Keep legacy import-time test doubles local to their owning test module."""

import sys
from pathlib import Path
from types import ModuleType


_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_PROJECT_IMPORT_ROOTS = tuple(_PROJECT_ROOT / name for name in ("backend", "sdk", "test"))


def _project_path(value):
    path = Path(value).resolve()
    if {".venv", "venv", "site-packages"}.intersection(part.lower() for part in path.parts):
        return False
    return any(path.is_relative_to(root) for root in _PROJECT_IMPORT_ROOTS)


def _owns_import(module):
    """Keep native and lazy third-party imports alive across test fixtures."""
    if not isinstance(module, ModuleType):
        return True
    namespace = vars(module)
    filename = namespace.get("__file__")
    if filename:
        return _project_path(filename)
    if namespace.get("__spec__") is None:
        return True  # Explicit ModuleType doubles have no import specification.
    return any(_project_path(path) for path in namespace.get("__path__", ()))


def capture_module_stubs(original):
    """Restore imports after collection; return a fixture installer for the stubs."""
    replacements = {
        name: module for name, module in sys.modules.copy().items()
        if original.get(name) is not module and (name in original or _owns_import(module))
    }
    for name, module in replacements.items():
        parent_name, _, attribute = name.rpartition(".")
        if name in original:
            sys.modules[name] = original[name]
        else:
            sys.modules.pop(name, None)
        parent = sys.modules.get(parent_name)
        if isinstance(parent, ModuleType):
            if name in original:
                setattr(parent, attribute, original[name])
            elif vars(parent).get(attribute) is module:
                delattr(parent, attribute)

    def install(monkeypatch):
        for name, module in replacements.items():
            monkeypatch.setitem(sys.modules, name, module)
        for name, module in replacements.items():
            parent_name, _, attribute = name.rpartition(".")
            parent = sys.modules.get(parent_name)
            if isinstance(parent, ModuleType):
                # Lazy packages can import recursively from __getattr__.
                # Preserve their concrete namespace without invoking hooks.
                monkeypatch.setitem(vars(parent), attribute, module)

    return install
