# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Coverage for the shared AIDP HTTP client helpers."""

from __future__ import annotations

import importlib
from unittest.mock import MagicMock

import httpx
import pytest


def _response(status=200, *, json_body=None, content=None, headers=None):
    request = httpx.Request("GET", "http://aidp.example/x")
    if json_body is not None:
        return httpx.Response(status, json=json_body, request=request, headers=headers)
    return httpx.Response(status, content=content or b"", request=request, headers=headers)


@pytest.fixture
def client(monkeypatch):
    module = importlib.import_module("ext_components.aidp.services.aidp_client")
    http = MagicMock()
    monkeypatch.setattr(module.http_client_manager, "get_sync_client", MagicMock(return_value=http))
    monkeypatch.setattr(module, "_request_with_retry", lambda fn, context: fn())
    return module, http


def test_language_header_prefers_request_context(client):
    module, _ = client
    module.set_aidp_accept_language("en-US")
    assert module._aidp_headers("key")["Accept-Language"] == "en-US"
    assert module._aidp_headers("key")["Content-Type"] == "application/json"
    assert "Content-Type" not in module._aidp_headers("key", content_type=False)


def test_upstream_error_and_code_extraction(client):
    module, _ = client
    response = _response(
        400,
        json_body={"error": {"code": 1056, "message": " missing "}},
    )
    assert module._extract_upstream_error(response) == "missing"
    assert module._extract_upstream_code(response) == 1056
    assert module._extract_upstream_error(_response(500, content=b"plain", headers={"content-type": "text/plain"})) == "plain"
    assert module._extract_upstream_code(_response(500, content=b"not json")) is None


def test_request_json_success_and_empty(client):
    module, http = client
    http.request.return_value = _response(200, json_body={"ok": True})
    assert module._request_aidp_json("http://aidp.example", "key", "GET", "/x", context="op") == {"ok": True}
    http.request.return_value = _response(204)
    assert module._request_aidp_json("http://aidp.example", "key", "GET", "/x", context="op") == {}


def test_request_json_error_paths(client):
    module, http = client
    http.request.return_value = _response(200, json_body=["bad"])
    with pytest.raises(module.AppException):
        module._request_aidp_json("http://aidp.example", "key", "GET", "/x", context="op")

    http.request.return_value = _response(200, content=b"not json")
    with pytest.raises(module.AppException):
        module._request_aidp_json("http://aidp.example", "key", "GET", "/x", context="op")

    http.request.side_effect = httpx.ConnectError("down")
    with pytest.raises(module.AppException):
        module._request_aidp_json("http://aidp.example", "key", "GET", "/x", context="op")


def test_validate_params_and_retry_wait(client):
    module, _ = client
    assert module._validate_params("http://aidp.example/", "key") == "http://aidp.example"
    with pytest.raises(module.AppException):
        module._validate_params("", "key")
    assert module._compute_retry_wait(_response(429, headers={"Retry-After": "2"}), 0) == 2.0
    assert module._compute_retry_wait(_response(429), 1) > 0


def test_resolve_folder_id(client):
    module, _ = client
    assert module._resolve_aidp_folder_id("s", "k", "kb", "/") == 0
    module_module = module
    original = module_module._get_aidp_folder_level
    module_module._get_aidp_folder_level = lambda *a, **kw: {"folders": []}
    try:
        with pytest.raises(module_module.AppException):
            module_module._resolve_aidp_folder_id("s", "k", "kb", "/missing")
    finally:
        module_module._get_aidp_folder_level = original


def test_path_builders_and_folder_level_params(client, monkeypatch):
    module, _ = client
    calls = []
    monkeypatch.setattr(
        module,
        "_request_aidp_json",
        lambda *a, **kw: calls.append((a, kw)) or {"folders": []},
    )
    assert module._get_folders_path("kb").endswith("/KnowledgeBases/kb/Folders")
    assert module._get_folder_tree_path("kb", 3).endswith("/Folders/3")
    assert module._join_folder_path("/", "a") == "/a"
    assert module._build_list_query(1, 20, " a ") == "?page=1&page_size=20&keyword=a"
    module._get_aidp_folder_level(
        "s",
        "k",
        "kb",
        0,
        "/",
        include_files=True,
        keyword=" k ",
        file_type=" pdf ",
        file_status=" 1 ",
    )
    params = calls[0][1]["params"]
    assert params["keyword"] == "k"
    assert params["file_type"] == "pdf"
    assert params["file_status"] == "1"


@pytest.mark.parametrize("status", [401, 403, 429, 500])
def test_http_error_mapping(client, status):
    module, _ = client
    response = _response(status, json_body={"error": {"message": "bad"}})
    error = httpx.HTTPStatusError("bad", request=response.request, response=response)
    with pytest.raises(module.AppException):
        module._raise_aidp_http_error(error, "op")
