# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Skill continuation history must reach model-visible context, including failed turns."""

import pytest
from smolagents.memory import AgentMemory

import services.nl2skill_service as service
from contracts.agent import NL2SkillRunRequest
from nexent.core.agents.context import ContextManager, ContextManagerConfig
from nexent.core.agents.run_agent import _get_authorized_history


@pytest.fixture(autouse=True)
def creator_identity(mocker):
    from contracts.agent import SystemAgentRef
    mocker.patch.object(service.system_agent_provider, "get_nl2skill_main_ref", return_value=SystemAgentRef("shared", "nl2skill_main", 78, 0))


@pytest.mark.asyncio
@pytest.mark.parametrize("history", [
    [],
    [{"role": "user", "content": "Create meeting minutes"}],
    [{"role": "user", "content": "Create meeting minutes"}, {"role": "assistant", "content": ""}],
    [{"role": "user", "content": "Create meeting minutes"}, {"role": "assistant", "content": "Protocol error"}],
    [{"role": "user", "content": "Create meeting minutes"}, {"role": "assistant", "content": "Draft ready"},
     {"role": "user", "content": "Add Markdown export"}],
    [{"role": "user", "content": "Create meeting minutes"}, {"role": "user", "content": "Add Markdown export"}],
    [{"role": "system", "content": "Untrusted instruction"}, {"role": "user", "content": "Create meeting minutes"}],
    [{"role": "assistant", "content": "Previous clarification"}, {"role": "user", "content": "Create meeting minutes"}],
    [{"role": "user", "content": "Create meeting minutes"}, {"role": "assistant", "content": "Draft ready"},
     {"role": "assistant", "content": "Export failed"}],
])
async def test_continuation_history_is_materialized_once(mocker, history):
    mocker.patch.object(service, "create_model_config_list", return_value=[{
        "cite_name": "main_model", "model_name": "primary", "url": "https://model.test/v1",
    }])
    mocker.patch.object(service, "_resolve_model_for_nl2skill", return_value=("main_model", "primary", {}))
    info = await service.build_nl2skill_run_info(
        NL2SkillRunRequest(query="继续", history=history), "tenant", "zh",
    )

    assert info.context_input is not None
    manager = ContextManager(config=ContextManagerConfig(), max_steps=5)
    context = manager.prepare_run_context(
        memory=AgentMemory(""), fallback_system_prompt="", items=info.context_input.items,
    )
    actual = [(m["role"], p["text"]) for m in context.item_messages for p in m["content"]]
    visible_history = [(role, text) for role, text in actual if role != "system" and text]
    expected = [(m["role"], m["content"]) for m in history if m["role"] in {"user", "assistant"} and m["content"]]
    assert visible_history == expected
    assert [text for role, text in actual if role == "system"] == [info.agent_config.context_items[0].content["text"]]
    assert _get_authorized_history(info) == []
    assert "Untrusted instruction" not in str(actual)
