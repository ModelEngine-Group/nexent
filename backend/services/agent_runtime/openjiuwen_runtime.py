"""OpenJiuwen runtime adapter."""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import re
import time
from collections.abc import AsyncIterator, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from consts.const import AGENT_RUNTIME_PROVIDER_OPENJIUWEN

from .events import RuntimeEvent, RuntimeEventType, emit_runtime_event
from .config import get_openjiuwen_sandbox_settings
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
from .openjiuwen_sandbox import (
    OpenJiuwenDevSandboxService,
    OpenJiuwenSandboxError,
    SandboxSkillScriptExecutor,
)
from .tool_factory import (
    ToolFactoryRegistry,
    build_production_tool_factory_registry,
    wrap_tool_with_runtime_events,
)
from .tool_schema import tool_input_schema_to_json_schema


logger = logging.getLogger(__name__)


OPENJIUWEN_PROCESS_TYPE_COMPATIBILITY = {
    "agent_new_run": "complete",
    "agent_finish": "complete",
    "card": "complete",
    "error": "complete",
    "execution_logs": "complete",
    "final_answer": "complete",
    "max_steps_reached": "complete",
    "memory_search": "partial",
    "model_output_code": "no-op",
    "model_output_deep_thinking": "partial",
    "model_output_thinking": "complete",
    "other": "no-op",
    "parse": "complete",
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
    ContextEngine: Any | None = None
    create_agent_session: Any | None = None
    NexentOpenAIModelClient: Any | None = None


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
    request_id: str
    task: asyncio.Task[Any] | None
    run_control: Any
    runner: Any
    mcp_server_ids: list[str] = field(default_factory=list)
    tool_ids: list[str] = field(default_factory=list)
    sys_operation_ids: list[str] = field(default_factory=list)
    session: Any | None = None
    context_engine: Any | None = None
    context_id: str | None = None
    sandbox_executor: SandboxSkillScriptExecutor | None = None
    cleaned: bool = False


@dataclass
class AgentRail:
    """Request-scoped OpenJiuwen event mapper and step counter."""

    runtime: "OpenJiuwenRuntime"
    request_id: str
    agent_name: str
    step_number: int = 1

    def map_chunk(self, chunk: Any) -> RuntimeEvent | None:
        chunk_type = str(_model_dump(chunk).get("type") or getattr(chunk, "type", ""))
        if chunk_type in {"tool_call", "tool"}:
            return None
        if chunk_type == "tool_result":
            self.step_number += 1
            return RuntimeEvent(
                type=RuntimeEventType.STEP,
                request_id=self.request_id,
                agent_name=self.agent_name,
                step_number=self.step_number,
                content={"step": self.step_number, "status": "tool_completed"},
                metadata={"native": _model_dump(chunk)},
            )
        event = self.runtime.runtime_event_from_openjiuwen_chunk(
            chunk,
            request_id=self.request_id,
            agent_name=self.agent_name,
        )
        return event


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
        sandboxed_execution=False,
        tool_artifacts=True,
        context_compression=False,
        tool_call_events=True,
        token_usage_events=True,
        interruptible=True,
        resumable_stream=False,
        verification=False,
    )

    def __init__(
        self,
        *,
        dependencies: OpenJiuwenRuntimeDependencies
        | Callable[[], OpenJiuwenRuntimeDependencies]
        | None = None,
        tool_factory_registry: ToolFactoryRegistry | None = None,
        prefer_streaming: bool = True,
        mcp_expiry_time: float | None = None,
        sandbox_service: OpenJiuwenDevSandboxService | None = None,
    ):
        self._dependencies = dependencies
        self._tool_factory_registry = tool_factory_registry
        self._prefer_streaming = prefer_streaming
        self._mcp_expiry_time = mcp_expiry_time
        self._sandbox_service = sandbox_service or OpenJiuwenDevSandboxService(
            get_openjiuwen_sandbox_settings(validate=False)
        )
        self.capabilities = type(self).capabilities.model_copy(
            update={"sandboxed_execution": self._sandbox_service.healthy}
        )
        self._active_runs: dict[str, _OpenJiuwenRunState] = {}

    async def run(
        self,
        plan: AgentRunPlan,
        event_sink: Any = None,
    ) -> AsyncIterator[Any]:
        """Execute an OpenJiuwen run from a framework-neutral AgentRunPlan."""
        started_at = time.monotonic()
        logger.info(
            "OpenJiuwen runtime run starting, request_id=%s, agent_id=%s, agent_name=%s, "
            "conversation_id=%s, max_steps=%s, history_count=%d, tool_count=%d, "
            "mcp_count=%d, required_capabilities=%s, optional_capabilities=%s",
            plan.request_id,
            plan.root_agent.agent_id,
            plan.root_agent.name,
            plan.run_control.conversation_id,
            plan.root_agent.max_steps,
            len(plan.history or []),
            _visible_tool_count(plan),
            len(plan.mcp_connections),
            _sorted_capabilities(plan.capability_requirements.required),
            _sorted_capabilities(plan.capability_requirements.optional),
        )
        dependencies = self._resolve_dependencies()
        state = _OpenJiuwenRunState(
            request_id=plan.request_id,
            task=asyncio.current_task(),
            run_control=plan.run_control,
            runner=dependencies.Runner,
        )
        self._active_runs[plan.request_id] = state

        try:
            await self._prepare_sandbox_execution(plan, state)
            self._validate_supported_plan(plan)
            logger.debug(
                "OpenJiuwen runtime plan validation passed, request_id=%s, "
                "tool_source_counts=%s, prompt_fragment_count=%d",
                plan.request_id,
                _tool_source_counts(plan),
                len(plan.root_agent.prompt.fragments),
            )
            bundle = self.to_agent_bundle(plan, dependencies=dependencies)
            logger.debug(
                "OpenJiuwen agent bundle created, request_id=%s, model_name=%s, "
                "model_provider=%s, history_message_count=%d",
                plan.request_id,
                getattr(bundle.react_agent_config, "model_name", plan.root_agent.model_name),
                getattr(bundle.react_agent_config, "model_provider", ""),
                len(bundle.history_messages),
            )
            await self._prepare_session_context(plan, dependencies, bundle, state)
            logger.debug(
                "OpenJiuwen session context prepared, request_id=%s, session_created=%s, "
                "context_created=%s, context_id=%s",
                plan.request_id,
                state.session is not None,
                state.context_engine is not None,
                state.context_id,
            )
            await self._register_mcp_connections(
                plan,
                dependencies,
                bundle.react_agent,
                event_sink,
                state,
            )
            await self._register_plan_tools(
                plan, dependencies, bundle.react_agent, event_sink, state
            )
            logger.debug(
                "OpenJiuwen runtime resources registered, request_id=%s, "
                "registered_mcp_count=%d, registered_tool_count=%d, "
                "registered_sys_operation_count=%d",
                plan.request_id,
                len(state.mcp_server_ids),
                len(state.tool_ids),
                len(state.sys_operation_ids),
            )

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

            rail = AgentRail(self, plan.request_id, plan.root_agent.name)
            async for chunk in self._run_react_agent(
                plan,
                dependencies,
                bundle.react_agent,
                session=state.session,
            ):
                event = rail.map_chunk(chunk)
                if event is not None:
                    await emit_runtime_event(event_sink, event)
                yield chunk

            self._record_process_type_coverage(plan)
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
            logger.info(
                "OpenJiuwen runtime run finished, request_id=%s, status=completed, duration_ms=%d, "
                "registered_mcp_count=%d, registered_tool_count=%d, registered_sys_operation_count=%d",
                plan.request_id,
                _elapsed_ms(started_at),
                len(state.mcp_server_ids),
                len(state.tool_ids),
                len(state.sys_operation_ids),
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
            logger.info(
                "OpenJiuwen runtime run finished, request_id=%s, status=stopped, duration_ms=%d",
                plan.request_id,
                _elapsed_ms(started_at),
            )
            raise
        except Exception as exc:
            error_metadata = {
                "runtime_provider": self.name,
                **_sandbox_error_metadata(exc),
            }
            await emit_runtime_event(
                event_sink,
                RuntimeEvent(
                    type=RuntimeEventType.ERROR,
                    request_id=plan.request_id,
                    agent_name=plan.root_agent.name,
                    error=str(exc),
                    metadata=error_metadata,
                ),
            )
            logger.error(
                "OpenJiuwen runtime run failed, request_id=%s, duration_ms=%d, error_type=%s",
                plan.request_id,
                _elapsed_ms(started_at),
                type(exc).__name__,
            )
            raise
        finally:
            await self._cleanup_state(state)
            self._active_runs.pop(plan.request_id, None)
            logger.debug(
                "OpenJiuwen runtime run state removed, request_id=%s, active_run_count=%d",
                plan.request_id,
                len(self._active_runs),
            )

    async def stop(self, request_id: str) -> None:
        """Cancel an OpenJiuwen run and clean request-scoped resources."""
        state = self._active_runs.get(request_id)
        if state is None:
            logger.debug(
                "OpenJiuwen runtime stop ignored, request_id=%s, reason=no_active_run",
                request_id,
            )
            return
        logger.info(
            "OpenJiuwen runtime stop requested, request_id=%s, registered_mcp_count=%d, "
            "registered_tool_count=%d, registered_sys_operation_count=%d",
            request_id,
            len(state.mcp_server_ids),
            len(state.tool_ids),
            len(state.sys_operation_ids),
        )
        state.run_control.cancel()
        if state.sandbox_executor is not None:
            await state.sandbox_executor.cancel()
        if state.task is not None and not state.task.done():
            state.task.cancel()
        await self._cleanup_state(state)

    def validate_installation(self) -> None:
        """Validate the selected OpenJiuwen SDK before starting a run."""
        self._resolve_dependencies()
        self._sandbox_service.validate_installation()

    def register_app_lifecycle(self, app: Any) -> None:
        """Register fixed sandbox startup and shutdown on a FastAPI app."""
        if not self._sandbox_service.enabled:
            return

        @app.on_event("startup")
        async def start_openjiuwen_sandbox() -> None:
            await self._sandbox_service.start()
            self._refresh_sandbox_capability()

        @app.on_event("shutdown")
        async def stop_openjiuwen_sandbox() -> None:
            await self._sandbox_service.stop()
            self._refresh_sandbox_capability()

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
        model_request_config = self._to_model_request_config(
            model_config, root_agent, dependencies
        )
        model_client_config = self._to_model_client_config(
            model_config, root_agent, dependencies
        )
        prompt_template = self._to_prompt_template(root_agent)
        context_engine_config = self._to_context_engine_config(root_agent, dependencies)

        selected_model_name = str(
            _first_present(
                model_config,
                "model_name",
                "model",
                default=root_agent.model_name,
            )
            or root_agent.model_name
        )
        react_agent_config = _construct_with_supported_kwargs(
            dependencies.ReActAgentConfig,
            {
                "model_name": selected_model_name,
                "model_provider": "NexentOpenAI",
                "model_config_obj": model_request_config,
                "model_client_config": model_client_config,
                "prompt_template": prompt_template,
                "max_iterations": root_agent.max_steps,
                "context_engine_config": context_engine_config,
            },
        )
        _set_if_possible(react_agent_config, "model_name", selected_model_name)
        _set_if_possible(react_agent_config, "model_provider", "NexentOpenAI")
        agent_card = dependencies.AgentCard(
            id=str(root_agent.agent_id),
            name=root_agent.name,
            description=root_agent.description or root_agent.name,
        )
        react_agent = dependencies.ReActAgent(card=agent_card).configure(
            react_agent_config
        )
        history_messages = self._history_to_messages(plan.history, dependencies)
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
            usage = _first_present(
                payload_data, "usage_metadata", "usage", default=payload_data
            )
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
            content = _first_present(
                payload_data, "output", "content", "answer", default=""
            )
            result_type = str(payload_data.get("result_type") or "answer").lower()
            if result_type == "error":
                return RuntimeEvent(
                    type=RuntimeEventType.ERROR,
                    request_id=request_id,
                    agent_name=agent_name,
                    error=str(content),
                    metadata=native_metadata,
                )
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
            tool_name = str(
                _first_present(payload_data, "tool_name", "name", default="")
            )
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
                error=str(
                    _first_present(
                        payload_data, "error", "output", "content", default=""
                    )
                ),
                metadata=native_metadata,
            )
        if not chunk_type:
            return None
        return None

    def _record_process_type_coverage(self, plan: AgentRunPlan) -> None:
        plan.monitoring_metadata["openjiuwen.process_type_coverage"] = dict(
            OPENJIUWEN_PROCESS_TYPE_COMPATIBILITY
        )

    def _resolve_dependencies(self) -> OpenJiuwenRuntimeDependencies:
        if isinstance(self._dependencies, OpenJiuwenRuntimeDependencies):
            return self._dependencies
        if callable(self._dependencies):
            return self._dependencies()
        return _load_openjiuwen_dependencies()

    async def _prepare_sandbox_execution(
        self,
        plan: AgentRunPlan,
        state: _OpenJiuwenRunState,
    ) -> None:
        spec = plan.sandbox_execution
        if spec is None or not spec.enabled:
            return
        await self._sandbox_service.start()
        self._refresh_sandbox_capability()
        if spec.required and not self._sandbox_service.healthy:
            raise OpenJiuwenDependencyError(
                "OpenJiuwen sandbox execution is required but unavailable."
            )
        attachments = plan.runtime_resources.get("sandbox.attachments") or {}
        host_staging_dirs = plan.runtime_resources.get("sandbox.host_staging_dirs")
        if not isinstance(host_staging_dirs, list):
            host_staging_dirs = []
            plan.runtime_resources["sandbox.host_staging_dirs"] = host_staging_dirs
        diagnostics = plan.runtime_resources.get("sandbox.diagnostics")
        if not isinstance(diagnostics, list):
            diagnostics = []
            plan.runtime_resources["sandbox.diagnostics"] = diagnostics
        state.sandbox_executor = SandboxSkillScriptExecutor(
            service=self._sandbox_service,
            request_id=plan.request_id,
            tenant_id=str(plan.run_control.metadata.get("tenant_id") or ""),
            run_control=plan.run_control,
            attachments=attachments if isinstance(attachments, Mapping) else {},
            host_staging_dirs=host_staging_dirs,
            diagnostics=diagnostics,
            host_staging_root=plan.runtime_resources.get(
                "sandbox.host_staging_root"
            ),
            execution_timeout_seconds=spec.execution_timeout_seconds,
        )

    def _refresh_sandbox_capability(self) -> None:
        self.capabilities = type(self).capabilities.model_copy(
            update={"sandboxed_execution": self._sandbox_service.healthy}
        )

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
        verification = root_agent.verification_config
        verification_enabled = (
            bool(verification.get("enabled"))
            if isinstance(verification, Mapping)
            else bool(getattr(verification, "enabled", False))
        )
        if verification_enabled:
            raise OpenJiuwenUnsupportedFeatureError(
                "OpenJiuwenRuntime does not support enabled verification."
            )
        if bool(plan.runtime_resources.get("runtime.resumable_stream_required")):
            raise OpenJiuwenUnsupportedFeatureError(
                "OpenJiuwenRuntime does not support resumable runtime streams."
            )
        if not root_agent.prompt.fragments:
            raise OpenJiuwenUnsupportedFeatureError(
                "OpenJiuwenRuntime requires neutral PromptBundle.fragments."
            )

    async def _register_mcp_connections(
        self,
        plan: AgentRunPlan,
        dependencies: OpenJiuwenRuntimeDependencies,
        react_agent: Any,
        event_sink: Any,
        state: _OpenJiuwenRunState,
    ) -> None:
        mcp_tools = [
            tool
            for tool in plan.root_agent.tools
            if _normalize_tool_source(tool.source) == ToolSource.MCP.value
            and tool.visibility != ToolVisibility.INTERNAL
        ]
        logger.debug(
            "OpenJiuwen MCP registration starting, request_id=%s, connection_count=%d, "
            "allowlisted_tool_count=%d",
            plan.request_id,
            len(plan.mcp_connections),
            len(mcp_tools),
        )
        for connection in plan.mcp_connections:
            mcp_config = self.to_mcp_server_config(
                connection,
                request_id=plan.request_id,
                dependencies=dependencies,
            )
            add_result = await _maybe_await(
                dependencies.Runner.resource_mgr.add_mcp_server(
                    mcp_config,
                    expiry_time=self._mcp_expiry_time,
                )
            )
            if not _result_is_ok(add_result):
                message = (
                    f"OpenJiuwen failed to connect MCP server '{connection.name}': "
                    f"{_result_message(add_result)}"
                )
                if connection.required:
                    logger.error(
                        "OpenJiuwen required MCP server registration failed, request_id=%s, "
                        "server_name=%s",
                        plan.request_id,
                        connection.name,
                    )
                    raise OpenJiuwenToolMappingError(message)
                logger.warning(
                    "OpenJiuwen optional MCP server registration failed, request_id=%s, server_name=%s",
                    plan.request_id,
                    connection.name,
                )
                _append_runtime_warning(plan, message, server_name=connection.name)
                continue
            state.mcp_server_ids.append(str(getattr(mcp_config, "server_id", "")))
            logger.debug(
                "OpenJiuwen MCP server registered, request_id=%s, server_name=%s, "
                "server_id=%s, required=%s, allowlisted_tool_count=%d",
                plan.request_id,
                connection.name,
                getattr(mcp_config, "server_id", ""),
                connection.required,
                len([tool for tool in mcp_tools if tool.usage == connection.name]),
            )
            await self._register_allowed_mcp_tools(
                plan,
                dependencies,
                react_agent,
                event_sink,
                state,
                connection,
                str(getattr(mcp_config, "server_id", "")),
                [tool for tool in mcp_tools if tool.usage == connection.name],
            )

    async def _register_allowed_mcp_tools(
        self,
        plan: AgentRunPlan,
        dependencies: OpenJiuwenRuntimeDependencies,
        react_agent: Any,
        event_sink: Any,
        state: _OpenJiuwenRunState,
        connection: MCPConnectionConfig,
        server_id: str,
        tools: list[ToolSpec],
    ) -> None:
        get_mcp_tool = getattr(dependencies.Runner.resource_mgr, "get_mcp_tool", None)
        if not callable(get_mcp_tool):
            if tools and connection.required:
                logger.error(
                    "OpenJiuwen MCP tool lookup unavailable, request_id=%s, server_name=%s",
                    plan.request_id,
                    connection.name,
                )
                raise OpenJiuwenDependencyError(
                    "OpenJiuwen resource manager does not expose get_mcp_tool()."
                )
            logger.debug(
                "OpenJiuwen MCP tool lookup skipped, request_id=%s, server_name=%s, reason=no_get_mcp_tool",
                plan.request_id,
                connection.name,
            )
            return
        for tool in tools:
            tool_name = tool.class_name or tool.name
            try:
                native_result = await _maybe_await(
                    get_mcp_tool(
                        name=tool_name,
                        server_id=server_id,
                        ignore_exception=not connection.required,
                        session=state.session,
                    )
                )
                native_tool = _first_non_none(native_result)
                if native_tool is None:
                    raise OpenJiuwenToolMappingError(
                        f"MCP tool '{tool_name}' is not available on '{connection.name}'."
                    )
            except Exception as exc:
                if connection.required or bool(tool.metadata.get("required", False)):
                    logger.error(
                        "OpenJiuwen required MCP tool registration failed, request_id=%s, "
                        "server_name=%s, tool_name=%s, error_type=%s",
                        plan.request_id,
                        connection.name,
                        tool_name,
                        type(exc).__name__,
                    )
                    raise
                logger.warning(
                    "OpenJiuwen optional MCP tool registration failed, request_id=%s, "
                    "server_name=%s, tool_name=%s, error_type=%s",
                    plan.request_id,
                    connection.name,
                    tool_name,
                    type(exc).__name__,
                )
                _append_runtime_warning(
                    plan,
                    str(exc),
                    server_name=connection.name,
                    tool_name=tool_name,
                )
                continue

            tool_context = self._tool_runtime_context(
                plan, dependencies, event_sink, state
            )
            wrapped_native_tool = wrap_tool_with_runtime_events(
                native_tool,
                tool,
                tool_context,
            )
            openjiuwen_tool = self._to_openjiuwen_local_tool(
                tool,
                wrapped_native_tool,
                dependencies,
                request_id=plan.request_id,
            )
            await _maybe_await(
                dependencies.Runner.resource_mgr.add_tool(openjiuwen_tool, refresh=True)
            )
            state.tool_ids.append(str(getattr(openjiuwen_tool.card, "id", "")))
            _add_agent_ability(react_agent, openjiuwen_tool.card)
            logger.debug(
                "OpenJiuwen MCP tool registered, request_id=%s, server_name=%s, tool_name=%s",
                plan.request_id,
                connection.name,
                tool_name,
            )

    async def _register_plan_tools(
        self,
        plan: AgentRunPlan,
        dependencies: OpenJiuwenRuntimeDependencies,
        react_agent: Any,
        event_sink: Any,
        state: _OpenJiuwenRunState,
    ) -> None:
        visible_tools = [
            tool
            for tool in plan.root_agent.tools
            if tool.visibility != ToolVisibility.INTERNAL
            and _normalize_tool_source(tool.source) != ToolSource.MCP.value
        ]
        registry = self._tool_factory_registry or plan.runtime_resources.get(
            "tool_factory_registry"
        )
        if visible_tools and registry is None:
            registry = build_production_tool_factory_registry()
        if visible_tools and not isinstance(registry, ToolFactoryRegistry):
            raise OpenJiuwenToolMappingError(
                "OpenJiuwenRuntime requires a ToolFactoryRegistry for non-MCP tools."
            )

        logger.debug(
            "OpenJiuwen local tool registration starting, request_id=%s, visible_tool_count=%d, "
            "tool_source_counts=%s",
            plan.request_id,
            len(visible_tools),
            _tool_source_counts(plan),
        )
        for tool in visible_tools:
            tool_context = self._tool_runtime_context(
                plan, dependencies, event_sink, state
            )
            native_tool = registry.create(tool, tool_context)
            openjiuwen_tool = self._to_openjiuwen_local_tool(
                tool,
                native_tool,
                dependencies,
                request_id=plan.request_id,
            )
            await _maybe_await(
                dependencies.Runner.resource_mgr.add_tool(openjiuwen_tool, refresh=True)
            )
            state.tool_ids.append(str(getattr(openjiuwen_tool.card, "id", "")))
            _add_agent_ability(react_agent, openjiuwen_tool.card)
            logger.debug(
                "OpenJiuwen local tool registered, request_id=%s, tool_name=%s, source=%s",
                plan.request_id,
                tool.name,
                _normalize_tool_source(tool.source),
            )

    @staticmethod
    def _tool_runtime_context(
        plan: AgentRunPlan,
        dependencies: OpenJiuwenRuntimeDependencies,
        event_sink: Any,
        state: _OpenJiuwenRunState,
    ) -> ToolRuntimeContext:
        resources = {
            **dict(plan.runtime_resources),
            "openjiuwen.runner": dependencies.Runner,
            "sandbox.execution_spec": plan.sandbox_execution,
        }
        if state.sandbox_executor is not None:
            resources["skill.script_executor"] = state.sandbox_executor
        return ToolRuntimeContext(
            request_id=plan.request_id,
            agent_name=plan.root_agent.name,
            user_id=plan.run_control.user_id,
            tenant_id=str(plan.run_control.metadata.get("tenant_id") or ""),
            runtime_provider=plan.runtime_provider,
            event_sink=event_sink,
            run_control=plan.run_control,
            resources=resources,
        )

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

        sys_operation_id = _request_scoped_resource_id(
            plan.request_id, "sys_operation", "skills"
        )
        await self._register_sys_operation(plan, dependencies, sys_operation_id)
        state.sys_operation_ids.append(sys_operation_id)
        await self._add_read_file_ability(
            dependencies, bundle.react_agent, sys_operation_id
        )

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
            add_section = getattr(
                bundle.react_agent, "add_prompt_builder_section", None
            )
            if callable(add_section):
                add_section("nexent_native_skills", skill_prompt, priority=250)

    async def _prepare_session_context(
        self,
        plan: AgentRunPlan,
        dependencies: OpenJiuwenRuntimeDependencies,
        bundle: OpenJiuwenAgentBundle,
        state: _OpenJiuwenRunState,
    ) -> None:
        create_session = dependencies.create_agent_session
        if not callable(create_session):
            if bundle.history_messages:
                logger.error(
                    "OpenJiuwen session creation unavailable for history, request_id=%s, "
                    "history_message_count=%d",
                    plan.request_id,
                    len(bundle.history_messages),
                )
                raise OpenJiuwenDependencyError(
                    "OpenJiuwen public create_agent_session() is required for history."
                )
            logger.debug(
                "OpenJiuwen session creation skipped, request_id=%s, reason=no_create_agent_session",
                plan.request_id,
            )
            return
        session_id = _request_scoped_resource_id(plan.request_id, "session", "root")
        state.session = create_session(session_id=session_id, card=bundle.agent_card)
        context_engine = getattr(bundle.react_agent, "context_engine", None)
        if context_engine is None:
            context_engine = getattr(bundle.react_agent, "_context_engine", None)
        if context_engine is None and dependencies.ContextEngine is not None:
            context_engine = dependencies.ContextEngine(bundle.context_engine_config)
            _set_if_possible(bundle.react_agent, "context_engine", context_engine)
        if context_engine is None:
            if bundle.history_messages:
                logger.error(
                    "OpenJiuwen context engine unavailable for history, request_id=%s, "
                    "history_message_count=%d",
                    plan.request_id,
                    len(bundle.history_messages),
                )
                raise OpenJiuwenDependencyError(
                    "OpenJiuwen ContextEngine is required for history injection."
                )
            logger.debug(
                "OpenJiuwen context creation skipped, request_id=%s, reason=no_context_engine",
                plan.request_id,
            )
            return
        state.context_engine = context_engine
        state.context_id = "default_context_id"
        await _maybe_await(
            context_engine.create_context(
                context_id=state.context_id,
                session=state.session,
                history_messages=list(bundle.history_messages),
            )
        )

    async def _register_sys_operation(
        self,
        plan: AgentRunPlan,
        dependencies: OpenJiuwenRuntimeDependencies,
        sys_operation_id: str,
    ) -> None:
        if (
            dependencies.SysOperationCard is None
            or dependencies.LocalWorkConfig is None
        ):
            raise OpenJiuwenDependencyError(
                "OpenJiuwen SysOperation dependencies are not available."
            )
        resource_config = dict(
            plan.runtime_resources.get("openjiuwen.sys_operation") or {}
        )
        local_work_config = dependencies.LocalWorkConfig(
            sandbox_root=resource_config.get("sandbox_root"),
            restrict_to_sandbox=bool(resource_config.get("restrict_to_sandbox", False)),
            shell_allowlist=resource_config.get("shell_allowlist"),
        )
        mode = (
            dependencies.OperationMode.LOCAL
            if dependencies.OperationMode is not None
            else "local"
        )
        sys_operation_card = dependencies.SysOperationCard(
            id=sys_operation_id,
            name="nexent_skill_sys_operation",
            description="Request-scoped system operation for OpenJiuwen skills.",
            mode=mode,
            work_config=local_work_config,
        )
        await _maybe_await(
            dependencies.Runner.resource_mgr.add_sys_operation(sys_operation_card)
        )

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
        generate_tool_id = getattr(
            dependencies.SysOperationCard, "generate_tool_id", None
        )
        if callable(get_tool) and callable(generate_tool_id):
            tool = get_tool(generate_tool_id(sys_operation_id, "fs", "read_file"))
            card = getattr(tool, "card", None)
            if card is not None:
                _add_agent_ability(react_agent, card)
                return
        raise OpenJiuwenRuntimeError(
            "OpenJiuwen native skill prompt requires read_file tool."
        )

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
        *,
        session: Any | None = None,
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
            stream_result = _call_with_optional_session(stream, inputs, session=session)
            async for chunk in stream_result:
                yield chunk
            return

        invoke = getattr(react_agent, "invoke", None)
        runner_run_agent = getattr(dependencies.Runner, "run_agent", None)
        if callable(invoke):
            result = await _maybe_await(
                _call_with_optional_session(invoke, inputs, session=session)
            )
        elif callable(runner_run_agent):
            result = await _maybe_await(runner_run_agent(react_agent, inputs))
        else:
            raise OpenJiuwenRuntimeError(
                "OpenJiuwen ReActAgent does not expose invoke or stream."
            )
        yield {
            "type": "answer",
            "payload": {
                "output": _first_present(
                    _model_dump(result), "output", "content", default=result
                ),
                "result_type": _first_present(
                    _model_dump(result), "result_type", default="answer"
                ),
            },
        }

    def _select_model_config(
        self, plan: AgentRunPlan, agent: AgentSpec
    ) -> dict[str, Any]:
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
            _first_present(
                model_config, "model_name", "model", default=agent.model_name
            )
            or agent.model_name
        )
        max_tokens = _first_present(
            model_config,
            "max_output_tokens",
            "max_tokens",
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
            "client_provider": "NexentOpenAI",
            "api_key": _first_present(model_config, "api_key", default=""),
            "api_base": _first_present(
                model_config, "api_base", "url", "base_url", default=""
            ),
            "timeout": _first_present(
                model_config,
                "timeout",
                "timeout_seconds",
                default=60.0,
            ),
            "verify_ssl": _first_present(
                model_config, "verify_ssl", "ssl_verify", default=True
            ),
            "ssl_cert": _first_present(
                model_config, "ssl_cert", "ca_cert", default=None
            ),
            "custom_headers": _first_present(
                model_config, "custom_headers", "headers", default=None
            ),
        }
        return dependencies.ModelClientConfig(**_drop_none_values(client_kwargs))

    def _to_prompt_template(self, agent: AgentSpec) -> list[dict[str, Any]]:
        prompt = agent.prompt
        if not prompt.fragments:
            raise OpenJiuwenUnsupportedFeatureError(
                "OpenJiuwenRuntime requires neutral prompt fragments."
            )
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
            content = _flatten_history_content(data.get("content", ""))
            message_cls = _message_class_for_role(role, dependencies)
            if message_cls is None:
                continue
            messages.append(message_cls(content=content))
        return messages

    async def _cleanup_state(self, state: _OpenJiuwenRunState) -> None:
        if state.cleaned:
            logger.debug(
                "OpenJiuwen cleanup skipped, request_id=%s, reason=already_cleaned",
                state.request_id,
            )
            return
        state.cleaned = True
        logger.debug(
            "OpenJiuwen cleanup starting, request_id=%s, registered_mcp_count=%d, registered_tool_count=%d, "
            "registered_sys_operation_count=%d, has_session=%s, has_context_engine=%s",
            state.request_id,
            len(state.mcp_server_ids),
            len(state.tool_ids),
            len(state.sys_operation_ids),
            state.session is not None,
            state.context_engine is not None,
        )
        resource_mgr = getattr(state.runner, "resource_mgr", None)
        if resource_mgr is not None and state.tool_ids:
            remove_tool = getattr(resource_mgr, "remove_tool", None)
            if callable(remove_tool):
                await _call_cleanup(remove_tool, tool_id=list(state.tool_ids))
        if resource_mgr is not None:
            for server_id in list(state.mcp_server_ids):
                remove_mcp_server = getattr(resource_mgr, "remove_mcp_server", None)
                if callable(remove_mcp_server):
                    await _call_cleanup(
                        remove_mcp_server,
                        server_id=server_id,
                        ignore_exception=True,
                    )
        for sys_operation_id in list(state.sys_operation_ids):
            if resource_mgr is None:
                break
            remove_sys_operation = getattr(resource_mgr, "remove_sys_operation", None)
            if callable(remove_sys_operation):
                await _call_cleanup(
                    remove_sys_operation, sys_operation_id=sys_operation_id
                )
        if state.context_engine is not None and state.session is not None:
            clear_context = getattr(state.context_engine, "clear_context", None)
            if callable(clear_context):
                await _call_cleanup(
                    clear_context,
                    context_id=state.context_id,
                    session_id=state.session.get_session_id(),
                )
        if state.session is not None:
            post_run = getattr(state.session, "post_run", None)
            if callable(post_run):
                await _call_cleanup(post_run)
        logger.debug(
            "OpenJiuwen cleanup finished, request_id=%s, registered_mcp_count=%d, registered_tool_count=%d, "
            "registered_sys_operation_count=%d",
            state.request_id,
            len(state.mcp_server_ids),
            len(state.tool_ids),
            len(state.sys_operation_ids),
        )


