# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Keep legacy import-time test doubles local to their owning test module."""

import sys
from types import ModuleType


def capture_module_stubs(original):
    """Restore imports after collection; return a fixture installer for the stubs."""
    replacements = {
        name: module for name, module in sys.modules.copy().items()
        if original.get(name) is not module
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
            elif getattr(parent, attribute, None) is module:
                delattr(parent, attribute)

    def install(monkeypatch):
        for name, module in replacements.items():
            monkeypatch.setitem(sys.modules, name, module)
        for name, module in replacements.items():
            parent_name, _, attribute = name.rpartition(".")
            parent = sys.modules.get(parent_name)
            if isinstance(parent, ModuleType):
                monkeypatch.setattr(parent, attribute, module, raising=False)

    return install
