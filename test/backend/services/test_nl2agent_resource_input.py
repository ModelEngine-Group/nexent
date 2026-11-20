# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Unit tests for the resource search input boundary."""

from types import SimpleNamespace

import pytest

from management.services.agent import nl2agent_tools as tools
from tool_collection.mcp import nl2agent_resource_tools as resource_tools


@pytest.mark.parametrize("search_query", [" ", "x" * 81])
async def test_discovery_rejects_invalid_short_search_query(mocker, search_query):
    run = mocker.patch.object(resource_tools, "_run")
    result = await resource_tools.discover_requirements(
        requirements=[{"query": "发送邮件", "search_query": search_query}],
    )
    assert result["code"] == "invalid_requirements"
    run.assert_not_called()


@pytest.mark.parametrize("search", [tools.search_installed_resources, tools.search_uninstalled_resources])
@pytest.mark.parametrize(
    ("count", "expected"),
    [(8, "success"), (9, "requirements_limit_exceeded"), (0, "invalid_requirements")],
)
async def test_resource_search_preserves_batch_boundary(mocker, search, count, expected):
    service = mocker.patch(
        f"management.services.agent.nl2agent.{search.__name__}_impl",
        return_value=tools.ResourceSearchOutput(candidates=[], uncovered_requirement_ids=[]),
    )
    resolve_agent = mocker.patch.object(tools, "_resolve_agent_context_id", return_value=42)
    mocker.patch.object(tools, "get_http_request", return_value=SimpleNamespace(headers={}))
    mocker.patch.object(tools, "_tool_actor", return_value=("user-a", "tenant-a"))
    mocker.patch("management.services.agent.authorization.require_agent_draft_edit")
    requirements = [{"requirement_id": f"req-{i}", "query": f"Capability {i}"} for i in range(count)]
    original = [item.copy() for item in requirements]

    result = await search(agent_id=42, requirements=requirements)

    assert requirements == original
    if expected == "success":
        assert result["status"] == "success"
        service.assert_awaited_once()
        assert [item.model_dump(exclude_unset=True) for item in service.call_args.kwargs["requirements"]] == original
    else:
        resolve_agent.assert_not_called()
        service.assert_not_called()
        assert result["status"] == "error"
        assert result["code"] == expected
        assert result["retryable"] is False
        assert result.get("max_requirements") == (8 if count == 9 else None)
