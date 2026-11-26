# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Coverage for the AIDP sensitive-word service layer."""

from __future__ import annotations

import importlib

import httpx
import pytest


def _response(payload, status=200):
    return httpx.Response(
        status,
        json=payload,
        request=httpx.Request("GET", "http://aidp.example/x"),
    )


@pytest.fixture
def service(monkeypatch):
    module = importlib.import_module(
        "ext_components.aidp.services.aidp_sensitive_word_service"
    )
    responses = {
        "GET": _response(
            {
                "data": {
                    "value": [
                        {"id": 1, "word": "bad", "mode": "BLACK", "description": "d"},
                        "bad",
                    ],
                    "total_count": 1,
                }
            }
        ),
        "PUT": _response({"data": {"id": 2}}),
        "PATCH": _response({}),
        "DELETE": _response({}, 204),
    }
    calls: list[tuple] = []

    def request(method, *_args, **_kwargs):
        calls.append((method, _args, _kwargs))
        if method == "GET" and len(calls) > 1:
            return _response(
                {"data": {"id": 1, "word": "bad", "mode": "BLACK", "description": "d"}}
            )
        return responses[method]

    monkeypatch.setattr(module, "_validate_params", lambda *a: "http://aidp.example")
    monkeypatch.setattr(module, "_request", request)
    return module, calls


def test_sensitive_word_crud(service):
    module, calls = service
    listed = module.list_sensitive_words_impl(
        "s", "k", "kb", 1, 20, keyword=" bad ", mode="BLACK"
    )
    assert listed["value"][0]["id"] == "1"
    assert listed["total_count"] == 1
    assert module.get_sensitive_word_impl("s", "k", "kb", "1")["word"] == "bad"
    assert module.create_sensitive_word_impl("s", "k", "kb", "bad", "BLACK", "d") == {
        "id": "2"
    }
    assert module.update_sensitive_word_impl("s", "k", "kb", "1", {"word": "w"}) == {}
    assert module.delete_sensitive_word_impl("s", "k", "kb", "1") is True
    assert len(calls) == 5


def test_sensitive_word_rejects_malformed_list(service, monkeypatch):
    module, _ = service
    monkeypatch.setattr(module, "_request", lambda *a, **kw: _response({"data": {}}))
    with pytest.raises(module.AppException):
        module.list_sensitive_words_impl("s", "k", "kb", 1, 20)


def test_sensitive_normalization_branches(service):
    module, _ = service
    assert module._normalize_mode("black") == "BLACK"
    assert module._normalize_mode("bad") == ""
    assert module._normalize_item({"word_id": 3, "word": "w"})["id"] == "3"
    assert module._normalize_item({"id": None, "word": ""}) is None
    assert module._normalize_item("bad") is None


def test_sensitive_response_shape_failure(service):
    module, _ = service
    with pytest.raises(module.AppException):
        module._response_json(_response(["bad"]))
