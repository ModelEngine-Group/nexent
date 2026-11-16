# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Certificate verification preferences across A2A service boundaries."""
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError

from contracts.a2a import DiscoverExternalAgentFromUrlRequest as DiscoverFromUrlRequest
from management.services.agent.a2a import catalog


@pytest.mark.parametrize("value", [True, False])
def test_discovery_request_preference(value):
    assert DiscoverFromUrlRequest(url="https://peer/card").ssl_verify is True
    assert DiscoverFromUrlRequest(url="https://peer/card", ssl_verify=value).ssl_verify is value
    with pytest.raises(ValidationError):
        DiscoverFromUrlRequest(url="https://peer/card", ssl_verify=None)


@pytest.fixture
def boundary(mocker):
    client = MagicMock()
    client.get_json = AsyncMock(return_value={"name": "Peer", "url": "https://peer"})
    client.post_json = AsyncMock(return_value={"result": {"ok": True}})

    async def events(*args, **kwargs):
        yield {"ok": True}

    client.post_stream = events
    constructor = mocker.patch.object(catalog, "A2AHttpClient")
    constructor.return_value.__aenter__ = AsyncMock(return_value=client)
    constructor.return_value.__aexit__ = AsyncMock(return_value=False)
    db = mocker.patch.object(catalog, "a2a_agent_db")
    return constructor, client, db


@pytest.mark.asyncio
@pytest.mark.parametrize("value", [True, False])
async def test_discovery_uses_and_persists_preference(boundary, value):
    constructor, _, db = boundary
    await catalog.A2AClientService().discover_from_url("https://peer/card", "tenant", "user", ssl_verify=value)
    assert constructor.call_args.kwargs["ssl_verify"] is value
    assert db.create_external_agent_from_url.call_args.kwargs["ssl_verify"] is value


@pytest.mark.asyncio
async def test_failed_discovery_does_not_write(boundary):
    _, client, db = boundary
    client.get_json.side_effect = ValueError("invalid card")
    with pytest.raises(catalog.AgentDiscoveryError):
        await catalog.A2AClientService().discover_from_url("https://peer/card", "tenant", "user", ssl_verify=False)
    db.create_external_agent_from_url.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["refresh", "send", "stream"])
@pytest.mark.parametrize("preference", [{}, {"ssl_verify": True}, {"ssl_verify": False}])
async def test_stored_preference_used_for_every_request(boundary, operation, preference):
    constructor, _, db = boundary
    db.get_external_agent_by_id.return_value = {
        "agent_url": "https://peer", "source_url": "https://peer/card",
        "source_type": "url", "is_available": True, **preference,
    }
    service = catalog.A2AClientService()
    if operation == "refresh":
        await service.refresh_agent_card(1, "tenant", "user")
    elif operation == "send":
        assert await service.call_agent(1, "tenant", {}) == {"ok": True}
    else:
        assert [event async for event in service.call_agent_streaming(1, "tenant", {})] == [{"ok": True}]
    constructor.assert_called_once_with(ssl_verify=preference.get("ssl_verify", True))
