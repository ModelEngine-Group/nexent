from types import SimpleNamespace

import pytest

from services.agent_automation import capability_resolver
from services.agent_automation.models import (
    CapabilityBinding,
    CapabilityResolution,
    CapabilityType,
)


def test_binding_helpers_preserve_runtime_identity_and_metadata():
    knowledge_tool = SimpleNamespace(
        class_name="KnowledgeBaseSearchTool",
        name=None,
        params={"index_names": ["kb-a", "kb-b"]},
        metadata={"index_name_to_display_map": {"kb-a": "产品知识"}},
    )
    regular_tool = SimpleNamespace(
        class_name="WebSearchTool",
        name="web_search",
        description="Search the public web",
        metadata=None,
    )

    knowledge = capability_resolver._tool_binding(knowledge_tool)
    tool = capability_resolver._tool_binding(regular_tool)
    skill = capability_resolver._skill_binding({"name": "report", "description": "Write reports"})
    managed = capability_resolver._agent_binding(
        SimpleNamespace(agent_id=9, description=None),
        CapabilityType.MANAGED_AGENT,
    )

    assert knowledge.type == CapabilityType.KNOWLEDGE_BASE
    assert knowledge.name == "kb-a,kb-b"
    assert knowledge.display_name == "产品知识, kb-b"
    assert knowledge.binding_ref == "tool:KnowledgeBaseSearchTool:index:kb-a,kb-b"
    assert tool.binding_ref == "tool:web_search"
    assert tool.reason == "Search the public web"
    assert skill.binding_ref == "skill:report"
    assert managed.name == "9"
    assert capability_resolver._safe_text("ABC", None) == "abc "
    assert capability_resolver._flatten_bindings([tool]) == {"tool:web_search": tool}


@pytest.mark.asyncio
async def test_resolve_agent_capabilities_collects_all_configured_sources(monkeypatch):
    agent_config = SimpleNamespace(
        name="weather-agent",
        description="Weather and knowledge assistant",
        tools=[
            SimpleNamespace(
                class_name="WebSearchTool",
                name="web_search",
                description="联网搜索",
                metadata={},
            ),
            SimpleNamespace(
                class_name="KnowledgeBaseSearchTool",
                name="knowledge",
                params={"index_names": ["project"]},
                metadata={"index_name_to_display_map": {"project": "项目资料"}},
            ),
        ],
        context_components=[
            SimpleNamespace(
                component_type="skills",
                skills=[{"name": "context-skill", "description": "Context skill"}],
            ),
            SimpleNamespace(component_type="memory", skills=[]),
        ],
        managed_agents=[SimpleNamespace(name="researcher", description="Research agent")],
        external_a2a_agents=[SimpleNamespace(name="external", description="External agent")],
    )
    captured = {}

    async def fake_create_agent_config(**kwargs):
        captured.update(kwargs)
        return agent_config

    monkeypatch.setattr("agents.create_agent_info.create_agent_config", fake_create_agent_config)
    monkeypatch.setattr(
        "services.skill_service.SkillService.get_enabled_skills_for_agent",
        lambda self, **kwargs: [{"name": "enabled-skill", "description": "Enabled skill"}],
    )
    monkeypatch.setattr(
        capability_resolver,
        "resolve_agent_display_names",
        lambda references, tenant_id: {(7, 3): "天气助手"},
    )

    resolution = await capability_resolver.resolve_agent_capabilities(
        7,
        "tenant",
        "user",
        "联网搜索项目资料",
        version_no=3,
    )

    assert resolution.executable is True
    assert resolution.missing_capabilities == []
    assert {binding.type for binding in resolution.matched_capabilities} == {
        CapabilityType.TOOL,
        CapabilityType.KNOWLEDGE_BASE,
        CapabilityType.SKILL,
        CapabilityType.MANAGED_AGENT,
        CapabilityType.EXTERNAL_A2A_AGENT,
    }
    assert resolution.agent_snapshot == {
        "agent_id": 7,
        "version_no": 3,
        "name": "weather-agent",
        "display_name": "天气助手",
        "description": "Weather and knowledge assistant",
        "tools_count": 2,
        "skills_count": 2,
        "managed_agents_count": 1,
        "external_a2a_agents_count": 1,
    }
    assert captured["allow_memory_search"] is False
    assert captured["last_user_query"] == "联网搜索项目资料"


@pytest.mark.asyncio
async def test_resolve_agent_capabilities_reports_missing_requirements_and_tolerates_skill_failure(monkeypatch):
    agent_config = SimpleNamespace(
        name="plain-agent",
        description="",
        tools=[],
        context_components=[],
        managed_agents=[],
        external_a2a_agents=[],
    )

    async def fake_create_agent_config(**kwargs):
        return agent_config

    def raise_skill_error(self, **kwargs):
        raise RuntimeError("skill service unavailable")

    monkeypatch.setattr("agents.create_agent_info.create_agent_config", fake_create_agent_config)
    monkeypatch.setattr(
        "services.skill_service.SkillService.get_enabled_skills_for_agent",
        raise_skill_error,
    )
    monkeypatch.setattr(capability_resolver, "resolve_agent_display_names", lambda references, tenant_id: {})

    resolution = await capability_resolver.resolve_agent_capabilities(
        8,
        "tenant",
        "user",
        "搜索知识库资料",
    )

    assert resolution.executable is False
    assert [item["name"] for item in resolution.missing_capabilities] == [
        "web_search",
        "knowledge_base",
    ]
    assert resolution.matched_capabilities == []
    assert resolution.agent_snapshot["display_name"] == "plain-agent"


@pytest.mark.asyncio
async def test_validate_bindings_available_returns_stale_bindings(monkeypatch):
    available = CapabilityBinding(
        type=CapabilityType.TOOL,
        name="web_search",
        display_name="web_search",
        binding_ref="tool:web_search",
    )
    resolution = CapabilityResolution(
        matched_capabilities=[available],
        agent_snapshot={"agent_id": 1},
        executable=True,
    )

    async def fake_resolve(*args, **kwargs):
        return resolution

    monkeypatch.setattr(capability_resolver, "resolve_agent_capabilities", fake_resolve)

    stale = {"binding_ref": "tool:removed", "name": "removed"}
    result = await capability_resolver.validate_bindings_available(
        1,
        "tenant",
        "user",
        "search",
        [available.model_dump(mode="json"), stale, {"name": "legacy-without-ref"}],
    )

    assert result["available"] is False
    assert result["unavailable_bindings"] == [stale]
    assert result["resolution"]["executable"] is True
