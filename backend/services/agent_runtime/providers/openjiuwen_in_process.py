"""Lazy, request-scoped OpenJiuwen execution inside nexent-runtime."""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import uuid
from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass
from threading import RLock
from typing import Any

from nexent.core.agents.a2a_agent_proxy import ExternalA2AAgentWrapper
from nexent.core.agents.nexent_agent import NexentAgent
from nexent.core.utils.observer import MessageObserver

from ..execution import AgentRuntimeExecution
from ..openjiuwen_spec import (
    OpenJiuwenRunSpec,
    build_openjiuwen_run_spec,
)

logger = logging.getLogger(__name__)

_END = object()


@dataclass(frozen=True)
class _Failure:
    error: Exception


@dataclass
class _ActiveRun:
    execution: AgentRuntimeExecution
    cancel_event: asyncio.Event
    task: asyncio.Task[None]
    queue: asyncio.Queue[Any]
    loop: asyncio.AbstractEventLoop


@dataclass(frozen=True)
class _OpenJiuwenBindings:
    Runner: Any
    ReActAgent: Any
    ReActAgentConfig: Any
    AgentCard: Any
    LocalFunction: Any
    ToolCard: Any
    McpServerConfig: Any
    ModelClientConfig: Any
    ModelRequestConfig: Any
    ContextEngineConfig: Any
    create_agent_session: Any
    UserMessage: Any
    AssistantMessage: Any
    SystemMessage: Any
    AgentCallbackEvent: Any
    ToolCallInputs: Any


def _load_openjiuwen_bindings() -> _OpenJiuwenBindings:
    """Import OpenJiuwen only after an OpenJiuwen Agent is selected."""
    from openjiuwen.core.context_engine import ContextEngineConfig
    from openjiuwen.core.foundation.llm import AssistantMessage, SystemMessage, UserMessage
    from openjiuwen.core.foundation.llm.schema.config import ModelClientConfig, ModelRequestConfig
    from openjiuwen.core.foundation.tool import LocalFunction, McpServerConfig, ToolCard
    from openjiuwen.core.runner import Runner
    from openjiuwen.core.session.agent import create_agent_session
    from openjiuwen.core.single_agent import AgentCard, ReActAgent, ReActAgentConfig
    from openjiuwen.core.single_agent.rail.base import AgentCallbackEvent, ToolCallInputs

    return _OpenJiuwenBindings(
        Runner=Runner,
        ReActAgent=ReActAgent,
        ReActAgentConfig=ReActAgentConfig,
        AgentCard=AgentCard,
        LocalFunction=LocalFunction,
        ToolCard=ToolCard,
        McpServerConfig=McpServerConfig,
        ModelClientConfig=ModelClientConfig,
        ModelRequestConfig=ModelRequestConfig,
        ContextEngineConfig=ContextEngineConfig,
        create_agent_session=create_agent_session,
        UserMessage=UserMessage,
        AssistantMessage=AssistantMessage,
        SystemMessage=SystemMessage,
        AgentCallbackEvent=AgentCallbackEvent,
        ToolCallInputs=ToolCallInputs,
    )


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (bool, float, int, str)):
        return value
    if hasattr(value, "model_dump"):
        return _json_safe(value.model_dump(mode="json", exclude_none=True))
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_json_safe(item) for item in value]
    return str(value)


def _json_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(_json_safe(value), ensure_ascii=False)


class _EventEmitter:
    """Serialize node events and assign one sequence across the recursive tree."""

    def __init__(self, queue: asyncio.Queue[Any]) -> None:
        self.queue = queue
        self._lock = asyncio.Lock()
        self._sequence = 0

    async def emit(
        self,
        event_type: str,
        content: Any,
        spec: OpenJiuwenRunSpec,
        *,
        event_kind: str | None = None,
    ) -> None:
        async with self._lock:
            self._sequence += 1
            payload = {
                "type": event_type,
                "content": _json_text(content),
                "sequence": self._sequence,
                "runtime_framework": "openjiuwen",
                "agent_id": spec.agent_id,
                "agent_name": spec.name,
                "parent_agent_id": spec.parent_agent_id,
                "depth": spec.depth,
            }
            if event_kind:
                payload["runtime_event"] = event_kind
            await self.queue.put(json.dumps(payload, ensure_ascii=False))

    async def emit_legacy_chunk(self, chunk: str, spec: OpenJiuwenRunSpec) -> None:
        try:
            payload = json.loads(chunk)
        except (TypeError, json.JSONDecodeError):
            await self.emit("other", str(chunk), spec, event_kind="tool_event")
            return
        async with self._lock:
            self._sequence += 1
            payload.update(
                {
                    "sequence": self._sequence,
                    "runtime_framework": "openjiuwen",
                    "agent_id": spec.agent_id,
                    "agent_name": spec.name,
                    "parent_agent_id": spec.parent_agent_id,
                    "depth": spec.depth,
                }
            )
            await self.queue.put(json.dumps(payload, ensure_ascii=False))


