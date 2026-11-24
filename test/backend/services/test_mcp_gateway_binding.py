# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""The deployed MCP entrypoint supplies explicit Gateway delegation settings."""

from unittest.mock import AsyncMock

import pytest

from backend.http import mcp_service as service
from gateway.identity.context import identity_context
from gateway.identity.protocol import IdentityError


@pytest.mark.asyncio
@pytest.mark.parametrize("result", ["valid", "other-tenant", "unavailable"])
async def test_mcp_entrypoint_binds_gateway_configuration(monkeypatch, result):
    monkeypatch.setattr(service, "gateway_identity_enabled", lambda: True)
    monkeypatch.setattr(service, "GATEWAY_SERVICE_URL", "http://gateway-fixture:5013", raising=False)
    monkeypatch.setattr(service, "gateway_signing_key", lambda: "fixture-delegation-key", raising=False)
    principal = {"user_id": "u1", "tenant_id": "other" if result == "other-tenant" else "t1"}
    calls, reached, sent = [], [], []

    async def resolve(scope, authorization, *, gateway_url, key):
        calls.append((scope["path"], authorization, gateway_url, key))
        if result == "unavailable":
            raise IdentityError("Gateway unavailable")
        return principal

    async def tenant_app(scope, receive, send):
        reached.append((scope["path"], identity_context.get()))
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    monkeypatch.setattr(service, "_resolve_gateway_mcp_identity", resolve)
    monkeypatch.setattr(service, "_tenant_mcp_apps", {"t1": tenant_app})
    await service.TenantMCPRouter()(
        {"type": "http", "method": "GET", "path": "/mcp/t1/sse", "query_string": b"",
         "headers": [(b"authorization", b"Bearer fixture-session")]},
        AsyncMock(), AsyncMock(side_effect=sent.append),
    )
    assert calls == [("/mcp/t1/sse", "Bearer fixture-session", "http://gateway-fixture:5013", "fixture-delegation-key")]
    assert sent[0]["status"] == (200 if result == "valid" else 403)
    assert reached == ([("/sse", principal)] if result == "valid" else [])
    assert identity_context.get() is None
