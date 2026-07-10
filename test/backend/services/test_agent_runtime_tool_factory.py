import os
import sys
from typing import Any

import pytest

backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../backend"))
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

from consts import const
from services.agent_runtime.events import RuntimeEventSink, RuntimeEventType
from services.agent_runtime.models import ToolRuntimeContext, ToolSource, ToolSpec
from services.agent_runtime.tool_factory import (
    BuiltinSkillToolFactory,
    DuplicateToolFactoryError,
    KnowledgeToolFactory,
    LangChainToolFactory,
    LocalToolFactory,
    MCPToolFactory,
    MemoryToolFactory,
    MissingToolFactoryError,
    PluginToolFactory,
    ToolCreationError,
    ToolFactoryRegistry,
)


class StaticFactory:
    name = "static"

    def __init__(self, value: Any, *, supported: bool = True):
        self.value = value
        self.supported = supported

    def supports(self, tool: ToolSpec, context: ToolRuntimeContext) -> bool:
        _ = (tool, context)
        return self.supported

    def create(self, tool: ToolSpec, context: ToolRuntimeContext) -> Any:
        _ = (tool, context)
        return self.value


class EchoTool:
    def __init__(self, text: str):
        self.text = text
        self.observer = None


class MemoryTool:
    pass


class KnowledgeTool:
    def __init__(self, **kwargs: Any):
        self.init_kwargs = kwargs
        self.document_paths = None
        self.observer = None

    def set_document_paths(self, document_paths: list[str] | None) -> None:
        self.document_paths = document_paths


class ParamTool:
    def __init__(self, **kwargs: Any):
        self.init_kwargs = kwargs
        self.observer = None


class AnalyzeTool:
    def __init__(self, **kwargs: Any):
        self.init_kwargs = kwargs
        self.observer = kwargs.get("observer")


class EventTool:
    def __init__(self, result: Any):
        self.result = result
        self.observer = None

    def __call__(self, query: str) -> Any:
        return self.result | {"query": query}


def _context(**overrides: Any) -> ToolRuntimeContext:
    payload = {
        "request_id": "req-1",
        "agent_name": "root",
        "user_id": "user-1",
        "tenant_id": "tenant-1",
        "runtime_provider": const.AGENT_RUNTIME_PROVIDER_SMOLAGENTS,
        "resources": {},
    }
    payload.update(overrides)
    return ToolRuntimeContext(**payload)


def test_tool_factory_registry_resolves_class_specific_then_source_default():
    registry = ToolFactoryRegistry()
    registry.register(ToolSource.LOCAL, StaticFactory("source-default"))
    registry.register(
        ToolSource.LOCAL,
        StaticFactory("class-specific"),
        class_name="EchoTool",
    )

    exact_tool = ToolSpec(
        name="echo",
        class_name="EchoTool",
        source=ToolSource.LOCAL,
    )
    fallback_tool = ToolSpec(
        name="other",
        class_name="OtherTool",
        source=ToolSource.LOCAL,
    )

    assert registry.create(exact_tool, _context()) == "class-specific"
    assert registry.create(fallback_tool, _context()) == "source-default"
    assert registry.list_factories() == [
        {"source": "local", "class_name": None},
        {"source": "local", "class_name": "EchoTool"},
    ]


def test_tool_factory_registry_rejects_duplicate_and_missing_factories():
    registry = ToolFactoryRegistry()
    registry.register(ToolSource.LOCAL, StaticFactory("source-default"))

    with pytest.raises(DuplicateToolFactoryError, match="local"):
        registry.register("local", StaticFactory("duplicate"))

    with pytest.raises(MissingToolFactoryError, match="source 'mcp'"):
        registry.create(
            ToolSpec(name="docs_search", source=ToolSource.MCP, class_name="search"),
            _context(),
        )