class _NodeScope:
    """Own one node invocation's native Agent, tools, MCP clients, and context."""

    def __init__(
        self,
        *,
        runtime: "OpenJiuwenInProcessRuntime",
        execution: AgentRuntimeExecution,
        spec: OpenJiuwenRunSpec,
        emitter: _EventEmitter,
        cancel_event: asyncio.Event,
        scope_id: str,
    ) -> None:
        self.runtime = runtime
        self.execution = execution
        self.spec = spec
        self.emitter = emitter
        self.cancel_event = cancel_event
        self.scope_id = scope_id
        self.agent: Any | None = None
        self.session: Any | None = None
        self.session_id: str | None = None
        self.mcp_server_ids: list[str] = []
        self.tool_instances: list[Any] = []
        self.node_observer = MessageObserver(
            lang=getattr(execution.agent_run_info.observer, "lang", "zh")
        )

    async def setup(self) -> None:
        bindings = self.runtime._bindings
        assert bindings is not None
        card = bindings.AgentCard(
            id=f"nexent-agent-{self.scope_id}",
            name=self.spec.name,
            description=self.spec.description,
        )
        self.agent = bindings.ReActAgent(card)
        self.agent.configure(self.runtime._build_agent_config(self.execution, self.spec))
        await self.runtime._register_callbacks(self, bindings)
        await self._setup_local_tools(bindings)
        await self._setup_a2a_tools(bindings)
        await self._setup_child_tools(bindings)
        await self._setup_mcp_tools(bindings)

        self.session_id = f"nexent-session-{self.scope_id}"
        self.session = bindings.create_agent_session(
            session_id=self.session_id,
            card=card,
        )
        history = self.runtime._history_messages(
            self.execution.agent_run_info.history if self.spec.depth == 0 else None,
            bindings,
        )
        await self.agent.context_engine.create_context(
            session=self.session,
            history_messages=history,
        )

    async def _setup_local_tools(self, bindings: _OpenJiuwenBindings) -> None:
        tool_factory = NexentAgent(
            observer=self.node_observer,
            model_config_list=self.execution.agent_run_info.model_config_list,
            stop_event=self.execution.agent_run_info.stop_event,
        )
        for tool_config in self.spec.agent_config.tools:
            if tool_config.source == "mcp":
                continue
            tool_instance, callable_obj = self._create_request_tool(
                tool_factory,
                tool_config,
            )
            self.tool_instances.append(tool_instance)
            card = bindings.ToolCard(
                id=f"nexent-tool-{self.scope_id}-{tool_config.name or tool_config.class_name}",
                name=tool_config.name or tool_config.class_name,
                description=tool_config.description or "",
                input_params=self.runtime._resolve_local_tool_input_schema(tool_config),
            )

            async def invoke_local(_callable=callable_obj, **kwargs):
                if self.cancel_event.is_set():
                    raise asyncio.CancelledError
                if inspect.iscoroutinefunction(_callable):
                    result = await _callable(**kwargs)
                else:
                    result = await asyncio.to_thread(_callable, **kwargs)
                    if inspect.isawaitable(result):
                        result = await result
                await self._drain_tool_observer()
                return _json_safe(result)

            local_function = bindings.LocalFunction(card=card, func=invoke_local)
            result = self.agent.ability_manager.add_ability(card, local_function)
            if not result.added:
                raise ValueError(f"Duplicate OpenJiuwen tool ability: {card.name}")

    @staticmethod
    def _create_request_tool(tool_factory: NexentAgent, tool_config: Any) -> tuple[Any, Any]:
        """Create a node-owned tool and avoid process-global builtin Skill wrappers."""
        if tool_config.source != "builtin":
            instance = tool_factory.create_tool(tool_config)
            return instance, getattr(instance, "forward", instance)

        metadata = tool_config.metadata or {}
        common_kwargs = {
            "local_skills_dir": (tool_config.params or {}).get("local_skills_dir"),
            "agent_id": metadata.get("agent_id"),
            "tenant_id": metadata.get("tenant_id"),
            "version_no": metadata.get("version_no", 0),
        }
        if tool_config.class_name == "RunSkillScriptTool":
            from nexent.core.tools.run_skill_script_tool import RunSkillScriptTool

            instance = RunSkillScriptTool(**common_kwargs)
            return instance, instance.execute
        if tool_config.class_name == "ReadSkillMdTool":
            from nexent.core.tools.read_skill_md_tool import ReadSkillMdTool

            instance = ReadSkillMdTool(**common_kwargs)

            def read_skill_md(skill_name: str, additional_files: list[str] | None = None):
                return instance.execute(skill_name, *(additional_files or []))

            return instance, read_skill_md
        if tool_config.class_name == "WriteSkillFileTool":
            from nexent.core.tools.write_skill_file_tool import WriteSkillFileTool

            instance = WriteSkillFileTool(**common_kwargs)
            return instance, instance.execute
        if tool_config.class_name == "ReadSkillConfigTool":
            from nexent.core.tools.read_skill_config_tool import ReadSkillConfigTool

            instance = ReadSkillConfigTool(**common_kwargs)
            return instance, instance.execute

        instance = tool_factory.create_tool(tool_config)
        return instance, getattr(instance, "forward", instance)

    async def _setup_a2a_tools(self, bindings: _OpenJiuwenBindings) -> None:
        for external_config in self.spec.agent_config.external_a2a_agents:
            wrapper = ExternalA2AAgentWrapper(
                agent_info=external_config.to_a2a_agent_info(),
                stop_event=self.execution.agent_run_info.stop_event,
                observer=self.node_observer,
            )
            self.tool_instances.append(wrapper)
            card = bindings.ToolCard(
                id=f"nexent-a2a-{self.scope_id}-{external_config.agent_id}",
                name=external_config.name,
                description=external_config.description or "External A2A Agent",
                input_params={
                    "type": "object",
                    "properties": {"task": {"type": "string"}},
                    "required": ["task"],
                },
            )

            async def invoke_a2a(task: str, _wrapper=wrapper, **kwargs):
                if self.cancel_event.is_set():
                    raise asyncio.CancelledError
                return await asyncio.to_thread(_wrapper.run, task=task, **kwargs)

            local_function = bindings.LocalFunction(card=card, func=invoke_a2a)
            result = self.agent.ability_manager.add_ability(card, local_function)
            if not result.added:
                raise ValueError(f"Duplicate OpenJiuwen A2A ability: {card.name}")

    async def _setup_child_tools(self, bindings: _OpenJiuwenBindings) -> None:
        for child_spec in self.spec.children:
            card = bindings.ToolCard(
                id=f"nexent-child-{self.scope_id}-{child_spec.agent_id}",
                name=child_spec.name,
                description=child_spec.description,
                input_params={
                    "type": "object",
                    "properties": {
                        "task": {
                            "type": "string",
                            "description": "Task delegated to the child Agent.",
                        }
                    },
                    "required": ["task"],
                },
            )

            async def invoke_child(task: str, _child=child_spec, **_kwargs):
                if self.cancel_event.is_set():
                    raise asyncio.CancelledError
                return await self.runtime._execute_node(
                    execution=self.execution,
                    spec=_child,
                    query=task,
                    emitter=self.emitter,
                    cancel_event=self.cancel_event,
                )

            local_function = bindings.LocalFunction(card=card, func=invoke_child)
            result = self.agent.ability_manager.add_ability(card, local_function)
            if not result.added:
                raise ValueError(f"Duplicate OpenJiuwen child Agent ability: {card.name}")

    async def _setup_mcp_tools(self, bindings: _OpenJiuwenBindings) -> None:
        configured_mcp_tools = {
            str(tool.class_name or tool.name)
            for tool in self.spec.agent_config.tools
            if tool.source == "mcp" and (tool.class_name or tool.name)
        }
        bound_mcp_tools = {
            tool_name
            for binding in self.spec.agent_config.mcp_bindings
            for tool_name in binding.tool_names
        }
        missing_bindings = configured_mcp_tools - bound_mcp_tools
        if missing_bindings:
            raise RuntimeError(
                "Required MCP bindings are unavailable: "
                + ", ".join(sorted(missing_bindings))
            )

        for binding in self.spec.agent_config.mcp_bindings:
            if not binding.available:
                if binding.required:
                    raise RuntimeError(
                        f"Required MCP server is unavailable: {binding.server_name} "
                        f"({binding.unavailable_reason or 'unavailable'})"
                    )
                await self.emitter.emit(
                    "other",
                    {
                        "warning": "optional_mcp_unavailable",
                        "server": binding.server_name,
                        "reason": binding.unavailable_reason or "unavailable",
                    },
                    self.spec,
                    event_kind="warning",
                )
                continue
            server_id = f"nexent-mcp-{self.scope_id}-{binding.server_id}"
            config = bindings.McpServerConfig(
                server_id=server_id,
                server_name=f"{binding.server_name}-{self.scope_id}",
                server_path=binding.url,
                client_type=binding.transport,
                auth_headers=dict(binding.headers),
            )
            self.mcp_server_ids.append(server_id)
            result = await bindings.Runner.resource_mgr.add_mcp_server(
                config,
                tag=["nexent", f"nexent-run-{self.execution.run_id}"],
            )
            if getattr(result, "is_err", lambda: False)():
                if binding.required:
                    raise RuntimeError(f"Required MCP server is unavailable: {binding.server_name}")
                await self.emitter.emit(
                    "other",
                    {"warning": "optional_mcp_unavailable", "server": binding.server_name},
                    self.spec,
                    event_kind="warning",
                )
                continue
            infos = await bindings.Runner.resource_mgr.get_mcp_tool_infos(server_id=server_id)
            info_items = infos if isinstance(infos, list) else [infos]
            discovered_names = {
                item.name
                for item in info_items
                if item is not None and getattr(item, "name", None)
            }
            missing_tools = set(binding.tool_names) - discovered_names
            missing_required_tools = set(binding.required_tool_names) - discovered_names
            if missing_required_tools:
                raise RuntimeError(
                    f"Required MCP tools are unavailable on {binding.server_name}: "
                    + ", ".join(sorted(missing_required_tools))
                )
            if missing_tools:
                await self.emitter.emit(
                    "other",
                    {
                        "warning": "optional_mcp_tools_unavailable",
                        "server": binding.server_name,
                        "tools": sorted(missing_tools),
                    },
                    self.spec,
                    event_kind="warning",
                )
            for tool_name in binding.tool_names:
                if tool_name not in discovered_names:
                    continue
                tool = await bindings.Runner.resource_mgr.get_mcp_tool(
                    name=tool_name,
                    server_id=server_id,
                )
                if isinstance(tool, list):
                    tool = next((item for item in tool if item is not None), None)
                if tool is None:
                    if tool_name in binding.required_tool_names:
                        raise RuntimeError(f"Required MCP tool cannot be bound: {tool_name}")
                    continue
                add_result = self.agent.ability_manager.add(tool.card)
                if not add_result.added:
                    raise ValueError(f"Duplicate OpenJiuwen MCP ability: {tool_name}")

    async def _drain_tool_observer(self) -> None:
        for chunk in self.node_observer.get_cached_message():
            await self.emitter.emit_legacy_chunk(chunk, self.spec)

    async def cleanup(self) -> None:
        bindings = self.runtime._bindings
        if bindings is None:
            return
        if self.agent is not None:
            with suppress(Exception):
                await self.agent.agent_callback_manager.clear()
            with suppress(Exception):
                self.agent.ability_manager.teardown_tools()
        for server_id in reversed(self.mcp_server_ids):
            with suppress(Exception):
                await bindings.Runner.resource_mgr.remove_mcp_server(
                    server_id=server_id,
                    skip_if_tag_not_exists=True,
                    ignore_exception=True,
                )
        if self.agent is not None and self.session_id is not None:
            with suppress(Exception):
                await self.agent.context_engine.clear_context(session_id=self.session_id)
        for tool_instance in reversed(self.tool_instances):
            close = getattr(tool_instance, "aclose", None)
            if callable(close):
                with suppress(Exception):
                    await close()
                continue
            close = getattr(tool_instance, "close", None)
            if callable(close):
                with suppress(Exception):
                    result = close()
                    if inspect.isawaitable(result):
                        await result
        self.mcp_server_ids.clear()
        self.tool_instances.clear()


