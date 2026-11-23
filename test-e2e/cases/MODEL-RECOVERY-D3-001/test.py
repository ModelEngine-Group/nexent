# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Exercise the real adapter, observer and HTTP/SSE client boundary."""

import json
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import pytest

from nexent.core.model_errors import ModelInvocationTerminalError
from nexent.core.models.openai_llm import OpenAIModel
from nexent.core.models.retry import ModelRetryConfig
from nexent.core.utils.observer import MessageObserver

pytestmark = [pytest.mark.case_id("MODEL-RECOVERY-D3-001"), pytest.mark.stage("D3")]
SECRET = "SYNTHETIC_PRIVATE_CONTENT"
HEADER_CANARY = "SYNTHETIC_UNAPPROVED_HEADER"


@contextmanager
def provider(sequence):
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            requests.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            item = sequence[min(len(requests) - 1, len(sequence) - 1)]
            chunk = {
                "id": "response-safe-id", "object": "chat.completion.chunk", "created": 1,
                "model": "provider-actual-version", "choices": [{
                    "index": 0, "delta": item[0], "finish_reason": item[1],
                }],
            }
            body = ("data: " + json.dumps(chunk) + "\n\ndata: [DONE]\n\n").encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("x-request-id", "provider-safe-id")
            self.send_header("x-diagnostic-test-marker", HEADER_CANARY)
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    observer = MessageObserver()
    model = OpenAIModel(
        observer=observer, model_id="verified-model", api_key="synthetic-key",
        api_base=f"http://127.0.0.1:{server.server_port}/v1",
        temperature=0.7, top_p=0.9, max_output_tokens=512,
        extra_body={"enable_thinking": False},
        reasoning_capability={"status": "supported", "control": "effort", "source": "models_dev",
                              "provider_id": "OpenAI-API-Compatible", "wire_format": "reasoning_effort",
                              "toggle_wire_format": "thinking_object"},
        retry_config=ModelRetryConfig(max_attempts=5, backoff_base_seconds=0, jitter=False),
        diagnostic_chunks_enabled=True,
    )
    try:
        yield model, observer, requests
    finally:
        model.client.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def phases(observer):
    return [event["phase"] for raw in observer.message_query
            if (event := json.loads(raw)).get("type") == "model_attempt_control"]


def test_recovery_preserves_wire_and_rolls_back_failed_attempt():
    with provider([
        ({"role": "assistant", "reasoning_content": SECRET}, "stop"),
        ({"role": "assistant", "content": "<final_answer>RECOVERED</final_answer>"}, "stop"),
    ]) as (model, observer, requests):
        result = model([{"role": "user", "content": "A frozen prompt"}])
        assert result.content == "<final_answer>RECOVERED</final_answer>"
        assert len(requests) == 2 and requests[0] == requests[1]
        assert requests[0]["thinking"] == {"type": "disabled"}
        assert "enable_thinking" not in requests[0]
        assert requests[0]["temperature"] == 0.7 and requests[0]["top_p"] == 0.9
        assert requests[0]["max_tokens"] == 512
        assert phases(observer) == ["begin", "rollback", "begin", "commit"]
        events = [json.loads(raw) for raw in observer.message_query]
        committed_id = next(event["attempt_id"] for event in events if event.get("phase") == "commit")
        committed = [event for event in events if event.get("attempt_id") == committed_id]
        assert "RECOVERED" in json.dumps(committed)
        assert SECRET not in json.dumps(committed)


@pytest.mark.parametrize("finish,tools,expected", [
    ("stop", False, 2), ("length", False, 1), (None, False, 1), ("stop", True, 1),
])
def test_terminal_bounds_and_private_diagnostics(caplog, finish, tools, expected):
    delta = {"role": "assistant", "reasoning_content": SECRET}
    if tools:
        delta["tool_calls"] = [{"index": 0, "id": "call-1", "type": "function",
                                "function": {"name": "unused", "arguments": SECRET}}]
    with provider([(delta, finish)]) as (model, observer, requests):
        with pytest.raises(ModelInvocationTerminalError):
            model([{"role": "user", "content": "PRIVATE_PROMPT"}])
        assert len(requests) == expected
        assert all(request == requests[0] for request in requests)
        assert phases(observer) == [phase for _ in range(expected) for phase in ("begin", "rollback")]
        diagnostics = model.last_response_diagnostics
        assert diagnostics["response_id"] == "response-safe-id"
        assert diagnostics["response_model"] == "provider-actual-version"
        assert diagnostics["provider_request_id"] == "provider-safe-id"
        assert len(diagnostics["request_fingerprint"]) == 64
        assert "event=empty_model_response_diagnostics" in caplog.text
        for private in (SECRET, "PRIVATE_PROMPT", "synthetic-key", "set-cookie",
                        HEADER_CANARY, "x-diagnostic-test-marker"):
            assert private not in caplog.text
        assert '"chunks"' in caplog.text
