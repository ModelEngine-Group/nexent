# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Each Jiuwen run supplies its tool deadline without changing process globals."""

from threading import Event

import pytest
from pydantic import ValidationError

from nexent.core.agents.contracts.config import AgentConfig
from nexent.core.agents.contracts.run import AgentRunInfo
from nexent.core.agents.cores.jiuwen.adapter import JiuwenAdapter
from nexent.core.utils.observer import MessageObserver


def run_info(**overrides):
    return AgentRunInfo(query="task", model_config_list=[], observer=MessageObserver(), stop_event=Event(),
                        agent_config=AgentConfig(name="agent", description="Agent", model_name="model", tools=[]),
                        **overrides)


def test_run_tool_deadline_overrides_jiuwen_global_without_cross_run_mutation():
    from openjiuwen.core.single_agent.ability_manager import (
        DEFAULT_TOOL_CALL_TIMEOUT,
        AbilityManager,
    )

    first = JiuwenAdapter(run_info(tool_call_timeout_seconds=900))
    second = JiuwenAdapter(run_info(tool_call_timeout_seconds=1200))
    cards = [adapter._tool_card(name="remote", description="A2A", input_params={})
             for adapter in (first, second)]
    assert AbilityManager._resolve_call_timeout(cards[0]) == 900
    assert AbilityManager._resolve_call_timeout(cards[1]) == 1200
    assert cards[0].properties is not cards[1].properties
    assert run_info().tool_call_timeout_seconds == 300
    from openjiuwen.core.single_agent import ability_manager
    assert ability_manager.DEFAULT_TOOL_CALL_TIMEOUT == DEFAULT_TOOL_CALL_TIMEOUT


def test_child_run_inherits_host_timeout_settings():
    from nexent.core.agents.orchestration.children import child_run_info
    from nexent.core.concurrency import RunCancellationScope

    parent = run_info(collaboration_timeout_seconds=900, tool_call_timeout_seconds=1200)
    child = child_run_info(parent, parent.agent_config, RunCancellationScope(Event()))
    assert child.collaboration_timeout_seconds == 900
    assert child.tool_call_timeout_seconds == 1200


@pytest.mark.parametrize("field", ["tool_call_timeout_seconds", "collaboration_timeout_seconds"])
@pytest.mark.parametrize("value", [0, -1, float("nan"), float("inf")])
def test_sdk_rejects_invalid_explicit_deadlines(field, value):
    with pytest.raises(ValidationError, match=field):
        run_info(**{field: value})
