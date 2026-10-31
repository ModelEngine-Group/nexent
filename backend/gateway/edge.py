# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Gateway credential verification and signed downstream HTTP/WS proxy."""

import asyncio
from contextlib import asynccontextmanager, suppress
from http.cookiejar import CookieJar, DefaultCookiePolicy
from urllib.parse import urlsplit

import httpx
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.background import BackgroundTask
from starlette.middleware.cors import CORSMiddleware
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed, InvalidHandshake

from contracts.constants.environment import (
    GATEWAY_MANAGEMENT_URL, GATEWAY_NORTHBOUND_URL, GATEWAY_RUNTIME_URL,
)
from gateway.routing import filtered_headers, select_upstream
from gateway.authentication.credentials import IdentityUnavailable, authorization_for, resolve_identity
from infrastructure.security.gateway_identity import (
    IDENTITY_HEADER, IdentityError, enabled, sign_identity, signing_key,
)


class _NoCookies(DefaultCookiePolicy):
    """A shared proxy connection pool must never retain user cookies."""

    def set_ok(self, cookie, request):
        return False


def create_edge_app(*, transport=None, upstreams=None, authentication=None):
    """Build an independent app with injectable transport for isolated verification."""
    targets = dict(upstreams or {
        "management": GATEWAY_MANAGEMENT_URL,
        "runtime": GATEWAY_RUNTIME_URL,
        "northbound": GATEWAY_NORTHBOUND_URL,
    })
    authenticate = enabled() if authentication is None else authentication
    for target in targets.values():
        parsed = urlsplit(target)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password:
            raise ValueError("Gateway upstream must be an HTTP origin without credentials")
        if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
            raise ValueError("Gateway upstream must not contain a path, query or fragment")

    @asynccontextmanager
    async def lifespan(app):
        if authenticate:
            signing_key()
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
        if not (path.startswith("/api/") or path.startswith("/nb/") or path.startswith("/user/")):
            return None
        selected = select_upstream(method, path)
        if selected is None:
            return None
        # Backend routers retain /api as their ASGI root path in existing deployments.
        return targets[selected].rstrip("/") + path + ("?" + query if query else "")

    @app.api_route("/{path:path}", methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
    async def proxy(request: Request, path: str):
        raw_path = request.scope["raw_path"].decode("ascii")
        url = target_url(request.method, request.url.path, request.scope["query_string"].decode("ascii"))
        if url is None:
            return JSONResponse({"detail": "Not found"}, status_code=404)
        # Preserve raw path escapes without allowing a request-selected authority.
        origin = urlsplit(url)
        url = origin.scheme + "://" + origin.netloc + raw_path + ("?" + origin.query if origin.query else "")
        headers = filtered_headers(request.headers.items(), request=True)
        client = request.app.state.client
        if authenticate:
            try:
                principal = await resolve_identity(request, client, targets["management"])
                selected = select_upstream(request.method, request.url.path)
                headers.append((IDENTITY_HEADER, sign_identity(principal, "runtime" if selected == "runtime" else "management",
                                                              request.method, request.url.path, request.scope["query_string"])))
                if not request.headers.get("authorization") and authorization_for(request):
                    headers.append(("authorization", authorization_for(request)))
            except IdentityError:
                return JSONResponse({"message": "Invalid or missing credentials"}, status_code=401)
            except IdentityUnavailable:
                return JSONResponse({"message": "Identity service unavailable"}, status_code=503)
        try:
            outgoing = client.build_request(request.method, url, headers=headers, content=request.stream())
            upstream = await client.send(outgoing, stream=True)
        except httpx.TimeoutException:
            return JSONResponse({"detail": "Upstream timeout"}, status_code=504)
        except httpx.RequestError:
            return JSONResponse({"detail": "Upstream unavailable"}, status_code=502)

        async def stream():
            try:
                async for chunk in upstream.aiter_raw():
                    yield chunk
            finally:
                await upstream.aclose()

        response = StreamingResponse(stream(), status_code=upstream.status_code,
                                     background=BackgroundTask(upstream.aclose))
        response.raw_headers = [(name.encode("latin-1"), value.encode("latin-1"))
                                for name, value in filtered_headers(upstream.headers.multi_items())]
        return response

    @app.websocket("/{path:path}")
    async def websocket_proxy(websocket: WebSocket, path: str):
        url = target_url("GET", websocket.url.path, websocket.scope["query_string"].decode("ascii"))
        if url is None:
            await websocket.close(code=1008)
            return
        url = ("wss" if url.startswith("https:") else "ws") + url[url.index(":"):]
        protocols = websocket.scope.get("subprotocols", [])
        headers = [(k, v) for k, v in filtered_headers(websocket.headers.items(), request=True)
                   if k.lower() not in {"host", "sec-websocket-key", "sec-websocket-version", "sec-websocket-extensions", "sec-websocket-protocol"}]
        if authenticate:
            try:
                principal = await resolve_identity(websocket, websocket.app.state.client, targets["management"])
                selected = select_upstream("GET", websocket.url.path)
                headers.append((IDENTITY_HEADER, sign_identity(principal, "runtime" if selected == "runtime" else "management",
                                                              "GET", websocket.url.path, websocket.scope["query_string"])))
            except (IdentityError, IdentityUnavailable):
                await websocket.close(code=1008)
                return
        accepted = False
        try:
            async with connect(url, additional_headers=headers, subprotocols=protocols or None,
                               open_timeout=10, max_size=16 * 1024 * 1024) as upstream:
                await websocket.accept(subprotocol=upstream.subprotocol)
                accepted = True

                async def upload():
                    while True:
                        message = await websocket.receive()
                        if message["type"] == "websocket.disconnect":
                            code = message.get("code", 1000)
                            await upstream.close(code=code if code not in {1005, 1006, 1015} else 1000)
                            return
                        await upstream.send(message.get("text") if message.get("text") is not None else message["bytes"])

                async def download():
                    async for message in upstream:
                        if isinstance(message, str):
                            await websocket.send_text(message)
                        else:
                            await websocket.send_bytes(message)

                tasks = [asyncio.create_task(upload()), asyncio.create_task(download())]
                try:
                    done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                    for task in done:
                        task.result()
                finally:
                    for task in tasks:
                        task.cancel()
                    await asyncio.gather(*tasks, return_exceptions=True)
                code = upstream.close_code or 1000
                with suppress(RuntimeError):
                    await websocket.close(code=code if code not in {1005, 1006, 1015} else 1011)
        except (OSError, TimeoutError, ConnectionClosed, InvalidHandshake, WebSocketDisconnect):
            with suppress(RuntimeError):
                await websocket.close(code=1011 if accepted else 1008)

    return app


app = create_edge_app()