def _load_openjiuwen_dependencies() -> OpenJiuwenRuntimeDependencies:
    try:
        from adapters.openjiuwen_compat import load_openjiuwen_public_api

        api = load_openjiuwen_public_api()
    except Exception as exc:
        raise OpenJiuwenDependencyError(
            f"OpenJiuwenRuntime requires compatible OpenJiuwen 0.1.15 APIs: {exc}"
        ) from exc

    return OpenJiuwenRuntimeDependencies(
        AgentCard=api.AgentCard,
        ReActAgentConfig=api.ReActAgentConfig,
        ReActAgent=api.ReActAgent,
        ModelRequestConfig=api.ModelRequestConfig,
        ModelClientConfig=api.ModelClientConfig,
        McpServerConfig=api.McpServerConfig,
        ToolCard=api.ToolCard,
        LocalFunction=api.LocalFunction,
        ContextEngineConfig=api.ContextEngineConfig,
        Runner=api.Runner,
        UserMessage=api.UserMessage,
        AssistantMessage=api.AssistantMessage,
        SystemMessage=api.SystemMessage,
        ToolMessage=api.ToolMessage,
        ContextEngine=api.ContextEngine,
        create_agent_session=api.create_agent_session,
        NexentOpenAIModelClient=api.NexentOpenAIModelClient,
    )


