"""Deterministic, isolated Mem0 HTTP fixture; not a semantic memory engine."""

from __future__ import annotations

import argparse
import copy
import hmac
import json
import os
import re
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

MAX_BODY = 262144
MAX_ITEMS = 10000
TTL_SECONDS = 86400


class RequestError(Exception):
    def __init__(self, status: int, message: str):
        self.status, self.message = status, message


def identity(value, field: str, *, optional=False) -> str:
    if optional and value is None:
        return ""
    if not isinstance(value, str) or not value.strip() or len(value) > 256:
        raise RequestError(422, f"{field} must be a non-empty string of at most 256 characters")
    return value


def search_scope(filters: dict) -> dict:
    """Accept only the equality/AND subset emitted by the current Mem0 plugin."""
    scope = {}

    def visit(node):
        if not isinstance(node, dict) or not node:
            raise RequestError(422, "filters must contain user_id or agent_id")
        for key, value in node.items():
            if key == "AND":
                if not isinstance(value, list) or not value:
                    raise RequestError(422, "AND must be a non-empty array")
                for child in value:
                    visit(child)
            elif key in {"user_id", "agent_id", "run_id"}:
                value = identity(value, key)
                if key in scope and scope[key] != value:
                    raise RequestError(422, "conflicting scope filters")
                scope[key] = value
            else:
                raise RequestError(422, "unsupported filter; only identity equality and AND are supported")

    visit(filters)
    if not (scope.get("user_id") or scope.get("agent_id")):
        raise RequestError(422, "user_id or agent_id is required")
    return scope


class MemoryState:
    def __init__(self):
        self.lock = threading.RLock()
        self.records = {}
        self.events = {}
        self.faults = {}
        self.observations = {}

    def prune(self):
        cutoff = time.monotonic() - TTL_SECONDS
        for collection in (self.records, self.events, self.faults, self.observations):
            for key in list(collection):
                if collection[key]["created"] < cutoff:
                    del collection[key]

    def observe(self, org: str, user: str, action: str):
        key = (org, user)
        if key not in self.observations and len(self.observations) >= MAX_ITEMS:
            raise RequestError(507, "observation capacity reached")
        entry = self.observations.setdefault(key, {"created": time.monotonic(), "counts": {}})
        entry["counts"][action] = entry["counts"].get(action, 0) + 1

    def fault(self, org: str, scope: dict):
        with self.lock:
            self.prune()
            fault = copy.copy(self.faults.get((org, scope.get("user_id", ""))))
        if fault:
            time.sleep(fault["delay_seconds"])
            if fault["status"] != 200:
                raise RequestError(fault["status"], "injected memory-provider fault")

    def add(self, org: str, payload: dict) -> dict:
        scope = {key: identity(payload.get(key), key, optional=True)
                 for key in ("user_id", "agent_id", "run_id")}
        if not (scope["user_id"] or scope["agent_id"]):
            raise RequestError(422, "user_id or agent_id is required")
        messages = payload.get("messages")
        if not isinstance(messages, list) or not messages or len(messages) > 100:
            raise RequestError(422, "messages must contain between 1 and 100 items")
        content = []
        for message in messages:
            if not isinstance(message, dict) or message.get("role") not in {"user", "assistant", "system"}:
                raise RequestError(422, "invalid message role")
            text = message.get("content")
            if not isinstance(text, str) or not text.strip() or len(text) > 65536:
                raise RequestError(422, "invalid message content")
            content.append(text)
        metadata = payload.get("metadata", {})
        if not isinstance(metadata, dict):
            raise RequestError(422, "metadata must be an object")
        if payload.get("infer", False) is not False:
            raise RequestError(422, "this fixture supports infer=false only")
        self.fault(org, scope)
        with self.lock:
            self.prune()
            event_id = metadata.get("event_id")
            # An event replay updates the same scoped unit, not another user's memory.
            existing = next((key for key, value in self.records.items()
                             if event_id and value["org"] == org
                             and all(value[key] == scope[key] for key in scope)
                             and value["metadata"].get("event_id") == event_id), None)
            if (len(self.records) >= MAX_ITEMS and not existing) or len(self.events) >= MAX_ITEMS:
                raise RequestError(507, "fixture capacity reached; clean up test records")
            record_id = existing or uuid.uuid4().hex
            self.records[record_id] = {"org": org, **scope, "memory": "\n".join(content),
                                       "metadata": copy.deepcopy(metadata), "created": time.monotonic()}
            event = uuid.uuid4().hex
            self.events[event] = {"org": org, "record_id": record_id,
                                  "status": "SUCCEEDED", "created": time.monotonic()}
            self.observe(org, scope["user_id"], "add")
            return {"event_id": event}

    def search(self, org: str, payload: dict) -> dict:
        query = payload.get("query")
        if not isinstance(query, str) or not query.strip() or len(query) > 4096:
            raise RequestError(422, "query must be a non-empty string of at most 4096 characters")
        scope = search_scope(payload.get("filters"))
        limit = payload.get("top_k", 5)
        if type(limit) is not int or not 1 <= limit <= 100:
            raise RequestError(422, "top_k must be an integer between 1 and 100")
        self.fault(org, scope)
        # Matching is lexical. A missing marker never fabricates a positive result.
        terms = re.findall(r"[\w-]+", query.casefold())
        with self.lock:
            self.prune()
            results = []
            for key, value in self.records.items():
                if value["org"] != org or any(value[name] != expected for name, expected in scope.items()):
                    continue
                score = sum(term in value["memory"].casefold() for term in terms) / max(1, len(terms))
                if score:
                    results.append({"id": key, "memory": value["memory"], "score": score,
                                    "metadata": copy.deepcopy(value["metadata"])})
            self.observe(org, scope.get("user_id", ""), "search")
            return {"results": sorted(results, key=lambda item: (-item["score"], item["id"]))[:limit]}


class MemoryServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, token: str):
        if not isinstance(token, str) or len(token) < 16:
            raise ValueError("NEXENT_EXTERNAL_MEMORY_API_KEY must contain at least 16 characters")
        self.token, self.state = token, MemoryState()
        super().__init__(address, MemoryHandler)


class MemoryHandler(BaseHTTPRequestHandler):
    server_version = "NexentMemoryMock/1.0"

    def log_message(self, *args):
        # Never log headers, query strings, memory contents or response bodies.
        pass

    def send_json(self, status, body):
        raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        if status == 429:
            self.send_header("Retry-After", "1")
        self.end_headers()
        try:
            self.wfile.write(raw)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def body(self):
        if self.headers.get("Transfer-Encoding"):
            raise RequestError(400, "chunked request bodies are not supported")
        try:
            size = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            raise RequestError(400, "invalid Content-Length")
        if not 0 < size <= MAX_BODY:
            raise RequestError(413, "request body must be between 1 and 262144 bytes")
        self.connection.settimeout(10)
        try:
            payload = json.loads(self.rfile.read(size))
        except (ValueError, OSError):
            raise RequestError(400, "invalid JSON body")
        if not isinstance(payload, dict):
            raise RequestError(422, "request body must be an object")
        return payload

    def dispatch(self):
        url = urlsplit(self.path)
        path = url.path.rstrip("/")
        if self.command == "GET" and path in {"/healthz", "/readyz"}:
            return 200, {"status": "ready", "service": "memory-provider", "profile": "mock", "protocol": "mem0-v3"}
        expected = f"Token {self.server.token}".encode()
        if not hmac.compare_digest(self.headers.get("Authorization", "").encode(), expected):
            raise RequestError(401, "invalid fixture credential")
        org = identity(self.headers.get("X-Org-Id"), "X-Org-Id", optional=True)
        state = self.server.state
        if self.command == "POST" and path == "/v3/memories/add":
            return 200, state.add(org, self.body())
        if self.command == "POST" and path == "/v3/memories/search":
            return 200, state.search(org, self.body())
        with state.lock:
            state.prune()
            if self.command == "GET" and path.startswith("/v1/event/"):
                event = state.events.get(path.removeprefix("/v1/event/"))
                if not event or event["org"] != org:
                    raise RequestError(404, "event not found")
                return 200, {"status": event["status"]}
            if self.command == "POST" and path == "/__control/fault":
                payload = self.body()
                user = identity(payload.get("user_id"), "user_id")
                status = payload.get("status", 200)
                delay = payload.get("delay_seconds", 0)
                if type(status) is not int or status not in {200, 401, 403, 429, 503}:
                    raise RequestError(422, "unsupported injected status")
                if type(delay) not in {int, float} or not 0 <= delay <= 30:
                    raise RequestError(422, "delay_seconds must be between 0 and 30")
                if (org, user) not in state.faults and len(state.faults) >= MAX_ITEMS:
                    raise RequestError(507, "fault capacity reached")
                state.faults[(org, user)] = {"status": status, "delay_seconds": delay, "created": time.monotonic()}
                return 200, {"status": "configured"}
            query = parse_qs(url.query)
            if path in {"/__control/observations", "/__control/reset"}:
                user = identity((query.get("user_id") or [None])[0], "user_id")
                if self.command == "GET" and path == "/__control/observations":
                    counts = state.observations.get((org, user), {}).get("counts", {})
                    return 200, {"counts": copy.deepcopy(counts)}
                if self.command == "DELETE" and path == "/__control/reset":
                    removed = {key for key, record in state.records.items()
                               if record["org"] == org and record["user_id"] == user}
                    for key in removed:
                        del state.records[key]
                    for key in list(state.events):
                        if state.events[key]["record_id"] in removed:
                            del state.events[key]
                    state.faults.pop((org, user), None)
                    state.observations.pop((org, user), None)
                    return 200, {"deleted": len(removed)}
            if self.command == "DELETE" and path.startswith("/v1/memories/"):
                key = path.removeprefix("/v1/memories/")
                record = state.records.get(key)
                user = identity((query.get("user_id") or [None])[0], "user_id")
                if not record or record["org"] != org or record["user_id"] != user:
                    raise RequestError(404, "memory not found")
                del state.records[key]
                for event in list(state.events):
                    if state.events[event]["record_id"] == key:
                        del state.events[event]
                return 200, {"status": "deleted"}
        raise RequestError(404, "route not found")

    def handle_request(self):
        try:
            status, body = self.dispatch()
        except RequestError as exc:
            status, body = exc.status, {"detail": exc.message}
        except Exception:
            status, body = 500, {"detail": "fixture internal error"}
        self.send_json(status, body)

    do_GET = handle_request
    do_POST = handle_request
    do_DELETE = handle_request


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18120)
    args = parser.parse_args()
    token = os.environ.get("NEXENT_EXTERNAL_MEMORY_API_KEY", "")
    with MemoryServer((args.host, args.port), token) as server:
        print(f"memory-provider ready on port {server.server_port} (mock/mem0-v3)", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
