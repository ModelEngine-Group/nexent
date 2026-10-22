# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Native file creation shares sandbox execution without exposing text internals."""

import json
from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from nexent.core.agents.agent_model import (
    AgentConfig,
    AgentRunInfo,
    ModelConfig,
    ToolConfig,
)
from nexent.core.agents.core_adapters.base import UnsupportedAgentCoreConfig
from nexent.core.agents.core_adapters.jiuwen import JiuwenAdapter
from nexent.core.agents.core_adapters.jiuwen_messages import resource_view
from nexent.core.agents.core_adapters.jiuwen_protocol import (
    EXECUTION_TOOL,
    NATIVE_EXECUTION_TOOL,
)
from nexent.core.utils.observer import MessageObserver
from test_jiuwen_model_service import saved_profile as _saved_profile

saved_profile = _saved_profile


@pytest.mark.parametrize("text_mode", [False, True])
def test_executor_registration_reuses_sandbox_and_keeps_self_out_of_bindings(mocker, text_mode):
    executor = Mock()
    executor_result = SimpleNamespace(output="created.docx", logs="written", is_final_answer=False)
    execute = mocker.patch("nexent.core.agents.sandbox._execute_with_tool_context", return_value=executor_result)
    build = mocker.patch("nexent.core.agents.sandbox.build_python_executor")
    adapter = JiuwenAdapter(SimpleNamespace(agent_config=SimpleNamespace(name="files")))
    adapter.text_protocol = text_mode
    adapter.resources = SimpleNamespace(agent=SimpleNamespace(python_executor=executor))
    adapter.native_agent = SimpleNamespace(ability_manager=Mock())
    adapter.resource_bridge = SimpleNamespace(bindings=Mock(return_value={"upload_to_s3": Mock()}))
    handler = mocker.patch.object(adapter, "_business_handler", side_effect=lambda name, fn, **kwargs: fn)
    adapter._bind_text_executor()
    build.assert_not_called()
    card, _ = adapter.native_agent.ability_manager.add_ability.call_args.args
    assert card.name == (EXECUTION_TOOL if text_mode else NATIVE_EXECUTION_TOOL)
    assert card.input_params["additionalProperties"] is False
    assert handler.call_args.kwargs["lane"] == "sandbox"
    result = json.loads(handler.call_args.args[1]("print('created.docx')"))
    execute.assert_called_once_with(executor, "print('created.docx')")
    executor.send_tools.assert_called_once_with(adapter.resource_bridge.bindings())
    assert result == {"output": "created.docx", "logs": "written", "is_final_answer": False}
    assert NATIVE_EXECUTION_TOOL not in adapter.visible_tool_names


def test_native_executor_is_model_visible_but_text_internal_entry_is_never_advertised():
    tools = [{"name": name, "parameters": {"type": "object"}}
             for name in (EXECUTION_TOOL, NATIVE_EXECUTION_TOOL, "read_skill_md")]
    view = resource_view("Create a document", tools)
    assert [tool.name for tool in view.tool_definitions] == [NATIVE_EXECUTION_TOOL, "read_skill_md"]


def test_native_guidance_uses_authorized_skill_api_not_guessed_s3_paths(mocker):
    mocker.patch("nexent.core.agents.run_agent._get_authorized_context_items", return_value=[])
    mocker.patch("nexent.core.agents.run_agent._get_authorized_history", return_value=[])
    info = SimpleNamespace(agent_config=SimpleNamespace(name="files", instructions="Write files", description=""))
    adapter = JiuwenAdapter(info)
    prompt = adapter._compile_context()
    assert "read_skill_md" in prompt and "run_skill_script" in prompt
    assert "never invent skill names, script paths or S3 paths" in prompt
    assert "nexent_execute_python" in prompt and "never for skills" in prompt


@pytest.mark.parametrize("reserved", [EXECUTION_TOOL, NATIVE_EXECUTION_TOOL])
def test_saved_tool_cannot_replace_runtime_owned_execution_entry(saved_profile, reserved):
    info = AgentRunInfo(query="Create a file", observer=MessageObserver(lang="en"), stop_event=Event(),
        tenant_id="tenant", agent_config=AgentConfig(name="files", description="Fixture", model_name="model",
            tools=[ToolConfig(name=reserved, class_name="Fake", source="builtin")]),
        model_config_list=[ModelConfig(cite_name="model", model_name=saved_profile.identity.request_model_id,
            url=saved_profile.connection.base_url, resolved_profile=saved_profile)])
    with pytest.raises(UnsupportedAgentCoreConfig, match="Reserved"):
        JiuwenAdapter(info).validate()


@pytest.mark.parametrize("class_name", ["ReadSkillMdTool", "ReadSkillConfigTool", "RunSkillScriptTool"])
@pytest.mark.parametrize("authorized", [None, [], ["docx"]])
def test_native_skill_rail_requires_explicit_snapshot_for_every_skill_tool(class_name, authorized, tmp_path):
    adapter = JiuwenAdapter(SimpleNamespace(agent_config=SimpleNamespace(name="files")))
    params = {"local_skills_dir": str(tmp_path)}
    if authorized is not None:
        params["authorized_skill_names"] = authorized
    adapter.tool_configs = [SimpleNamespace(class_name=class_name, params=params)]
    if authorized is None:
        with pytest.raises(UnsupportedAgentCoreConfig, match="explicit authorized"):
            adapter._skill_rails()
    else:
        rails = adapter._skill_rails()
        assert len(rails) == bool(authorized)
        if rails:
            assert rails[0]._names == frozenset({"docx"})
