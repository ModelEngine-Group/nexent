"""OpenJiuwen runtime adapter."""

from __future__ import annotations

import asyncio
import inspect
import json
import re
import threading
from collections.abc import AsyncIterator, Callable, Mapping
from dataclasses import dataclass, field
from types import MethodType
from typing import Any

from consts.const import AGENT_RUNTIME_PROVIDER_OPENJIUWEN

from .events import RuntimeEvent, RuntimeEventType, emit_runtime_event
from .models import (
    AgentRunPlan,
    AgentSpec,
    ContextMode,
    MCPConnectionConfig,
    RuntimeCapabilities,
    ToolRuntimeContext,
    ToolSource,
    ToolSpec,
    ToolVisibility,
)
from .tool_factory import ToolFactoryRegistry


OPENJIUWEN_PROCESS_TYPE_COMPATIBILITY = {
    "agent_new_run": "complete",
    "agent_finish": "partial",
    "card": "complete",
    "error": "complete",
    "execution_logs": "partial",
    "final_answer": "complete",
    "max_steps_reached": "partial",
    "memory_search": "no-op",
    "model_output_code": "no-op",
    "model_output_deep_thinking": "partial",
    "model_output_thinking": "complete",
    "other": "complete",
    "parse": "partial",
    "picture_web": "complete",
    "search_content": "complete",
    "step_count": "partial",
    "token_count": "complete",
    "tool": "complete",
    "verification": "no-op",
}


class OpenJiuwenRuntimeError(RuntimeError):
    """Base error raised by the OpenJiuwen runtime adapter."""


class OpenJiuwenDependencyError(OpenJiuwenRuntimeError):
    """Raised when OpenJiuwen is selected but its package is unavailable."""


class OpenJiuwenUnsupportedFeatureError(OpenJiuwenRuntimeError):
    """Raised when a plan requires an unsupported OpenJiuwen spike feature."""


class OpenJiuwenToolMappingError(OpenJiuwenRuntimeError):
    """Raised when a neutral tool cannot be mapped to an OpenJiuwen tool."""


@dataclass(frozen=True)
class OpenJiuwenRuntimeDependencies:
    """OpenJiuwen native classes used by the adapter.

    Tests inject fakes here so importing this module never requires openjiuwen.
    """

    AgentCard: Any
    ReActAgentConfig: Any
    ReActAgent: Any
    ModelRequestConfig: Any
    ModelClientConfig: Any
    McpServerConfig: Any
    ToolCard: Any
    LocalFunction: Any
    ContextEngineConfig: Any | None
    Runner: Any
    UserMessage: Any | None = None
    AssistantMessage: Any | None = None
    SystemMessage: Any | None = None
    ToolMessage: Any | None = None
    SkillUtil: Any | None = None
    SysOperationCard: Any | None = None
    LocalWorkConfig: Any | None = None
    OperationMode: Any | None = None


@dataclass
class OpenJiuwenAgentBundle:
    """Framework-native OpenJiuwen objects created from a run plan."""

    agent_card: Any
    react_agent_config: Any
    react_agent: Any
    model_request_config: Any
    model_client_config: Any
    prompt_template: list[dict[str, Any]]
    context_engine_config: Any | None
    history_messages: list[Any] = field(default_factory=list)


@dataclass
class _OpenJiuwenRunState:
    task: asyncio.Task[Any] | None
    run_control: Any
    runner: Any
    mcp_server_ids: list[str] = field(default_factory=list)
    tool_ids: list[str] = field(default_factory=list)
    sys_operation_ids: list[str] = field(default_factory=list)
    cleaned: bool = False