def test_tool_factory_registry_wraps_new_tools_with_runtime_event_sink():
    event_sink = RuntimeEventSink(request_id="req-1")
    registry = ToolFactoryRegistry()
    registry.register(
        ToolSource.LOCAL,
        LocalToolFactory(
            {
                "EventTool": lambda **kwargs: EventTool(
                    {
                        "card": {"title": "Tool card"},
                        "search_content": [{"title": "Search result"}],
                        "picture_web": {"url": "https://image.example/a.png"},
                        "absolute_path": "/tmp/report.txt",
                    }
                )
            }
        ),
    )
    tool = ToolSpec(
        name="event_tool",
        class_name="EventTool",
        source=ToolSource.LOCAL,
    )

    wrapped_tool = registry.create(tool, _context(event_sink=event_sink))
    result = wrapped_tool("hello")

    assert result["query"] == "hello"
    assert [event.type for event in event_sink.events] == [
        RuntimeEventType.TOOL_CALL,
        RuntimeEventType.TOOL_CALL,
        RuntimeEventType.TOOL_CALL,
        RuntimeEventType.LEGACY_PROCESS,
        RuntimeEventType.TOOL_DISPLAY,
        RuntimeEventType.RETRIEVAL,
        RuntimeEventType.IMAGE,
        RuntimeEventType.ARTIFACT_CREATED,
    ]
    assert event_sink.events[0].tool_input == {
        "args": ["hello"],
        "kwargs": {},
    }
    assert event_sink.events[0].compat_process_type == "parse"
    assert event_sink.events[1].metadata["tool_status"] == "started"
    assert event_sink.events[2].tool_output["query"] == "hello"
    assert event_sink.events[3].compat_process_type == "execution_logs"
    assert event_sink.events[4].compat_process_type == "card"
    assert event_sink.events[5].compat_process_type == "search_content"
    assert event_sink.events[6].compat_process_type == "picture_web"
    assert event_sink.events[7].artifact["absolute_path"] == "/tmp/report.txt"


def test_local_tool_factory_instantiates_from_params_without_injected_param_leakage():
    observer = object()
    factory = LocalToolFactory({"EchoTool": EchoTool})
    tool = ToolSpec(
        name="echo",
        class_name="EchoTool",
        source=ToolSource.LOCAL,
        params={"text": "hello"},
        injected_params={"secret": "do-not-pass"},
    )

    tool_obj = factory.create(
        tool,
        _context(resources={"smolagents.observer": observer}),
    )

    assert isinstance(tool_obj, EchoTool)
    assert tool_obj.text == "hello"
    assert tool_obj.observer is observer
    assert not hasattr(tool_obj, "secret")


def test_local_tool_factory_preserves_search_analysis_memory_special_rules():
    observer = object()
    validator = lambda url: True
    factory = LocalToolFactory(
        {
            "DifySearchTool": ParamTool,
            "RAGFlowSearchTool": ParamTool,
            "AnalyzeTextFileTool": AnalyzeTool,
            "SearchMemoryTool": MemoryTool,
        }
    )
    context = _context(resources={"smolagents.observer": observer})

    dify_tool = factory.create(
        ToolSpec(
            name="dify",
            class_name="DifySearchTool",
            source=ToolSource.LOCAL,
            params={"top_k": 3, "observer": "hidden", "rerank_model": "hidden"},
            metadata={"rerank_model": "reranker"},
        ),
        context,
    )
    ragflow_tool = factory.create(
        ToolSpec(
            name="ragflow",
            class_name="RAGFlowSearchTool",
            source=ToolSource.LOCAL,
            params={"dataset_id": "ds", "rerank": True, "rerank_model_name": "bge"},
            metadata={"rerank_model": "reranker"},
        ),
        context,
    )
    analyze_tool = factory.create(
        ToolSpec(
            name="analyze",
            class_name="AnalyzeTextFileTool",
            source=ToolSource.LOCAL,
            params={"path": "s3://bucket/file.txt"},
            metadata={
                "llm_model": "llm",
                "storage_client": "storage",
                "data_process_service_url": "http://data-process",
                "validate_url_access": validator,
            },
        ),
        context,
    )
    memory_tool = factory.create(
        ToolSpec(
            name="search_memory",
            class_name="SearchMemoryTool",
            source=ToolSource.LOCAL,
            injected_params={"memory_config": {"provider": "mem0"}},
        ),
        context,
    )

    assert dify_tool.init_kwargs == {"top_k": 3}
    assert dify_tool.observer is observer
    assert dify_tool.rerank_model == "reranker"
    assert ragflow_tool.init_kwargs == {"dataset_id": "ds"}
    assert ragflow_tool.rerank_model == "reranker"
    assert analyze_tool.init_kwargs["observer"] is observer
    assert analyze_tool.init_kwargs["llm_model"] == "llm"
    assert analyze_tool.init_kwargs["storage_client"] == "storage"
    assert analyze_tool.init_kwargs["data_process_service_url"] == "http://data-process"
    assert analyze_tool.init_kwargs["validate_url_access"] is validator
    assert analyze_tool.init_kwargs["path"] == "s3://bucket/file.txt"
    assert memory_tool.memory_config == {"provider": "mem0"}
    assert memory_tool.observer is observer


def test_mcp_tool_factory_uses_connected_resources_only():
    native_tool = object()
    factory = MCPToolFactory()
    tool = ToolSpec(
        name="docs_search",
        class_name="search",
        source=ToolSource.MCP,
        usage="docs",
    )

    assert factory.create(
        tool,
        _context(resources={"mcp.tools": {"docs": {"search": native_tool}}}),
    ) is native_tool

    with pytest.raises(ToolCreationError, match="connected server 'docs'"):
        factory.create(tool, _context(resources={"mcp.tools": {"docs": {}}}))


