"""
Unit tests for the northbound agent-config endpoints.

Covers ``GET /nb/v1/agents/{agent_name}/tools`` and
``GET /nb/v1/agents/{agent_name}/skills`` exposed by
``backend.apps.northbound_app`` and implemented in
``backend.services.northbound_service``.

The data layer (``database.tool_db.search_tools_for_sub_agent`` and
``database.skill_db.*``) is fully mocked, so these tests exercise only the
northbound shaping/visibility logic without a live database.
"""
import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from test.common.test_mocks import bootstrap_test_env

# Bootstrap must run before importing backend service modules.
env_state = bootstrap_test_env()  # noqa: F841

from services.northbound_service import (  # noqa: E402
    get_agent_tools_for_northbound,
    get_agent_skills_for_northbound,
)


def _ctx():
    return SimpleNamespace(tenant_id="tenant-1", user_id="user-1", request_id="req-1")


def _visible_agent(name="demo", agent_id=10, version_no=3, tenant_id="tenant-1"):
    return {
        "name": name,
        "agent_id": agent_id,
        "current_version_no": version_no,
        "_northbound_tenant_id": tenant_id,
    }


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


async def test_get_agent_tools_success():
    agent = _visible_agent()
    tool_instances = [
        {
            "tool_instance_id": 1,
            "tool_id": 100,
            "name": "web_search",
            "source": "local",
            "enabled": True,
            "params": [
                {
                    "name": "query",
                    "type": "string",
                    "description": "search query",
                    "default": "",
                    "required": True,
                },
                {
                    "name": "top_k",
                    "type": "integer",
                    "description": "number of results",
                    "default": 5,
                    "required": False,
                },
            ],
        },
        {
            "tool_instance_id": 2,
            "tool_id": 101,
            "name": "calculator",
            "source": "local",
            "enabled": True,
            "params": [],
        },
    ]
    with patch(
        "services.northbound_service._get_visible_published_agents",
        new=AsyncMock(return_value=[agent]),
    ), patch(
        "services.northbound_service.search_tools_for_sub_agent",
        return_value=tool_instances,
    ):
        result = await get_agent_tools_for_northbound(_ctx(), "demo")

    assert result["message"] == "success"
    data = result["data"]
    assert data["agent_name"] == "demo"
    assert data["agent_id"] == 10
    assert data["version_no"] == 3
    assert len(data["tools"]) == 2

    first = data["tools"][0]
    assert first["tool_instance_id"] == 1
    assert first["tool_id"] == 100
    assert first["name"] == "web_search"
    assert first["source"] == "local"
    assert first["enabled"] is True
    assert len(first["params"]) == 2
    assert first["params"][0]["name"] == "query"
    assert first["params"][0]["required"] is True
    assert first["params"][1]["default"] == 5

    second = data["tools"][1]
    assert second["name"] == "calculator"
    assert second["params"] == []


async def test_get_agent_tools_empty_name_raises_value_error():
    with pytest.raises(ValueError):
        await get_agent_tools_for_northbound(_ctx(), "   ")


async def test_get_agent_tools_agent_not_found_raises_lookup_error():
    with patch(
        "services.northbound_service._get_visible_published_agents",
        new=AsyncMock(return_value=[]),
    ):
        with pytest.raises(LookupError):
            await get_agent_tools_for_northbound(_ctx(), "missing")


# ---------------------------------------------------------------------------
# Skills
# ---------------------------------------------------------------------------


async def test_get_agent_skills_success():
    agent = _visible_agent()
    skill_instances = [
        {
            "skill_instance_id": 5,
            "skill_id": 200,
            "enabled": True,
            "config_values": {"temperature": 0.5},
            "config_schemas": {"temperature": {"type": "number"}},
        }
    ]
    skill_info = {
        "skill_name": "summarizer",
        "skill_description": "summarize text",
        "source": "official",
    }
    with patch(
        "services.northbound_service._get_visible_published_agents",
        new=AsyncMock(return_value=[agent]),
    ), patch(
        "database.skill_db.search_skills_for_agent",
        return_value=skill_instances,
    ), patch(
        "database.skill_db.get_skill_by_id",
        return_value=skill_info,
    ), patch(
        "database.skill_db.get_skill_by_id_global",
        return_value=None,
    ):
        result = await get_agent_skills_for_northbound(_ctx(), "demo")

    assert result["message"] == "success"
    data = result["data"]
    assert len(data["skills"]) == 1
    skill = data["skills"][0]
    assert skill["skill_instance_id"] == 5
    assert skill["skill_id"] == 200
    assert skill["enabled"] is True
    assert skill["skill_name"] == "summarizer"
    assert skill["skill_description"] == "summarize text"
    assert skill["source"] == "official"
    assert skill["config_values"] == {"temperature": 0.5}
    assert skill["config_schemas"] == {"temperature": {"type": "number"}}


async def test_get_agent_skills_skips_stale_instance():
    agent = _visible_agent()
    skill_instances = [
        {"skill_instance_id": 5, "skill_id": 999, "enabled": True},
    ]
    with patch(
        "services.northbound_service._get_visible_published_agents",
        new=AsyncMock(return_value=[agent]),
    ), patch(
        "database.skill_db.search_skills_for_agent",
        return_value=skill_instances,
    ), patch(
        "database.skill_db.get_skill_by_id",
        return_value=None,
    ), patch(
        "database.skill_db.get_skill_by_id_global",
        return_value=None,
    ):
        result = await get_agent_skills_for_northbound(_ctx(), "demo")

    assert result["data"]["skills"] == []


async def test_get_agent_skills_empty_name_raises_value_error():
    with pytest.raises(ValueError):
        await get_agent_skills_for_northbound(_ctx(), "")


# ---------------------------------------------------------------------------
# HTTP endpoint status-code mapping (app layer)
# ---------------------------------------------------------------------------


async def test_get_agent_tools_endpoint_maps_lookup_error_to_404():
    from fastapi import HTTPException

    from apps.northbound_app import get_agent_tools

    with patch(
        "apps.northbound_app._get_northbound_context",
        new=AsyncMock(return_value=_ctx()),
    ), patch(
        "apps.northbound_app.get_agent_tools_for_northbound",
        new=AsyncMock(side_effect=LookupError("Published agent not found: x")),
    ):
        try:
            await get_agent_tools(request=MagicMock(), agent_name="x")
            assert False, "expected HTTPException"
        except HTTPException as exc:
            assert exc.status_code == 404


async def test_get_agent_tools_endpoint_maps_value_error_to_400():
    from fastapi import HTTPException

    from apps.northbound_app import get_agent_tools

    with patch(
        "apps.northbound_app._get_northbound_context",
        new=AsyncMock(return_value=_ctx()),
    ), patch(
        "apps.northbound_app.get_agent_tools_for_northbound",
        new=AsyncMock(side_effect=ValueError("agent_name is required")),
    ):
        try:
            await get_agent_tools(request=MagicMock(), agent_name="x")
            assert False, "expected HTTPException"
        except HTTPException as exc:
            assert exc.status_code == 400
