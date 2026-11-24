# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Saved outlet output preferences must reach the existing context-budget resolver."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from infrastructure import agent_model_config, model_adapter
from management.services.agent.preparation import run as run_preparation
from management.services.conversation import model_preferences
from management.services.model import run_budget as model_budget


@pytest.mark.parametrize("reserve,requested,expected", [(None, 4096, 4096), (1024, 4096, 4096),
    (8192, 4096, 4096), (1024, None, 1024), (None, None, None)])
def test_saved_output_default_does_not_become_provider_hard_limit(monkeypatch, reserve, requested, expected):
    parameters = {} if requested is None else {"max_output_tokens": requested}
    profile = SimpleNamespace(identity=SimpleNamespace(request_model_id="exact", provider_id="provider"),
        connection=SimpleNamespace(base_url="https://models.invalid/v1"),
        capabilities=SimpleNamespace(context=SimpleNamespace(combined_window=200000,
            input_limit=None, output_limit=32768)),
        context_configuration=SimpleNamespace(output_reserve_tokens=reserve, tokenizer_family=None,
            capacity_source="profile", capability_profile_version=None), parameter_values=parameters)
    monkeypatch.setattr(model_adapter, "project_saved_outlet", Mock(
        return_value={"reasoning_capability": {"status": "unknown"}},
    ))
    factory = Mock()
    monkeypatch.setattr(agent_model_config, "ModelConfig", factory)
    agent_model_config._resolved_model_config({"display_name": "chosen", "api_key": None}, profile)
    values = factory.call_args.kwargs
    assert values["api_key"] == ""
    assert values["max_output_tokens"] == 32768
    assert values["default_output_reserve_tokens"] == expected
    assert values["resolved_profile"] is profile
    assert profile.parameter_values == parameters


def test_frozen_outlet_request_default_controls_budget_without_replacing_saved_reserve():
    record = {"profile_schema_version": 1, "default_output_reserve_tokens": 8192,
              "default_max_output_tokens": 2048, "max_output_tokens": 32768}
    overrides = model_budget._operator_overrides_from_model_info(record)
    assert overrides["default_output_reserve_tokens"] == 2048
    assert overrides["max_output_tokens"] == 32768
    assert record["default_output_reserve_tokens"] == 8192


def test_conversation_preferences_clone_only_the_root_and_keep_child_model_references(monkeypatch):

    profile = SimpleNamespace(outlet_id=42)
    resolved = SimpleNamespace(parameter_values={"temperature": 0})
    merge = Mock(return_value=resolved)
    monkeypatch.setattr(model_preferences, "merge_model_preferences", merge)
    copied = SimpleNamespace(cite_name="private-root")
    original = SimpleNamespace(cite_name="selected", resolved_profile=profile,
        default_output_reserve_tokens=512, model_copy=Mock(return_value=copied))
    child_model = SimpleNamespace(cite_name="child", resolved_profile=profile)
    models = [original, child_model]
    agent = SimpleNamespace(model_name="selected", worker_agents=[SimpleNamespace(model_name="selected")])
    run_preparation.apply_root_model_preferences(models, agent, {"42": {"temperature": 0}})
    merge.assert_called_once_with(profile, {"temperature": 0})
    assert models == [original, child_model, copied]
    assert original.resolved_profile is profile and child_model.resolved_profile is profile
    assert agent.model_name == "private-root" and agent.worker_agents[0].model_name == "selected"
