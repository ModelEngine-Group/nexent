# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Capture child version options before parent request overlays."""

import pytest
import management.services.agent.preparation.run as service
from nexent.core.agents.contracts.config import AgentConfig, ModelConfig
from test.backend.database.model_outlet_helpers import profile  # noqa: F401


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


def test_canonical_child_snapshot_is_not_rebuilt_from_legacy_scalar_defaults(profile, mocker):
    child = config("child")
    root = config("root", children=[child])
    model = ModelConfig(cite_name="shared", model_name=profile.identity.request_model_id,
                        url=profile.connection.base_url, resolved_profile=profile, temperature=0.9)
    legacy = mocker.patch("management.services.model.runtime_options.compile_model_runtime_profile",
                          side_effect=AssertionError("Canonical views must not replay legacy scalar values"))
    service._capture_child_model_configs(root, [model], "tenant")
    assert child.runtime_model_config.resolved_profile == profile
    assert child.runtime_model_config.resolved_profile.parameter_values == {"custom": False}
    assert child.runtime_model_config is not model
    legacy.assert_not_called()


def test_bound_profile_rejects_missing_provisioning():
    from management.services.model.runtime_options import compile_bound_model_profile
    with pytest.raises(ValueError, match="PROVISIONING_REQUIRED"):
        compile_bound_model_profile(ModelConfig(cite_name="shared", model_name="model", url="http://saved"), config("root"))
