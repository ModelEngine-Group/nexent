"""Tool factory registry for runtime-native tool creation."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

from .events import RuntimeEvent, RuntimeEventType
from .models import ToolRuntimeContext, ToolSource, ToolSpec


class ToolFactoryError(ValueError):
    """Base error for tool factory failures."""


class DuplicateToolFactoryError(ToolFactoryError):
    """Raised when a factory is registered twice for the same key."""


class MissingToolFactoryError(ToolFactoryError):
    """Raised when no factory can create a tool."""


class ToolCreationError(ToolFactoryError):
    """Raised when a factory cannot instantiate a supported tool."""


class ToolFactory(Protocol):
    """Factory contract for creating runtime-native tools."""

    name: str

    def supports(self, tool: ToolSpec, context: ToolRuntimeContext) -> bool:
        """Return whether this factory can create the given tool."""
        ...

    def create(self, tool: ToolSpec, context: ToolRuntimeContext) -> Any:
        """Create a runtime-native tool from neutral tool data."""
        ...


ToolFactoryKey = tuple[str, str | None]


@dataclass
class ToolFactoryRegistry:
    """Registry resolving tool factories by source and optional class name."""

    _factories: dict[ToolFactoryKey, ToolFactory] = field(default_factory=dict)

    def register(
        self,
        source: ToolSource | str,
        factory: ToolFactory,
        *,
        class_name: str | None = None,
    ) -> None:
        """Register a factory for a source and optional class name."""
        key = (_normalize_source(source), _normalize_class_name(class_name))
        if key in self._factories:
            source_name, class_key = key
            suffix = f":{class_key}" if class_key else ""
            raise DuplicateToolFactoryError(
                f"Duplicate tool factory for {source_name}{suffix}."
            )
        self._factories[key] = factory

    def get(self, tool: ToolSpec, context: ToolRuntimeContext) -> ToolFactory:
        """Resolve the best matching factory for a tool."""
        source = _normalize_source(tool.source)
        class_name = _normalize_class_name(tool.class_name)
        for key in ((source, class_name), (source, None)):
            factory = self._factories.get(key)
            if factory is not None and factory.supports(tool, context):
                return factory
        raise MissingToolFactoryError(
            f"No tool factory registered for source '{source}'"
            + (f" and class '{tool.class_name}'." if tool.class_name else ".")
        )

    def create(self, tool: ToolSpec, context: ToolRuntimeContext) -> Any:
        """Create a runtime-native tool using the resolved factory."""
        tool_obj = self.get(tool, context).create(tool, context)
        return wrap_tool_with_runtime_events(tool_obj, tool, context)

    def list_factories(self) -> list[dict[str, str | None]]:
        """Return registered factory keys for diagnostics."""
        return [
            {"source": source, "class_name": class_name}
            for source, class_name in sorted(
                self._factories,
                key=lambda key: (key[0], key[1] or ""),
            )
        ]


class LocalToolFactory:
    """Factory for ordinary local tools backed by explicit class mappings."""

    name = "local"

    def __init__(
        self,
        tool_classes: Mapping[str, Callable[..., Any]],
    ):
        self._tool_classes = {
            str(class_name): tool_class
            for class_name, tool_class in tool_classes.items()
        }

    def supports(self, tool: ToolSpec, context: ToolRuntimeContext) -> bool:
        """Return whether the local registry contains the requested class."""
        _ = context
        source = _normalize_source(tool.source)
        class_name = tool.class_name or tool.name
        return source == ToolSource.LOCAL.value and class_name in self._tool_classes

    def create(self, tool: ToolSpec, context: ToolRuntimeContext) -> Any:
        """Instantiate a local tool using explicit params and migrated injections."""
        class_name = tool.class_name or tool.name
        tool_class = self._tool_classes.get(class_name)
        if tool_class is None:
            raise ToolCreationError(f"{class_name} not found in local tool registry.")
        if class_name == "KnowledgeBaseSearchTool":
            return _create_knowledge_tool(tool_class, tool, context)
        if class_name in _MEMORY_TOOL_NAMES:
            return _create_memory_tool(tool_class, tool, context)
        if class_name in _RERANK_SEARCH_TOOL_NAMES:
            return _create_rerank_search_tool(tool_class, tool, context)
        if class_name == "RAGFlowSearchTool":
            return _create_ragflow_search_tool(tool_class, tool, context)
        if class_name == "HaotianSearchTool":
            return _create_haotian_search_tool(tool_class, tool, context)
        if class_name == "AnalyzeTextFileTool":
            return _create_analyze_text_tool(tool_class, tool, context)
        if class_name in _ANALYZE_MEDIA_TOOL_NAMES:
            return _create_analyze_media_tool(tool_class, tool, context)
        try:
            tool_obj = tool_class(**dict(tool.params))
        except Exception as exc:
            raise ToolCreationError(f"Failed to create local tool {class_name}: {exc}") from exc
        _attach_runtime_context(tool_obj, context)
        return tool_obj


class MCPToolFactory:
    """Factory resolving MCP tools from adapter-connected resources."""

    name = "mcp"

    def supports(self, tool: ToolSpec, context: ToolRuntimeContext) -> bool:
        """Return whether the tool is an MCP tool with a server reference."""
        _ = context
        return _normalize_source(tool.source) == ToolSource.MCP.value and bool(tool.usage)

    def create(self, tool: ToolSpec, context: ToolRuntimeContext) -> Any:
        """Return an already-connected MCP native tool."""
        server_name = str(tool.usage or "")
        tool_name = tool.class_name or tool.name
        native_tool = _lookup_mcp_native_tool(
            context.resources,
            server_name=server_name,
            tool_name=tool_name,
        )
        if native_tool is None:
            raise ToolCreationError(
                f"MCP tool '{tool_name}' not found in connected server '{server_name}'."
            )
        return native_tool


class LangChainToolFactory:
    """Factory wrapping LangChain tool references from runtime resources."""

    name = "langchain"

    def __init__(self, wrapper: Callable[[Any], Any] | None = None):
        self._wrapper = wrapper

    def supports(self, tool: ToolSpec, context: ToolRuntimeContext) -> bool:
        """Return whether the tool is a LangChain reference."""
        _ = context
        return _normalize_source(tool.source) == ToolSource.LANGCHAIN.value

    def create(self, tool: ToolSpec, context: ToolRuntimeContext) -> Any:
        """Wrap a LangChain native object without re-discovering tools."""
        reference = _lookup_langchain_tool_reference(tool, context.resources)
        if reference is None:
            raise ToolCreationError(
                f"LangChain tool '{tool.class_name or tool.name}' was not provided."
            )
        if self._wrapper is not None:
            return self._wrapper(reference)
        return reference


class BuiltinSkillToolFactory:
    """Factory creating builtin skill tools from SkillProvider metadata."""

    name = "builtin_skill"

    def __init__(
        self,
        initializers: Mapping[str, Callable[..., Any]] | None = None,
        tool_resolvers: Mapping[str, Callable[[], Any]] | None = None,
    ):
        self._initializers = dict(initializers or {})
        self._tool_resolvers = dict(tool_resolvers or {})

    def supports(self, tool: ToolSpec, context: ToolRuntimeContext) -> bool:
        """Return whether this is a supported builtin skill tool."""
        _ = context
        return (
            _normalize_source(tool.source) == ToolSource.BUILTIN.value
            and (tool.class_name or tool.name) in _BUILTIN_SKILL_TOOL_NAMES
        )

    def create(self, tool: ToolSpec, context: ToolRuntimeContext) -> Any:
        """Initialize and return the builtin skill runtime tool."""
        class_name = tool.class_name or tool.name
        initializer = self._initializers.get(class_name) or _default_skill_initializer(
            class_name
        )
        resolver = self._tool_resolvers.get(class_name) or _default_skill_tool_resolver(
            class_name
        )
        skill_metadata = _skill_tool_metadata(tool, context)
        initializer(**skill_metadata)
        return resolver()


class MemoryToolFactory:
    """Factory creating memory tools from MemoryProvider output."""

    name = "memory"

    def __init__(self, tool_classes: Mapping[str, Callable[..., Any]]):
        self._tool_classes = {
            str(class_name): tool_class
            for class_name, tool_class in tool_classes.items()
        }

    def supports(self, tool: ToolSpec, context: ToolRuntimeContext) -> bool:
        """Return whether this factory can create the requested memory tool."""
        _ = context
        class_name = tool.class_name or tool.name
        return (
            _normalize_source(tool.source) == ToolSource.MEMORY.value
            and class_name in self._tool_classes
        )

    def create(self, tool: ToolSpec, context: ToolRuntimeContext) -> Any:
        """Create a memory tool and inject hidden memory config."""
        class_name = tool.class_name or tool.name
        tool_class = self._tool_classes.get(class_name)
        if tool_class is None:
            raise ToolCreationError(f"{class_name} not found in memory tool registry.")
        return _create_memory_tool(tool_class, tool, context)


class KnowledgeToolFactory:
    """Factory creating knowledge tools from KnowledgeProvider metadata."""

    name = "knowledge"

    def __init__(self, tool_classes: Mapping[str, Callable[..., Any]]):
        self._tool_classes = {
            str(class_name): tool_class
            for class_name, tool_class in tool_classes.items()
        }

    def supports(self, tool: ToolSpec, context: ToolRuntimeContext) -> bool:
        """Return whether this factory can create the requested knowledge tool."""
        _ = context
        class_name = tool.class_name or tool.name
        return (
            _normalize_source(tool.source) == ToolSource.KNOWLEDGE.value
            or class_name == "KnowledgeBaseSearchTool"
        ) and class_name in self._tool_classes

    def create(self, tool: ToolSpec, context: ToolRuntimeContext) -> Any:
        """Create a knowledge tool and inject hidden access-control metadata."""
        class_name = tool.class_name or tool.name
        tool_class = self._tool_classes.get(class_name)
        if tool_class is None:
            raise ToolCreationError(
                f"{class_name} not found in knowledge tool registry."
            )
        return _create_knowledge_tool(tool_class, tool, context)


class PluginToolFactory:
    """Factory creating plugin tools from trusted registered creators."""

    name = "plugin"

    def __init__(
        self,
        creators: Mapping[str, Callable[[ToolSpec, ToolRuntimeContext], Any]] | None = None,
    ):
        self._creators = dict(creators or {})

    def supports(self, tool: ToolSpec, context: ToolRuntimeContext) -> bool:
        """Return whether a trusted plugin creator exists for this tool."""
        if _normalize_source(tool.source) != ToolSource.PLUGIN.value:
            return False
        return _plugin_creator(tool, context, self._creators) is not None

    def create(self, tool: ToolSpec, context: ToolRuntimeContext) -> Any:
        """Create a plugin tool through a trusted creator."""
        creator = _plugin_creator(tool, context, self._creators)
        if creator is None:
            raise ToolCreationError(
                f"Plugin tool '{tool.class_name or tool.name}' was not registered."
            )
        return creator(tool, context)


class ToolRuntimeEventWrapper:
    """Proxy that emits standard runtime events for newly-created tools."""

    def __init__(
        self,
        tool_obj: Any,
        tool: ToolSpec,
        context: ToolRuntimeContext,
    ):
        self._tool_obj = tool_obj
        self._tool = tool
        self._context = context
        self.name = getattr(tool_obj, "name", tool.name)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._tool_obj, name)

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        return self._call_target(None, *args, **kwargs)

    def forward(self, *args: Any, **kwargs: Any) -> Any:
        return self._call_target("forward", *args, **kwargs)

    def _call_target(
        self,
        method_name: str | None,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        call_target = _tool_call_target(self._tool_obj, method_name)
        tool_input = {"args": list(args), "kwargs": dict(kwargs)}
        _emit_tool_runtime_event(
            self._context,
            RuntimeEvent(
                type=RuntimeEventType.TOOL_CALL,
                request_id=self._context.request_id,
                agent_name=self._context.agent_name,
                tool_name=self._tool.name,
                tool_input=tool_input,
                compat_process_type="parse",
                metadata={"tool_status": "parsed"},
            ),
        )
        _emit_tool_runtime_event(
            self._context,
            RuntimeEvent(
                type=RuntimeEventType.TOOL_CALL,
                request_id=self._context.request_id,
                agent_name=self._context.agent_name,
                tool_name=self._tool.name,
                tool_input=tool_input,
                compat_process_type="tool",
                metadata={"tool_status": "started"},
            ),
        )
        try:
            result = call_target(*args, **kwargs)
        except Exception as exc:
            _emit_tool_runtime_event(
                self._context,
                RuntimeEvent(
                    type=RuntimeEventType.ERROR,
                    request_id=self._context.request_id,
                    agent_name=self._context.agent_name,
                    tool_name=self._tool.name,
                    error=str(exc),
                    metadata={"tool_status": "error"},
                ),
            )
            raise
        _emit_tool_runtime_event(
            self._context,
            RuntimeEvent(
                type=RuntimeEventType.TOOL_CALL,
                request_id=self._context.request_id,
                agent_name=self._context.agent_name,
                tool_name=self._tool.name,
                tool_output=result,
                compat_process_type="tool",
                metadata={"tool_status": "finished"},
            ),
        )
        _emit_tool_runtime_event(
            self._context,
            RuntimeEvent(
                type=RuntimeEventType.LEGACY_PROCESS,
                request_id=self._context.request_id,
                agent_name=self._context.agent_name,
                tool_name=self._tool.name,
                content=result,
                compat_process_type="execution_logs",
                metadata={"tool_status": "execution_logs"},
            ),
        )
        _emit_tool_output_events(self._context, self._tool, result)
        return result


def wrap_tool_with_runtime_events(
    tool_obj: Any,
    tool: ToolSpec,
    context: ToolRuntimeContext,
) -> Any:
    """Wrap callable tools when a request-scoped event sink is available."""
    if context.event_sink is None:
        return tool_obj
    if isinstance(tool_obj, ToolRuntimeEventWrapper):
        return tool_obj
    if callable(tool_obj) or callable(getattr(tool_obj, "forward", None)):
        return ToolRuntimeEventWrapper(tool_obj, tool, context)
    return tool_obj


def _attach_runtime_context(tool_obj: Any, context: ToolRuntimeContext) -> None:
    observer = (
        context.resources.get("smolagents.observer")
        or context.resources.get("observer")
        or context.resources.get("message_observer")
    )
    if observer is not None and hasattr(tool_obj, "observer"):
        setattr(tool_obj, "observer", observer)
    if hasattr(tool_obj, "tool_runtime_context"):
        setattr(tool_obj, "tool_runtime_context", context)


def _tool_call_target(tool_obj: Any, method_name: str | None) -> Callable[..., Any]:
    if method_name is not None:
        method = getattr(tool_obj, method_name, None)
        if callable(method):
            return method
    if callable(tool_obj):
        return tool_obj
    forward = getattr(tool_obj, "forward", None)
    if callable(forward):
        return forward
    raise ToolCreationError(f"Tool '{getattr(tool_obj, 'name', 'unknown')}' is not callable.")


def _emit_tool_runtime_event(
    context: ToolRuntimeContext,
    event: RuntimeEvent,
) -> None:
    event_sink = context.event_sink
    emit = getattr(event_sink, "emit", None)
    if callable(emit):
        emit(event)


def _emit_tool_output_events(
    context: ToolRuntimeContext,
    tool: ToolSpec,
    output: Any,
) -> None:
    for payload in _iter_tool_output_payloads(output):
        if "card" in payload:
            _emit_tool_runtime_event(
                context,
                RuntimeEvent(
                    type=RuntimeEventType.TOOL_DISPLAY,
                    request_id=context.request_id,
                    agent_name=context.agent_name,
                    tool_name=tool.name,
                    content=payload["card"],
                    compat_process_type="card",
                ),
            )
        search_content = payload.get("search_content") or payload.get("search_results")
        if search_content is not None:
            _emit_tool_runtime_event(
                context,
                RuntimeEvent(
                    type=RuntimeEventType.RETRIEVAL,
                    request_id=context.request_id,
                    agent_name=context.agent_name,
                    tool_name=tool.name,
                    content=search_content,
                    compat_process_type="search_content",
                ),
            )
        image_content = (
            payload.get("picture_web")
            or payload.get("image")
            or payload.get("image_url")
        )
        if image_content is not None:
            _emit_tool_runtime_event(
                context,
                RuntimeEvent(
                    type=RuntimeEventType.IMAGE,
                    request_id=context.request_id,
                    agent_name=context.agent_name,
                    tool_name=tool.name,
                    content=image_content,
                    compat_process_type="picture_web",
                ),
            )
        artifact = payload.get("artifact")
        if isinstance(artifact, Mapping):
            _emit_artifact_event(context, tool, dict(artifact))
        if payload.get("absolute_path"):
            _emit_artifact_event(context, tool, dict(payload))


def _emit_artifact_event(
    context: ToolRuntimeContext,
    tool: ToolSpec,
    artifact: dict[str, Any],
) -> None:
    _emit_tool_runtime_event(
        context,
        RuntimeEvent(
            type=RuntimeEventType.ARTIFACT_CREATED,
            request_id=context.request_id,
            agent_name=context.agent_name,
            tool_name=tool.name,
            artifact=artifact,
        ),
    )


def _iter_tool_output_payloads(output: Any) -> list[dict[str, Any]]:
    if isinstance(output, Mapping):
        payloads = [dict(output)]
        for nested_key in ("content", "output", "payload", "result"):
            if nested_key in output:
                payloads.extend(_iter_tool_output_payloads(output[nested_key]))
        return payloads
    if isinstance(output, list | tuple | set):
        payloads: list[dict[str, Any]] = []
        for item in output:
            payloads.extend(_iter_tool_output_payloads(item))
        return payloads
    return []


def _lookup_mcp_native_tool(
    resources: Mapping[str, Any],
    *,
    server_name: str,
    tool_name: str,
) -> Any | None:
    server_tools = resources.get("mcp.tools", {})
    if isinstance(server_tools, Mapping):
        native_tool = _lookup_nested_tool(server_tools, server_name, tool_name)
        if native_tool is not None:
            return native_tool

    per_server_tools = resources.get(f"mcp.{server_name}.tools", {})
    if isinstance(per_server_tools, Mapping):
        return per_server_tools.get(tool_name)
    if isinstance(per_server_tools, list | tuple):
        return _find_tool_by_name(per_server_tools, tool_name)
    return None


def _lookup_nested_tool(
    server_tools: Mapping[str, Any],
    server_name: str,
    tool_name: str,
) -> Any | None:
    tools = server_tools.get(server_name)
    if isinstance(tools, Mapping):
        return tools.get(tool_name)
    if isinstance(tools, list | tuple):
        return _find_tool_by_name(tools, tool_name)
    return None


def _find_tool_by_name(tools: list[Any] | tuple[Any, ...], tool_name: str) -> Any | None:
    for native_tool in tools:
        if getattr(native_tool, "name", None) == tool_name:
            return native_tool
    return None


def _lookup_langchain_tool_reference(
    tool: ToolSpec,
    resources: Mapping[str, Any],
) -> Any | None:
    metadata_reference = (
        tool.metadata.get("langchain_tool")
        or tool.metadata.get("native_tool")
        or tool.metadata.get("tool")
    )
    if metadata_reference is not None:
        return metadata_reference
    tool_name = (
        str(tool.metadata.get("langchain_tool_name") or "")
        or tool.class_name
        or tool.name
    )
    references = resources.get("langchain.tools", {})
    if isinstance(references, Mapping):
        return references.get(tool_name)
    if isinstance(references, list | tuple):
        return _find_tool_by_name(references, tool_name)
    return None


_BUILTIN_SKILL_TOOL_NAMES = {
    "ReadSkillConfigTool",
    "ReadSkillMdTool",
    "RunSkillScriptTool",
    "WriteSkillFileTool",
}

_KNOWLEDGE_INJECTED_PARAM_NAMES = {
    "display_name_to_index_map",
    "document_paths",
    "embedding_model",
    "index_name_to_display_map",
    "observer",
    "rerank_model",
    "vdb_core",
}

_MEMORY_TOOL_NAMES = {"SearchMemoryTool", "StoreMemoryTool"}
_RERANK_SEARCH_TOOL_NAMES = {"DataMateSearchTool", "DifySearchTool"}
_ANALYZE_MEDIA_TOOL_NAMES = {
    "AnalyzeAudioTool",
    "AnalyzeImageTool",
    "AnalyzeVideoTool",
}


def _tool_value(
    tool: ToolSpec,
    context: ToolRuntimeContext,
    key: str,
    default: Any = None,
) -> Any:
    for source in (tool.injected_params, tool.metadata, context.resources):
        if key in source:
            return source[key]
    return default


def _create_knowledge_tool(
    tool_class: Callable[..., Any],
    tool: ToolSpec,
    context: ToolRuntimeContext,
) -> Any:
    filtered_params = {
        key: value
        for key, value in dict(tool.params).items()
        if key not in _KNOWLEDGE_INJECTED_PARAM_NAMES
    }
    tool_obj = tool_class(**filtered_params)
    _inject_attributes(
        tool_obj,
        {
            "vdb_core": _tool_value(tool, context, "vdb_core", None),
            "embedding_model": _tool_value(tool, context, "embedding_model", None),
            "rerank_model": _tool_value(tool, context, "rerank_model", None),
            "display_name_to_index_map": _tool_value(
                tool,
                context,
                "display_name_to_index_map",
                {},
            ),
            "index_name_to_display_map": _tool_value(
                tool,
                context,
                "index_name_to_display_map",
                {},
            ),
        },
    )
    document_paths = _tool_value(tool, context, "document_paths", None)
    if hasattr(tool_obj, "set_document_paths"):
        tool_obj.set_document_paths(document_paths)
    else:
        setattr(tool_obj, "_internal_document_paths", document_paths)
    _attach_runtime_context(tool_obj, context)
    return tool_obj


def _create_memory_tool(
    tool_class: Callable[..., Any],
    tool: ToolSpec,
    context: ToolRuntimeContext,
) -> Any:
    tool_obj = tool_class()
    _inject_attributes(
        tool_obj,
        {
            "memory_config": _tool_value(tool, context, "memory_config", {}),
            "memory_user_config": _tool_value(
                tool,
                context,
                "memory_user_config",
                None,
            ),
            "tenant_id": _tool_value(tool, context, "tenant_id", context.tenant_id),
            "user_id": _tool_value(tool, context, "user_id", context.user_id),
            "agent_id": _tool_value(tool, context, "agent_id", ""),
            "observer": _observer_from_context(context),
        },
    )
    _attach_runtime_context(tool_obj, context)
    return tool_obj


def _create_rerank_search_tool(
    tool_class: Callable[..., Any],
    tool: ToolSpec,
    context: ToolRuntimeContext,
) -> Any:
    filtered_params = {
        key: value
        for key, value in dict(tool.params).items()
        if key not in {"observer", "rerank_model"}
    }
    tool_obj = tool_class(**filtered_params)
    _inject_attributes(
        tool_obj,
        {"rerank_model": _tool_value(tool, context, "rerank_model", None)},
    )
    _attach_runtime_context(tool_obj, context)
    return tool_obj


def _create_ragflow_search_tool(
    tool_class: Callable[..., Any],
    tool: ToolSpec,
    context: ToolRuntimeContext,
) -> Any:
    filtered_params = {
        key: value
        for key, value in dict(tool.params).items()
        if key not in {"observer", "rerank", "rerank_model", "rerank_model_name"}
    }
    tool_obj = tool_class(**filtered_params)
    _inject_attributes(
        tool_obj,
        {"rerank_model": _tool_value(tool, context, "rerank_model", None)},
    )
    _attach_runtime_context(tool_obj, context)
    return tool_obj


def _create_haotian_search_tool(
    tool_class: Callable[..., Any],
    tool: ToolSpec,
    context: ToolRuntimeContext,
) -> Any:
    filtered_params = {
        key: value
        for key, value in dict(tool.params).items()
        if key not in {"observer", "rerank", "rerank_model"}
    }
    tool_obj = tool_class(**filtered_params)
    _attach_runtime_context(tool_obj, context)
    return tool_obj


def _create_analyze_text_tool(
    tool_class: Callable[..., Any],
    tool: ToolSpec,
    context: ToolRuntimeContext,
) -> Any:
    metadata = {**dict(tool.metadata), **dict(tool.injected_params)}
    validate_url_access = _callable_or_none(metadata.get("validate_url_access"))
    tool_obj = tool_class(
        observer=_observer_from_context(context),
        llm_model=metadata.get("llm_model", []),
        storage_client=metadata.get("storage_client", []),
        data_process_service_url=metadata.get("data_process_service_url", []),
        validate_url_access=validate_url_access,
        **dict(tool.params),
    )
    _attach_runtime_context(tool_obj, context)
    return tool_obj


def _create_analyze_media_tool(
    tool_class: Callable[..., Any],
    tool: ToolSpec,
    context: ToolRuntimeContext,
) -> Any:
    metadata = {**dict(tool.metadata), **dict(tool.injected_params)}
    validate_url_access = _callable_or_none(metadata.get("validate_url_access"))
    tool_obj = tool_class(
        observer=_observer_from_context(context),
        vlm_model=metadata.get("vlm_model", []),
        storage_client=metadata.get("storage_client", []),
        validate_url_access=validate_url_access,
        **dict(tool.params),
    )
    _attach_runtime_context(tool_obj, context)
    return tool_obj


def _observer_from_context(context: ToolRuntimeContext) -> Any | None:
    return (
        context.resources.get("smolagents.observer")
        or context.resources.get("observer")
        or context.resources.get("message_observer")
    )


def _callable_or_none(value: Any) -> Callable[..., Any] | None:
    return value if callable(value) else None


def _inject_attributes(tool_obj: Any, values: Mapping[str, Any]) -> None:
    for name, value in values.items():
        setattr(tool_obj, name, value)


def _skill_tool_metadata(
    tool: ToolSpec,
    context: ToolRuntimeContext,
) -> dict[str, Any]:
    return {
        "local_skills_dir": _tool_value(
            tool,
            context,
            "local_skills_dir",
            context.resources.get("skill.local_skills_dir"),
        ),
        "agent_id": _tool_value(tool, context, "agent_id", None),
        "tenant_id": _tool_value(tool, context, "tenant_id", context.tenant_id),
        "version_no": _tool_value(tool, context, "version_no", 0),
    }


def _default_skill_initializer(class_name: str) -> Callable[..., Any]:
    if class_name == "RunSkillScriptTool":
        from nexent.core.tools.run_skill_script_tool import get_run_skill_script_tool

        return get_run_skill_script_tool
    if class_name == "ReadSkillMdTool":
        from nexent.core.tools.read_skill_md_tool import get_read_skill_md_tool

        return get_read_skill_md_tool
    if class_name == "ReadSkillConfigTool":
        from nexent.core.tools.read_skill_config_tool import get_read_skill_config_tool

        return get_read_skill_config_tool
    if class_name == "WriteSkillFileTool":
        from nexent.core.tools.write_skill_file_tool import get_write_skill_file_tool

        return get_write_skill_file_tool
    raise ToolCreationError(f"Unknown builtin skill tool: {class_name}.")


def _default_skill_tool_resolver(class_name: str) -> Callable[[], Any]:
    if class_name == "RunSkillScriptTool":
        from nexent.core.tools.run_skill_script_tool import run_skill_script

        return lambda: run_skill_script
    if class_name == "ReadSkillMdTool":
        from nexent.core.tools.read_skill_md_tool import read_skill_md

        return lambda: read_skill_md
    if class_name == "ReadSkillConfigTool":
        from nexent.core.tools.read_skill_config_tool import read_skill_config

        return lambda: read_skill_config
    if class_name == "WriteSkillFileTool":
        from nexent.core.tools.write_skill_file_tool import write_skill_file

        return lambda: write_skill_file
    raise ToolCreationError(f"Unknown builtin skill tool: {class_name}.")


def _plugin_creator(
    tool: ToolSpec,
    context: ToolRuntimeContext,
    creators: Mapping[str, Callable[[ToolSpec, ToolRuntimeContext], Any]],
) -> Callable[[ToolSpec, ToolRuntimeContext], Any] | None:
    creator_keys = [
        str(tool.class_name or ""),
        tool.name,
        str(tool.metadata.get("plugin_tool_id") or ""),
    ]
    resources_creators = context.resources.get("plugin.tool_creators", {})
    for key in creator_keys:
        if not key:
            continue
        creator = creators.get(key)
        if creator is not None:
            return creator
        if isinstance(resources_creators, Mapping):
            creator = resources_creators.get(key)
            if creator is not None:
                return creator
    return None


def _normalize_source(source: ToolSource | str) -> str:
    source_value = source.value if hasattr(source, "value") else str(source)
    normalized = source_value.strip().lower()
    if not normalized:
        raise ToolFactoryError("Tool factory source cannot be empty.")
    return normalized


def _normalize_class_name(class_name: str | None) -> str | None:
    if class_name is None:
        return None
    normalized = str(class_name).strip()
    return normalized or None