def _elapsed_ms(started_at: float) -> int:
    return int((time.monotonic() - started_at) * 1000)


def _sorted_capabilities(values: Any) -> list[str]:
    return sorted(str(value) for value in (values or []))


def _visible_tool_count(plan: AgentRunPlan) -> int:
    return sum(
        1 for tool in plan.root_agent.tools if tool.visibility != ToolVisibility.INTERNAL
    )


def _tool_source_counts(plan: AgentRunPlan) -> dict[str, int]:
    counts: dict[str, int] = {}
    for tool in plan.root_agent.tools:
        if tool.visibility == ToolVisibility.INTERNAL:
            continue
        source = _normalize_tool_source(tool.source)
        counts[source] = counts.get(source, 0) + 1
    return dict(sorted(counts.items()))


def _sandbox_error_metadata(exc: Exception) -> dict[str, str]:
    """Return a safe sandbox stage without exposing endpoint or path details."""
    if not isinstance(exc, OpenJiuwenSandboxError):
        return {}
    return {"sandbox_stage": exc.stage}


def _render_prompt_fragments(fragments: Mapping[str, Any]) -> str:
    sections: list[str] = []
    consumed: set[str] = set()
    ordered_keys = (
        "identity",
        "app_identity",
        "duty",
        "constraint",
        "constraints",
        "few_shots",
        "few-shot",
        "knowledge_base_summary",
        "knowledge",
        "memory_list",
        "memory",
        "skills",
        "skill",
        "runtime_instructions",
        "instructions",
    )
    for key in ordered_keys:
        if key not in fragments or key in consumed:
            continue
        value = fragments[key]
        if value in (None, "", [], {}):
            continue
        sections.append(f"[{key}]\n{_format_prompt_value(value)}")
        consumed.add(key)
    return "\n\n".join(sections)