class OpenJiuwenInProcessRuntime:
    """Own the lazily started Runner and all active OpenJiuwen run tasks."""

    def __init__(self) -> None:
        self._bindings: _OpenJiuwenBindings | None = None
        self._start_lock: asyncio.Lock | None = None
        self._started = False
        self._active: dict[str, _ActiveRun] = {}
        self._active_lock = RLock()
        self._shutting_down = False

    async def _ensure_started(self) -> None:
        if self._started:
            return
        if self._start_lock is None:
            self._start_lock = asyncio.Lock()
        async with self._start_lock:
            if self._shutting_down:
                raise RuntimeError("OpenJiuwen runtime is shutting down.")
            if self._started:
                return
            self._bindings = _load_openjiuwen_bindings()
            await self._bindings.Runner.start()
            self._started = True

    async def run(self, execution: AgentRuntimeExecution) -> AsyncIterator[str]:
        if self._shutting_down:
            raise RuntimeError("OpenJiuwen runtime is shutting down.")
        try:
            await self._ensure_started()
        except Exception as exc:
            fallback_spec = OpenJiuwenRunSpec(
                agent_id=getattr(execution.agent_run_info.agent_config, "id", -1),
                name=getattr(execution.agent_run_info.agent_config, "name", "openjiuwen"),
                description="",
                agent_config=execution.agent_run_info.agent_config,
                parent_agent_id=None,
                depth=0,
                children=(),
            )
            queue: asyncio.Queue[Any] = asyncio.Queue()
            await _EventEmitter(queue).emit(
                "error",
                "OpenJiuwen runtime initialization failed.",
                fallback_spec,
                event_kind="initialization_error",
            )
            yield await queue.get()
            raise RuntimeError("OpenJiuwen runtime initialization failed.") from exc
        if self._shutting_down:
            raise RuntimeError("OpenJiuwen runtime is shutting down.")
        queue: asyncio.Queue[Any] = asyncio.Queue()
        cancel_event = asyncio.Event()
        emitter = _EventEmitter(queue)
        task = asyncio.create_task(
            self._produce(execution, cancel_event, emitter, queue),
            name=f"openjiuwen-run-{execution.run_id}",
        )
        active = _ActiveRun(
            execution=execution,
            cancel_event=cancel_event,
            task=task,
            queue=queue,
            loop=asyncio.get_running_loop(),
        )
        with self._active_lock:
            if execution.run_id in self._active:
                task.cancel()
                raise ValueError(f"OpenJiuwen run already exists: {execution.run_id}")
            self._active[execution.run_id] = active
        try:
            while True:
                item = await queue.get()
                if item is _END:
                    break
                if isinstance(item, _Failure):
                    raise RuntimeError("OpenJiuwen execution failed.") from item.error
                yield item
            try:
                await task
            except asyncio.CancelledError:
                if not cancel_event.is_set():
                    raise
        finally:
            cancel_event.set()
            if not task.done():
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
            with self._active_lock:
                current = self._active.get(execution.run_id)
                if current is active:
                    self._active.pop(execution.run_id, None)

    async def _produce(
        self,
        execution: AgentRuntimeExecution,
        cancel_event: asyncio.Event,
        emitter: _EventEmitter,
        queue: asyncio.Queue[Any],
    ) -> None:
        try:
            spec = build_openjiuwen_run_spec(execution.agent_run_info.agent_config)
            await self._execute_node(
                execution=execution,
                spec=spec,
                query=execution.agent_run_info.query,
                emitter=emitter,
                cancel_event=cancel_event,
            )
        except asyncio.CancelledError:
            execution.agent_run_info.stop_event.set()
        except asyncio.TimeoutError as exc:
            logger.exception("OpenJiuwen in-process run timed out, run_id=%s", execution.run_id)
            await emitter.emit(
                "error",
                "OpenJiuwen execution timed out.",
                spec if "spec" in locals() else OpenJiuwenRunSpec(
                    agent_id=getattr(execution.agent_run_info.agent_config, "id", -1),
                    name=getattr(execution.agent_run_info.agent_config, "name", "openjiuwen"),
                    description="",
                    agent_config=execution.agent_run_info.agent_config,
                    parent_agent_id=None,
                    depth=0,
                    children=(),
                ),
                event_kind="timeout",
            )
            await queue.put(_Failure(exc))
        except Exception as exc:
            logger.exception("OpenJiuwen in-process run failed, run_id=%s", execution.run_id)
            await emitter.emit(
                "error",
                "OpenJiuwen execution failed.",
                spec if "spec" in locals() else OpenJiuwenRunSpec(
                    agent_id=getattr(execution.agent_run_info.agent_config, "id", -1),
                    name=getattr(execution.agent_run_info.agent_config, "name", "openjiuwen"),
                    description="",
                    agent_config=execution.agent_run_info.agent_config,
                    parent_agent_id=None,
                    depth=0,
                    children=(),
                ),
                event_kind="error",
            )
            await queue.put(_Failure(exc))
        finally:
            await queue.put(_END)

    async def _execute_node(
        self,
        *,
        execution: AgentRuntimeExecution,
        spec: OpenJiuwenRunSpec,
        query: str,
        emitter: _EventEmitter,
        cancel_event: asyncio.Event,
    ) -> str:
        if cancel_event.is_set():
            raise asyncio.CancelledError
        scope_id = f"{execution.run_id}-{spec.agent_id}-{uuid.uuid4().hex[:8]}"
        scope = _NodeScope(
            runtime=self,
            execution=execution,
            spec=spec,
            emitter=emitter,
            cancel_event=cancel_event,
            scope_id=scope_id,
        )
        output_parts: list[str] = []
        final_answer = ""
        try:
            await emitter.emit(
                "agent_new_run",
                query,
                spec,
                event_kind="agent_started",
            )
            await scope.setup()
            stream = scope.agent.stream(
                {"query": query, "conversation_id": scope.session.get_session_id()},
                session=scope.session,
            )
            try:
                async for chunk in stream:
                    if cancel_event.is_set():
                        raise asyncio.CancelledError
                    chunk_type = str(getattr(chunk, "type", ""))
                    payload = getattr(chunk, "payload", None)
                    payload = payload if isinstance(payload, Mapping) else {"content": payload}
                    if chunk_type == "llm_reasoning":
                        await emitter.emit(
                            "model_output_deep_thinking",
                            payload.get("content", ""),
                            spec,
                            event_kind="model_reasoning_delta",
                        )
                    elif chunk_type == "llm_output":
                        content = str(payload.get("content") or "")
                        output_parts.append(content)
                        await emitter.emit(
                            "model_output_thinking",
                            content,
                            spec,
                            event_kind="model_output_delta",
                        )
                    elif chunk_type == "llm_usage":
                        await emitter.emit(
                            "token_count",
                            payload.get("usage_metadata", payload),
                            spec,
                            event_kind="token_usage",
                        )
                    elif chunk_type == "answer":
                        if str(payload.get("result_type") or "answer") == "error":
                            raise RuntimeError("OpenJiuwen Agent returned an error result.")
                        final_answer = str(payload.get("output") or payload.get("content") or "")
            finally:
                close_stream = getattr(stream, "aclose", None)
                if callable(close_stream):
                    with suppress(asyncio.CancelledError, Exception):
                        await close_stream()
            if not final_answer:
                final_answer = "".join(output_parts)
            if spec.depth == 0:
                await emitter.emit(
                    "final_answer",
                    final_answer,
                    spec,
                    event_kind="final_answer",
                )
            else:
                await emitter.emit(
                    "agent_finish",
                    final_answer,
                    spec,
                    event_kind="child_agent_finished",
                )
            return final_answer
        finally:
            await scope.cleanup()

    def _build_agent_config(
        self,
        execution: AgentRuntimeExecution,
        spec: OpenJiuwenRunSpec,
    ) -> Any:
        bindings = self._bindings
        assert bindings is not None
        model = next(
            (
                item
                for item in execution.agent_run_info.model_config_list
                if item is not None and item.cite_name == spec.agent_config.model_name
            ),
            None,
        )
        if model is None:
            raise ValueError(f"OpenJiuwen model config not found: {spec.agent_config.model_name}")
        provider = self._model_provider(model.model_factory)
        ssl_cert = getattr(model, "ssl_cert", None)
        verify_ssl = bool(model.ssl_verify) and bool(ssl_cert)
        client_kwargs = {
            "client_id": f"nexent-model-{execution.run_id}-{spec.agent_id}",
            "client_provider": provider,
            "api_key": model.api_key,
            "api_base": model.url,
            "verify_ssl": verify_ssl,
        }
        if ssl_cert:
            client_kwargs["ssl_cert"] = ssl_cert
        if model.timeout_seconds:
            client_kwargs["timeout"] = model.timeout_seconds
        model_client_config = bindings.ModelClientConfig(**client_kwargs)
        request_kwargs = {
            "model": model.model_name,
            "temperature": model.temperature,
            "top_p": model.top_p,
            "max_tokens": model.max_output_tokens,
        }
        if model.extra_body:
            request_kwargs["extra_body"] = model.extra_body
        model_request_config = bindings.ModelRequestConfig(**request_kwargs)
        context_config = bindings.ContextEngineConfig(
            max_context_message_num=100,
            context_window_tokens=model.context_window_tokens,
            model_name=model.model_name,
        )
        return bindings.ReActAgentConfig(
            model_name=model.model_name,
            model_provider=provider,
            api_key=model.api_key,
            api_base=model.url,
            max_iterations=spec.agent_config.max_steps,
            model_client_config=model_client_config,
            model_config_obj=model_request_config,
            context_engine_config=context_config,
            prompt_template=[
                {"role": "system", "content": self._prompt_text(spec.agent_config)}
            ],
        )

    @staticmethod
    def _model_provider(model_factory: str | None) -> str:
        normalized = str(model_factory or "").lower()
        if "anthropic" in normalized:
            return "Anthropic"
        if "openrouter" in normalized:
            return "OpenRouter"
        if "silicon" in normalized:
            return "SiliconFlow"
        if "dashscope" in normalized or "qwen" in normalized:
            return "DashScope"
        if "deepseek" in normalized:
            return "DeepSeek"
        return "OpenAI"

    @staticmethod
    def _prompt_text(agent_config: Any) -> str:
        sections: list[str] = []
        for component in getattr(agent_config, "context_components", None) or []:
            for message in component.to_messages():
                content = message.get("content", "")
                if isinstance(content, list):
                    sections.extend(
                        str(part.get("text") or "")
                        for part in content
                        if isinstance(part, dict) and part.get("text")
                    )
                elif content:
                    sections.append(str(content))
        if not sections:
            prompt_templates = getattr(agent_config, "prompt_templates", None) or {}
            system_prompt = prompt_templates.get("system_prompt")
            if system_prompt:
                sections.append(str(system_prompt))
        instructions = getattr(agent_config, "instructions", None)
        if instructions:
            sections.insert(0, str(instructions))
        return "\n\n".join(section for section in sections if section)

    @staticmethod
    def _history_messages(history: Any, bindings: _OpenJiuwenBindings) -> list[Any]:
        messages = []
        for item in history or []:
            common = {"content": item.content}
            if item.role == "assistant":
                messages.append(bindings.AssistantMessage(**common))
            elif item.role == "system":
                messages.append(bindings.SystemMessage(**common))
            else:
                messages.append(bindings.UserMessage(**common))
        return messages

    @staticmethod
    def _tool_input_schema(raw_inputs: str | None) -> dict[str, Any]:
        if not raw_inputs:
            return {"type": "object", "properties": {}}
        try:
            parsed = json.loads(raw_inputs) if isinstance(raw_inputs, str) else raw_inputs
        except json.JSONDecodeError:
            return {"type": "object", "properties": {}}
        if not isinstance(parsed, dict):
            return {"type": "object", "properties": {}}
        if parsed.get("type") == "object" and isinstance(parsed.get("properties"), dict):
            return parsed

        def normalize_property(value: Any) -> dict[str, Any]:
            if isinstance(value, dict):
                return value
            type_name = str(value or "string").strip().lower().replace("typing.", "")
            optional = "optional[" in type_name or "none" in type_name
            if "list" in type_name or type_name.endswith("[]"):
                item_type = "string"
                if "int" in type_name:
                    item_type = "integer"
                elif "float" in type_name or "number" in type_name:
                    item_type = "number"
                schema = {"type": "array", "items": {"type": item_type}}
            elif "dict" in type_name or "object" in type_name:
                schema = {"type": "object"}
            elif "bool" in type_name:
                schema = {"type": "boolean"}
            elif "int" in type_name:
                schema = {"type": "integer"}
            elif "float" in type_name or "number" in type_name:
                schema = {"type": "number"}
            else:
                schema = {"type": "string"}
            if optional:
                schema["nullable"] = True
            return schema

        properties = {
            str(name): normalize_property(value)
            for name, value in parsed.items()
        }
        required = [
            name
            for name, value in properties.items()
            if value.get("nullable") is not True and "default" not in value
        ]
        schema: dict[str, Any] = {"type": "object", "properties": properties}
        if required:
            schema["required"] = required
        return schema

    @classmethod
    def _resolve_local_tool_input_schema(cls, tool_config: Any) -> dict[str, Any]:
        """Resolve local tool schemas without changing shared tool metadata."""
        if tool_config.class_name == "RunSkillScriptTool":
            return {
                "type": "object",
                "properties": {
                    "skill_name": {"type": "string"},
                    "script_path": {"type": "string"},
                    "params": {"type": "string"},
                },
                "required": ["skill_name", "script_path"],
                "additionalProperties": False,
            }
        if tool_config.class_name == "ReadSkillMdTool":
            return {
                "type": "object",
                "properties": {
                    "skill_name": {"type": "string"},
                    "additional_files": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "required": ["skill_name"],
                "additionalProperties": False,
            }
        return cls._tool_input_schema(tool_config.inputs)

    async def _register_callbacks(
        self,
        scope: _NodeScope,
        bindings: _OpenJiuwenBindings,
    ) -> None:
        step = 0

        async def before_model(_context):
            nonlocal step
            step += 1
            await scope.emitter.emit(
                "step_count",
                step,
                scope.spec,
                event_kind="step_started",
            )

        async def model_error(_context):
            await scope.emitter.emit(
                "error",
                "OpenJiuwen model call failed.",
                scope.spec,
                event_kind="model_error",
            )

        async def before_tool(context):
            inputs = context.inputs
            tool_name = getattr(inputs, "tool_name", "")
            await scope.emitter.emit(
                "tool",
                {
                    "event": "started",
                    "tool_name": tool_name,
                    "arguments": _json_safe(getattr(inputs, "tool_args", None)),
                },
                scope.spec,
                event_kind="tool_call_started",
            )

        async def after_tool(context):
            inputs = context.inputs
            await scope.emitter.emit(
                "execution_logs",
                {
                    "tool_name": getattr(inputs, "tool_name", ""),
                    "result": _json_safe(getattr(inputs, "tool_result", None)),
                },
                scope.spec,
                event_kind="tool_call_finished",
            )

        async def tool_error(context):
            inputs = context.inputs
            await scope.emitter.emit(
                "error",
                f"OpenJiuwen tool call failed: {getattr(inputs, 'tool_name', '')}",
                scope.spec,
                event_kind="tool_error",
            )

        callbacks = {
            bindings.AgentCallbackEvent.BEFORE_MODEL_CALL: before_model,
            bindings.AgentCallbackEvent.ON_MODEL_EXCEPTION: model_error,
            bindings.AgentCallbackEvent.BEFORE_TOOL_CALL: before_tool,
            bindings.AgentCallbackEvent.AFTER_TOOL_CALL: after_tool,
            bindings.AgentCallbackEvent.ON_TOOL_EXCEPTION: tool_error,
        }
        for event, callback in callbacks.items():
            await scope.agent.register_callback(event, callback)

    def request_stop(self, run_id: str) -> bool:
        with self._active_lock:
            active = self._active.get(run_id)
        if active is None:
            return False
        active.execution.agent_run_info.stop_event.set()

        def cancel_run() -> None:
            active.cancel_event.set()
            active.task.cancel()
            active.queue.put_nowait(_END)

        active.loop.call_soon_threadsafe(cancel_run)
        return True

    async def shutdown(self) -> None:
        self._shutting_down = True
        if self._start_lock is not None:
            async with self._start_lock:
                pass
        if not self._started or self._bindings is None:
            return
        with self._active_lock:
            active_runs = list(self._active.values())
        for active in active_runs:
            active.execution.agent_run_info.stop_event.set()
            active.cancel_event.set()
            active.task.cancel()
            active.queue.put_nowait(_END)
        if active_runs:
            await asyncio.gather(
                *(active.task for active in active_runs),
                return_exceptions=True,
            )
        await self._bindings.Runner.stop()
        self._started = False


def create_runtime() -> OpenJiuwenInProcessRuntime:
    """Create the lazy in-process OpenJiuwen provider."""
    return OpenJiuwenInProcessRuntime()


__all__ = ["OpenJiuwenInProcessRuntime", "create_runtime"]
