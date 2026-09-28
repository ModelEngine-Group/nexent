#!/usr/bin/env python3
"""Deterministic OpenAI-compatible server for Nexent deployment tests.

The server is deliberately self-contained and never forwards requests to a
real provider. It implements the OpenAI surfaces used by Nexent and exposes a
small control API for selecting retry/failure scenarios.
"""

from __future__ import annotations

import argparse
import json
import re
import socket
import threading
import time
import uuid
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlsplit


SUPPORTED_SCENARIOS = {
    "success",
    "partial_then_success",
    "always_429",
    "always_503",
    "always_401",
    "empty_stop",
    "length",
}


@dataclass
class MockState:
    scenario: str = "success"
    response_text: str = "MOCK_SUCCESS"
    retry_after: float = 0.0
    partial_chunk_delay: float = 0.05
    request_count: int = 0
    requests: list[dict[str, Any]] = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def configure(self, payload: dict[str, Any]) -> dict[str, Any]:
        scenario = payload.get("scenario", "success")
        if scenario not in SUPPORTED_SCENARIOS:
            raise ValueError(f"unsupported scenario: {scenario}")
        with self.lock:
            self.scenario = scenario
            self.response_text = str(payload.get("response_text", "MOCK_SUCCESS"))
            self.retry_after = max(0.0, float(payload.get("retry_after", 0.0)))
            self.partial_chunk_delay = max(
                0.0, float(payload.get("partial_chunk_delay", 0.05))
            )
            self.request_count = 0
            self.requests.clear()
            return self._snapshot_unlocked()

    def record(self, payload: dict[str, Any], has_bearer_auth: bool) -> tuple[int, str]:
        with self.lock:
            self.request_count += 1
            request_number = self.request_count
            self.requests.append(
                {
                    "request_number": request_number,
                    "model": payload.get("model"),
                    "stream": payload.get("stream") is True,
                    "include_usage": (
                        isinstance(payload.get("stream_options"), dict)
                        and payload["stream_options"].get("include_usage") is True
                    ),
                    "message_count": len(payload.get("messages", [])),
                    "max_tokens": payload.get("max_tokens"),
                    "stop_count": len(payload.get("stop", []) or []),
                    "has_bearer_auth": has_bearer_auth,
                }
            )
            return request_number, self.scenario

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            return self._snapshot_unlocked()

    def _snapshot_unlocked(self) -> dict[str, Any]:
        return {
            "scenario": self.scenario,
            "response_text": self.response_text,
            "retry_after": self.retry_after,
            "request_count": self.request_count,
            "requests": list(self.requests),
        }


def _extract_requested_answer(payload: dict[str, Any], fallback: str) -> str:
    messages = payload.get("messages")
    if not isinstance(messages, list):
        return fallback
    text_parts: list[str] = []
    for message in reversed(messages):
        if not isinstance(message, dict) or message.get("role") != "user":
            continue
        content = message.get("content")
        if isinstance(content, str):
            text_parts.append(content)
        elif isinstance(content, list):
            text_parts.extend(
                str(item.get("text", ""))
                for item in content
                if isinstance(item, dict) and item.get("type") == "text"
            )
        break
    user_text = "\n".join(text_parts)
    match = re.search(
        r"reply\s+with\s+exactly\s+([A-Za-z0-9_.:-]+)", user_text, re.IGNORECASE
    )
    return match.group(1) if match else fallback


class OpenAICompatibleMockHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "NexentOpenAICompatibleMock/1.0"

    @property
    def state(self) -> MockState:
        return self.server.mock_state  # type: ignore[attr-defined]

    def log_message(self, _format: str, *_args: Any) -> None:
        return

    def _send_bytes(
        self, status: int, body: bytes, content_type: str = "application/json"
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("x-request-id", f"mock-{uuid.uuid4().hex}")
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        self._send_bytes(status, json.dumps(payload).encode())

    def _read_json(self) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, json.JSONDecodeError) as exc:
            raise ValueError("request body must be valid JSON") from exc
        if not isinstance(payload, dict):
            raise ValueError("request body must be a JSON object")
        return payload

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler contract
        path = urlsplit(self.path).path
        if path == "/__stats":
            self._send_json(HTTPStatus.OK, self.state.snapshot())
            return
        if path in {"/v1/models", "/models"}:
            self._send_json(
                HTTPStatus.OK,
                {
                    "object": "list",
                    "data": [
                        {
                            "id": "nexent-mock-model",
                            "object": "model",
                            "created": 0,
                            "owned_by": "nexent-test",
                        }
                    ],
                },
            )
            return
        self._send_error(HTTPStatus.NOT_FOUND, "not_found", "Unknown endpoint")

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler contract
        path = urlsplit(self.path).path
        try:
            payload = self._read_json()
        except ValueError as exc:
            self._send_error(HTTPStatus.BAD_REQUEST, "invalid_request_error", str(exc))
            return

        if path == "/__control":
            try:
                snapshot = self.state.configure(payload)
            except (TypeError, ValueError) as exc:
                self._send_error(HTTPStatus.BAD_REQUEST, "invalid_request_error", str(exc))
                return
            self._send_json(HTTPStatus.OK, snapshot)
            return

        if path not in {"/v1/chat/completions", "/chat/completions"}:
            self._send_error(HTTPStatus.NOT_FOUND, "not_found", "Unknown endpoint")
            return
        if not isinstance(payload.get("model"), str) or not isinstance(
            payload.get("messages"), list
        ):
            self._send_error(
                HTTPStatus.BAD_REQUEST,
                "invalid_request_error",
                "model and messages are required",
            )
            return

        has_bearer_auth = self.headers.get("Authorization", "").startswith("Bearer ")
        request_number, scenario = self.state.record(payload, has_bearer_auth)
        if scenario == "always_429":
            self._send_error(
                HTTPStatus.TOO_MANY_REQUESTS,
                "rate_limit_error",
                "Injected rate limit",
                retry_after=self.state.retry_after,
            )
            return
        if scenario == "always_503":
            self._send_error(
                HTTPStatus.SERVICE_UNAVAILABLE,
                "server_error",
                "Injected temporary outage",
                retry_after=self.state.retry_after,
            )
            return
        if scenario == "always_401":
            self._send_error(
                HTTPStatus.UNAUTHORIZED,
                "authentication_error",
                "Injected authentication failure",
            )
            return
        if scenario == "partial_then_success" and request_number == 1:
            self._send_partial_stream(payload)
            return

        finish_reason = "length" if scenario == "length" else "stop"
        answer = "" if scenario == "empty_stop" else _extract_requested_answer(
            payload, self.state.response_text
        )
        if payload.get("stream") is True:
            self._send_complete_stream(payload, answer, finish_reason)
        else:
            self._send_non_stream_response(payload, answer, finish_reason)

    def _send_error(
        self,
        status: int,
        error_type: str,
        message: str,
        *,
        retry_after: float | None = None,
    ) -> None:
        body = json.dumps(
            {
                "error": {
                    "message": message,
                    "type": error_type,
                    "param": None,
                    "code": error_type,
                }
            }
        ).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("x-request-id", f"mock-{uuid.uuid4().hex}")
        if retry_after is not None:
            self.send_header("Retry-After", str(retry_after))
        self.end_headers()
        self.wfile.write(body)

    @staticmethod
    def _completion_chunk(
        *,
        request_id: str,
        model: str,
        delta: dict[str, Any],
        finish_reason: str | None,
        usage: dict[str, int] | None = None,
        choices: bool = True,
    ) -> bytes:
        payload: dict[str, Any] = {
            "id": request_id,
            "object": "chat.completion.chunk",
            "created": int(time.time()),
            "model": model,
            "choices": (
                [{"index": 0, "delta": delta, "finish_reason": finish_reason}]
                if choices
                else []
            ),
        }
        if usage is not None:
            payload["usage"] = usage
        return f"data: {json.dumps(payload)}\n\n".encode()

    def _send_complete_stream(
        self, payload: dict[str, Any], answer: str, finish_reason: str
    ) -> None:
        request_id = f"chatcmpl-mock-{uuid.uuid4().hex}"
        model = payload["model"]
        code = f'<code>final_answer({json.dumps(answer)})</code>' if answer else ""
        chunks = [
            self._completion_chunk(
                request_id=request_id,
                model=model,
                delta={"role": "assistant", "content": ""},
                finish_reason=None,
            ),
            self._completion_chunk(
                request_id=request_id,
                model=model,
                delta={"reasoning_content": "Deterministic mock reasoning. "},
                finish_reason=None,
            ),
        ]
        chunks.extend(
            self._completion_chunk(
                request_id=request_id,
                model=model,
                delta={"content": code[index : index + 8]},
                finish_reason=None,
            )
            for index in range(0, len(code), 8)
        )
        chunks.extend(
            [
                self._completion_chunk(
                    request_id=request_id,
                    model=model,
                    delta={},
                    finish_reason=finish_reason,
                ),
                self._completion_chunk(
                    request_id=request_id,
                    model=model,
                    delta={},
                    finish_reason=None,
                    usage={
                        "prompt_tokens": 100,
                        "completion_tokens": max(1, len(code) // 4),
                        "total_tokens": 100 + max(1, len(code) // 4),
                    },
                    choices=False,
                ),
                b"data: [DONE]\n\n",
            ]
        )
        self._send_bytes(HTTPStatus.OK, b"".join(chunks), "text/event-stream")

    def _send_partial_stream(self, payload: dict[str, Any]) -> None:
        request_id = f"chatcmpl-mock-{uuid.uuid4().hex}"
        model = payload["model"]
        chunks = [
            self._completion_chunk(
                request_id=request_id,
                model=model,
                delta={"reasoning_content": f"CMSR_LEAK_{index:02d}"},
                finish_reason=None,
            )
            for index in range(12)
        ]
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Transfer-Encoding", "chunked")
        self.send_header("x-request-id", f"mock-{uuid.uuid4().hex}")
        self.end_headers()
        for chunk in chunks:
            self.wfile.write(f"{len(chunk):X}\r\n".encode() + chunk + b"\r\n")
            self.wfile.flush()
            time.sleep(self.state.partial_chunk_delay)
        self.close_connection = True
        try:
            self.connection.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.connection.close()

    def _send_non_stream_response(
        self, payload: dict[str, Any], answer: str, finish_reason: str
    ) -> None:
        code = f'<code>final_answer({json.dumps(answer)})</code>' if answer else ""
        self._send_json(
            HTTPStatus.OK,
            {
                "id": f"chatcmpl-mock-{uuid.uuid4().hex}",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": payload["model"],
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "reasoning_content": "Deterministic mock reasoning. ",
                            "content": code,
                        },
                        "finish_reason": finish_reason,
                    }
                ],
                "usage": {
                    "prompt_tokens": 100,
                    "completion_tokens": max(1, len(code) // 4),
                    "total_tokens": 100 + max(1, len(code) // 4),
                },
            },
        )


class OpenAICompatibleMockServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], state: MockState | None = None):
        self.mock_state = state or MockState()
        super().__init__(address, OpenAICompatibleMockHandler)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=18080)
    args = parser.parse_args()
    server = OpenAICompatibleMockServer((args.host, args.port))
    print(f"openai_compatible_mock_ready={args.host}:{args.port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
