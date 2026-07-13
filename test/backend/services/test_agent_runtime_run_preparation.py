import os
import sys
import types
from types import SimpleNamespace

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
backend_path = os.path.join(project_root, "backend")
for path in (project_root, backend_path):
    if path not in sys.path:
        sys.path.insert(0, path)

from backend.services.agent_runtime.models import (
    AgentRunRequestContext,
    ContextMode,
    ToolSource,
)
from backend.services.agent_runtime.providers import KnowledgeProvider
from backend.services.agent_runtime.run_preparation import (
    agent_run_plan_from_legacy_info,
    build_production_capability_providers,
    enhance_legacy_knowledge_tools,
)


def _request() -> AgentRunRequestContext:
    return AgentRunRequestContext(
        request_id="req-1",
        runtime_provider="smolagents",
        agent_id=1,
        conversation_id=10,
        query="hello",
        history=[],
        minio_files=[],
        user_id="user-1",
        tenant_id="tenant-1",
        language="zh",
        is_debug=False,
        version_no=0,
    )


def test_enhance_legacy_knowledge_tools_uses_knowledge_provider(monkeypatch):
    run_preparation = sys.modules[enhance_legacy_knowledge_tools.__module__]

    class FakeToolConfig(SimpleNamespace):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)

    agent_model_module = types.ModuleType("nexent.core.agents.agent_model")
    agent_model_module.ToolConfig = FakeToolConfig
    monkeypatch.setitem(sys.modules, "nexent", types.ModuleType("nexent"))
    monkeypatch.setitem(sys.modules, "nexent.core", types.ModuleType("nexent.core"))
    monkeypatch.setitem(
        sys.modules, "nexent.core.agents", types.ModuleType("nexent.core.agents")
    )
    monkeypatch.setitem(
        sys.modules, "nexent.core.agents.agent_model", agent_model_module
    )

    provider = KnowledgeProvider(
        embedding_model_resolver=lambda tenant_id, index_name: "embedding-model",
        rerank_model_resolver=lambda tenant_id, model_name: "rerank-model",
        vector_db_resolver=lambda: "vdb-core",
        knowledge_name_map_resolver=lambda index_names: {"idx": "Handbook"},
        knowledge_summary_resolver=lambda index_name: {"summary": "Summary"},
    )
    monkeypatch.setattr(
        run_preparation, "_default_knowledge_provider", lambda: provider
    )

    tool = FakeToolConfig(
        class_name="KnowledgeBaseSearchTool",
        name="knowledge_base_search",
        description="Search KB",
        inputs='{"query": {"type": "string"}}',
        output_type="string",
        params={
            "index_names": ["idx"],
            "rerank": True,
            "rerank_model_name": "reranker",
            "document_paths": ["/docs/a.md"],
        },
        source="local",
        usage=None,
        metadata=None,
    )
    agent_run_info = SimpleNamespace(
        agent_config=SimpleNamespace(name="root", tools=[tool])
    )

    enhance_legacy_knowledge_tools(agent_run_info, _request())

    enhanced = agent_run_info.agent_config.tools[0]
    assert enhanced.source == "local"
    assert enhanced.metadata["vdb_core"] == "vdb-core"
    assert enhanced.metadata["embedding_model"] == "embedding-model"
    assert enhanced.metadata["rerank_model"] == "rerank-model"
    assert enhanced.metadata["display_name_to_index_map"] == {"Handbook": "idx"}
    assert enhanced.metadata["index_name_to_display_map"] == {"idx": "Handbook"}
    assert enhanced.metadata["document_paths"] == ["/docs/a.md"]
    assert "document_paths" not in enhanced.inputs


def test_production_legacy_bridge_builds_non_empty_openjiuwen_plan():
    tool = SimpleNamespace(
        class_name="ReadSkillMdTool",
        name="read_skill_md",
        description="Read skill",
        inputs='{"skill_name": "str", "additional_files": "list[str]"}',
        output_type="string",
        params={"local_skills_dir": "/skills"},
        source="builtin",
        usage="builtin",
        metadata={"agent_id": 1, "tenant_id": "tenant-1", "version_no": 2},
    )
    agent_config = SimpleNamespace(
        name="root",
        description="Root agent",
        model_name="main_model",
        max_steps=5,
        prompt_templates={"system_prompt": "legacy final_answer() prompt"},
        prompt_fragments={
            "duty": "Answer the user.",
            "runtime_instructions": "Use function tools.",
        },
        tools=[tool],
        managed_agents=[],
        external_a2a_agents=[],
        context_manager_config=SimpleNamespace(
            enabled=True,
            token_threshold=8192,
            soft_input_budget_tokens=7168,
            hard_input_budget_tokens=8192,
        ),
        context_components=[],
        verification_config={"enabled": False},
        requested_output_tokens=256,
        provide_run_summary=False,
        instructions=None,
        capacity_snapshot=None,
        safe_input_budget_snapshot=None,
    )
    run_info = SimpleNamespace(
        query="hello",
        history=[SimpleNamespace(role="user", content="previous")],
        model_config_list=[
            SimpleNamespace(
                cite_name="main_model",
                model_name="gpt-4o-mini",
                api_key="key",
                url="https://api.example/v1",
                ssl_verify=True,
                model_factory="OpenAIModel",
            )
        ],
        agent_config=agent_config,
        mcp_host=[],
        observer=object(),
        stop_event=__import__("threading").Event(),
    )
    request = _request().model_copy(update={"runtime_provider": "openjiuwen"})

    providers = build_production_capability_providers(run_info, request)
    plan = agent_run_plan_from_legacy_info(run_info, request)

    assert [provider.name for provider in providers] == ["prepared-agent-run"]
    assert plan.runtime_provider == "openjiuwen"
    assert plan.root_agent.prompt.fragments["duty"] == "Answer the user."
    assert plan.root_agent.prompt.rendered_legacy_system_prompt == (
        "legacy final_answer() prompt"
    )
    assert plan.root_agent.tools[0].source == ToolSource.BUILTIN
    assert plan.root_agent.tools[0].input_schema == {
        "skill_name": {"type": "string"},
        "additional_files": {
            "type": "array",
            "items": {"type": "string"},
        },
    }
    assert plan.model_config_list[0]["model_name"] == "gpt-4o-mini"
    assert "streaming" in plan.capability_requirements.required
    assert plan.root_agent.context_policy.mode == ContextMode.RUNTIME_NATIVE
    assert "context_compression" not in plan.capability_requirements.required
    assert plan.monitoring_metadata["assembly_warnings"][0]["code"] == (
        "context_policy_normalized"
    )
    assert "tool_artifacts" in plan.capability_requirements.optional
    assert [operator.name for operator in plan.operators] == ["skill_file_upload"]
    assert plan.monitoring_metadata["assembly_path"] == ("production_prepared_provider")
    assert plan.runtime_resources["tool_factory_registry"].list_factories()

    smolagents_plan = agent_run_plan_from_legacy_info(run_info, _request())
    assert smolagents_plan.root_agent.context_policy.mode == ContextMode.MANAGED
    assert "context_compression" in smolagents_plan.capability_requirements.required
