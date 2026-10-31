# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Independent edge transport regressions (UT-BE-MGWI-001 through 004)."""

import httpx
import pytest

from gateway.edge import create_edge_app
from gateway.routing import select_upstream, filtered_headers


@pytest.mark.parametrize("method,path,target", [
    ("GET", "/api/model/list", "management"),
    ("POST", "/api/agent/run", "runtime"),
    ("POST", "/api/agent/runner", "management"),
    ("POST", "/api/file/storage", "runtime"),
    ("GET", "/api/file/storage", "management"),
    ("GET", "/nb/v1/chat/run", "northbound"),
    ("GET", "/api/nb/a2a/test", "northbound"),
    ("GET", "/api/voice/stt/ws", "runtime"),
    ("GET", "/api/internal/thread-capacity", None),
    ("POST", "/api/agent/internal/northbound/run", None),
    ("GET", "/not-an-api", None),
])
def test_routes(method, path, target):
    assert select_upstream(method, path) == target


def test_header_filter():
    headers = [("connection", "x-secret"), ("x-secret", "hidden"),
               ("x-user-id", "forged"), ("x-forwarded-host", "evil"),
               ("authorization", "Bearer original")]
    assert filtered_headers(headers, request=True) == [("authorization", "Bearer original")]


@pytest.mark.asyncio
async def test_http_preserves_body_query_status_and_cookies():
    seen = []

    async def upstream(request):
        seen.append(request)
        assert await request.aread() == b"payload"
        return httpx.Response(409, stream=httpx.ByteStream(b"event: token\n\n"), headers=[
            ("content-type", "text/event-stream"), ("set-cookie", "a=1"), ("set-cookie", "b=2")])

    app = create_edge_app(transport=httpx.MockTransport(upstream))
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://edge") as client:
            response = await client.post("/api/agent/run?q=a%2Fb&q=2", content=b"payload")
            denied = await client.post("/api/agent/internal/northbound/run")
    assert response.status_code == 409
    assert response.content == b"event: token\n\n"
    assert response.headers.get_list("set-cookie") == ["a=1", "b=2"]
    assert seen[0].url.query == b"q=a%2Fb&q=2"
    assert denied.status_code == 404
    assert len(seen) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("error,status", [(httpx.ConnectError, 502), (httpx.ReadTimeout, 504)])
async def test_upstream_errors(error, status):
    calls = []

    async def upstream(request):
        calls.append(request)
        raise error("secret upstream detail")

    app = create_edge_app(transport=httpx.MockTransport(upstream))
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://edge") as client:
            response = await client.get("/api/model/list")
    assert response.status_code == status
    assert "secret" not in response.text
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_upstream_cookies_never_leak_between_users():
    seen = []

    async def upstream(request):
        seen.append(request.headers.get("cookie"))
        return httpx.Response(200, stream=httpx.ByteStream(b"ok"), headers={"set-cookie": "session=alice; Path=/"})

    app = create_edge_app(transport=httpx.MockTransport(upstream))
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://edge") as client:
            await client.get("/api/user/current_user_info")
            client.cookies.clear()
            await client.get("/api/user/current_user_info")
    assert seen == [None, None]


@pytest.mark.parametrize("origin", ["ftp://host", "http://user:pass@host", "http://host/path", "http://host?q=1"])
def test_reject_invalid_upstream(origin):
    with pytest.raises(ValueError):
        create_edge_app(upstreams={"management": origin})
