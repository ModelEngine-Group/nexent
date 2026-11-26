# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Controlled OpenAI wire responses for actual Jiuwen Runner execution."""

import json
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Event, Thread

from shared.model_service_profiles import resolved_profile_for_test

from nexent.core.agents.contracts.config import ModelConfig


def model_config(base, tenant, role, number):
    url = base + "/" + role + "/v1"
    profile = resolved_profile_for_test(url)
    data = profile.model_dump()
    data["outlet_id"] = number
    data["identity"]["tenant_id"] = tenant
    data["connection"]["credential_ref"]["model_id"] = number
    profile = type(profile).model_validate(data)
    assert profile.capabilities.tools.status == "supported"
    return ModelConfig(cite_name=role, model_name=profile.identity.request_model_id,
                       url=url, api_key="synthetic", resolved_profile=profile)


@contextmanager
def provider(mode, *, child_answer=None):
    requests = []
    child_started, release = Event(), Event()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            role = "child" if "/child/" in self.path else "root"
            requests.append({"role": role, "stream": bool(payload.get("stream")), "payload": payload})
            ordinal = sum(item["role"] == role for item in requests)
            if role == "child":
                child_started.set()
            if (mode == "root_failed" and role == "root") or (
                    mode == "child_failed" and role == "child"):
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": {"message": "controlled failure",
                                                       "type": "invalid_request_error"}}).encode())
                return
            if mode == "cancelled" and role == "child":
                if not release.wait(15):
                    return
            calls = []
            if role == "root" and ordinal == 1:
                calls = [{"id": f"delegate-{i}", "type": "function",
                          "function": {"name": "child", "arguments": json.dumps({"task": f"task-{i}"})}}
                         for i in (1, 2)]
            answer = child_answer(payload) if role == "child" and child_answer else f"{role}-ready"
            content = "" if calls else f"<final_answer>{answer}</final_answer>"
            reason = "tool_calls" if calls else "stop"
            usage = None
            if role == "root":
                usage = {"prompt_tokens": 10 if ordinal == 1 else 20,
                         "completion_tokens": 2 if ordinal == 1 else 3,
                         "total_tokens": 12 if ordinal == 1 else 23}
            elif ordinal == 1:
                usage = {"prompt_tokens": 100, "completion_tokens": 0, "total_tokens": 100}
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream" if payload.get("stream") else "application/json")
            self.end_headers()
            try:
                if payload.get("stream"):
                    delta = {"tool_calls": [{"index": i, **call} for i, call in enumerate(calls)]} if calls else (
                        {"content": content}
                    )
                    chunk = {"id": f"{role}-{ordinal}", "object": "chat.completion.chunk", "created": 1,
                             "model": payload["model"],
                             "choices": [{"index": 0, "delta": delta, "finish_reason": reason}]}
                    if usage is not None:
                        chunk["usage"] = usage
                    self.wfile.write(f"data: {json.dumps(chunk)}\n\ndata: [DONE]\n\n".encode())
                else:
                    message = {"role": "assistant", "content": content}
                    if calls:
                        message["tool_calls"] = calls
                    result = {"id": f"{role}-{ordinal}", "object": "chat.completion", "created": 1,
                              "model": payload["model"],
                              "choices": [{"index": 0, "message": message, "finish_reason": reason}]}
                    if usage is not None:
                        result["usage"] = usage
                    self.wfile.write(json.dumps(result).encode())
            except (BrokenPipeError, ConnectionResetError):
                if mode != "cancelled":
                    raise

    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        worker = Thread(target=server.serve_forever)
        worker.start()
        try:
            yield f"http://127.0.0.1:{server.server_port}", requests, child_started, release
        finally:
            release.set()
            server.shutdown()
            worker.join(timeout=5)
            assert not worker.is_alive()
