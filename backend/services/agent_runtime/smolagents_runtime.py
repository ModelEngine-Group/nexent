"""Smolagents runtime adapter preserving the legacy SDK execution path."""

from __future__ import annotations

import json
import threading
from collections.abc import AsyncIterator, Callable, Mapping
from dataclasses import fields, is_dataclass
from functools import lru_cache
from typing import Any

from consts.const import AGENT_RUNTIME_PROVIDER_SMOLAGENTS, MINIO_DEFAULT_BUCKET

from .models import (
    AgentRunPlan,
    AgentSpec,
    ContextMode,
    ContextPolicy,
    MCPConnectionConfig,
    RuntimeCapabilities,
    RunControl,
    ToolSpec,
)
from .events import emit_runtime_event, runtime_event_from_legacy_observer_message
from .operators import OperatorContext, OperatorRegistry, OperatorRunner, default_operator_registry


AgentRunCallable = Callable[[Any], AsyncIterator[Any]]
ContextManagerResolver = Callable[[Any, Any, int], Any]


def _default_agent_run(agent_run_info: Any) -> AsyncIterator[Any]:
    from nexent.core.agents.run_agent import agent_run

    return agent_run(agent_run_info)


@lru_cache(maxsize=1)
def _legacy_agent_models() -> dict[str, Any]:
    from nexent.core.agents.agent_model import (
        AgentConfig,
        AgentHistory,
        AgentRunInfo,
        AgentVerificationConfig,
        ExternalA2AAgentConfig,
        ModelConfig,
        ToolConfig,
    )
    from nexent.core.agents.summary_config import ContextManagerConfig
    from nexent.core.utils.observer import MessageObserver

    return {
        "AgentConfig": AgentConfig,
        "AgentHistory": AgentHistory,
        "AgentRunInfo": AgentRunInfo,
        "AgentVerificationConfig": AgentVerificationConfig,
        "ExternalA2AAgentConfig": ExternalA2AAgentConfig,
        "ModelConfig": ModelConfig,
        "ToolConfig": ToolConfig,
        "ContextManagerConfig": ContextManagerConfig,
        "MessageObserver": MessageObserver,
    }


