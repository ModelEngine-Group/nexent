# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Run-owned loopback HTTP peer; never connects to a hosted service."""

import json
import socket
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit


def frame(delta=None, finish=None, **extra):
    document = {
        "id": "peer-response",
        "model": "qwen3.5-plus",
        "choices": [
            {"index": 0, "delta": delta or {}, "finish_reason": finish},
        ],
    } | extra
    # Multiple data lines form one JSON document, exercising actual SSE framing.
    text = json.dumps(document, ensure_ascii=False)
    return (
        "data: " + text.replace(', "choices":', ',\ndata: "choices":') + "\r\n\r\n"
    ).encode()


def stream_frames():
    return [
        b"\xef\xbb\xbf: comment\r\n\r\n",
        frame({"role": "assistant", "reasoning_content": "consider"}),
        frame({"content": "中间正文"}),
        frame(
            {
                "tool_calls": [
                    {
                        "index": 0,
                        "id": "call-peer",
                        "type": "function",
                        "function": {"name": "test_tool", "arguments": '{"n":'},
                    }
                ]
            }
        ),
        frame({"tool_calls": [{"index": 0, "function": {"arguments": "0}"}}]}),
        frame(finish="tool_calls"),
        b'data: {"choices":[],"usage":{"prompt_tokens":10,"completion_tokens":5,"total_tokens":15}}\n\n',
        b"data: [DONE]\n\n",
    ]


class Peer(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def record(self, value):
        with self.server.journal.open("a") as handle:
            handle.write(json.dumps(value, ensure_ascii=False) + "\n")

    def json_response(self, status, body):
        payload = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(payload)

    def chunk(self, payload):
        # Actual chunked HTTP boundaries split UTF-8 and SSE newlines arbitrarily.
        for index in range(0, len(payload), 3):
            fragment = payload[index : index + 3]
            self.wfile.write(f"{len(fragment):x}\r\n".encode() + fragment + b"\r\n")
            self.wfile.flush()

    def do_POST(self):
        scenario = parse_qs(urlsplit(self.path).query)["scenario"][0]
        self.server.counts[scenario] = self.server.counts.get(scenario, 0) + 1
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.record(
            {
                "kind": "request",
                "path": self.path,
                "scenario": scenario,
                "attempt": self.server.counts[scenario],
                "body": body,
                "authorization": self.headers.get("Authorization"),
                "gateway": self.headers.get("X-Gateway"),
            }
        )
        self.close_connection = True
        disconnected = False
        try:
            if scenario in {"error_json", "error_text"}:
                reason = "top_p must be 0.95; dummy-loopback"
                if scenario == "error_json":
                    return self.json_response(400, {"error": {"message": reason, "param": "top_p"}})
                raw = reason.encode()
                self.send_response(500)
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
                return
            if scenario == "auth":
                return self.json_response(
                    401, {"error": {"message": "provider rejected dummy-loopback"}}
                )
            if (
                scenario == "exhaust"
                or scenario == "legacy_empty_budget" and self.server.counts[scenario] == 1
                or scenario == "legacy_context_budget" and self.server.counts[scenario] == 1
                or scenario == "retry"
                and self.server.counts[scenario] == 1
            ):
                return self.json_response(
                    503, {"error": {"message": "provider rejected dummy-loopback"}}
                )
            if scenario == "legacy_context_budget" and self.server.counts[scenario] == 2:
                return self.json_response(400, {"error": {
                    "code": "context_length_exceeded", "message": "provider rejected dummy-loopback",
                }})
            if scenario == "disconnect" and self.server.counts[scenario] == 1:
                self.connection.shutdown(socket.SHUT_RDWR)
                return
            if scenario == "header_stall":
                self.record({"kind": "waiting", "scenario": scenario})
                self.connection.settimeout(3)
                disconnected = self.connection.recv(1) == b""
                return
            if not body["stream"]:
                return self.json_response(
                    200,
                    {
                        "choices": [
                            {
                                "index": 0,
                                "message": {
                                    "role": "assistant",
                                    "content": "answer",
                                    "reasoning_content": "consider",
                                },
                                "finish_reason": "stop",
                            }
                        ],
                        "usage": {
                            "prompt_tokens": 10,
                            "completion_tokens": 5,
                            "total_tokens": 15,
                        },
                    },
                )
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Transfer-Encoding", "chunked")
            self.send_header("Connection", "close")
            self.end_headers()
            if scenario == "stall":
                self.chunk(b": waiting\n\n")
                self.record({"kind": "waiting", "scenario": scenario})
                self.connection.settimeout(3)
                disconnected = self.connection.recv(1) == b""
                return
            if scenario == "vllm_023_tail":
                sample = Path(__file__).resolve().parents[3] / "test/fixtures/model_service/vllm_023_glm_tail.sse"
                self.chunk(sample.read_bytes())
            elif scenario == "late_content":
                self.chunk(frame({"content": "ok"}, finish="stop"))
                self.chunk(frame({"content": "late"}))
                self.chunk(b"data: [DONE]\n\n")
            elif scenario in {"compatible_duplicate", "compatible_eof", "usage_conflict"}:
                usage = {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
                self.chunk(frame({"content": "compatible"}, finish="stop", usage=usage))
                if scenario == "usage_conflict":
                    usage = {"prompt_tokens": 10, "completion_tokens": 6, "total_tokens": 16}
                self.chunk(("data: " + json.dumps({"choices": [], "usage": usage}) + "\n\n").encode())
                if scenario != "compatible_eof":
                    self.chunk(b"data: [DONE]\n\n")
            elif scenario in {"legacy_empty_fail", "legacy_reasoning_empty"} or (
                scenario == "legacy_empty_budget" and self.server.counts[scenario] == 2
            ):
                if scenario == "legacy_reasoning_empty":
                    self.chunk(frame({"reasoning_content": "thought"}))
                self.chunk(frame(finish="stop"))
                self.chunk(b'data: {"choices":[],"usage":{"prompt_tokens":10,"completion_tokens":0}}\n\n')
                self.chunk(b"data: [DONE]\n\n")
            elif scenario == "malformed":
                self.chunk(b"data: invalid-json\n\n")
            elif scenario in {"truncate", "visible_disconnect"}:
                self.chunk(frame({"content": "partial"}))
                if scenario == "visible_disconnect":
                    self.connection.shutdown(socket.SHUT_RDWR)
                    return
            else:
                for payload in stream_frames():
                    self.chunk(payload)
            self.wfile.write(b"0\r\n\r\n")
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            disconnected = True
        except TimeoutError:
            self.record({"kind": "peer_timeout", "scenario": scenario})
        finally:
            self.record(
                {"kind": "finished", "scenario": scenario, "disconnected": disconnected}
            )


if __name__ == "__main__":
    server = HTTPServer(("127.0.0.1", 0), Peer)
    server.journal = Path(sys.argv[2])
    server.counts = {}
    Path(sys.argv[1]).write_text(str(server.server_port))
    try:
        server.serve_forever(poll_interval=0.05)
    finally:
        server.server_close()
