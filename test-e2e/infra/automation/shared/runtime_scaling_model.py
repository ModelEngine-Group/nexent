# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Case-owned model endpoint for a Run blocked at its first model invocation."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import re
import sys
from threading import Event, Lock
from uuid import UUID


MODEL_NAME = "runtime-scaling-fixture"
INPUT_NAME = "runtime-input.txt"
OUTPUT_NAME = "runtime-artifact.txt"
TURN_TAG = r"[a-z][a-z0-9-]{0,31}"
MODEL_MODES = frozenset({"storage", "storage-pair", "admission", "stream", "scheduler", "maintenance"})


def fixture_server(token, host="0.0.0.0", port=8090, *, mode="storage"):
    if UUID(hex=token).hex != token or mode not in MODEL_MODES:
        raise ValueError("Expected the Runtime scaling run ID and a supported fixture mode")
    streams_with_barrier = mode in {"stream", "scheduler", "maintenance"}
    storage_pair = mode == "storage-pair"
    first_model_call, release = Event(), Event()
    lock = Lock()
    counts = {"stream_calls": 0, "unexpected_calls": 0}
    if mode in {"admission", "stream", "maintenance"}:
        counts["auxiliary_calls"] = 0
    calls_by_tag = {}
    stream_barriers = {tag: Event() for tag in ("a", "b")} if storage_pair else {}
    auxiliary_tags = set()
    tag_mode = "stream" if streams_with_barrier else mode
    tagged_query = re.compile(rf"runtime-{tag_mode}:{token}:({TURN_TAG})\b(?!-)")
    marker = f"runtime-storage-run:{token}"
    artifact_code = f'<code>\nprint(upload_to_s3("inputs/000_{INPUT_NAME}", "{OUTPUT_NAME}"))\n</code>'
    answer = f"<final_answer>runtime-storage-completed:{token}</final_answer>"

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            return

        def json_response(self, status, value):
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(value).encode())

        def do_GET(self):
            if self.path == "/ready":
                return self.json_response(200, {"ready": True})
            if self.path == "/probe" and self.client_address[0] == "127.0.0.1":
                with lock:
                    snapshot = {**counts, "entered": first_model_call.is_set(), "released": release.is_set()}
                    if mode == "admission" or streams_with_barrier or storage_pair:
                        snapshot["calls_by_tag"] = dict(calls_by_tag)
                    if storage_pair:
                        snapshot["released_tags"] = sorted(tag for tag, event in stream_barriers.items() if event.is_set())
                    if mode == "admission":
                        snapshot["auxiliary_tags"] = sorted(auxiliary_tags)
                return self.json_response(200, snapshot)
            return self.json_response(404, {})

        def do_POST(self):
            if self.path == "/release" and self.client_address[0] == "127.0.0.1":
                release.set()
                with lock:
                    for barrier in stream_barriers.values():
                        barrier.set()
                return self.json_response(200, {"released": True})
            if (streams_with_barrier or storage_pair) and self.client_address[0] == "127.0.0.1":
                match = re.fullmatch(rf"/release/({TURN_TAG})", self.path)
                if match:
                    with lock:
                        barrier = stream_barriers.get(match[1]) if calls_by_tag.get(match[1]) else None
                    if barrier is None:
                        return self.json_response(409, {"error": {"message": "Turn has not entered the fixture"}})
                    barrier.set()
                    return self.json_response(200, {"released": True})
            if self.path != "/v1/chat/completions":
                return self.json_response(404, {})
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 1024 * 1024:
                    raise ValueError("Invalid request size")
                body = json.loads(self.rfile.read(length))
                if body["model"] != MODEL_NAME or not isinstance(body.get("messages"), list):
                    raise ValueError("Wrong fixture model")
                tag = None
                if body.get("stream"):
                    if mode == "maintenance" or storage_pair:
                        for message in reversed(body["messages"]):
                            if isinstance(message, dict) and message.get("role") == "user":
                                match = tagged_query.search(json.dumps(message.get("content")))
                                if match is not None:
                                    tag = match[1]
                                    break
                        if storage_pair and tag not in stream_barriers:
                            raise ValueError("Wrong storage pair role")
                        if tag is None:
                            raise ValueError("Missing fixture turn tag")
                    elif mode == "admission" or streams_with_barrier:
                        user_message = next((message for message in reversed(body["messages"])
                                             if isinstance(message, dict) and message.get("role") == "user"), {})
                        match = tagged_query.search(json.dumps(user_message.get("content")))
                        if match is None:
                            raise ValueError("Wrong tagged fixture query")
                        tag = match[1]
                    elif marker not in json.dumps(body["messages"]):
                        raise ValueError("Wrong storage fixture query")
            except (KeyError, TypeError, ValueError):
                with lock:
                    counts["unexpected_calls"] += 1
                return self.json_response(400, {"error": {"message": "Unexpected fixture request"}})
            if not body.get("stream"):
                if mode in {"admission", "stream", "maintenance"}:
                    with lock:
                        counts["auxiliary_calls"] += 1
                        if mode == "admission":
                            auxiliary_tags.update(tagged_query.findall(json.dumps(body["messages"])))
                return self.json_response(200, {"id": "runtime-fixture", "object": "chat.completion", "created": 0,
                                                "model": MODEL_NAME, "choices": [{"index": 0, "finish_reason": "stop",
                                                "message": {"role": "assistant", "content": "Runtime storage fixture"}}],
                                                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}})
            with lock:
                counts["stream_calls"] += 1
                call = counts["stream_calls"]
                if tag is not None:
                    round_number = calls_by_tag[tag] = calls_by_tag.get(tag, 0) + 1
                    two_rounds = storage_pair or mode == "maintenance" or (
                        mode == "scheduler" and tag in {"auto", "settled"}
                    )
                    within_limit = round_number <= (2 if two_rounds else 1)
                else:
                    round_number = call
                    within_limit = call <= 2
                first_model_call.set()
                upload_step = mode == "maintenance" and round_number == 1
                if streams_with_barrier and within_limit and not upload_step:
                    barrier = stream_barriers.setdefault(tag, Event())
            if storage_pair:
                ready = round_number != 1 or (within_limit and stream_barriers[tag].wait(300))
            else:
                ready = streams_with_barrier or (within_limit and release.wait(300))
            if not within_limit or not ready:
                return self.json_response(409, {"error": {"message": "Fixture sequencing failed"}})
            try:
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                if storage_pair:
                    content = artifact_code if round_number == 1 else (
                        f"<final_answer>runtime-storage-completed:{token}:{tag}</final_answer>"
                    )
                elif upload_step:
                    content = artifact_code.replace(OUTPUT_NAME, f"runtime-maintenance-{tag}.txt")
                elif streams_with_barrier:
                    self.send_delta(call, {"role": "assistant", "reasoning_content": f"stream-prefix:{tag}:界🌊"})
                    self.wfile.flush()
                    if not barrier.wait(300):
                        return
                    content = f"<final_answer>stream-tail:{tag}:结束🌊</final_answer>"
                elif tag is not None:
                    content = f"<final_answer>runtime-admitted:{tag}</final_answer>"
                else:
                    content = artifact_code if call == 1 else answer
                for delta, finish in (({"role": "assistant", "content": content}, None), ({}, "stop")):
                    self.send_delta(call, delta, finish)
                self.wfile.write(b"data: [DONE]\n\n")
            except (BrokenPipeError, ConnectionResetError):
                pass

        def send_delta(self, call, delta, finish=None):
            chunk = {"id": f"runtime-fixture-{call}", "object": "chat.completion.chunk", "created": 0,
                     "model": MODEL_NAME, "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}
            self.wfile.write(("data: " + json.dumps(chunk) + "\n\n").encode())

    return ThreadingHTTPServer((host, port), Handler)


if __name__ == "__main__":
    mode_args, token_arg = sys.argv[1:-1], sys.argv[-1]
    mode = mode_args[0] if len(mode_args) == 1 else "storage" if not mode_args else "invalid"
    with fixture_server(token_arg, mode=mode) as server:
        server.serve_forever()
