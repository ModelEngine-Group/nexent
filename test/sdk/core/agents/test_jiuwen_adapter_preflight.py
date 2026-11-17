# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Jiuwen rejects unsupported policies and untrusted outlets before acquisition."""

from threading import Event

import pytest
from jsonschema import validate

from nexent.core.agents.contracts.adapter import UnsupportedAgentCoreConfig
from nexent.core.agents.contracts.config import AgentConfig, AgentVerificationConfig, ModelConfig, ToolConfig
from nexent.core.agents.contracts.run import AgentRunInfo
from nexent.core.agents.cores.jiuwen.adapter import JiuwenAdapter, _tool_schema
from nexent.core.utils.observer import MessageObserver
from test_jiuwen_model_service import saved_profile


@pytest.fixture
def info(saved_profile):
    return AgentRunInfo(query="Summarize", tenant_id="tenant", stop_event=Event(), observer=MessageObserver(),
        agent_config=AgentConfig(name="fixture", description="Fixture", model_name="model", tools=[]),
        model_config_list=[ModelConfig(cite_name="model", model_name=saved_profile.identity.request_model_id,
            url=saved_profile.connection.base_url, resolved_profile=saved_profile)])


@pytest.mark.parametrize("option,value", [
    ("enable_planning", True), ("provide_run_summary", True), ("enable_protocol_repair_retry", True),
    ("output_protocol", "final_envelope"), ("verification_config", AgentVerificationConfig(enabled=True)),
])
def test_unsupported_policies_fail_before_preparation(info, option, value, mocker):
    setattr(info.agent_config, option, value)
    resources = mocker.patch("nexent.core.agents.cores.jiuwen.adapter.AgentResources")
    with pytest.raises(UnsupportedAgentCoreConfig, match="does not yet support"):
        JiuwenAdapter(info).validate()
    resources.assert_not_called()


@pytest.mark.parametrize("failure,expected", [
    ("missing_alias", "Model alias not found"), ("missing_profile", "trusted resolved"),
    ("unsaved", "saved model outlet"), ("tenant", "tenant mismatch"),
    ("model", "identity mismatch"), ("endpoint", "identity mismatch"),
])
def test_outlet_binding_is_checked_before_execution(info, failure, expected):
    model = info.model_config_list[0]
    if failure == "missing_alias":
        info.agent_config.model_name = "absent"
    elif failure == "missing_profile":
        model.resolved_profile = None
    elif failure == "unsaved":
        model.resolved_profile = model.resolved_profile.model_copy(update={"outlet_id": None})
    elif failure == "tenant":
        info.tenant_id = "other"
    elif failure == "model":
        model.model_name = "other-model"
    else:
        model.url = "https://other.invalid/v1"
    with pytest.raises((UnsupportedAgentCoreConfig, ValueError), match=expected):
        JiuwenAdapter(info).validate()


def test_tool_name_and_host_validation_preserves_saved_configuration(info):
    duplicate = ToolConfig(name="lookup", class_name="Lookup", source="local")
    info.agent_config.tools = [duplicate, duplicate.model_copy()]
    with pytest.raises(ValueError, match="Duplicate tool names"):
        JiuwenAdapter(info).validate()
    info.agent_config.tools = [ToolConfig(name="lookup", class_name="Lookup", source="mcp")]
    with pytest.raises(ValueError, match="resolved MCP hosts"):
        JiuwenAdapter(info).validate()
    info.mcp_host = ["http://fixture.invalid/mcp"]
    before = info.agent_config.model_dump()
    adapter = JiuwenAdapter(info)
    adapter.validate()
    assert adapter.visible_tool_names == {"lookup"}
    assert info.agent_config.model_dump() == before


def test_tool_schema_retains_defaults_nullable_omission_and_array_items():
    source = {"query": {"type": "string", "description_zh": "localized"},
              "optional": {"type": "string", "nullable": True},
              "limit": {"type": "integer", "default": 3}, "items": {"type": "array"},
              "payload": {"type": "any"}}
    schema = _tool_schema(source)
    assert schema["required"] == ["query", "items", "payload"]
    assert schema["properties"]["limit"]["default"] == 3
    assert schema["properties"]["optional"] == {"type": "string"}
    assert schema["properties"]["items"]["items"] == {}
    assert schema["properties"]["payload"] == {}
    validate({"query": "term", "items": [], "payload": {"empty": None}}, schema)
    assert source["query"]["description_zh"] == "localized"
    assert source["optional"]["nullable"] is True


@pytest.mark.parametrize("source", [None, {}, '{"type":"object","properties":{"x":{"type":"integer"}}}'])
def test_native_and_empty_tool_schema_acceptance(source):
    schema = _tool_schema(source)
    validate({}, schema)
    assert schema["type"] == "object" and schema["properties"] == ({"x": {"type": "integer"}} if source else {})


def test_prompt_policy_filters_visible_tools_without_dropping_hidden_execution_bindings(info):
    info.agent_config.tools = [ToolConfig(name=name, class_name="Lookup", source="local")
                               for name in ("visible", "hidden", "denied")]
    info.agent_config.prompt_tool_policy_snapshot = {
        "enabled": ["visible", "denied"], "allowed": ["visible"], "system_default_hidden": ["hidden"],
        "policy_version": "policy-1", "tool_schema_version": "schema-1",
    }
    adapter = JiuwenAdapter(info)
    adapter.validate()
    assert adapter.visible_tool_names == {"visible"}
    assert {tool.name for tool in adapter.tool_configs} == {"visible", "hidden"}
    assert len(info.agent_config.tools) == 3


def test_collaborator_name_cannot_shadow_an_authorized_tool(info):
    info.agent_config.tools = [ToolConfig(name="child", class_name="Lookup", source="local")]
    info.agent_config.worker_agents = [AgentConfig(name="child", description="Child", model_name="model", tools=[])]
    with pytest.raises(UnsupportedAgentCoreConfig, match="collaboration tool name"):
        JiuwenAdapter(info).validate()
