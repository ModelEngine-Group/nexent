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


ROUTES = {"web-cut": "/api/agent/run", "northbound-cut": "/api/agent/internal/northbound/run"}
CONTROL_PATHS = {"web": (ROUTES["web-cut"], "GET", "/api/agent/stop/"),
                 "northbound": (ROUTES["northbound-cut"], "POST", "/api/agent/internal/northbound/stop/")}
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


class RouteReceipts:
    def observe(self, routing, response):
        tag, operation, target = routing
        if len(self.receipts[tag]) >= 8:
            raise web.HTTPTooManyRequests(text="Too many requests for the owned transport fixture")
        self.receipts[tag].append({"operation": operation, "target": target, "status": response.status,
                                   "origin": str(response.url.origin())})


class StreamControlRouting(RouteReceipts):
    def __init__(self, token):
        self.tags = {f"public-{entrance}-{action}": entrance for entrance in CONTROL_PATHS
                     for action in ("resume", "stop")}
        self.queries = {f"runtime-stream:{token}:{tag}": tag for tag in self.tags}
        self.conversations = {}
        self.receipts = {tag: [] for tag in self.tags}

    def classify(self, method, path, payload):
        for entrance, (run_path, stop_method, stop_prefix) in CONTROL_PATHS.items():
            if method == "POST" and path == run_path:
                identifier = payload.get("conversation_id")
                if type(identifier) is not int or identifier < 1:
                    continue
                if isinstance(payload.get("replay_cursor"), str) and payload["replay_cursor"]:
                    tag = self.conversations.get((entrance, identifier))
                    return (tag, "replay", "peer") if tag else None
                query = payload.get("query")
                tag = self.queries.get(query) if isinstance(query, str) else None
                if self.tags.get(tag) == entrance:
                    self.conversations[(entrance, identifier)] = tag
                    return tag, "start", "producer"
            elif method == stop_method and path.startswith(stop_prefix):
                identifier = path.removeprefix(stop_prefix)
                if identifier.isascii() and identifier.isdecimal() and 1 <= len(identifier) <= 10:
                    tag = self.conversations.get((entrance, int(identifier)))
                    return (tag, "stop", "peer") if tag else None
        return None


class NorthboundAdmissionRouting(RouteReceipts):
    def __init__(self, token):
        self.queries = {f"runtime-stream:{token}:{tag}": tag for tag in NORTHBOUND_ADMISSION_TAGS}
        self.receipts = {tag: [] for tag in NORTHBOUND_ADMISSION_TAGS}

    def classify(self, method, path, payload):
        if method != "POST" or path != ROUTES["northbound-cut"]:
            return None
        query = payload.get("query")
        tag = self.queries.get(query) if isinstance(query, str) else None
        identifier = payload.get("conversation_id")
        if tag is None or type(identifier) is not int or identifier < 1 or payload.get("replay_cursor"):
            raise web.HTTPBadRequest(text="Expected an owned Northbound admission request")
        return tag, "start", NORTHBOUND_ADMISSION_TAGS[tag]


def transport_app(token, web_origin, northbound_origin, mode="cut"):
    if UUID(hex=token).hex != token:
        raise ValueError("Expected the owned Runtime scaling run ID")
    if mode not in {"cut", "stream-control", "northbound-admission"}:
        raise ValueError("Unsupported Runtime transport fixture mode")
    web_origin, northbound_origin = map(verify_origin, (web_origin, northbound_origin))
    routing_class = {"stream-control": StreamControlRouting, "northbound-admission": NorthboundAdmissionRouting}.get(mode)
    routing = routing_class(token) if routing_class else None
    counts = {tag: {"attempts": 0, "prefix_observed": False, "transport_aborted": False} for tag in ROUTES}
    cuts = {tag: asyncio.Event() for tag in ROUTES}
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
        return web.json_response(routing.receipts if routing is not None else counts)

    async def cut(request):
        tag = request.match_info["tag"]
        if routing is not None or request.remote not in {"127.0.0.1", "::1"} or tag not in counts:
            raise web.HTTPNotFound()
        if not counts[tag]["prefix_observed"] or counts[tag]["transport_aborted"]:
            raise web.HTTPConflict()
        cuts[tag].set()
        return web.json_response({"cut_requested": True})

    async def relay(request):
        body = await request.read()
        tag = None
        payload = {}
        if request.method == "POST" and request.path in ROUTES.values():
            try:
                value = json.loads(body)
                if isinstance(value, dict):
                    payload = value
            except ValueError:
                pass
            if routing is None:
                tag = next((name for name, path in ROUTES.items() if path == request.path
                            and payload.get("query") == f"runtime-stream:{token}:{name}"), None)
        if tag is not None:
            counts[tag]["attempts"] += 1
            if counts[tag]["attempts"] != 1:
                raise web.HTTPConflict(text="The case-owned request was forwarded more than once")

        route = routing.classify(request.method, request.path, payload) if routing is not None else None
        if routing is not None:
            origin = northbound_origin if route is not None and route[2] == "peer" else web_origin
        else:
            origin = northbound_origin if request.path == ROUTES["northbound-cut"] else web_origin
        target = URL(origin + request.raw_path, encoded=True)
        async with client.request(request.method, target, data=body or None, headers=relay_headers(request.headers),
                                  allow_redirects=False) as response:
            if route is not None:
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
                if routing is None:
                    raise
            return downstream

    app = web.Application()
    app.cleanup_ctx.append(session)
    app.router.add_get("/test-relay/ready", ready)
    app.router.add_get("/test-relay/probe", probe)
    app.router.add_post("/test-relay/cut/{tag}", cut)
    app.router.add_route("*", "/{path:.*}", relay)
    return app


if __name__ == "__main__":
    run_token, web_runtime, northbound_runtime, port, *mode = sys.argv[1:]
    web.run_app(transport_app(run_token, web_runtime, northbound_runtime, *mode), port=int(port), access_log=None)
