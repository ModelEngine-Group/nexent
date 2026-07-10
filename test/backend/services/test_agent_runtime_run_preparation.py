import os
import sys
import types
from types import SimpleNamespace

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
backend_path = os.path.join(project_root, "backend")
for path in (project_root, backend_path):
    if path not in sys.path:
        sys.path.insert(0, path)

from backend.services.agent_runtime.models import AgentRunRequestContext
from backend.services.agent_runtime.providers import KnowledgeProvider
from backend.services.agent_runtime.run_preparation import enhance_legacy_knowledge_tools


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
    monkeypatch.setitem(sys.modules, "nexent.core.agents", types.ModuleType("nexent.core.agents"))
    monkeypatch.setitem(sys.modules, "nexent.core.agents.agent_model", agent_model_module)

    provider = KnowledgeProvider(
        embedding_model_resolver=lambda tenant_id, index_name: "embedding-model",
        rerank_model_resolver=lambda tenant_id, model_name: "rerank-model",
        vector_db_resolver=lambda: "vdb-core",
        knowledge_name_map_resolver=lambda index_names: {"idx": "Handbook"},
        knowledge_summary_resolver=lambda index_name: {"summary": "Summary"},
    )
    monkeypatch.setattr(run_preparation, "_default_knowledge_provider", lambda: provider)

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
