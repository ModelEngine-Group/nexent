# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Skill continuation history must reach model-visible context, including failed turns."""

import pytest
from smolagents.memory import AgentMemory

from contracts.agentos import PreparedSkillCreatorRun
from infrastructure.agentos_identity import ServicePrincipal
from nexent.core.agents.agent_model import ModelConfig
from runtime.agentos import prepared_skill_creator as runtime
from nexent.core.agents.context import ContextManager, ContextManagerConfig
from nexent.core.agents.run_agent import _get_authorized_history


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
    mocker.patch.object(runtime, "_materialize_model", return_value=ModelConfig(
        cite_name="model", model_name="primary", api_key="test", url="https://provider.invalid",
    ))
    payload = PreparedSkillCreatorRun.model_validate({
        "mode": "nl2skill", "run_id": "a" * 32,
        "input": {"query": "继续", "history": [item for item in history if item["role"] in {"user", "assistant"}]},
        "model": {"model_id": 5, "alias": "model", "revision": "v1"},
        "input_budget": 8192, "context_window_tokens": 8192,
    })
    info = runtime.prepare_skill_creator_run(payload, ServicePrincipal("owner", "tenant"))

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
