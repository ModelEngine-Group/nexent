# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Prepared HTTP boundary validation without external I/O."""

import json

import pytest
from nexent.core.model_service.http_contracts import (
    PreparedHttpRequest,
    model_request_url,
    validate_headers,
)
from nexent.core.model_service.profiles.resolved_profile import CredentialReference


def prepared(**overrides):
    values = {
        "request_id": "request-1",
        "method": "POST",
        "base_url": "https://example.test/v1?api-version=1",
        "relative_path": "chat/completions",
        "headers": {},
        "credential_ref": CredentialReference(kind="none", model_id=None),
        "json_body": {"model": "exact-model", "messages": []},
        "timeout_seconds": 10,
        "ssl_verify": True,
    }
    return PreparedHttpRequest(**(values | overrides))


def test_exact_root_query_and_body_are_preserved_and_detached():
    body = {
        "model": "exact-model",
        "messages": [{"content": "中文"}],
        "temperature": 0,
        "enable_thinking": False,
    }
    headers = {"Accept": "application/json"}
    request = prepared(json_body=body, headers=headers)
    body["messages"][0]["content"] = "mutated"
    headers["Accept"] = "changed"
    assert request.url == "https://example.test/v1/chat/completions?api-version=1"
    assert json.loads(request.body_bytes)["messages"] == [{"content": "中文"}]
    assert json.loads(request.body_bytes)["temperature"] == 0
    assert json.loads(request.body_bytes)["enable_thinking"] is False
    assert request.headers == {"accept": "application/json"}
    with pytest.raises(TypeError):
        request.headers["accept"] = "changed"
    assert "中文" not in repr(request)
    assert "api-version" not in repr(request)


@pytest.mark.parametrize(
    "root,path",
    [
        ("ftp://example.test", "chat"),
        ("https://user:password@example.test", "chat"),
        ("https://example.test/#fragment", "chat"),
        ("https://example.test:99999", "chat"),
        ("https://example.test", "https://other.test/chat"),
        ("https://example.test", "//other.test/chat"),
        ("https://example.test", "../chat"),
        ("https://example.test", "x/%2e%2e/chat"),
        ("https://example.test", "chat?token=private"),
        ("https://example.test", "chat#x"),
        ("https://example.test", "chat\\x"),
        ("https://example.test", "chat//x"),
        ("https://example.test", ""),
        ("https://example.test\n", "chat"),
        (None, "chat"),
    ],
)
def test_url_rejects_credentials_and_root_overrides_with_safe_error(root, path):
    with pytest.raises(ValueError, match="^Invalid model HTTP URL$"):
        model_request_url(root, path)


@pytest.mark.parametrize(
    "headers",
    [
        {"Authorization": "private"},
        {"Host": "other.test"},
        {"a": "private\n"},
        {"bad name": "private"},
        {"A": "1", "a": "2"},
        {"a": 3},
        None,
        {"x-api-key": "private"},
        {"a": "中文"},
    ],
)
def test_fixed_headers_do_not_accept_auth_transport_or_invalid_values(headers):
    with pytest.raises(ValueError, match="^Invalid model HTTP headers$"):
        validate_headers(headers)


def test_explicit_credential_headers_accept_authorization_without_exposing_value():
    assert validate_headers({"Authorization": "Bearer dummy"}, credentials=True) == {
        "authorization": "Bearer dummy"
    }


@pytest.mark.parametrize(
    "overrides",
    [
        {"timeout_seconds": 0},
        {"timeout_seconds": float("nan")},
        {"timeout_seconds": float("inf")},
        {"timeout_seconds": True},
        {"ssl_verify": 1},
        {"method": "DELETE"},
        {"stream_protocol": "unknown"},
        {"json_body": []},
        {"request_id": " "},
        {"credential_ref": {}},
    ],
)
def test_invalid_prepared_request_is_rejected(overrides):
    with pytest.raises(ValueError, match="^Invalid prepared model HTTP request$"):
        prepared(**overrides)


@pytest.mark.parametrize(
    "body", [{"value": float("nan")}, {"value": object()}, {"value": "\ud800"}]
)
def test_invalid_json_body_is_rejected_without_payload_echo(body):
    with pytest.raises(ValueError, match="^Invalid model HTTP body$"):
        prepared(json_body=body)


def test_leading_path_separator_preserves_api_root():
    assert (
        model_request_url("https://example.test/v1", "/chat/completions")
        == "https://example.test/v1/chat/completions"
    )
