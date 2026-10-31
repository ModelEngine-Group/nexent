# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Shared serialization doubles for tests that replace the session client."""

import sys
from types import ModuleType


def install_serialization_stub(client_module):
    """Reuse configured helper doubles at their canonical utility lookup site."""
    module = ModuleType("management.utils.orm")
    for name in ("as_dict", "filter_property"):
        if hasattr(client_module, name):
            setattr(module, name, getattr(client_module, name))
    if hasattr(module, "as_dict") or hasattr(module, "filter_property"):
        sys.modules[module.__name__] = module