def _format_prompt_value(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _flatten_history_content(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            if isinstance(item, Mapping) and isinstance(item.get("text"), str):
                parts.append(item["text"])
            elif isinstance(item, Mapping) and "content" in item:
                parts.append(str(item["content"]))
            else:
                parts.append(str(item))
        return "".join(parts)
    return "" if value is None else str(value)


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
            key: item for key, item in vars(value).items() if not key.startswith("_")
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
    explicit_extra_body = model_config.get("extra_body")
    if isinstance(explicit_extra_body, Mapping):
        return {"extra_body": dict(explicit_extra_body)}
    for key in ("model_params", "extra_params", "extra"):
        value = model_config.get(key)
        if isinstance(value, Mapping):
            return {"extra_body": dict(value)}
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
    return tool_input_schema_to_json_schema(input_schema)


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
        raise OpenJiuwenRuntimeError(
            "OpenJiuwen ReActAgent does not expose ability_manager.add()."
        )
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


def _construct_with_supported_kwargs(factory: Any, kwargs: dict[str, Any]) -> Any:
    """Construct SDK or injected fake classes without losing supported fields."""
    try:
        signature = inspect.signature(factory)
    except (TypeError, ValueError):
        return factory(**kwargs)
    accepts_kwargs = any(
        parameter.kind == inspect.Parameter.VAR_KEYWORD
        for parameter in signature.parameters.values()
    )
    if accepts_kwargs:
        return factory(**kwargs)
    supported = {
        key: value for key, value in kwargs.items() if key in signature.parameters
    }
    return factory(**supported)


def _set_if_possible(target: Any, name: str, value: Any) -> None:
    try:
        setattr(target, name, value)
    except Exception:
        pass


def _call_with_optional_session(callable_obj: Any, inputs: Any, *, session: Any) -> Any:
    if session is None:
        return callable_obj(inputs)
    try:
        signature = inspect.signature(callable_obj)
    except (TypeError, ValueError):
        return callable_obj(inputs, session=session)
    if "session" in signature.parameters:
        return callable_obj(inputs, session=session)
    return callable_obj(inputs)


def _result_is_ok(result: Any) -> bool:
    if result is None:
        return True
    is_ok = getattr(result, "is_ok", None)
    if callable(is_ok):
        return bool(is_ok())
    return bool(result)


def _result_message(result: Any) -> str:
    if result is None:
        return "unknown error"
    message = getattr(result, "msg", None)
    if callable(message):
        return str(message())
    return str(result)


def _first_non_none(value: Any) -> Any | None:
    if isinstance(value, list | tuple):
        return next((item for item in value if item is not None), None)
    return value


def _append_runtime_warning(plan: AgentRunPlan, message: str, **metadata: Any) -> None:
    warnings = plan.monitoring_metadata.setdefault("runtime_warnings", [])
    warnings.append({"message": message, **metadata})
