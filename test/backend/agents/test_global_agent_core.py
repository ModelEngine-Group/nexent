# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Deployment policy, creator boundaries and saved configuration regressions."""

import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from management.services.agent import core_policy
from nexent.core.agents.contracts.adapter import UnsupportedAgentCoreConfig
from nexent.core.agents.contracts.config import AgentConfig, AgentVerificationConfig, GuardrailConfig
from nexent.core.agents.cores.jiuwen.adapter import JiuwenAdapter
from nexent.core.agents.cores.jiuwen.events import JiuwenEventAdapter
from nexent.core.utils.observer import MessageObserver


def agent(**values):
    return AgentConfig(**{"name": "fixture", "description": "fixture", "model_name": "model", "tools": [], **values})


@pytest.mark.parametrize("core", ["smolagents", "jiuwen"])
def test_global_policy_overrides_conflicting_root_and_child_without_changing_saved_values(monkeypatch, core):
    monkeypatch.setattr(core_policy, "NEXENT_AGENT_CORE", core)
    saved = agent(agent_core="jiuwen" if core == "smolagents" else "smolagents",
                  enable_protocol_repair_retry=True, provide_run_summary=True,
                  verification_config=AgentVerificationConfig(enabled=True),
                  worker_agents=[agent(model_name="child-model")])
    snapshot = saved.model_dump()
    config = core_policy.apply_agent_core_policy(saved.model_copy(deep=True))
    assert config.agent_core == core
    assert config.worker_agents[0].agent_core == core
    assert config.worker_agents[0].model_name == "child-model"
    assert saved.model_dump() == snapshot
    assert config.enable_protocol_repair_retry is (core == "smolagents")
    assert config.verification_config.enabled is (core == "smolagents")


def test_global_jiuwen_never_silently_disables_guardrails(monkeypatch):
    monkeypatch.setattr(core_policy, "NEXENT_AGENT_CORE", "jiuwen")
    config = agent(verification_config=AgentVerificationConfig(guardrail_config=GuardrailConfig(enabled=True)))
    with pytest.raises(UnsupportedAgentCoreConfig, match="guardrail"):
        core_policy.apply_agent_core_policy(config)
    assert config.verification_config.guardrail_config.enabled


def test_creator_preparation_carries_identity_and_final_model_profile(monkeypatch):
    monkeypatch.setattr(core_policy, "NEXENT_AGENT_CORE", "jiuwen")
    compile_profile = Mock(return_value="compiled")
    monkeypatch.setattr("management.services.model.runtime_options.compile_bound_model_profile", compile_profile)
    model = SimpleNamespace(cite_name="model", prompt_cache={"enabled": True}, resolved_profile="saved")
    info = SimpleNamespace(agent_config=agent(), model_config_list=[model])
    core_policy.prepare_creator_core(info, tenant_id="tenant", user_id="user")
    assert info.tenant_id == "tenant" and info.user_id == "user"
    assert info.user_context == {"tenant_id": "tenant", "user_id": "user"}
    assert model.resolved_profile == "compiled" and model.prompt_cache is None
    compile_profile.assert_called_once_with(model, info.agent_config)


def test_artifact_output_preserves_literal_code_without_registering_tools():
    text = '<final_answer><skill>Example <code>print(1)</code></skill><summary>done</summary></final_answer>'
    observer = MessageObserver()
    events = JiuwenEventAdapter(observer, "artifact")
    events.artifact_output = True
    events.emit({"type": "answer", "payload": {"output": text}})
    assert events.finish().final_content == text
    assert events.result.status == "completed"


def test_interactive_boundary_is_completed_without_fabricating_an_answer():
    events = JiuwenEventAdapter(MessageObserver(), "creator")
    events.waiting_for_input = True
    result = events.finish()
    assert result.status == "completed" and result.end_reason == "awaiting_input"
    assert result.final_content == "" and result.final_block_ids == [] and result.error is None


def test_workflow_result_exposes_trusted_card_payload_instead_of_json_escaped_logs():
    observer = MessageObserver(enable_nl2a_wrapper=True)
    info = SimpleNamespace(agent_config=agent(response_mode="python_workflow"), observer=observer, query="create")
    adapter = JiuwenAdapter(info)
    log = '<nl2a>\n{"subtype":"requirement_clarification","agent_id":42,"questions":[]}\n</nl2a>'
    captured = []
    observer.add_message = lambda name, kind, content, **kwargs: captured.append(content)
    adapter._resource_result(json.dumps({"logs": log, "output": "None"}))
    assert captured == [log]


