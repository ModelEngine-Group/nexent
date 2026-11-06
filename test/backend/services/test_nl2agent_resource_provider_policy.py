# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from unittest.mock import AsyncMock

import pytest
from services.nl2agent_service import (
    _score_resource_requirement,
    search_installed_resources_impl,
)
from tool_collection.mcp.nl2agent_mcp_tools import ResourceRequirement


@pytest.fixture
def provider_catalog(mocker):
    tools = [
        {
            "tool_id": tool_id,
            "name": name,
            "origin_name": origin,
            "description": "Knowledge base search DataMate documents",
            "description_zh": "知识库检索",
            "labels": ["knowledge-base"],
            "source": "local",
            "is_available": True,
        }
        for tool_id, (name, origin) in enumerate(
            [
                ("knowledge_base_search", None),
                ("aidp_search", None),
                ("datamate_search", None),
                ("custom_datamate", "datamate_search"),
            ],
            start=1,
        )
    ]
    mocker.patch(
        "management.services.tool.configuration.list_all_tools",
        new=AsyncMock(return_value=tools),
    )
    mocker.patch(
        "management.services.skill.service.SkillService.list_visible_skills",
        return_value=[],
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled", [True, False])
@pytest.mark.parametrize(
    ("query", "hint", "expected_datamate"),
    [
        ("知识库检索", None, False),
        ("knowledge base search", None, False),
        ("DataMate", None, True),
        ("在DataMate知识库中检索", None, True),
        ("knowledge base search", "datamate_search", True),
        ("knowledge base search", "DATA MATE", True),
        ("knowledge base search", "data-mate", True),
    ],
)
async def test_provider_scoring_prefers_default_unless_named(
    mocker, provider_catalog, enabled, query, hint, expected_datamate
):
    mocker.patch("services.nl2agent_service.ENABLE_AIDP_KNOWLEDGE", enabled)
    result = await search_installed_resources_impl(
        requirements=[
            ResourceRequirement(
                requirement_id="knowledge",
                query=query,
                resource_name_hint=hint,
            )
        ],
        tenant_id="tenant-a",
        user_id="user-a",
    )
    names = {item.name for item in result.candidates}
    assert ("knowledge_base_search" if enabled else "aidp_search") not in names
    assert names & {"datamate_search", "custom_datamate"}
    if expected_datamate:
        assert result.candidates[0].name in {"datamate_search", "custom_datamate"}
    else:
        assert result.candidates[0].name == (
            "aidp_search" if enabled else "knowledge_base_search"
        )
    assert all(0 <= item.score <= 1 for item in result.candidates)


def test_default_bonus_does_not_admit_unrelated_tools():
    resource = {
        "names": ["aidp_search"],
        "labels": [],
        "descriptions": [],
        "interfaces": [],
        "installed": True,
        "quality": 1.0,
    }
    score = _score_resource_requirement(
        ResourceRequirement(requirement_id="other", query="zzzzzzzzzz"), resource
    )
    assert score < 0.5


@pytest.mark.parametrize("hint", [None, "datamate_search"])
def test_bonus_is_small_and_does_not_override_name_hints(mocker, hint):
    resource = {
        "names": ["aidp_search"],
        "labels": ["knowledge-base"],
        "descriptions": ["knowledge base search"],
        "interfaces": [],
        "installed": True,
        "quality": 1.0,
    }
    requirement = ResourceRequirement(
        requirement_id="knowledge",
        query="knowledge base search",
        resource_name_hint=hint,
    )
    actual = _score_resource_requirement(requirement, resource)
    mocker.patch("services.nl2agent_service.MANAGED_KNOWLEDGE_NAMES", set())
    baseline = _score_resource_requirement(requirement, resource)
    assert actual == pytest.approx(min(1.0, baseline + (0.02 if hint is None else 0)))
