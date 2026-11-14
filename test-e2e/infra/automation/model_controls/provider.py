# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""A case-owned HTTP provider whose wire is captured without credentials."""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Provider:
    def __init__(self):
        self.wire = []
        self.auxiliary_wire = []
        self.failure = False
        self.delay = False
        self.release = threading.Event()
        self.answer = "<final_answer>Model control fixture completed.</final_answer>"
        self.responder = None
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                # Agent execution streams; background title generation does not.
                # Keep both, but do not let its completion order change which
                # Agent invocation the runtime assertions inspect.
                wire = owner.wire if body.get("stream") else owner.auxiliary_wire
                wire.append({"path": self.path, **body})
                if owner.failure:
                    self.send_response(400)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(b'{"error":{"message":"Controlled provider failure","type":"server_error"}}')
                    return
                if owner.delay:
                    owner.release.wait(30)
                answer = owner.responder(body) if owner.responder else owner.answer
                streaming = body.get("stream", False)
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream" if streaming else "application/json")
                self.end_headers()
                try:
                    if streaming:
                        for delta, finish in [({"role": "assistant", "content": answer}, None), ({}, "stop")]:
                            chunk = {"id": "fixture", "object": "chat.completion.chunk", "created": 0,
                                     "model": body["model"], "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}
                            self.wfile.write(("data: " + json.dumps(chunk) + "\n\n").encode())
                        self.wfile.write(b"data: [DONE]\n\n")
                    else:
                        response = {"id": "fixture", "object": "chat.completion", "created": 0, "model": body["model"],
                                    "choices": [{"index": 0, "message": {"role": "assistant", "content": answer}, "finish_reason": "stop"}],
                                    "usage": {"prompt_tokens": 12, "completion_tokens": 15, "total_tokens": 27}}
                        self.wfile.write(json.dumps(response).encode())
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                    pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_port}/v1"

    def close(self):
        self.release.set()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