def test_langchain_tool_factory_wraps_explicit_resource_reference():
    native_tool = object()
    wrapped_tool = object()
    factory = LangChainToolFactory(
        wrapper=lambda reference: wrapped_tool if reference is native_tool else None
    )
    tool = ToolSpec(
        name="calendar",
        class_name="CalendarTool",
        source=ToolSource.LANGCHAIN,
        metadata={"langchain_tool_name": "CalendarTool"},
    )

    assert factory.create(
        tool,
        _context(resources={"langchain.tools": {"CalendarTool": native_tool}}),
    ) is wrapped_tool

    with pytest.raises(ToolCreationError, match="CalendarTool"):
        factory.create(tool, _context())


def test_builtin_skill_tool_factory_uses_skill_provider_metadata_only():
    initialized: dict[str, Any] = {}
    native_tool = object()
    factory = BuiltinSkillToolFactory(
        initializers={
            "RunSkillScriptTool": lambda **kwargs: initialized.update(kwargs),
        },
        tool_resolvers={"RunSkillScriptTool": lambda: native_tool},
    )
    tool = ToolSpec(
        name="run_skill_script",
        class_name="RunSkillScriptTool",
        source=ToolSource.BUILTIN,
        metadata={"agent_id": 1, "tenant_id": "tenant-1", "version_no": 3},
        injected_params={"local_skills_dir": "/opt/nexent/skills"},
    )

    assert factory.create(tool, _context()) is native_tool
    assert initialized == {
        "local_skills_dir": "/opt/nexent/skills",
        "agent_id": 1,
        "tenant_id": "tenant-1",
        "version_no": 3,
    }


def test_memory_tool_factory_injects_hidden_memory_runtime_config():
    observer = object()
    factory = MemoryToolFactory({"SearchMemoryTool": MemoryTool})
    tool = ToolSpec(
        name="search_memory",
        class_name="SearchMemoryTool",
        source=ToolSource.MEMORY,
        metadata={"tenant_id": "tenant-1", "user_id": "user-1", "agent_id": "1"},
        injected_params={
            "memory_config": {"provider": "mem0"},
            "memory_user_config": {"memory_switch": True},
        },
    )

    tool_obj = factory.create(
        tool,
        _context(resources={"smolagents.observer": observer}),
    )

    assert isinstance(tool_obj, MemoryTool)
    assert tool_obj.memory_config == {"provider": "mem0"}
    assert tool_obj.memory_user_config == {"memory_switch": True}
    assert tool_obj.tenant_id == "tenant-1"
    assert tool_obj.user_id == "user-1"
    assert tool_obj.agent_id == "1"


def test_knowledge_tool_factory_injects_access_control_without_schema_leakage():
    observer = object()
    factory = KnowledgeToolFactory({"KnowledgeBaseSearchTool": KnowledgeTool})
    tool = ToolSpec(
        name="knowledge_base_search",
        class_name="KnowledgeBaseSearchTool",
        source=ToolSource.KNOWLEDGE,
        params={
            "top_k": 3,
            "document_paths": ["/docs/hidden.md"],
            "embedding_model": "hidden",
        },
        metadata={"vdb_core": "vdb", "embedding_model": "embedding"},
        injected_params={
            "rerank_model": "reranker",
            "display_name_to_index_map": {"Handbook": "kb-index"},
            "document_paths": ["/docs/handbook.md"],
        },
    )

    tool_obj = factory.create(
        tool,
        _context(resources={"smolagents.observer": observer}),
    )

    assert isinstance(tool_obj, KnowledgeTool)
    assert tool_obj.init_kwargs == {"top_k": 3}
    assert tool_obj.vdb_core == "vdb"
    assert tool_obj.embedding_model == "embedding"
    assert tool_obj.rerank_model == "reranker"
    assert tool_obj.display_name_to_index_map == {"Handbook": "kb-index"}
    assert tool_obj.document_paths == ["/docs/handbook.md"]
    assert tool_obj.observer is observer


def test_plugin_tool_factory_uses_trusted_registered_creator():
    tool = ToolSpec(
        name="plugin_tool",
        class_name="PluginTool",
        source=ToolSource.PLUGIN,
    )
    context = _context()
    native_tool = object()
    factory = PluginToolFactory(
        creators={"PluginTool": lambda created_tool, created_context: native_tool}
    )

    assert factory.create(tool, context) is native_tool

    with pytest.raises(ToolCreationError, match="PluginTool"):
        PluginToolFactory().create(tool, context)
