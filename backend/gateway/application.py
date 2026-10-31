# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Independent Gateway assembly; business services are reached over HTTP only."""

from contextlib import asynccontextmanager
from http.cookiejar import CookieJar, DefaultCookiePolicy
from urllib.parse import urlsplit

import httpx
from fastapi import FastAPI, Request, WebSocket
from fastapi.responses import JSONResponse
from starlette.middleware.cors import CORSMiddleware

from gateway.authentication.credentials import IdentityUnavailable, authorization_for, resolve_identity
from gateway.configuration import load_settings
from gateway.protocol.identity import IDENTITY_HEADER, IdentityError, sign_identity
from gateway.proxy.http import forward_http
from gateway.proxy.websocket import forward_websocket
from gateway.routing import filtered_headers, select_upstream


class _NoCookies(DefaultCookiePolicy):
    """The shared upstream client must never retain user cookies."""

    def set_ok(self, cookie, request):
        return False


def create_gateway_app(*, settings=None, transport=None, upstreams=None, authentication=None):
    settings = load_settings() if settings is None else settings
    targets = dict(upstreams or {"management": settings.management_url, "runtime": settings.runtime_url,
                                "northbound": settings.northbound_url})
    authenticate = settings.auth_enabled if authentication is None else authentication
    for target in targets.values():
        parsed = urlsplit(target)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password:
            raise ValueError("Gateway upstream must be an HTTP origin without credentials")
        if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
            raise ValueError("Gateway upstream must not contain a path, query or fragment")

    @asynccontextmanager
    async def lifespan(app):
        if authenticate:
            settings.signing_key()
        async with httpx.AsyncClient(
            transport=transport, trust_env=False, follow_redirects=False,
            cookies=CookieJar(policy=_NoCookies()),
            timeout=httpx.Timeout(connect=10, read=None, write=30, pool=10),
        ) as client:
            app.state.client = client
            yield

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True,
                       allow_methods=["*"], allow_headers=["*"])

    @app.get("/health/live")
    @app.get("/health/ready")
    async def health():
        return {"status": "ready"}

    def target_url(method, path, query):
        selected = select_upstream(method, path)
        if selected is None:
            return None
        return targets[selected].rstrip("/") + path + ("?" + query if query else "")

    async def request_headers(connection):
        headers = filtered_headers(connection.headers.items(), request=True)
        if authenticate:
            method = connection.scope.get("method", "GET")
            principal = await resolve_identity(connection, connection.app.state.client, targets["management"], settings=settings)
            selected = select_upstream(method, connection.url.path)
            token = sign_identity(principal, "runtime" if selected == "runtime" else "management",
                                  method, connection.url.path, connection.scope["query_string"], key=settings.signing_key())
            headers.append((IDENTITY_HEADER, token))
            if connection.scope["type"] == "http" and not connection.headers.get("authorization") and authorization_for(connection):
                headers.append(("authorization", authorization_for(connection)))
        return headers

    @app.api_route("/{path:path}", methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
    async def proxy(request: Request, path: str):
        url = target_url(request.method, request.url.path, request.scope["query_string"].decode("ascii"))
        if url is None:
            return JSONResponse({"detail": "Not found"}, status_code=404)
        origin = urlsplit(url)
        url = origin.scheme + "://" + origin.netloc + request.scope["raw_path"].decode("ascii") + ("?" + origin.query if origin.query else "")
        try:
            headers = await request_headers(request)
        except IdentityError:
            return JSONResponse({"message": "Invalid or missing credentials"}, status_code=401)
        except IdentityUnavailable:
            return JSONResponse({"message": "Identity service unavailable"}, status_code=503)
        return await forward_http(request, url, headers, request.app.state.client)

    @app.websocket("/{path:path}")
    async def websocket_proxy(websocket: WebSocket, path: str):
        url = target_url("GET", websocket.url.path, websocket.scope["query_string"].decode("ascii"))
        if url is None:
            await websocket.close(code=1008)
            return
        url = ("wss" if url.startswith("https:") else "ws") + url[url.index(":"):]
        try:
            headers = await request_headers(websocket)
        except (IdentityError, IdentityUnavailable):
            await websocket.close(code=1008)
            return
        headers = [(k, v) for k, v in headers if k.lower() not in {
            "host", "sec-websocket-key", "sec-websocket-version", "sec-websocket-extensions", "sec-websocket-protocol"}]
        await forward_websocket(websocket, url, headers)

    return app