class SmolagentsRuntime:
    """Default runtime adapter preserving the current smolagents path."""

    name = AGENT_RUNTIME_PROVIDER_SMOLAGENTS
    capabilities = RuntimeCapabilities(
        streaming=True,
        token_streaming=True,
        reasoning_streaming=True,
        process_type_compatibility="complete",
        mcp=True,
        managed_agents=True,
        external_a2a_agents=True,
        code_execution=True,
        tool_artifacts=True,
        context_compression=True,
        tool_call_events=True,
        token_usage_events=True,
        interruptible=True,
        resumable_stream=True,
    )

    def __init__(
        self,
        agent_run_func: AgentRunCallable | None = None,
        context_manager_resolver: ContextManagerResolver | None = None,
        operator_registry: OperatorRegistry | None = None,
    ):
        self._agent_run_func = agent_run_func or _default_agent_run
        self._context_manager_resolver = context_manager_resolver
        self._operator_registry = operator_registry or default_operator_registry()
        self._active_runs: dict[str, tuple[Any, RunControl]] = {}
        self._lock = threading.Lock()

    async def run(self, plan: AgentRunPlan, event_sink: Any = None) -> AsyncIterator[Any]:
        """Execute a smolagents run by delegating to the legacy agent_run path."""
        agent_run_info = self.to_agent_run_info(plan, event_sink)
        with self._lock:
            self._active_runs[plan.request_id] = (agent_run_info, plan.run_control)
        try:
            async for chunk in self._agent_run_func(agent_run_info):
                event = runtime_event_from_legacy_observer_message(
                    chunk,
                    request_id=plan.request_id,
                )
                await self._run_observable_operator_stages(
                    plan,
                    event,
                    event_sink,
                    timing="before",
                )
                await emit_runtime_event(
                    event_sink,
                    event,
                )
                await self._run_observable_operator_stages(
                    plan,
                    event,
                    event_sink,
                    timing="after",
                )
                yield chunk
        finally:
            with self._lock:
                self._active_runs.pop(plan.request_id, None)
            self._reconcile_stop_state(agent_run_info, plan.run_control)

    async def _run_observable_operator_stages(
        self,
        plan: AgentRunPlan,
        event: Any,
        event_sink: Any,
        *,
        timing: str,
    ) -> None:
        """Run model/tool/final-answer operators at legacy observer boundaries."""
        stages = _observable_operator_stages(event, timing=timing)
        for stage in stages:
            context = OperatorContext.from_plan(
                stage=stage,
                plan=plan,
                step_number=event.step_number,
                model_output=event.content,
                tool_input=event.tool_input,
                tool_output=event.tool_output if event.tool_output is not None else event.content,
                final_answer=event.content if event.compat_process_type == "final_answer" else None,
                runtime_events=[event],
            )
            result = await OperatorRunner(self._operator_registry).run_stage(
                stage,
                context,
                plan.operators,
            )
            for generated_event in context.runtime_events[1:]:
                await emit_runtime_event(event_sink, generated_event)
            if result.status == "blocking_failure":
                message = _operator_stage_failure_message(stage, result)
                raise RuntimeError(message)

    async def stop(self, request_id: str) -> None:
        """Cancel a smolagents run through the request-scoped stop event."""
        with self._lock:
            active_run = self._active_runs.get(request_id)
        if active_run is None:
            return
        agent_run_info, run_control = active_run
        run_control.cancel()
        agent_run_info.stop_event.set()

    def to_agent_run_info(
        self,
        plan: AgentRunPlan,
        event_sink: Any = None,
    ) -> Any:
        """Map the neutral run plan back to the SDK AgentRunInfo contract."""
        legacy_models = _legacy_agent_models()
        stop_event = self._ensure_legacy_stop_event(plan.run_control)
        agent_config = self.to_agent_config(plan.root_agent, plan=plan)
        context_manager = self._resolve_context_manager(
            plan.run_control,
            agent_config,
        )
        observer = self._resolve_observer(event_sink, plan)

        return legacy_models["AgentRunInfo"](
            query=plan.query,
            model_config_list=[
                self._to_model_config(model_config)
                for model_config in plan.model_config_list
            ],
            observer=observer,
            agent_config=agent_config,
            mcp_host=[self._to_mcp_host(connection) for connection in plan.mcp_connections],
            history=self._to_agent_history(plan.history),
            stop_event=stop_event,
            context_manager=context_manager,
            capacity_snapshot=self._capacity_snapshot(plan, plan.root_agent),
            safe_input_budget_snapshot=self._safe_input_budget_snapshot(
                plan,
                plan.root_agent,
            ),
        )

    def to_agent_config(
        self,
        agent: AgentSpec,
        *,
        plan: AgentRunPlan | None = None,
    ) -> Any:
        """Map a neutral AgentSpec to the legacy SDK AgentConfig."""
        legacy_models = _legacy_agent_models()
        context_manager_config = self._to_context_manager_config(agent.context_policy)
        capacity_snapshot = self._capacity_snapshot(plan, agent)
        safe_input_budget_snapshot = self._safe_input_budget_snapshot(plan, agent)

        return legacy_models["AgentConfig"](
            name=agent.name or "undefined",
            description=agent.description or "undefined",
            prompt_templates=self._to_prompt_templates(agent),
            tools=[self._to_tool_config(tool) for tool in agent.tools],
            max_steps=agent.max_steps,
            requested_output_tokens=agent.runtime_hints.get("requested_output_tokens"),
            model_name=agent.model_name,
            provide_run_summary=bool(agent.runtime_hints.get("provide_run_summary", False)),
            instructions=agent.runtime_hints.get("instructions"),
            managed_agents=[
                self.to_agent_config(managed_agent, plan=None)
                for managed_agent in agent.managed_agents
            ],
            external_a2a_agents=[
                self._to_external_a2a_agent_config(external_agent)
                for external_agent in agent.external_a2a_agents
            ],
            context_manager_config=context_manager_config,
            context_components=list(agent.prompt.context_components),
            capacity_snapshot=capacity_snapshot,
            safe_input_budget_snapshot=safe_input_budget_snapshot,
            verification_config=self._to_verification_config(agent.verification_config),
        )

    @staticmethod
    def _ensure_legacy_stop_event(run_control: RunControl) -> threading.Event:
        stop_event = run_control.legacy_stop_event
        if stop_event is None:
            stop_event = threading.Event()
            run_control.legacy_stop_event = stop_event
        if run_control.cancelled:
            stop_event.set()
        return stop_event

    @staticmethod
    def _reconcile_stop_state(
        agent_run_info: Any,
        run_control: RunControl,
    ) -> None:
        if agent_run_info.stop_event.is_set():
            run_control.cancelled = True

    @staticmethod
    def _resolve_observer(event_sink: Any, plan: AgentRunPlan) -> Any:
        message_observer = _legacy_agent_models()["MessageObserver"]
        if isinstance(event_sink, message_observer):
            return event_sink
        observer = plan.runtime_resources.get("smolagents.observer")
        if isinstance(observer, message_observer):
            return observer
        language = (
            plan.monitoring_metadata.get("language")
            or plan.run_control.metadata.get("language")
            or "zh"
        )
        return message_observer(lang=str(language))

    @staticmethod
    def _to_model_config(model_config: Any) -> Any:
        model_config_class = _legacy_agent_models()["ModelConfig"]
        if isinstance(model_config, model_config_class):
            return model_config
        data = _model_dump(model_config)
        return model_config_class.model_validate(data)

    @staticmethod
    def _to_tool_config(tool: ToolSpec) -> Any:
        tool_config_class = _legacy_agent_models()["ToolConfig"]
        inputs = tool.raw_inputs
        if inputs is None:
            inputs = json.dumps(tool.input_schema or {}, ensure_ascii=False)
        source = tool.source.value if hasattr(tool.source, "value") else str(tool.source)
        return tool_config_class(
            class_name=tool.class_name or tool.name,
            name=tool.name,
            description=tool.description,
            inputs=inputs,
            output_type=tool.output_type,
            params=dict(tool.params),
            source=source,
            usage=tool.usage,
            metadata=dict(tool.metadata or {}),
        )

    @staticmethod
    def _to_prompt_templates(agent: AgentSpec) -> dict[str, Any] | None:
        templates = dict(agent.prompt.templates or {})
        if agent.prompt.rendered_legacy_system_prompt is not None:
            templates["system_prompt"] = agent.prompt.rendered_legacy_system_prompt
        return templates or None

    @staticmethod
    def _to_context_manager_config(policy: ContextPolicy) -> Any:
        context_manager_config_class = _legacy_agent_models()["ContextManagerConfig"]
        if policy.mode == ContextMode.RUNTIME_NATIVE:
            raise ValueError(
                "SmolagentsRuntime does not support runtime_native context policy."
            )

        default_config = context_manager_config_class()
        config = context_manager_config_class(
            enabled=policy.mode == ContextMode.MANAGED,
            token_threshold=policy.token_threshold
            if policy.token_threshold is not None
            else default_config.token_threshold,
            soft_input_budget_tokens=policy.soft_input_budget_tokens or 0,
            hard_input_budget_tokens=policy.hard_input_budget_tokens or 0,
        )
        _apply_context_compression(config, policy.compression)
        return config

    @staticmethod
    def _to_external_a2a_agent_config(agent: Any) -> Any:
        external_config_class = _legacy_agent_models()["ExternalA2AAgentConfig"]
        if isinstance(agent, external_config_class):
            return agent
        data = _model_dump(agent)
        agent_id = data.get("agent_id") or data.get("external_agent_id") or data.get("id") or ""
        data["agent_id"] = str(agent_id)
        data.setdefault("name", data.get("agent_name") or data["agent_id"] or "Unknown")
        data.setdefault("description", "")
        data.setdefault("url", data.get("agent_url") or "")
        data.setdefault("api_key", None)
        return external_config_class.model_validate(data)

    @staticmethod
    def _to_verification_config(config: Any) -> Any:
        verification_config_class = _legacy_agent_models()["AgentVerificationConfig"]
        if isinstance(config, verification_config_class):
            return config
        if config is None:
            return verification_config_class()
        return verification_config_class.model_validate(_model_dump(config))

    @staticmethod
    def _to_mcp_host(connection: MCPConnectionConfig) -> dict[str, Any]:
        data: dict[str, Any] = {
            "url": connection.url,
            "transport": connection.transport,
        }
        if connection.headers:
            data["headers"] = dict(connection.headers)
        return data

    @staticmethod
    def _to_agent_history(history: list[Any] | None) -> list[Any] | None:
        if history is None:
            return None
        agent_history_class = _legacy_agent_models()["AgentHistory"]
        converted_history: list[Any] = []
        for item in history:
            if isinstance(item, agent_history_class):
                converted_history.append(item)
                continue
            data = _model_dump(item)
            content = data.get("content", "")
            file_description = _format_minio_files_for_content(data.get("minio_files"))
            if file_description:
                content = f"{content}{file_description}" if content else file_description
            converted_history.append(
                agent_history_class(
                    role=str(data.get("role") or "user"),
                    content=str(content),
                )
            )
        return converted_history

    @staticmethod
    def _capacity_snapshot(
        plan: AgentRunPlan | None,
        agent: AgentSpec,
    ) -> dict[str, Any] | None:
        value = agent.runtime_hints.get("capacity_snapshot")
        if value is None and plan is not None:
            value = plan.monitoring_metadata.get("model.capacity_snapshot")
        return dict(value) if isinstance(value, Mapping) else value

    @staticmethod
    def _safe_input_budget_snapshot(
        plan: AgentRunPlan | None,
        agent: AgentSpec,
    ) -> dict[str, Any] | None:
        value = agent.runtime_hints.get("safe_input_budget_snapshot")
        if value is None and plan is not None:
            value = plan.monitoring_metadata.get("model.safe_input_budget_snapshot")
        return dict(value) if isinstance(value, Mapping) else value

    def _resolve_context_manager(
        self,
        run_control: RunControl,
        agent_config: Any,
    ) -> Any | None:
        config = agent_config.context_manager_config
        if not getattr(config, "enabled", False):
            return None
        if run_control.conversation_id is None:
            return None
        if self._context_manager_resolver is not None:
            return self._context_manager_resolver(
                run_control.conversation_id,
                config,
                agent_config.max_steps,
            )
        from agents.agent_run_manager import agent_run_manager

        return agent_run_manager.get_or_create_context_manager(
            run_control.conversation_id,
            config,
            agent_config.max_steps,
        )


