from __future__ import annotations

import http.client
import json
import threading
import urllib.error
import urllib.request

import pytest

from test.common.openai_compatible_mock_server import OpenAICompatibleMockServer


@pytest.fixture()
def mock_server():
    server = OpenAICompatibleMockServer(("127.0.0.1", 0))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server, server.server_address[1]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _post_json(port: int, path: str, payload: dict):
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=json.dumps(payload).encode(),
        headers={"Authorization": "Bearer test-key", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=3) as response:
        return response.status, dict(response.headers), response.read()


def _stream_content(body: bytes) -> str:
    content_parts = []
    for line in body.decode().splitlines():
        if not line.startswith("data: ") or line == "data: [DONE]":
            continue
        payload = json.loads(line[6:])
        for choice in payload.get("choices", []):
            content = choice.get("delta", {}).get("content")
            if content:
                content_parts.append(content)
    return "".join(content_parts)


def test_cmsr_mock_stream_matches_nexent_openai_contract(mock_server):
    _server, port = mock_server
    status, _headers, body = _post_json(
        port,
        "/v1/chat/completions",
        {
            "model": "nexent-mock-model",
            "messages": [{"role": "user", "content": "Reply with exactly CONTRACT_OK"}],
            "stream": True,
            "stream_options": {"include_usage": True},
            "max_tokens": 512,
            "stop": ["Observation:"],
        },
    )

    assert status == 200
    assert b'"object": "chat.completion.chunk"' in body
    assert b'"reasoning_content": "Deterministic mock reasoning. "' in body
    assert _stream_content(body) == '<code>final_answer("CONTRACT_OK")</code>'
    assert b'"finish_reason": "stop"' in body
    assert b'"prompt_tokens": 100' in body
    assert body.endswith(b"data: [DONE]\n\n")

    stats = _server.mock_state.snapshot()
    assert stats["request_count"] == 1
    assert stats["requests"] == [
        {
            "request_number": 1,
            "model": "nexent-mock-model",
            "stream": True,
            "include_usage": True,
            "message_count": 1,
            "max_tokens": 512,
            "stop_count": 1,
            "has_bearer_auth": True,
        }
    ]


@pytest.mark.parametrize(
    ("scenario", "expected_status", "expected_type"),
    [
        ("always_429", 429, "rate_limit_error"),
        ("always_503", 503, "server_error"),
        ("always_401", 401, "authentication_error"),
    ],
)
def test_cmsr_mock_standard_error_contract(
    mock_server, scenario, expected_status, expected_type
):
    _server, port = mock_server
    _post_json(port, "/__control", {"scenario": scenario, "retry_after": 0.25})

    with pytest.raises(urllib.error.HTTPError) as caught:
        _post_json(
            port,
            "/v1/chat/completions",
            {"model": "nexent-mock-model", "messages": [], "stream": True},
        )

    assert caught.value.code == expected_status
    error = json.loads(caught.value.read())
    assert error["error"]["type"] == expected_type
    if expected_status in {429, 503}:
        assert caught.value.headers["Retry-After"] == "0.25"


def test_cmsr_mock_partial_then_success_is_deterministic(mock_server):
    server, port = mock_server
    _post_json(
        port,
        "/__control",
        {
            "scenario": "partial_then_success",
            "response_text": "RECOVERED",
            "partial_chunk_delay": 0,
        },
    )
    request_body = json.dumps(
        {"model": "nexent-mock-model", "messages": [], "stream": True}
    )

    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
    connection.request(
        "POST",
        "/v1/chat/completions",
        body=request_body,
        headers={"Content-Type": "application/json", "Authorization": "Bearer test"},
    )
    response = connection.getresponse()
    with pytest.raises(http.client.IncompleteRead) as caught:
        response.read()
    assert b"CMSR_LEAK_00" in caught.value.partial
    assert b"CMSR_LEAK_11" in caught.value.partial
    connection.close()

    status, _headers, body = _post_json(
        port,
        "/v1/chat/completions",
        {"model": "nexent-mock-model", "messages": [], "stream": True},
    )
    assert status == 200
    assert _stream_content(body) == '<code>final_answer("RECOVERED")</code>'
    assert server.mock_state.snapshot()["request_count"] == 2


def test_cmsr_mock_can_pause_after_first_success_content(mock_server):
    server, port = mock_server
    _post_json(
        port,
        "/__control",
        {
            "scenario": "success",
            "response_text": "PAUSED_OK",
            "pause_after_success_chunks": 3,
        },
    )
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
    connection.request(
        "POST",
        "/v1/chat/completions",
        body=json.dumps(
            {"model": "nexent-mock-model", "messages": [], "stream": True}
        ),
        headers={"Content-Type": "application/json", "Authorization": "Bearer test"},
    )
    response = connection.getresponse()
    prefix = b"".join(response.readline() for _ in range(6))
    assert response.status == 200
    assert _stream_content(prefix).startswith("<code>fi")
    assert server.mock_state.snapshot()["success_stream_paused"] is True
    _post_json(port, "/__release", {})
    assert _stream_content(prefix + response.read()) == (
        '<code>final_answer("PAUSED_OK")</code>'
    )
    connection.close()


def test_cmsr_mock_can_emit_code_without_reasoning(mock_server):
    _server, port = mock_server
    _post_json(
        port,
        "/__control",
        {"scenario": "success", "response_text": "CODE_ONLY", "emit_reasoning": False},
    )
    status, _headers, body = _post_json(
        port,
        "/v1/chat/completions",
        {"model": "nexent-mock-model", "messages": [], "stream": True},
    )
    assert status == 200
    assert b"reasoning_content" not in body
    assert _stream_content(body) == '<code>final_answer("CODE_ONLY")</code>'


def test_cmsr_mock_invalid_protocol_then_valid_repair(mock_server):
    server, port = mock_server
    _post_json(
        port,
        "/__control",
        {"scenario": "invalid_then_success", "response_text": "REPAIR_OK"},
    )
    request = {"model": "nexent-mock-model", "messages": [], "stream": True}
    first = _post_json(port, "/v1/chat/completions", request)
    second = _post_json(port, "/v1/chat/completions", request)
    assert _stream_content(first[2]) == "INVALID_SEMANTIC_FIRST <code></code>"
    assert _stream_content(second[2]) == '<code>final_answer("REPAIR_OK")</code>'
    assert server.mock_state.snapshot()["request_count"] == 2


def test_cmsr_mock_non_stream_and_models_contract(mock_server):
    _server, port = mock_server
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/v1/models", timeout=3) as response:
        models = json.loads(response.read())
    assert models["data"][0]["id"] == "nexent-mock-model"

    status, _headers, body = _post_json(
        port,
        "/v1/chat/completions",
        {"model": "nexent-mock-model", "messages": [], "stream": False},
    )
    completion = json.loads(body)
    assert status == 200
    assert completion["object"] == "chat.completion"
    assert completion["choices"][0]["finish_reason"] == "stop"
    assert completion["usage"]["total_tokens"] > 100