class OpenJiuwenRuntime:
    """Second runtime spike using OpenJiuwen ReActAgent."""

    name = AGENT_RUNTIME_PROVIDER_OPENJIUWEN
    capabilities = RuntimeCapabilities(
        streaming=True,
        token_streaming=True,
        reasoning_streaming=True,
        process_type_compatibility="partial",
        mcp=True,
        managed_agents=False,
        external_a2a_agents=False,
        code_execution=False,
        tool_artifacts=False,
        context_compression=False,
        tool_call_events=True,
        token_usage_events=True,
        interruptible=True,
        resumable_stream=False,
    )

    def __init__(
        self,
        *,
        dependencies: OpenJiuwenRuntimeDependencies | Callable[[], OpenJiuwenRuntimeDependencies] | None = None,
        tool_factory_registry: ToolFactoryRegistry | None = None,
        prefer_streaming: bool = True,
        mcp_expiry_time: float | None = None,
    ):
        self._dependencies = dependencies
        self._tool_factory_registry = tool_factory_registry
        self._prefer_streaming = prefer_streaming
        self._mcp_expiry_time = mcp_expiry_time
        self._active_runs: dict[str, _OpenJiuwenRunState] = {}
        self._lock = threading.Lock()

    async def run(
        self,
        plan: AgentRunPlan,
        event_sink: Any = None,
    ) -> AsyncIterator[Any]:
        """Execute an OpenJiuwen run from a framework-neutral AgentRunPlan."""
        dependencies = self._resolve_dependencies()
        state = _OpenJiuwenRunState(
            task=asyncio.current_task(),
            run_control=plan.run_control,
            runner=dependencies.Runner,
        )
        with self._lock:
            self._active_runs[plan.request_id] = state

        try:
            self._validate_supported_plan(plan)
            bundle = self.to_agent_bundle(plan, dependencies=dependencies)
            await self._register_mcp_connections(plan, dependencies, bundle.react_agent, state)
            await self._register_plan_tools(plan, dependencies, bundle.react_agent, event_sink, state)
            await self._setup_native_skill_util(plan, dependencies, bundle, state)

            await emit_runtime_event(
                event_sink,
                RuntimeEvent(
                    type=RuntimeEventType.RUN,
                    request_id=plan.request_id,
                    agent_name=plan.root_agent.name,
                    content={"status": "started", "runtime_provider": self.name},
                    metadata={"runtime_provider": self.name},
                ),
            )
            await emit_runtime_event(
                event_sink,
                RuntimeEvent(
                    type=RuntimeEventType.STEP,
                    request_id=plan.request_id,
                    agent_name=plan.root_agent.name,
                    step_number=1,
                    content={"step": 1, "status": "started"},
                    metadata={"runtime_provider": self.name},
                ),
            )

            seen_reasoning = False
            async for chunk in self._run_react_agent(plan, dependencies, bundle.react_agent):
                event = self.runtime_event_from_openjiuwen_chunk(
                    chunk,
                    request_id=plan.request_id,
                    agent_name=plan.root_agent.name,
                )
                if event is not None:
                    if event.type == RuntimeEventType.MODEL_REASONING and (
                        event.reasoning or event.content
                    ):
                        seen_reasoning = True
                    await emit_runtime_event(event_sink, event)
                yield chunk

            await self._emit_process_type_noop_diagnostics(
                plan,
                event_sink,
                seen_reasoning=seen_reasoning,
            )
            await emit_runtime_event(
                event_sink,
                RuntimeEvent(
                    type=RuntimeEventType.RUN_FINISHED,
                    request_id=plan.request_id,
                    agent_name=plan.root_agent.name,
                    content={"status": "completed"},
                    metadata={"runtime_provider": self.name, "status": "completed"},
                ),
            )
        except asyncio.CancelledError:
            plan.run_control.cancel()
            await emit_runtime_event(
                event_sink,
                RuntimeEvent(
                    type=RuntimeEventType.RUN_FINISHED,
                    request_id=plan.request_id,
                    agent_name=plan.root_agent.name,
                    content={"status": "stopped"},
                    metadata={"runtime_provider": self.name, "status": "stopped"},
                ),
            )
            raise
        except Exception as exc:
            await emit_runtime_event(
                event_sink,
                RuntimeEvent(
                    type=RuntimeEventType.ERROR,
                    request_id=plan.request_id,
                    agent_name=plan.root_agent.name,
                    error=str(exc),
                    metadata={"runtime_provider": self.name},
                ),
            )
            raise
        finally:
            await self._cleanup_state(state)
            with self._lock:
                self._active_runs.pop(plan.request_id, None)

    async def stop(self, request_id: str) -> None:
        """Cancel an OpenJiuwen run and clean request-scoped resources."""
        with self._lock:
            state = self._active_runs.get(request_id)
        if state is None:
            return
        state.run_control.cancel()
        if state.task is not None and not state.task.done():
            state.task.cancel()
        await self._cleanup_state(state)

    def to_agent_bundle(
        self,
        plan: AgentRunPlan,
        *,
        dependencies: OpenJiuwenRuntimeDependencies | None = None,
    ) -> OpenJiuwenAgentBundle:
        """Map AgentRunPlan root data to OpenJiuwen native agent objects."""
        dependencies = dependencies or self._resolve_dependencies()
        root_agent = plan.root_agent
        model_config = self._select_model_config(plan, root_agent)
        model_request_config = self._to_model_request_config(model_config, root_agent, dependencies)
        model_client_config = self._to_model_client_config(model_config, root_agent, dependencies)
        prompt_template = self._to_prompt_template(root_agent)
        context_engine_config = self._to_context_engine_config(root_agent, dependencies)

        react_agent_config = dependencies.ReActAgentConfig(
            model_config_obj=model_request_config,
            model_client_config=model_client_config,
            prompt_template=prompt_template,
            max_iterations=root_agent.max_steps,
            context_engine_config=context_engine_config,
        )
        agent_card = dependencies.AgentCard(
            id=str(root_agent.agent_id),
            name=root_agent.name,
            description=root_agent.description or root_agent.name,
        )
        react_agent = dependencies.ReActAgent(card=agent_card).configure(react_agent_config)
        history_messages = self._history_to_messages(plan.history, dependencies)
        self._install_history_initializer(react_agent, history_messages, request_id=plan.request_id)
        return OpenJiuwenAgentBundle(
            agent_card=agent_card,
            react_agent_config=react_agent_config,
            react_agent=react_agent,
            model_request_config=model_request_config,
            model_client_config=model_client_config,
            prompt_template=prompt_template,
            context_engine_config=context_engine_config,
            history_messages=history_messages,
        )

    def to_mcp_server_config(
        self,
        connection: MCPConnectionConfig,
        *,
        request_id: str,
        dependencies: OpenJiuwenRuntimeDependencies | None = None,
    ) -> Any:
        """Map Nexent MCP connection data to OpenJiuwen McpServerConfig."""
        dependencies = dependencies or self._resolve_dependencies()
        return dependencies.McpServerConfig(
            server_id=_request_scoped_resource_id(request_id, "mcp", connection.name),
            server_name=connection.name,
            server_path=connection.url,
            client_type=_to_openjiuwen_mcp_transport(connection.transport),
            params={},
            auth_headers=dict(connection.headers),
        )

    def runtime_event_from_openjiuwen_chunk(
        self,
        chunk: Any,
        *,
        request_id: str,
        agent_name: str,
    ) -> RuntimeEvent | None:
        """Normalize OpenJiuwen stream chunks into RuntimeEvent values."""
        data = _model_dump(chunk)
        chunk_type = str(data.get("type") or getattr(chunk, "type", "") or "")
        payload = data.get("payload", getattr(chunk, "payload", None))
        payload_data = _model_dump(payload)
        native_metadata = {"native": data}

        if chunk_type == "llm_output":
            content = _first_present(payload_data, "content", "output", default="")
            return RuntimeEvent(
                type=RuntimeEventType.MODEL_DELTA,
                request_id=request_id,
                agent_name=agent_name,
                delta=str(content),
                content=content,
                compat_process_type="model_output_thinking",
                metadata=native_metadata,
            )
        if chunk_type == "llm_reasoning":
            reasoning = _first_present(payload_data, "content", "reasoning", default="")
            return RuntimeEvent(
                type=RuntimeEventType.MODEL_REASONING,
                request_id=request_id,
                agent_name=agent_name,
                reasoning=str(reasoning),
                content=reasoning,
                compat_process_type="model_output_deep_thinking",
                metadata=native_metadata,
            )
        if chunk_type == "llm_usage":
            usage = _first_present(payload_data, "usage_metadata", "usage", default=payload_data)
            usage_data = _model_dump(usage)
            return RuntimeEvent(
                type=RuntimeEventType.TOKEN_COUNT,
                request_id=request_id,
                agent_name=agent_name,
                token_usage=usage_data,
                payload=payload_data,
                metadata=native_metadata,
            )
        if chunk_type == "answer":
            content = _first_present(payload_data, "output", "content", "answer", default="")
            if "max iterations reached" in str(content).lower():
                return RuntimeEvent(
                    type=RuntimeEventType.MAX_STEPS,
                    request_id=request_id,
                    agent_name=agent_name,
                    content=content,
                    metadata=native_metadata,
                )
            return RuntimeEvent(
                type=RuntimeEventType.FINAL_ANSWER,
                request_id=request_id,
                agent_name=agent_name,
                content=content,
                metadata=native_metadata,
            )
        if chunk_type in {"tool_call", "tool_result", "tool"}:
            tool_name = str(_first_present(payload_data, "tool_name", "name", default=""))
            return RuntimeEvent(
                type=RuntimeEventType.TOOL_CALL,
                request_id=request_id,
                agent_name=agent_name,
                tool_name=tool_name or None,
                tool_input=payload_data.get("input") or payload_data.get("arguments"),
                tool_output=payload_data.get("output") or payload_data.get("result"),
                compat_process_type="tool",
                metadata=native_metadata,
            )
        if chunk_type == "error":
            return RuntimeEvent(
                type=RuntimeEventType.ERROR,
                request_id=request_id,
                agent_name=agent_name,
                error=str(_first_present(payload_data, "error", "output", "content", default="")),
                metadata=native_metadata,
            )
        if not chunk_type:
            return None
        return RuntimeEvent(
            type=RuntimeEventType.LEGACY_PROCESS,
            request_id=request_id,
            agent_name=agent_name,
            content=payload_data or data,
            compat_process_type="other",
            payload=payload_data if isinstance(payload_data, dict) else {},
            metadata=native_metadata,
        )

    async def _emit_process_type_noop_diagnostics(
        self,
        plan: AgentRunPlan,
        event_sink: Any,
        *,
        seen_reasoning: bool,
    ) -> None:
        if not bool(plan.runtime_resources.get("openjiuwen.emit_noop_diagnostics", True)):
            return
        diagnostics = [
            (
                "model_output_code",
                "OpenJiuwen ReActAgent does not expose smolagents Python code blocks.",
            ),
            (
                "verification",
                "OpenJiuwenRuntime spike does not run Nexent final-answer verification.",
            ),
        ]
        if not seen_reasoning:
            diagnostics.append(
                (
                    "model_output_deep_thinking",
                    "The selected model stream did not provide reasoning content.",
                )
            )
        for process_type, reason in diagnostics:
            await emit_runtime_event(
                event_sink,
                RuntimeEvent(
                    type=RuntimeEventType.LEGACY_PROCESS,
                    request_id=plan.request_id,
                    agent_name=plan.root_agent.name,
                    compat_process_type="other",
                    content={
                        "process_type": process_type,
                        "compatibility": "no-op",
                        "reason": reason,
                    },
                    metadata={
                        "runtime_provider": self.name,
                        "noop_process_type": process_type,
                    },
                ),
            )

    def _resolve_dependencies(self) -> OpenJiuwenRuntimeDependencies:
        if isinstance(self._dependencies, OpenJiuwenRuntimeDependencies):
            return self._dependencies
        if callable(self._dependencies):
            return self._dependencies()
        return _load_openjiuwen_dependencies()

    def _validate_supported_plan(self, plan: AgentRunPlan) -> None:
        root_agent = plan.root_agent
        if root_agent.managed_agents:
            raise OpenJiuwenUnsupportedFeatureError(
                "OpenJiuwenRuntime spike does not support managed agents."
            )
        if root_agent.external_a2a_agents:
            raise OpenJiuwenUnsupportedFeatureError(
                "OpenJiuwenRuntime spike does not support external A2A agents."
            )
        policy = root_agent.context_policy
        if policy.mode == ContextMode.MANAGED:
            raise OpenJiuwenUnsupportedFeatureError(
                "OpenJiuwenRuntime spike does not support managed context."
            )
        if policy.compression:
            raise OpenJiuwenUnsupportedFeatureError(
                "OpenJiuwenRuntime spike does not support context compression."
            )

    async def _register_mcp_connections(
        self,
        plan: AgentRunPlan,
        dependencies: OpenJiuwenRuntimeDependencies,
        react_agent: Any,
        state: _OpenJiuwenRunState,
    ) -> None:
        for connection in plan.mcp_connections:
            mcp_config = self.to_mcp_server_config(
                connection,
                request_id=plan.request_id,
                dependencies=dependencies,
            )
            await _maybe_await(
                dependencies.Runner.resource_mgr.add_mcp_server(
                    mcp_config,
                    expiry_time=self._mcp_expiry_time,
                )
            )
            state.mcp_server_ids.append(str(getattr(mcp_config, "server_id", "")))
            _add_agent_ability(react_agent, mcp_config)

    async def _register_plan_tools(
        self,
        plan: AgentRunPlan,
        dependencies: OpenJiuwenRuntimeDependencies,
        react_agent: Any,
        event_sink: Any,
        state: _OpenJiuwenRunState,
    ) -> None:
        registry = self._tool_factory_registry or plan.runtime_resources.get("tool_factory_registry")
        visible_tools = [
            tool for tool in plan.root_agent.tools
            if tool.visibility != ToolVisibility.INTERNAL
            and _normalize_tool_source(tool.source) != ToolSource.MCP.value
        ]
        if visible_tools and not isinstance(registry, ToolFactoryRegistry):
            raise OpenJiuwenToolMappingError(
                "OpenJiuwenRuntime requires a ToolFactoryRegistry for non-MCP tools."
            )

        for tool in visible_tools:
            tool_context = ToolRuntimeContext(
                request_id=plan.request_id,
                agent_name=plan.root_agent.name,
                user_id=plan.run_control.user_id,
                tenant_id=str(plan.run_control.metadata.get("tenant_id") or ""),
                runtime_provider=plan.runtime_provider,
                event_sink=event_sink,
                run_control=plan.run_control,
                resources={
                    **dict(plan.runtime_resources),
                    "openjiuwen.runner": dependencies.Runner,
                },
            )
            native_tool = registry.create(tool, tool_context)
            openjiuwen_tool = self._to_openjiuwen_local_tool(
                tool,
                native_tool,
                dependencies,
                request_id=plan.request_id,
            )
            await _maybe_await(dependencies.Runner.resource_mgr.add_tool(openjiuwen_tool, refresh=True))
            state.tool_ids.append(str(getattr(openjiuwen_tool.card, "id", "")))
            _add_agent_ability(react_agent, openjiuwen_tool.card)

    async def _setup_native_skill_util(
        self,
        plan: AgentRunPlan,
        dependencies: OpenJiuwenRuntimeDependencies,
        bundle: OpenJiuwenAgentBundle,
        state: _OpenJiuwenRunState,
    ) -> None:
        if not bool(plan.runtime_resources.get("openjiuwen.skill_util.enabled", False)):
            return
        skill_path = plan.runtime_resources.get("skill.local_skills_dir")
        enabled_skills = plan.runtime_resources.get("skill.enabled_skills") or []
        if not skill_path or not enabled_skills:
            return
        if dependencies.SkillUtil is None:
            raise OpenJiuwenDependencyError("OpenJiuwen SkillUtil is not available.")

        sys_operation_id = _request_scoped_resource_id(plan.request_id, "sys_operation", "skills")
        await self._register_sys_operation(plan, dependencies, sys_operation_id)
        state.sys_operation_ids.append(sys_operation_id)
        await self._add_read_file_ability(dependencies, bundle.react_agent, sys_operation_id)

        skill_util = dependencies.SkillUtil(sys_operation_id=sys_operation_id)
        await _maybe_await(
            skill_util.register_skills(
                skill_path=skill_path,
                agent=bundle.react_agent,
                session_id=plan.request_id,
            )
        )
        skill_prompt = skill_util.get_skill_prompt()
        if skill_prompt:
            bundle.prompt_template.append({"role": "system", "content": skill_prompt})
            config_prompt = getattr(bundle.react_agent_config, "prompt_template", None)
            if isinstance(config_prompt, list):
                config_prompt.append({"role": "system", "content": skill_prompt})
            add_section = getattr(bundle.react_agent, "add_prompt_builder_section", None)
            if callable(add_section):
                add_section("nexent_native_skills", skill_prompt, priority=250)

    async def _register_sys_operation(
        self,
        plan: AgentRunPlan,
        dependencies: OpenJiuwenRuntimeDependencies,
        sys_operation_id: str,
    ) -> None:
        if dependencies.SysOperationCard is None or dependencies.LocalWorkConfig is None:
            raise OpenJiuwenDependencyError("OpenJiuwen SysOperation dependencies are not available.")
        resource_config = dict(plan.runtime_resources.get("openjiuwen.sys_operation") or {})
        local_work_config = dependencies.LocalWorkConfig(
            sandbox_root=resource_config.get("sandbox_root"),
            restrict_to_sandbox=bool(resource_config.get("restrict_to_sandbox", False)),
            shell_allowlist=resource_config.get("shell_allowlist"),
        )
        mode = dependencies.OperationMode.LOCAL if dependencies.OperationMode is not None else "local"
        sys_operation_card = dependencies.SysOperationCard(
            id=sys_operation_id,
            name="nexent_skill_sys_operation",
            description="Request-scoped system operation for OpenJiuwen skills.",
            mode=mode,
            work_config=local_work_config,
        )
        await _maybe_await(dependencies.Runner.resource_mgr.add_sys_operation(sys_operation_card))

    async def _add_read_file_ability(
        self,
        dependencies: OpenJiuwenRuntimeDependencies,
        react_agent: Any,
        sys_operation_id: str,
    ) -> None:
        resource_mgr = dependencies.Runner.resource_mgr
        get_cards = getattr(resource_mgr, "get_sys_op_tool_cards", None)
        if callable(get_cards):
            cards = get_cards(
                sys_operation_id,
                operation_name="fs",
                tool_name="read_file",
            )
            for card in _as_list(cards):
                _add_agent_ability(react_agent, card)
            if cards:
                return
        get_tool = getattr(resource_mgr, "get_tool", None)
        generate_tool_id = getattr(dependencies.SysOperationCard, "generate_tool_id", None)
        if callable(get_tool) and callable(generate_tool_id):
            tool = get_tool(generate_tool_id(sys_operation_id, "fs", "read_file"))
            card = getattr(tool, "card", None)
            if card is not None:
                _add_agent_ability(react_agent, card)
                return
        raise OpenJiuwenRuntimeError("OpenJiuwen native skill prompt requires read_file tool.")

    def _to_openjiuwen_local_tool(
        self,
        tool: ToolSpec,
        native_tool: Any,
        dependencies: OpenJiuwenRuntimeDependencies,
        *,
        request_id: str,
    ) -> Any:
        tool_card = dependencies.ToolCard(
            id=_request_scoped_resource_id(request_id, "tool", tool.name),
            name=tool.name,
            description=tool.description,
            input_params=_to_openjiuwen_tool_schema(tool.input_schema),
            stateless=False,
        )

        async def invoke_neutral_tool(**kwargs: Any) -> Any:
            return await _call_neutral_tool(native_tool, kwargs)

        return dependencies.LocalFunction(card=tool_card, func=invoke_neutral_tool)

    async def _run_react_agent(
        self,
        plan: AgentRunPlan,
        dependencies: OpenJiuwenRuntimeDependencies,
        react_agent: Any,
    ) -> AsyncIterator[Any]:
        inputs = {
            "query": plan.query,
            "conversation_id": str(plan.run_control.conversation_id or plan.request_id),
            "user_id": plan.run_control.user_id,
            "run_kind": "nexent_agent_runtime",
            "run_context": plan.request_id,
        }

        stream = getattr(react_agent, "stream", None)
        if self._prefer_streaming and callable(stream):
            async for chunk in stream(inputs):
                yield chunk
            return

        invoke = getattr(react_agent, "invoke", None)
        runner_run_agent = getattr(dependencies.Runner, "run_agent", None)
        if callable(invoke):
            result = await _maybe_await(invoke(inputs))
        elif callable(runner_run_agent):
            result = await _maybe_await(runner_run_agent(react_agent, inputs))
        else:
            raise OpenJiuwenRuntimeError("OpenJiuwen ReActAgent does not expose invoke or stream.")
        yield {
            "type": "answer",
            "payload": {
                "output": _first_present(_model_dump(result), "output", "content", default=result),
                "result_type": _first_present(_model_dump(result), "result_type", default="answer"),
            },
        }

    def _select_model_config(self, plan: AgentRunPlan, agent: AgentSpec) -> dict[str, Any]:
        if not plan.model_config_list:
            return {}
        for model_config in plan.model_config_list:
            data = _model_dump(model_config)
            identifiers = {
                str(data.get("cite_name") or ""),
                str(data.get("model_name") or data.get("model") or ""),
                str(data.get("alias") or ""),
            }
            if agent.model_name in identifiers:
                return data
        return _model_dump(plan.model_config_list[0])

    def _to_model_request_config(
        self,
        model_config: Mapping[str, Any],
        agent: AgentSpec,
        dependencies: OpenJiuwenRuntimeDependencies,
    ) -> Any:
        model_name = str(
            _first_present(model_config, "model_name", "model", default=agent.model_name)
            or agent.model_name
        )
        max_tokens = _first_present(
            model_config,
            "max_tokens",
            "max_output_tokens",
            default=agent.runtime_hints.get("requested_output_tokens"),
        )
        request_kwargs = {
            "model": model_name,
            "temperature": _first_present(model_config, "temperature", default=0.95),
            "top_p": _first_present(model_config, "top_p", default=0.1),
            "max_tokens": max_tokens,
        }
        request_kwargs.update(_model_extra_params(model_config))
        return dependencies.ModelRequestConfig(**_drop_none_values(request_kwargs))

    def _to_model_client_config(
        self,
        model_config: Mapping[str, Any],
        agent: AgentSpec,
        dependencies: OpenJiuwenRuntimeDependencies,
    ) -> Any:
        _ = agent
        client_kwargs = {
            "client_provider": _first_present(
                model_config,
                "client_provider",
                "model_provider",
                "model_factory",
                "provider",
                default="openai",
            ),
            "api_key": _first_present(model_config, "api_key", default=""),
            "api_base": _first_present(model_config, "api_base", "url", "base_url", default=""),
            "timeout": _first_present(model_config, "timeout", default=60.0),
            "verify_ssl": _first_present(model_config, "verify_ssl", "ssl_verify", default=True),
            "custom_headers": _first_present(model_config, "custom_headers", "headers", default=None),
        }
        return dependencies.ModelClientConfig(**_drop_none_values(client_kwargs))

    def _to_prompt_template(self, agent: AgentSpec) -> list[dict[str, Any]]:
        prompt = agent.prompt
        if prompt.rendered_legacy_system_prompt:
            system_prompt = prompt.rendered_legacy_system_prompt
        else:
            system_prompt = _render_prompt_fragments(prompt.fragments)
        return [{"role": "system", "content": system_prompt}]

    def _to_context_engine_config(
        self,
        agent: AgentSpec,
        dependencies: OpenJiuwenRuntimeDependencies,
    ) -> Any | None:
        context_engine_config_cls = dependencies.ContextEngineConfig
        if context_engine_config_cls is None:
            return None
        hints = dict(agent.runtime_hints.get("context_engine") or {})
        if agent.context_policy.mode != ContextMode.RUNTIME_NATIVE and not hints:
            return context_engine_config_cls(
                max_context_message_num=None,
                default_window_round_num=None,
            )
        kwargs = {
            "max_context_message_num": hints.get("max_context_message_num"),
            "default_window_message_num": hints.get("default_window_message_num"),
            "default_window_round_num": hints.get("default_window_round_num"),
            "context_window_tokens": hints.get("context_window_tokens"),
            "model_name": hints.get("model_name") or agent.model_name,
        }
        return context_engine_config_cls(**_drop_none_values(kwargs))

    def _history_to_messages(
        self,
        history: list[Any] | None,
        dependencies: OpenJiuwenRuntimeDependencies,
    ) -> list[Any]:
        if not history:
            return []
        messages: list[Any] = []
        for item in history:
            data = _model_dump(item)
            role = str(data.get("role") or "user").lower()
            content = data.get("content", "")
            message_cls = _message_class_for_role(role, dependencies)
            if message_cls is None:
                continue
            messages.append(message_cls(content=content))
        return messages

    def _install_history_initializer(
        self,
        react_agent: Any,
        history_messages: list[Any],
        *,
        request_id: str,
    ) -> None:
        if not history_messages:
            return
        original_init_context = getattr(react_agent, "_init_context", None)
        if not callable(original_init_context):
            setattr(react_agent, "nexent_history_messages", list(history_messages))
            return

        async def init_context_with_history(agent_self: Any, session: Any) -> Any:
            context = await _maybe_await(original_init_context(session))
            marker = f"_nexent_history_injected_{request_id}"
            if not getattr(context, marker, False):
                add_messages = getattr(context, "add_messages", None)
                if callable(add_messages):
                    await _maybe_await(add_messages(list(history_messages)))
                setattr(context, marker, True)
            return context

        setattr(react_agent, "_init_context", MethodType(init_context_with_history, react_agent))

    async def _cleanup_state(self, state: _OpenJiuwenRunState) -> None:
        if state.cleaned:
            return
        state.cleaned = True
        resource_mgr = getattr(state.runner, "resource_mgr", None)
        if resource_mgr is None:
            return
        for server_id in list(state.mcp_server_ids):
            remove_mcp_server = getattr(resource_mgr, "remove_mcp_server", None)
            if callable(remove_mcp_server):
                await _call_cleanup(remove_mcp_server, server_id=server_id, ignore_exception=True)
        if state.tool_ids:
            remove_tool = getattr(resource_mgr, "remove_tool", None)
            if callable(remove_tool):
                await _call_cleanup(remove_tool, tool_id=list(state.tool_ids))
        for sys_operation_id in list(state.sys_operation_ids):
            remove_sys_operation = getattr(resource_mgr, "remove_sys_operation", None)
            if callable(remove_sys_operation):
                await _call_cleanup(remove_sys_operation, sys_operation_id=sys_operation_id)


