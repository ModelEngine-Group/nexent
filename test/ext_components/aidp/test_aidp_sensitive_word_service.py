# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Unit tests for the AIDP per-knowledge-base sensitive word proxy service."""
from __future__ import annotations

import importlib.util
import os
import sys
from types import ModuleType
from unittest.mock import MagicMock

import httpx
import pytest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../"))
BACKEND_ROOT = os.path.join(PROJECT_ROOT, "backend")
SERVICE_PATH = os.path.join(
    BACKEND_ROOT, "ext_components", "aidp", "services", "aidp_sensitive_word_service.py"
)

if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from ext_components.aidp.consts.aidp_exceptions import AidpSensitiveWordError


@pytest.fixture
def service_module():
    original_modules = {}

    def register_module(name: str, module: ModuleType):
        if name in sys.modules:
            original_modules[name] = sys.modules[name]
        sys.modules[name] = module

    nexent_pkg = ModuleType("nexent")
    nexent_pkg.__path__ = []
    register_module("nexent", nexent_pkg)

    nexent_utils_pkg = ModuleType("nexent.utils")
    nexent_utils_pkg.__path__ = []
    register_module("nexent.utils", nexent_utils_pkg)

    http_client_mod = ModuleType("nexent.utils.http_client_manager")
    http_client_mod.http_client_manager = MagicMock()
    register_module("nexent.utils.http_client_manager", http_client_mod)

    module_name = "aidp_sensitive_word_service_under_test"
    spec = importlib.util.spec_from_file_location(module_name, SERVICE_PATH)
    module = importlib.util.module_from_spec(spec)
    register_module(module_name, module)
    spec.loader.exec_module(module)
    module.http_client_manager = http_client_mod.http_client_manager

    try:
        yield module
    finally:
        for name in [
            module_name,
            "nexent.utils.http_client_manager",
            "nexent.utils",
            "nexent",
        ]:
            if name in original_modules:
                sys.modules[name] = original_modules[name]
            else:
                sys.modules.pop(name, None)


def _configure_client(module, response: httpx.Response):
    client = MagicMock()
    client.request.return_value = response
    module.http_client_manager.get_sync_client.return_value = client
    return client


def test_list_uses_the_knowledge_base_path_and_returns_the_upstream_shape(
    service_module,
):
    client = _configure_client(
        service_module,
        httpx.Response(
            200,
            json={
                "value": [
                    {
                        "id": 7,
                        "word": "暴力",
                        "mode": "black",
                        "description": "desc",
                        "source": "custom",
                    }
                ],
                "next_link": "/KnowledgeBase/.../SensitiveWords?page=3&page_size=10",
                "total_count": 25,
            },
        ),
    )

    result = service_module.list_sensitive_words_impl(
        "http://aidp.example.com", "api-key", "kb-1", 2, 10, "暴力", "BLACK"
    )

    url = client.request.call_args.args[1]
    assert url == (
        "http://aidp.example.com/KnowledgeBase/Tenants/aidp/KnowledgeBases/kb-1"
        "/SensitiveWords?page=2&page_size=10&keyword=%E6%9A%B4%E5%8A%9B&mode=BLACK"
    )
    assert result["total_count"] == 25
    assert result["next_link"] == (
        "/KnowledgeBase/.../SensitiveWords?page=3&page_size=10"
    )
    assert "has_more" not in result
    assert "total_reliable" not in result
    assert result["value"][0] == {
        "id": "7",
        "word": "暴力",
        "mode": "BLACK",
        "description": "desc",
        "source": "CUSTOM",
    }



def test_create_returns_only_the_upstream_id(service_module):
    client = _configure_client(
        service_module, httpx.Response(201, json={"id": "sw-9"})
    )

    result = service_module.create_sensitive_word_impl(
        "http://aidp.example.com", "api-key", "kb-1", "暴力", "BLACK", "desc"
    )

    assert result == {"id": "sw-9"}
    assert client.request.call_args.args[1] == (
        "http://aidp.example.com/KnowledgeBase/Tenants/aidp/KnowledgeBases/kb-1"
        "/SensitiveWords"
    )
    assert client.request.call_args.kwargs["json"] == {
        "word": "暴力",
        "mode": "BLACK",
        "description": "desc",
    }


def test_duplicate_code_is_preserved_from_a_500_body(service_module):
    _configure_client(
        service_module,
        httpx.Response(
            500,
            json={"error": {"code": 1022, "message": "Sensitive word already exists"}},
        ),
    )

    with pytest.raises(AidpSensitiveWordError) as exc_info:
        service_module.create_sensitive_word_impl(
            "http://aidp.example.com", "api-key", "kb-1", "暴力", "BLACK", "desc"
        )

    assert exc_info.value.upstream_code == "1022"
    assert exc_info.value.upstream_status == 500
    assert str(exc_info.value) == "Sensitive word already exists"


def test_delete_accepts_an_empty_204(service_module):
    client = _configure_client(service_module, httpx.Response(204))

    assert service_module.delete_sensitive_word_impl(
        "http://aidp.example.com", "api-key", "kb-1", "sw-1"
    ) is True
    assert client.request.call_args.args[1] == (
        "http://aidp.example.com/KnowledgeBase/Tenants/aidp/KnowledgeBases/kb-1"
        "/SensitiveWords/sw-1"
    )


def test_update_sends_only_the_supplied_fields(service_module):
    client = _configure_client(service_module, httpx.Response(200, json={}))

    result = service_module.update_sensitive_word_impl(
        "http://aidp.example.com", "api-key", "kb-1", "sw-1", {"mode": "WHITE"}
    )

    request_kwargs = client.request.call_args.kwargs
    assert client.request.call_args.args[0] == "PATCH"
    assert request_kwargs["json"] == {"mode": "WHITE"}
    assert client.request.call_args.args[1] == (
        "http://aidp.example.com/KnowledgeBase/Tenants/aidp/KnowledgeBases/kb-1"
        "/SensitiveWords/sw-1"
    )
    assert result == {}
