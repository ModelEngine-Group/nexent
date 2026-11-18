# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Independent Gateway assembly; business services are reached over HTTP only."""

from contextlib import asynccontextmanager
from http.cookiejar import CookieJar, DefaultCookiePolicy
from urllib.parse import urlsplit

import httpx
from fastapi import FastAPI, Request, WebSocket
from fastapi.responses import JSONResponse
from starlette.middleware.cors import CORSMiddleware

from gateway.security.credentials import IdentityUnavailable, authorization_for, resolve_identity
from gateway.security.delegation import DELEGATION_PATH, delegate_mcp
from gateway.configuration import load_settings
from gateway.exposure.middleware import ExposureMiddleware
from gateway.exposure.registry import default_registry
from gateway.security.identity import IDENTITY_HEADER, IdentityError, sign_identity
from gateway.proxy.http import forward_http
from gateway.proxy.websocket import forward_websocket
from gateway.routing import exposure_target, filtered_headers


class _NoCookies(DefaultCookiePolicy):
    """The shared upstream client must never retain user cookies."""

    def set_ok(self, cookie, request):
        return False


def create_gateway_app(*, settings=None, transport=None, upstreams=None, authentication=None, registry=None,
                       identity_lookup=None):
    settings = load_settings() if settings is None else settings
    targets = dict(upstreams or {"management": settings.management_url, "runtime": settings.runtime_url,
                                "northbound": settings.northbound_url, "ops": settings.ops_url})
    authenticate = settings.auth_enabled if authentication is None else authentication
    registry = default_registry() if registry is None else registry
    for target in targets.values():
        parsed = urlsplit(target)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password:
            raise ValueError("Gateway upstream must be an HTTP origin without credentials")
        if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
            raise ValueError("Gateway upstream must not contain a path, query or fragment")

    @asynccontextmanager
    async def lifespan(app):
        repository = None
        if authenticate:
            settings.signing_key()
        if authenticate and identity_lookup is None:
            from infrastructure.rdb.identity import IdentityRepository
            from gateway.security.database_provider import DatabaseIdentityProvider

            repository = await IdentityRepository.open(**settings.database_options())
            app.state.identity_lookup = DatabaseIdentityProvider(repository)
        try:
            async with httpx.AsyncClient(
                transport=transport, trust_env=False, follow_redirects=False,
                cookies=CookieJar(policy=_NoCookies()),
                timeout=httpx.Timeout(connect=10, read=None, write=30, pool=10),
            ) as client:
                app.state.client = client
                yield
        finally:
            app.state.identity_lookup = unavailable_identity
            if repository is not None:
                await repository.close()

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

    async def unavailable_identity(query):
        raise IdentityUnavailable("Identity provider is unavailable")

    app.state.identity_lookup = identity_lookup or unavailable_identity
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True,
                       allow_methods=["*"], allow_headers=["*"])
    # Last-added middleware runs first, including before CORS preflight handling.
    app.add_middleware(ExposureMiddleware, registry=registry)
    app.state.exposure_revision, app.state.exposure_digest = registry.revision, registry.digest

    @app.get("/health/live")
    @app.get("/health/ready")
    async def health():
        return {"status": "ready"}

    def target_url(connection, target):
        # Preserve the exact request path and query used for the downstream signature.
        scope = connection.scope
        path = scope["raw_path"].decode("ascii")
        query = scope["query_string"].decode("ascii")
        return targets[target].rstrip("/") + path + ("?" + query if query else "")

    async def request_headers(connection, target):
        headers = filtered_headers(connection.headers.items(), request=True)
        if authenticate:
            method = connection.scope.get("method", "GET")
            principal = await resolve_identity(connection, settings=settings,
                                               identity_lookup=connection.app.state.identity_lookup)
            match = connection.scope["gateway.exposure"]
            if principal is not None and principal.get("kind") not in match.credential_kinds:
                raise IdentityError("Credential policy mismatch")
            if principal is None and "anonymous" not in match.credential_kinds:
                raise IdentityError("Identity required by exposure policy")
            audience = "management" if target == "northbound" else target
            token = sign_identity(principal, audience,
                                  method, connection.url.path, connection.scope["query_string"], key=settings.signing_key())
            headers.append((IDENTITY_HEADER, token))
            if connection.scope["type"] == "http" and not connection.headers.get("authorization") and authorization_for(connection):
                headers.append(("authorization", authorization_for(connection)))
        return headers

    @app.post(DELEGATION_PATH)
    async def credential_delegation(request: Request):
        try:
            result = await delegate_mcp(request, settings=settings,
                                        identity_lookup=request.app.state.identity_lookup)
        except IdentityError:
            return JSONResponse({"message": "Invalid or missing credentials"}, status_code=401)
        except IdentityUnavailable:
            return JSONResponse({"message": "Identity service unavailable"}, status_code=503)
        return JSONResponse(result)

    @app.api_route("/{path:path}", methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
    async def proxy(request: Request, path: str):
        target = exposure_target(request.scope["gateway.exposure"], request.scope["query_string"])
        url = target_url(request, target)
        try:
            headers = await request_headers(request, target)
        except IdentityError:
            return JSONResponse({"message": "Invalid or missing credentials"}, status_code=401)
        except IdentityUnavailable:
            return JSONResponse({"message": "Identity service unavailable"}, status_code=503)
        return await forward_http(request, url, headers, request.app.state.client)

    @app.websocket("/{path:path}")
    async def websocket_proxy(websocket: WebSocket, path: str):
        target = websocket.scope["gateway.exposure"].target
        url = target_url(websocket, target)
        url = ("wss" if url.startswith("https:") else "ws") + url[url.index(":"):]
        try:
            headers = await request_headers(websocket, target)
        except (IdentityError, IdentityUnavailable):
            await websocket.close(code=1008)
            return
        headers = [(k, v) for k, v in headers if k.lower() not in {
            "host", "sec-websocket-key", "sec-websocket-version", "sec-websocket-extensions", "sec-websocket-protocol"}]
        await forward_websocket(websocket, url, headers)

    return app