def _load_openjiuwen_dependencies() -> OpenJiuwenRuntimeDependencies:
    try:
        from openjiuwen.core.context_engine import ContextEngineConfig
        from openjiuwen.core.foundation.llm import (
            AssistantMessage,
            ModelClientConfig,
            ModelRequestConfig,
            SystemMessage,
            ToolMessage,
            UserMessage,
        )
        from openjiuwen.core.foundation.tool import LocalFunction, ToolCard
        from openjiuwen.core.foundation.tool.mcp.base import McpServerConfig
        from openjiuwen.core.runner import Runner
        from openjiuwen.core.single_agent import AgentCard, ReActAgent, ReActAgentConfig
    except ImportError as exc:
        raise OpenJiuwenDependencyError(
            "OpenJiuwenRuntime requires the optional openjiuwen package."
        ) from exc

    try:
        from openjiuwen.core.skills import SkillUtil
    except ImportError:
        SkillUtil = None

    try:
        from openjiuwen.core.sys_operation import SysOperationCard
        from openjiuwen.core.sys_operation import LocalWorkConfig, OperationMode
    except ImportError:
        SysOperationCard = None
        LocalWorkConfig = None
        OperationMode = None

    return OpenJiuwenRuntimeDependencies(
        AgentCard=AgentCard,
        ReActAgentConfig=ReActAgentConfig,
        ReActAgent=ReActAgent,
        ModelRequestConfig=ModelRequestConfig,
        ModelClientConfig=ModelClientConfig,
        McpServerConfig=McpServerConfig,
        ToolCard=ToolCard,
        LocalFunction=LocalFunction,
        ContextEngineConfig=ContextEngineConfig,
        Runner=Runner,
        UserMessage=UserMessage,
        AssistantMessage=AssistantMessage,
        SystemMessage=SystemMessage,
        ToolMessage=ToolMessage,
        SkillUtil=SkillUtil,
        SysOperationCard=SysOperationCard,
        LocalWorkConfig=LocalWorkConfig,
        OperationMode=OperationMode,
    )


