# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Route and observe case-owned Runtime HTTP requests."""

import asyncio
from ipaddress import ip_address
import json
import sys
from urllib.parse import urlsplit
from uuid import UUID

from aiohttp import ClientSession, ClientTimeout, web
from yarl import URL

from contracts.agentos import AgentOperation


RUN_PATH = "/api" + AgentOperation.RUN.value
RESUME_PATH = "/api" + AgentOperation.RESUME.value
STOP_PATH = "/api" + AgentOperation.STOP.value
CUT_TARGETS = {"web-cut": "producer", "northbound-cut": "peer"}
CONTROL_TARGETS = {f"public-{entrance}-{action}": "producer" for entrance in ("web", "northbound")
                   for action in ("resume", "stop")}
NORTHBOUND_ADMISSION_TARGETS = {"a": "producer", "b": "peer"}
NORTHBOUND_ADMISSION_TAGS = {
    f"nb-{operation}-{side}": target for operation in ("race", "overlap", "second", "quota", "retry")
    for side, target in NORTHBOUND_ADMISSION_TARGETS.items()
}
HOP_HEADERS = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailer",
               "transfer-encoding", "upgrade"}


def relay_headers(headers):
    named_by_connection = {item.strip().lower() for value in headers.getall("Connection", ())
                           for item in value.split(",")}
    return [(key, value) for key, value in headers.items() if key.lower() not in HOP_HEADERS | named_by_connection]


def verify_origin(origin):
    url = urlsplit(origin)
    if (url.scheme != "http" or url.username or url.password or url.path or url.query or url.fragment
            or not url.port or ip_address(url.hostname).is_unspecified):
        raise ValueError("Expected a direct HTTP address of a case-owned Runtime")
    return origin


class OwnedRouting:
    def __init__(self, token, targets):
        self.queries = {f"runtime-stream:{token}:{tag}": tag for tag in targets}
        self.targets = targets
        self.runs = {}

    def classify(self, method, path, payload):
        run_id = payload.get("run_id")
        identifier = payload.get("conversation_id")
        if method != "POST" or not isinstance(run_id, str) or len(run_id) != 32:
            return None
        if path == RUN_PATH:
            run_input = payload.get("input")
            if not isinstance(run_input, dict) or type(identifier) is not int or identifier < 1:
                return None
            query = run_input.get("user_query") or run_input.get("query")
            tag = self.queries.get(query) if isinstance(query, str) else None
            if tag is None:
                return None
            self.runs[run_id] = (identifier, tag)
            return tag, "start", self.targets[tag]

        owned = self.runs.get(run_id)
        if owned is None:
            return None
        conversation, tag = owned
        if path == RESUME_PATH and identifier == conversation:
            if payload.get("after_event_id"):
                return tag, "replay", "peer"
            return tag, "initial-resume", self.targets[tag]
        if path == STOP_PATH and identifier in (None, conversation):
            return tag, "stop", "peer"
        return None


class RouteReceipts(OwnedRouting):
    def __init__(self, token, targets):
        super().__init__(token, targets)
        self.receipts = {tag: [] for tag in targets}

    def observe(self, routing, response):
        tag, operation, target = routing
        # Cursorless reads also restore public formatting or project a terminal reply.
        if operation == "initial-resume":
            return
        if len(self.receipts[tag]) >= 8:
            raise web.HTTPTooManyRequests(text="Too many requests for the owned transport fixture")
        self.receipts[tag].append({"operation": operation, "target": target, "status": response.status,
                                   "origin": str(response.url.origin())})


