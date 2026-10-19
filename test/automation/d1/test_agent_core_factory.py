"""Formal factory, configuration compilation and observer contracts."""

import asyncio
import json
from threading import Event
from types import SimpleNamespace

import pytest

from nexent.core.agents.agent_model import AgentConfig, AgentHistory, AgentRunInfo, ModelConfig, ToolConfig
from nexent.core.agents.context.models import ContextItemInput, ContextItemType
from nexent.core.agents.core_adapters import AgentCoreAdapter, AgentCoreFactory, UnsupportedAgentCoreConfig
from nexent.core.agents.core_adapters.events import JiuwenEventAdapter
from nexent.core.agents.core_adapters.jiuwen import JiuwenAdapter, _tool_schema
from nexent.core.agents.core_adapters.smolagents import SmolagentsAdapter
from nexent.core.utils.observer import MessageObserver


def run_info(**agent_values):
    return AgentRunInfo(query="fixture", observer=MessageObserver(lang="en"), stop_event=Event(),
                        agent_config=AgentConfig(name="fixture", description="Fixture", tools=[], model_name="model",
                                                 **agent_values),
                        model_config_list=[ModelConfig(cite_name="model", model_name="native-model", url="http://fixture")])


def test_AGENT_CORE_D1_001_factory_dispatch_and_extensions(monkeypatch):
    monkeypatch.setattr(AgentCoreFactory, "_adapters", {})
    calls = []
    legacy = AgentCoreFactory.create(run_info(), smolagents_executor=lambda info: calls.append(info.query))
    assert isinstance(legacy, SmolagentsAdapter)
    legacy.validate()
    legacy.run()
    assert calls == ["fixture"]
    assert isinstance(AgentCoreFactory.create(run_info(agent_core="jiuwen")), JiuwenAdapter)
    with pytest.raises(UnsupportedAgentCoreConfig, match="Unknown"):
        AgentCoreFactory.create(run_info(agent_core="unknown"))

    class Extension(AgentCoreAdapter):
        core_name = "extension"

        @classmethod
        def capabilities(cls):
            return frozenset()

        def validate(self):
            pass

        def run(self):
            pass

    AgentCoreFactory.register("extension", Extension)
    assert isinstance(AgentCoreFactory.create(run_info(agent_core="extension")), Extension)
    with pytest.raises(ValueError, match="already registered"):
        AgentCoreFactory.register("extension", Extension)
    child = run_info(agent_core="jiuwen").agent_config
    with pytest.raises(UnsupportedAgentCoreConfig, match="Mixed-core"):
        SmolagentsAdapter(run_info(worker_agents=[child])).validate()


def test_AGENT_CORE_D1_002_native_config_and_fail_closed(monkeypatch, tmp_path):
    items = [
        ContextItemInput(id="system:duty", type=ContextItemType.SYSTEM, content={"text": "Business duty"}),
        ContextItemInput(id="system:knowledge_scope_policy", type=ContextItemType.SYSTEM,
                         content={"text": "Authorized knowledge scope"}, metadata={"authority": "platform"}),
        ContextItemInput(id="system:code_protocol", type=ContextItemType.SYSTEM, content={"text": "Forbidden code protocol"},
                         metadata={"authority": "platform"}),
        ContextItemInput(id="knowledge:fixture", type=ContextItemType.KNOWLEDGE_BASE, content={"text": "Authorized facts"}),
    ]
    info = run_info(agent_core="jiuwen", max_steps=7, instructions="Additional business instruction", context_items=items)
    info.history = [AgentHistory(role="user", content="Earlier question"), AgentHistory(role="assistant", content="Earlier answer")]
    adapter = JiuwenAdapter(info)
    adapter.validate()
    prompt = adapter._compile_context()
    assert "Business duty" in prompt and "Additional business instruction" in prompt
    assert "Authorized knowledge scope" in prompt
    assert "Forbidden code protocol" not in prompt
    assert "Earlier answer" in str(adapter.prefix_messages) and "Authorized facts" in str(adapter.prefix_messages)
    model = adapter._create_model()
    assert model.model_config.model_name == "native-model"
    assert model.model_client_config.api_base == "http://fixture"
    schema = _tool_schema({"x": {"type": "integer"}, "y": {"type": "array", "nullable": True}})
    assert schema["required"] == ["x"] and schema["properties"]["y"]["items"] == {}
    info.agent_config.enable_planning = True
    with pytest.raises(UnsupportedAgentCoreConfig, match="enable_planning"):
        JiuwenAdapter(info).validate()
    info.agent_config.enable_planning = False
    info.agent_config.tools = [ToolConfig(name="multiply", class_name="multiply", source="mcp", params={})]
    with pytest.raises(ValueError, match="resolved MCP hosts"):
        JiuwenAdapter(info).validate()
    info.agent_config.tools = []
    info.agent_config.provide_run_summary = True
    with pytest.raises(UnsupportedAgentCoreConfig, match="provide_run_summary"):
        JiuwenAdapter(info).validate()
    info.agent_config.provide_run_summary = False
    info.model_config_list[0].prompt_cache = True
    with pytest.raises(UnsupportedAgentCoreConfig, match="prompt_cache"):
        JiuwenAdapter(info).validate()

    from nexent.core.agents.core_adapters.skills import NexentSkillRail

    root = tmp_path / "library"
    allowed = root / "allowed" / "SKILL.md"
    allowed.parent.mkdir(parents=True)
    allowed.write_text("Authorized guide", encoding="utf-8-sig")
    denied = root / "denied" / "SKILL.md"
    denied.parent.mkdir()
    denied.write_text("Unauthorized guide", encoding="utf-8")
    rail = NexentSkillRail([str(root)], ["allowed"])
    assert asyncio.run(rail._read_skill_text(allowed)) == "Authorized guide"
    with pytest.raises(PermissionError, match="authorized snapshot"):
        asyncio.run(rail._read_skill_text(denied))
    escaped = tmp_path / "allowed" / "SKILL.md"
    escaped.parent.mkdir()
    escaped.write_text("Outside root", encoding="utf-8")
    with pytest.raises(PermissionError, match="escapes"):
        asyncio.run(rail._read_skill_text(escaped))


def test_AGENT_CORE_D1_003_stream_and_terminal_errors():
    info = run_info(agent_core="jiuwen")
    events = JiuwenEventAdapter(info.observer, "fixture")
    events.emit(SimpleNamespace(type="llm_output", payload={"content": "Native delta"}))
    events.emit(SimpleNamespace(type="answer", payload={"output": "Final answer", "result_type": "answer"}))
    events.finish()
    messages = [json.loads(message) for message in info.observer.get_cached_message()]
    assert [message["type"] for message in messages].count("final_answer") == 1
    assert any("Native delta" in str(message) for message in messages)
    with pytest.raises(RuntimeError, match="multiple"):
        events.emit(SimpleNamespace(type="answer", payload={"output": "Second"}))
    events = JiuwenEventAdapter(info.observer, "fixture")
    with pytest.raises(RuntimeError, match="failed"):
        events.emit(SimpleNamespace(type="answer", payload={"result_type": "error", "output": "failed"}))
    with pytest.raises(RuntimeError, match="without"):
        events.finish()
