# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Native tool continuation through the real compatibility/HTTP/SSE pipeline."""

import json
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import pytest
from smolagents import Tool

from nexent.core.model_service.compatibility.legacy_chat_model import LegacyChatModel
from nexent.core.model_service.profiles.resolved_profile import ResolvedModelProfile
from shared.model_service_profiles import resolved_profile_for_test

pytestmark = [pytest.mark.case_id("MODEL-LEGACY-TOOLS-D3-001"), pytest.mark.stage("D3")]


@pytest.mark.parametrize("assistant_kind", ["object", "dictionary"])
@pytest.mark.parametrize("tool_role", ["tool", "tool-response"])
@pytest.mark.parametrize("streaming", [False, True])
def test_native_tool_continuation(assistant_kind, tool_role, streaming):
    requests = []
    executions = []
    expected_calls = [{"id": "call-" + str(i), "type": "function",
                       "function": {"name": "calculate", "arguments": '{"value":  ' + str(i) + '}'}}
                      for i in range(2)]

    class Calculate(Tool):
        name = "calculate"
        description = "Calculate the supplied integer."
        inputs = {"value": {"type": "integer", "description": "Input value"}}
        output_type = "integer"

        def forward(self, value):
            executions.append(value)
            return value

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            requests.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            first = len(requests) == 1
            delta = ({"role": "assistant", "tool_calls": [dict(call, index=i)
                      for i, call in enumerate(expected_calls)]} if first else {"content": "DONE"})
            chunk = {"id": "controlled-response", "model": "controlled-model",
                     "choices": [{"index": 0, "delta": delta,
                                  "finish_reason": "tool_calls" if first else "stop"}]}
            body = ("data: " + json.dumps(chunk) + "\n\ndata: [DONE]\n\n").encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        snapshot = resolved_profile_for_test(f"http://127.0.0.1:{server.server_port}/v1").model_dump(mode="json")
        snapshot["capabilities"]["tools"]["status"] = "supported"
        model = LegacyChatModel.from_profile(ResolvedModelProfile.model_validate(snapshot), "synthetic-key")
        tools = [Calculate()]
        first = model.generate([{"role": "user", "content": "Calculate two values"}], tools_to_call_from=tools)
        assert [call.id for call in first.tool_calls] == ["call-0", "call-1"]
        assert [call.function.arguments for call in first.tool_calls] == [call["function"]["arguments"] for call in expected_calls]
        assistant = first if assistant_kind == "object" else {"role": "assistant", "content": None,
                                                               "tool_calls": deepcopy(expected_calls)}
        history = [{"role": "user", "content": "Calculate two values"}, assistant,
                   {"role": tool_role, "tool_call_id": "call-0", "content": "10"},
                   {"role": tool_role, "tool_call_id": "call-1", "content": "20"}]
        original = deepcopy(history)
        result = ("".join(delta.content or "" for delta in model.generate_stream(history, tools_to_call_from=tools))
                  if streaming else model.generate(history, tools_to_call_from=tools).content)
        assert result == "DONE" and len(requests) == 2 and history == original
        assert requests[0]["tools"][0]["function"]["name"] == "calculate"
        wire = requests[1]["messages"]
        assert len(wire) == 4 and wire[0]["role"] == "user" and wire[1]["role"] == "assistant"
        assert wire[1]["tool_calls"] == expected_calls
        assert wire[2:] == [{"role": "tool", "tool_call_id": "call-0", "content": "10"},
                           {"role": "tool", "tool_call_id": "call-1", "content": "20"}]
        assert executions == []
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
        assert not thread.is_alive()