def transport_app(token, web_origin, northbound_origin, mode="cut"):
    if UUID(hex=token).hex != token:
        raise ValueError("Expected the owned Runtime scaling run ID")
    if mode not in {"cut", "stream-control", "northbound-admission"}:
        raise ValueError("Unsupported Runtime transport fixture mode")
    web_origin, northbound_origin = map(verify_origin, (web_origin, northbound_origin))
    cut_mode = mode == "cut"
    targets = {"cut": CUT_TARGETS, "stream-control": CONTROL_TARGETS, "northbound-admission": NORTHBOUND_ADMISSION_TAGS}
    routing = OwnedRouting(token, targets[mode]) if cut_mode else RouteReceipts(token, targets[mode])
    counts = {tag: {"attempts": 0, "resume_attempts": 0, "prefix_observed": False, "transport_aborted": False}
              for tag in CUT_TARGETS}
    cuts = {tag: asyncio.Event() for tag in CUT_TARGETS}
    finished = set()
    client = None

    async def session(_app):
        nonlocal client
        timeout = ClientTimeout(total=None, sock_connect=10, sock_read=90)
        async with ClientSession(timeout=timeout, auto_decompress=False, trust_env=False) as upstream:
            client = upstream
            yield

    async def ready(_request):
        return web.json_response({"ready": True})

    async def probe(request):
        if request.remote not in {"127.0.0.1", "::1"}:
            raise web.HTTPNotFound()
        return web.json_response(counts if cut_mode else routing.receipts)

    async def cut(request):
        tag = request.match_info["tag"]
        if not cut_mode or request.remote not in {"127.0.0.1", "::1"} or tag not in counts:
            raise web.HTTPNotFound()
        if not counts[tag]["prefix_observed"] or counts[tag]["transport_aborted"]:
            raise web.HTTPConflict()
        cuts[tag].set()
        return web.json_response({"cut_requested": True})

    async def finish(request):
        tag = request.match_info["tag"]
        if not cut_mode or request.remote not in {"127.0.0.1", "::1"} or tag not in counts:
            raise web.HTTPNotFound()
        if not counts[tag]["transport_aborted"]:
            raise web.HTTPConflict()
        finished.add(tag)
        return web.json_response({"finished": True})

    async def relay(request):
        body = await request.read()
        tag = None
        payload = {}
        if request.method == "POST" and request.path in {RUN_PATH, RESUME_PATH, STOP_PATH}:
            try:
                value = json.loads(body)
                if isinstance(value, dict):
                    payload = value
            except ValueError:
                pass
        route = routing.classify(request.method, request.path, payload)
        if cut_mode and route is not None:
            owned_tag, operation, _ = route
            receipt = counts[owned_tag]
            if operation == "start":
                receipt["attempts"] += 1
                if receipt["attempts"] != 1:
                    raise web.HTTPConflict(text="The case-owned RUN was forwarded more than once")
            if operation == "initial-resume" and owned_tag not in finished:
                receipt["resume_attempts"] += 1
                if receipt["resume_attempts"] != 1:
                    raise web.HTTPConflict(text="The case-owned initial RESUME was forwarded more than once")
                tag = owned_tag
        origin = northbound_origin if route is not None and route[2] == "peer" else web_origin
        target = URL(origin + request.raw_path, encoded=True)
        async with client.request(request.method, target, data=body or None, headers=relay_headers(request.headers),
                                  allow_redirects=False) as response:
            if not cut_mode and route is not None:
                routing.observe(route, response)
            if tag is not None:
                assert response.status == 200 and response.content_type == "text/event-stream"
                marker = f"stream-prefix:{tag}:".encode()
                prefix = bytearray()
                async for chunk in response.content.iter_any():
                    prefix.extend(chunk)
                    assert len(prefix) <= 1024 * 1024
                    if marker in prefix:
                        counts[tag]["prefix_observed"] = True
                        counts[tag]["origin"] = str(response.url.origin())
                        await asyncio.wait_for(cuts[tag].wait(), timeout=90)
                        assert request.transport is not None
                        request.transport.abort()
                        counts[tag]["transport_aborted"] = True
                        return web.Response(status=204)
                raise AssertionError("The Runtime closed without emitting the expected prefix")

            downstream = web.StreamResponse(status=response.status, headers=relay_headers(response.headers))
            try:
                await downstream.prepare(request)
                async for chunk in response.content.iter_any():
                    await downstream.write(chunk)
                await downstream.write_eof()
            except ConnectionResetError:
                if cut_mode:
                    raise
            return downstream

    app = web.Application()
    app.cleanup_ctx.append(session)
    app.router.add_get("/test-relay/ready", ready)
    app.router.add_get("/test-relay/probe", probe)
    app.router.add_post("/test-relay/cut/{tag}", cut)
    app.router.add_post("/test-relay/finish/{tag}", finish)
    app.router.add_route("*", "/{path:.*}", relay)
    return app


if __name__ == "__main__":
    run_token, web_runtime, northbound_runtime, port, *mode = sys.argv[1:]
    web.run_app(transport_app(run_token, web_runtime, northbound_runtime, *mode), port=int(port), access_log=None)
