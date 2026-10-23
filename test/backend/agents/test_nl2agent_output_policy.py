# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Output policy boundaries for the ephemeral NL2Agent creator."""

import pytest

from nexent.core.agents.agent_model import AgentConfig

from agents.nl2agent_agent import create_nl2agent_agent_config


@pytest.mark.parametrize("language", ["zh", "en"])
def test_creator_enables_strict_output_without_changing_target_defaults(language):
    creator = create_nl2agent_agent_config(language)
    target = AgentConfig(name="target", description="Target", tools=[], model_name="main_model")

    assert creator.output_protocol == "code_action"
    assert creator.enable_protocol_repair_retry is True
    assert creator.model_dump()["enable_protocol_repair_retry"] is True
    assert target.enable_protocol_repair_retry is False


@pytest.mark.parametrize("strict", [False, True])
def test_target_output_policy_remains_independent(strict):
    target = AgentConfig(
        name="target", description="Target", tools=[], model_name="main_model",
        enable_protocol_repair_retry=strict,
    )
    create_nl2agent_agent_config("zh")

    assert target.enable_protocol_repair_retry is strict
