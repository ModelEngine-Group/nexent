# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Timeout objects belong to the OpenAI client's actual HTTP implementation."""

import importlib
from types import SimpleNamespace

import httpx
import pytest

from nexent.core.models.openai_llm import _build_compatible_http_timeout


class CompatibleTimeout:
    def __init__(self, *, connect, read, write, pool):
        self.connect, self.read, self.write, self.pool = connect, read, write, pool


@pytest.mark.parametrize("backend", ["httpx2", "httpx", "unknown"])
def test_timeout_backend_and_phase_values_are_preserved(monkeypatch, backend):
    original = importlib.import_module
    monkeypatch.setattr(importlib, "import_module", lambda name: SimpleNamespace(Timeout=CompatibleTimeout)
                        if name == "httpx2" else original(name))
    parent = type("HttpClient", (), {"__module__": backend + ".client"})
    client = type("DefaultHttpxClient", (parent,), {"__module__": "openai._base_client"})
    timeout = _build_compatible_http_timeout(client, connect=11, read=45, write=31, pool=12)
    assert isinstance(timeout, CompatibleTimeout if backend == "httpx2" else httpx.Timeout)
    assert (timeout.connect, timeout.read, timeout.write, timeout.pool) == (11, 45, 31, 12)


def test_timeout_builder_without_http_base_uses_standard_httpx():
    timeout = _build_compatible_http_timeout(object, connect=1, read=2, write=3, pool=4)
    assert isinstance(timeout, httpx.Timeout)
    assert (timeout.connect, timeout.read, timeout.write, timeout.pool) == (1, 2, 3, 4)
