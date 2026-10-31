# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Real local Gateway-to-Management Northbound HTTP contract verification.

External business collaborators use the existing Northbound route fixtures.
No database, provider, or deployed model acceptance is claimed.
"""

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from test.backend.app import test_northbound_base_app as fixtures
from test.backend.gateway.test_edge_integration import serve
from gateway.edge import create_edge_app


@pytest.mark.local_only
@pytest.mark.asyncio
async def test_gateway_forwards_original_northbound_and_a2a_paths_to_management():
    card_service = fixtures.a2a_service_module.a2a_server_service
    card_service.get_agent_card.side_effect = None
    card_service.get_agent_card.return_value = {"name": "management-owned-agent", "version": "1.0"}
    with patch.object(fixtures.northbound_base_app_module, "recover_northbound_tasks_on_startup", new=AsyncMock()):
        with serve(fixtures.app) as management_port:
            origin = f"http://127.0.0.1:{management_port}"
            app = create_edge_app(upstreams={"management": origin, "runtime": origin, "northbound": origin})
            with serve(app) as gateway_port:
                async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{gateway_port}", trust_env=False) as client:
                    for prefix in ("", "/api"):
                        health = await client.get(prefix + "/nb/v1/health")
                        assert health.status_code == 200
                        assert health.json() == {"status": "healthy", "service": "northbound-api"}
                        card = await client.get(prefix + "/nb/a2a/endpoint/.well-known/agent-card.json")
                        assert card.status_code == 200
                        assert card.json()["name"] == "management-owned-agent"
                    denied = await client.get("/api/internal/thread-capacity")
                    assert denied.status_code == 404
                    wrong_method = await client.delete("/nb/v1/health")
                    assert wrong_method.status_code == 405
