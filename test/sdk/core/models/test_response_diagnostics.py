# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import json
from types import SimpleNamespace

from nexent.core.models.response_diagnostics import ResponseDiagnostics


def test_diagnostics_are_bounded_structural_and_private():
    capture = ResponseDiagnostics({"messages": [{"content": "private input"}], "api_key": "SECRET"}, capture_chunks=True)
    for i in range(30):
        capture.add(SimpleNamespace(id="response-1", model="model-1", choices=[SimpleNamespace(index=0, finish_reason="stop", delta=SimpleNamespace(content="private output SECRET", reasoning_content="private thinking", tool_calls=[{"arguments": "SECRET"}]))]))
    result = capture.summary()
    serialized = json.dumps(result)
    assert len(result["chunks"]) <= 8
    assert len(result["request_fingerprint"]) == 64
    for secret in ["private input", "private output", "private thinking", "SECRET", "arguments"]:
        assert secret not in serialized
    assert result["response_id"] == "response-1"


def test_default_diagnostics_do_not_retain_chunks():
    result = ResponseDiagnostics({"messages": []}).summary()
    assert "chunks" not in result


def test_only_safe_correlation_headers_are_recorded_and_credentials_do_not_change_fingerprint():
    capture = ResponseDiagnostics({"messages": ["input"], "api_key": "first", "headers": {"cookie": "secret"}})
    changed_key = ResponseDiagnostics({"messages": ["input"], "api_key": "second", "headers": {"cookie": "other"}})
    assert capture.fingerprint == changed_key.fingerprint
    response = SimpleNamespace(headers={"x-request-id": "unsafe\ncontent", "x-tt-logid": "safe-id",
                                        "authorization": "SECRET"})
    result = capture.summary(SimpleNamespace(_stream=SimpleNamespace(response=response)))
    assert result["provider_request_id"] == "safe-id"
    assert "SECRET" not in json.dumps(result)
    capture.add(SimpleNamespace(id="unsafe\ntext", model="unsafe@text", choices=[]))
    assert capture.summary()["response_id"] is None
    assert capture.summary()["response_model"] is None