def test_jiuwen_rejects_artifact_tools_before_model_acquisition():
    from nexent.core.agents.contracts.config import ToolConfig
    config = agent(response_mode="artifact", output_protocol="final_envelope")
    config.tools = [ToolConfig(name="forbidden", class_name="forbidden", source="local", params={})]
    info = SimpleNamespace(agent_config=config, observer=None, query="create", model_config_list=[])
    with pytest.raises(UnsupportedAgentCoreConfig, match="artifact"):
        JiuwenAdapter(info).validate()


@pytest.mark.parametrize("core", ["smolagents", "jiuwen"])
@pytest.mark.parametrize("language", ["zh", "en"])
def test_creator_configs_follow_global_policy_and_target_prompt_contract(monkeypatch, core, language):
    from management.services.agent import creation
    from management.services.skill.creation import create_nl2skill_agent_config
    monkeypatch.setattr(core_policy, "NEXENT_AGENT_CORE", core)
    monkeypatch.setattr(creation, "NEXENT_AGENT_CORE", core)
    config = creation.create_nl2agent_agent_config(language)
    assert config.agent_core == core and config.response_mode == "python_workflow"
    assert config.enable_protocol_repair_retry is (core == "smolagents")
    prompt = config.context_items[0].content["text"]
    assert "nl2agent_verified_state" in prompt and "agent_generation_completed" in prompt
    if core == "jiuwen":
        assert "Core" in prompt
        assert "\\x3ccode>" not in prompt
        assert "Think-Code example" not in prompt and "思考-代码”示例" not in prompt
    skill = create_nl2skill_agent_config("literal data", "model")
    assert skill.agent_core == core and skill.response_mode == "artifact"
    assert skill.tools == [] and skill.output_protocol == "final_envelope"


@pytest.mark.parametrize("value,expected", [(None,"smolagents"),("jiuwen","jiuwen"),(" SMOLAGENTS ","smolagents"),("unknown",None),("",None)])
def test_deployment_core_environment_is_validated_at_import(value, expected):
    import os
    import subprocess
    import sys
    from pathlib import Path
    environment = dict(os.environ)
    environment.pop("NEXENT_AGENT_CORE", None)
    if value is not None:
        environment["NEXENT_AGENT_CORE"] = value
    code = "import dotenv; dotenv.load_dotenv=lambda **kwargs: False; from contracts.constants.environment import NEXENT_AGENT_CORE; print(NEXENT_AGENT_CORE)"
    environment["PYTHONPATH"] = str(Path(__file__).resolve().parents[3] / "backend")
    result = subprocess.run([sys.executable,"-c",code], env=environment, capture_output=True, text=True, encoding="utf-8")
    if expected is None:
        assert result.returncode != 0 and "NEXENT_AGENT_CORE must be" in result.stderr
    else:
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == expected


@pytest.mark.parametrize("core", ["smolagents", "jiuwen"])
def test_local_child_factory_uses_global_core_and_its_own_model(monkeypatch, core):
    from threading import Event
    from nexent.core.agents.contracts.config import ModelConfig
    from nexent.core.agents.contracts.run import AgentRunInfo
    from nexent.core.agents.factory import AgentCoreFactory
    from nexent.core.agents.orchestration.children import child_run_info
    from nexent.core.concurrency import RunCancellationScope

    monkeypatch.setattr(core_policy, "NEXENT_AGENT_CORE", core)
    binding = ModelConfig(cite_name="child-model", model_name="child-outlet", url="http://child.invalid/v1")
    child = agent(model_name="child-model", runtime_model_config=binding)
    config = core_policy.apply_agent_core_policy(agent(worker_agents=[child]))
    parent = AgentRunInfo(query="parent-only", agent_config=config,
                          model_config_list=[ModelConfig(cite_name="model", model_name="parent-outlet", url="http://parent.invalid/v1")],
                          observer=MessageObserver(), stop_event=Event(), tenant_id="tenant")
    info = child_run_info(parent, config.worker_agents[0], RunCancellationScope())
    assert AgentCoreFactory.create(info).core_name == core
    assert info.agent_config.model_name == "child-model"
    selected = next(model for model in info.model_config_list if model.cite_name == "child-model")
    assert selected.model_name == "child-outlet" and selected.url == binding.url
    assert info.query == "" and info.history is None and info.context_input is None
