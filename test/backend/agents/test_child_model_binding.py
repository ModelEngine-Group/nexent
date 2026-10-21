# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Capture child version options before parent request overlays."""

import pytest
from agents import create_agent_info as service
from nexent.core.agents.agent_model import AgentConfig, ModelConfig


def config(name, core="jiuwen", children=None):
    return AgentConfig(name=name, description=name, model_name="shared", tools=[], agent_core=core,
                       worker_agents=children or [], agent_id=2, version_no=3)


def test_child_and_grandchild_capture_saved_options_without_parent_overlay(mocker):
    grandchild = config("grandchild", "smolagents")
    child = config("child", children=[grandchild])
    root = config("parent", children=[child])
    models = [ModelConfig(cite_name="shared", model_name="model", url="http://saved", temperature=0.5)]
    lookup = mocker.patch.object(service, "search_agent_info_by_agent_id", return_value={
        "model_params_override": {"7": {"temperature": 0.2, "extra_params": {"__custom__": {"saved": 1}}}}})
    mocker.patch.object(service, "get_model_by_model_id", return_value={"display_name": "shared"})
    compile_profile = mocker.patch("management.services.model.runtime_options.compile_model_runtime_profile",
                                  return_value=None)
    service._capture_child_model_configs(root, models, "tenant")
    models[0].temperature = 0.9
    assert child.runtime_model_config.temperature == grandchild.runtime_model_config.temperature == 0.2
    assert child.runtime_model_config.extra_body == {"saved": 1}
    child.runtime_model_config.extra_body["saved"] = 2
    assert grandchild.runtime_model_config.extra_body == {"saved": 1}
    assert lookup.call_count == 2
    assert lookup.call_args.kwargs == {"agent_id": 2, "tenant_id": "tenant", "version_no": 3}
    compile_profile.assert_called_once()


def test_missing_child_model_fails_before_runtime(mocker):
    mocker.patch.object(service, "search_agent_info_by_agent_id", return_value={})
    with pytest.raises(ValueError, match="CHILD_MODEL_OUTLET_NOT_FOUND"):
        service._capture_child_model_configs(config("root", children=[config("child")]), [], "tenant")