def _render_prompt_fragments(fragments: Mapping[str, Any]) -> str:
    sections: list[str] = []
    for key, value in fragments.items():
        if value in (None, "", [], {}):
            continue
        sections.append(f"[{key}]\n{_format_prompt_value(value)}")
    return "\n\n".join(sections)


def _format_prompt_value(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _model_dump(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, Mapping):
        return dict(value)
    if hasattr(value, "model_dump"):
        return dict(value.model_dump(exclude_none=True))
    if hasattr(value, "dict"):
        return dict(value.dict(exclude_none=True))
    if hasattr(value, "__dict__"):
        return {
            key: item
            for key, item in vars(value).items()
            if not key.startswith("_")
        }
    return {}


def _first_present(data: Mapping[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        value = data.get(key)
        if value is not None:
            return value
    return default


def _drop_none_values(data: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in data.items() if value is not None}


def _model_extra_params(model_config: Mapping[str, Any]) -> dict[str, Any]:
    for key in ("model_params", "extra_params", "extra"):
        value = model_config.get(key)
        if isinstance(value, Mapping):
            return dict(value)
    return {}


def _to_openjiuwen_mcp_transport(transport: str) -> str:
    if transport == "streamable-http":
        return "streamable_http"
    return transport


def _request_scoped_resource_id(request_id: str, resource_type: str, name: str) -> str:
    raw = f"{request_id}:{resource_type}:{name}"
    return re.sub(r"[^A-Za-z0-9_.:-]+", "_", raw)


def _normalize_tool_source(source: ToolSource | str) -> str:
    return source.value if hasattr(source, "value") else str(source)


def _to_openjiuwen_tool_schema(input_schema: Mapping[str, Any]) -> dict[str, Any]:
    schema = dict(input_schema or {})
    if schema.get("type") == "object" or "properties" in schema:
        return schema
    return {
        "type": "object",
        "properties": schema,
        "required": [
            name
            for name, config in schema.items()
            if isinstance(config, Mapping) and config.get("required") is True
        ],
    }


async def _call_neutral_tool(native_tool: Any, kwargs: Mapping[str, Any]) -> Any:
    if callable(native_tool):
        result = native_tool(**dict(kwargs))
    else:
        forward = getattr(native_tool, "forward", None)
        invoke = getattr(native_tool, "invoke", None)
        if callable(forward):
            result = forward(**dict(kwargs))
        elif callable(invoke):
            result = invoke(dict(kwargs))
        else:
            raise OpenJiuwenToolMappingError(
                f"Tool '{getattr(native_tool, 'name', 'unknown')}' is not callable."
            )
    return await _maybe_await(result)


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


async def _call_cleanup(cleanup: Callable[..., Any], **kwargs: Any) -> Any:
    try:
        return await _maybe_await(cleanup(**kwargs))
    except TypeError:
        minimal_kwargs = {
            key: value
            for key, value in kwargs.items()
            if key in {"server_id", "tool_id", "sys_operation_id"}
        }
        return await _maybe_await(cleanup(**minimal_kwargs))


def _add_agent_ability(react_agent: Any, ability: Any) -> None:
    ability_manager = getattr(react_agent, "ability_manager", None)
    if ability_manager is None:
        ability_manager = getattr(react_agent, "_ability_manager", None)
    add = getattr(ability_manager, "add", None)
    if not callable(add):
        raise OpenJiuwenRuntimeError("OpenJiuwen ReActAgent does not expose ability_manager.add().")
    add(ability)


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list | tuple | set):
        return list(value)
    return [value]


def _message_class_for_role(
    role: str,
    dependencies: OpenJiuwenRuntimeDependencies,
) -> Any | None:
    if role == "assistant":
        return dependencies.AssistantMessage
    if role == "system":
        return dependencies.SystemMessage
    if role == "tool":
        return dependencies.ToolMessage
    return dependencies.UserMessage
