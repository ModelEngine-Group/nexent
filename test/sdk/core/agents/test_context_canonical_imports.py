# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Removed context facades no longer participate in canonical imports."""
import importlib
import pickle

import pytest


@pytest.mark.parametrize("module,symbol", [
    ("nexent.core.agents.context.manager", "ContextManager"),
    ("nexent.core.agents.context.config", "ContextManagerConfig"),
    ("nexent.core.agents.cores.smolagents.context", "ManagedContextRuntime"),
])
def test_context_owner_and_canonical_pickle(module, symbol):
    value = getattr(importlib.import_module(module), symbol)
    assert value.__module__ == module
    assert pickle.loads(pickle.dumps(value)) is value