def _apply_context_compression(
    config: Any,
    compression: Mapping[str, Any] | None,
) -> None:
    if not compression:
        return
    allowed_fields = {field.name for field in fields(config)}
    for key, value in compression.items():
        if key in allowed_fields:
            setattr(config, key, value)


def _model_dump(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, Mapping):
        return dict(value)
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if is_dataclass(value):
        return {
            field.name: getattr(value, field.name)
            for field in fields(value)
        }
    return dict(vars(value))


def _format_minio_files_for_content(minio_files: Any, max_files: int = 20) -> str:
    if not minio_files or not isinstance(minio_files, list):
        return ""

    file_lines: list[str] = []
    for index, file_info in enumerate(minio_files):
        if index >= max_files:
            file_lines.append(f"  - ... (and {len(minio_files) - max_files} more files)")
            break
        if not isinstance(file_info, Mapping):
            continue
        file_name = file_info.get("name")
        object_name = str(file_info.get("object_name") or "").strip().lstrip("/")
        url = str(file_info.get("url") or "").strip()
        if not file_name or not (object_name or url):
            continue
        if object_name:
            bucket = MINIO_DEFAULT_BUCKET or "nexent"
            file_url = f"s3://{bucket}/{object_name}"
        else:
            file_url = url
        presigned_url = file_info.get("presigned_url")
        if presigned_url:
            file_lines.append(
                f"  - {file_name}: {file_url} (for non-MCP tools), "
                f"presigned_url: {presigned_url} (for [MCP] tools)"
            )
        else:
            file_lines.append(f"  - {file_name}: {file_url}")

    if not file_lines:
        return ""
    return "\n[Attached files]:\n" + "\n".join(file_lines)


def _observable_operator_stages(event: Any, *, timing: str) -> tuple[str, ...]:
    process_type = event.compat_process_type
    if timing == "before":
        if process_type == "step_count":
            return ("before_model_call",)
        if process_type in {"parse", "tool"}:
            return ("before_tool_call",)
        if process_type == "final_answer":
            return ("before_final_answer",)
        return ()

    if process_type in {
        "model_output_code",
        "model_output_thinking",
        "model_output_deep_thinking",
    }:
        return ("after_model_call",)
    if process_type == "execution_logs":
        return ("after_tool_call",)
    return ()


def _operator_stage_failure_message(stage: str, result: Any) -> str:
    for operator_result in reversed(result.results):
        if operator_result.status == "blocking_failure" and operator_result.message:
            return f"Operator stage '{stage}' failed: {operator_result.message}"
    return f"Operator stage '{stage}' failed."
