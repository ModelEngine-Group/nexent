"""Operator lifecycle framework for runtime middleware."""

from __future__ import annotations

import inspect
import json
import os
from collections.abc import Callable, Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from .events import RuntimeEvent, RuntimeEventType
from .models import (
    AgentRunPlan,
    AgentRunRequestContext,
    MCPConnectionConfig,
    OperatorSpec,
    ToolSpec,
    ToolSource,
)


OperatorStage = Literal[
    "before_run",
    "prepare_context",
    "before_model_call",
    "after_model_call",
    "before_tool_call",
    "after_tool_call",
    "before_final_answer",
    "after_run",
    "on_error",
]

OperatorStatus = Literal["ok", "soft_failure", "blocking_failure"]

OPERATOR_STAGES: tuple[OperatorStage, ...] = (
    "before_run",
    "prepare_context",
    "before_model_call",
    "after_model_call",
    "before_tool_call",
    "after_tool_call",
    "before_final_answer",
    "after_run",
    "on_error",
)

ALLOWED_CONTEXT_PATCH_KEYS = {
    "prompt_fragments",
    "context_components",
    "tools",
    "runtime_resources",
    "monitoring_metadata",
    "metadata",
}

FORBIDDEN_CONTEXT_PATCH_KEYS = {
    "request_id",
    "runtime_provider",
    "agent_id",
    "conversation_id",
    "user_id",
    "tenant_id",
    "run_control",
}


class OperatorError(ValueError):
    """Base error for operator framework failures."""


class DuplicateOperatorError(OperatorError):
    """Raised when an operator is registered twice."""


class UnknownOperatorError(OperatorError):
    """Raised when an operator spec cannot be resolved."""


class OperatorPatchError(OperatorError):
    """Raised when an operator returns an illegal context patch."""


class OperatorContext(BaseModel):
    """Mutable context passed to lifecycle operators."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    stage: OperatorStage
    request: AgentRunRequestContext | None = None
    plan: AgentRunPlan | None = None
    agent_name: str | None = None
    step_number: int | None = None
    model_input: Any | None = None
    model_output: Any | None = None
    tool_input: Any | None = None
    tool_output: Any | None = None
    final_answer: Any | None = None
    error: Any | None = None
    tools: list[ToolSpec] = Field(default_factory=list)
    prompt_fragments: dict[str, Any] = Field(default_factory=dict)
    context_components: list[Any] = Field(default_factory=list)
    runtime_resources: dict[str, Any] = Field(default_factory=dict)
    monitoring_metadata: dict[str, Any] = Field(default_factory=dict)
    runtime_events: list[RuntimeEvent] = Field(default_factory=list)
    added_tools: list[ToolSpec] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_plan(
        cls,
        *,
        stage: OperatorStage,
        plan: AgentRunPlan,
        request: AgentRunRequestContext | None = None,
        **overrides: Any,
    ) -> "OperatorContext":
        """Create an operator context from a run plan snapshot."""
        prompt_fragments = dict(plan.root_agent.prompt.fragments)
        context_components = list(plan.root_agent.prompt.context_components)
        payload = {
            "stage": stage,
            "request": request,
            "plan": plan,
            "agent_name": plan.root_agent.name,
            "tools": list(plan.root_agent.tools),
            "prompt_fragments": prompt_fragments,
            "context_components": context_components,
            "runtime_resources": dict(plan.runtime_resources),
            "monitoring_metadata": dict(plan.monitoring_metadata),
            "runtime_events": [],
        }
        payload.update(overrides)
        return cls(**payload)


class OperatorResult(BaseModel):
    """Result returned by one lifecycle operator."""

    status: OperatorStatus = "ok"
    context_patch: dict[str, Any] = Field(default_factory=dict)
    added_tools: list[ToolSpec] = Field(default_factory=list)
    added_context_components: list[Any] = Field(default_factory=list)
    added_metadata: dict[str, Any] = Field(default_factory=dict)
    runtime_events: list[RuntimeEvent] = Field(default_factory=list)
    message: str | None = None

    @classmethod
    def ok(cls, **kwargs: Any) -> "OperatorResult":
        """Build an ok result."""
        return cls(status="ok", **kwargs)

    @classmethod
    def soft_failure(cls, message: str, **kwargs: Any) -> "OperatorResult":
        """Build a recoverable failure result."""
        return cls(status="soft_failure", message=message, **kwargs)

    @classmethod
    def blocking_failure(cls, message: str, **kwargs: Any) -> "OperatorResult":
        """Build a blocking failure result."""
        return cls(status="blocking_failure", message=message, **kwargs)


class OperatorStageResult(BaseModel):
    """Aggregate result for a lifecycle stage."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    status: OperatorStatus = "ok"
    context: OperatorContext
    executed: list[str] = Field(default_factory=list)
    skipped: list[str] = Field(default_factory=list)
    results: list[OperatorResult] = Field(default_factory=list)
    diagnostics: list[dict[str, Any]] = Field(default_factory=list)


class RuntimeOperator(Protocol):
    """Runtime operator instance created from an OperatorSpec."""

    spec: OperatorSpec

    def supports(self, context: OperatorContext) -> bool:
        """Return whether this operator should run for the context."""
        ...

    def execute(self, context: OperatorContext) -> OperatorResult:
        """Execute the operator."""
        ...


OperatorFactory = Callable[[OperatorSpec], RuntimeOperator]


class OperatorRegistry:
    """Registry creating operator instances from declarative specs."""

    def __init__(self, factories: dict[str, OperatorFactory] | None = None):
        self._factories: dict[str, OperatorFactory] = {}
        for name, factory in (factories or {}).items():
            self.register(name, factory)

    def register(self, name: str, factory: OperatorFactory) -> None:
        """Register an operator factory."""
        operator_name = _normalize_operator_name(name)
        if operator_name in self._factories:
            raise DuplicateOperatorError(f"Duplicate operator name: {operator_name}.")
        self._factories[operator_name] = factory

    def create(self, spec: OperatorSpec) -> RuntimeOperator:
        """Create an operator for a spec."""
        operator_name = _normalize_operator_name(spec.name)
        factory = self._factories.get(operator_name)
        if factory is None:
            raise UnknownOperatorError(f"Unknown operator: {operator_name}.")
        return factory(spec)

    def list_operators(self) -> list[str]:
        """Return registered operator names."""
        return sorted(self._factories)


class OperatorRunner:
    """Execute lifecycle operators serially for one stage."""

    def __init__(self, registry: OperatorRegistry):
        self.registry = registry

    async def run_stage(
        self,
        stage: OperatorStage,
        context: OperatorContext,
        operator_specs: Iterable[OperatorSpec],
        *,
        _handling_error: bool = False,
    ) -> OperatorStageResult:
        """Run matching operators for a stage in priority order."""
        context.stage = stage
        aggregate = OperatorStageResult(context=context)
        for spec in _sorted_operator_specs(operator_specs):
            if stage not in spec.stages:
                aggregate.skipped.append(spec.name)
                continue

            operator = self.registry.create(spec)
            if not operator.supports(context):
                aggregate.skipped.append(spec.name)
                continue

            result = operator.execute(context)
            if inspect.isawaitable(result):
                result = await result
            aggregate.executed.append(spec.name)
            aggregate.results.append(result)

            try:
                _apply_operator_result(context, spec, result)
            except OperatorPatchError as exc:
                result = OperatorResult.blocking_failure(str(exc))
                aggregate.results[-1] = result
                _record_operator_diagnostic(context, spec, result)

            aggregate.diagnostics.append(_operator_diagnostic(spec, result))
            if result.status == "soft_failure" and aggregate.status == "ok":
                aggregate.status = "soft_failure"
            if result.status == "blocking_failure":
                aggregate.status = "blocking_failure"
                if not _handling_error and stage != "on_error":
                    # Preserve request-scoped handles by identity while isolating
                    # the mutable containers used by on_error operators.
                    on_error_context = context.model_copy(
                        update={
                            "stage": "on_error",
                            "error": result.message,
                            "tools": list(context.tools),
                            "prompt_fragments": dict(context.prompt_fragments),
                            "context_components": list(context.context_components),
                            "runtime_resources": dict(context.runtime_resources),
                            "monitoring_metadata": dict(context.monitoring_metadata),
                            "runtime_events": list(context.runtime_events),
                            "added_tools": list(context.added_tools),
                            "metadata": dict(context.metadata),
                        },
                    )
                    on_error_result = await self.run_stage(
                        "on_error",
                        on_error_context,
                        operator_specs,
                        _handling_error=True,
                    )
                    context.runtime_events.extend(on_error_context.runtime_events)
                    aggregate.executed.extend(on_error_result.executed)
                    aggregate.skipped.extend(on_error_result.skipped)
                    aggregate.results.extend(on_error_result.results)
                    aggregate.diagnostics.extend(on_error_result.diagnostics)
                break
        return aggregate


def default_operator_registry() -> OperatorRegistry:
    """Return the built-in operator registry used by assembly and API hooks."""
    return OperatorRegistry(
        {
            "mcp_connection": lambda spec: MCPConnectionOperator(spec),
            "skill_file_upload": lambda spec: SkillFileUploadOperator(spec),
            "memory_retrieval": lambda spec: MemoryRetrievalOperator(spec),
            "memory_persistence": lambda spec: MemoryPersistenceOperator(spec),
            "knowledge_summary": lambda spec: KnowledgeSummaryOperator(spec),
        }
    )


def apply_operator_context_to_plan(
    plan: AgentRunPlan,
    context: OperatorContext,
) -> AgentRunPlan:
    """Build a new plan snapshot from mutable operator context output."""
    # AgentRunPlan may contain events, clients, and locks. Rebuild the mutable
    # neutral containers without deep-copying those request-scoped handles.
    prompt = plan.root_agent.prompt.model_copy(
        update={
            "fragments": dict(context.prompt_fragments),
            "context_components": list(context.context_components),
            "templates": dict(plan.root_agent.prompt.templates),
        },
    )
    root_agent = plan.root_agent.model_copy(
        update={
            "tools": list(context.tools),
            "prompt": prompt,
            "managed_agents": list(plan.root_agent.managed_agents),
            "external_a2a_agents": list(plan.root_agent.external_a2a_agents),
            "runtime_hints": dict(plan.root_agent.runtime_hints),
        },
    )
    monitoring_metadata = dict(context.monitoring_metadata)
    if context.runtime_events:
        monitoring_metadata["operator_runtime_event_count"] = len(context.runtime_events)
    return plan.model_copy(
        update={
            "root_agent": root_agent,
            "history": list(plan.history) if plan.history is not None else None,
            "model_config_list": list(plan.model_config_list),
            "mcp_connections": list(plan.mcp_connections),
            "runtime_resources": dict(context.runtime_resources),
            "operators": list(plan.operators),
            "monitoring_metadata": monitoring_metadata,
        },
    )


def _apply_operator_result(
    context: OperatorContext,
    spec: OperatorSpec,
    result: OperatorResult,
) -> None:
    _validate_context_patch(result.context_patch)
    _merge_context_patch(context, result.context_patch)
    context.added_tools.extend(result.added_tools)
    context.tools.extend(result.added_tools)
    context.context_components.extend(result.added_context_components)
    context.monitoring_metadata.update(result.added_metadata)
    context.runtime_events.extend(result.runtime_events)
    _record_operator_diagnostic(context, spec, result)
    if result.status in {"soft_failure", "blocking_failure"} and result.message:
        context.runtime_events.append(
            RuntimeEvent(
                type=RuntimeEventType.ERROR,
                content=result.message,
                metadata={
                    "operator": spec.name,
                    "operator_stage": context.stage,
                    "operator_status": result.status,
                },
            )
        )


def _validate_context_patch(context_patch: dict[str, Any]) -> None:
    illegal_keys = set(context_patch) - ALLOWED_CONTEXT_PATCH_KEYS
    protected_keys = set(context_patch) & FORBIDDEN_CONTEXT_PATCH_KEYS
    if illegal_keys or protected_keys:
        rejected = sorted(illegal_keys | protected_keys)
        raise OperatorPatchError(
            "Operator context_patch contains non-whitelisted keys: "
            + ", ".join(rejected)
        )


def _merge_context_patch(
    context: OperatorContext,
    context_patch: dict[str, Any],
) -> None:
    if "tools" in context_patch:
        context.tools = list(context_patch["tools"])
    if "prompt_fragments" in context_patch:
        prompt_patch = context_patch["prompt_fragments"]
        if _is_replace_patch(prompt_patch):
            context.prompt_fragments = dict(prompt_patch["items"])
        else:
            for key, value in dict(prompt_patch).items():
                if value is None:
                    context.prompt_fragments.pop(key, None)
                else:
                    context.prompt_fragments[key] = value
    if "context_components" in context_patch:
        components_patch = context_patch["context_components"]
        if _is_replace_patch(components_patch):
            context.context_components = list(components_patch["items"])
        else:
            context.context_components.extend(list(components_patch))
    if "runtime_resources" in context_patch:
        context.runtime_resources.update(dict(context_patch["runtime_resources"]))
    if "monitoring_metadata" in context_patch:
        context.monitoring_metadata.update(dict(context_patch["monitoring_metadata"]))
    if "metadata" in context_patch:
        context.metadata.update(dict(context_patch["metadata"]))


def _is_replace_patch(value: Any) -> bool:
    return isinstance(value, Mapping) and value.get("__replace__") is True


def _record_operator_diagnostic(
    context: OperatorContext,
    spec: OperatorSpec,
    result: OperatorResult,
) -> None:
    diagnostics = context.monitoring_metadata.setdefault("operator_results", [])
    diagnostics.append(_operator_diagnostic(spec, result))


def _operator_diagnostic(
    spec: OperatorSpec,
    result: OperatorResult,
) -> dict[str, Any]:
    return {
        "operator": spec.name,
        "status": result.status,
        "message": result.message,
        "patch_keys": sorted(result.context_patch),
    }


def _sorted_operator_specs(
    operator_specs: Iterable[OperatorSpec],
) -> list[OperatorSpec]:
    return sorted(operator_specs, key=lambda spec: (spec.priority, spec.name))


def _normalize_operator_name(name: str) -> str:
    operator_name = name.strip().lower()
    if not operator_name:
        raise OperatorError("Operator name cannot be empty.")
    return operator_name


class MCPConnectionOperator:
    """Operator managing MCP required/optional connection failures."""

    def __init__(self, spec: OperatorSpec):
        self.spec = spec

    def supports(self, context: OperatorContext) -> bool:
        """Run only when the plan contains MCP connections."""
        return bool(context.plan and context.plan.mcp_connections)

    def execute(self, context: OperatorContext) -> OperatorResult:
        """Validate MCP connection availability using injected connector state."""
        if context.plan is None:
            return OperatorResult.ok()
        connector = self.spec.config.get("connector")
        connection_results = dict(self.spec.config.get("connection_results") or {})
        optional_failures: list[str] = []
        for connection in context.plan.mcp_connections:
            error_message = _mcp_connection_error(
                connection,
                connector=connector,
                connection_results=connection_results,
            )
            if error_message is None:
                continue
            event = _mcp_connection_error_event(connection, error_message)
            if connection.required:
                return OperatorResult.blocking_failure(
                    f"Required MCP server '{connection.name}' failed: {error_message}",
                    runtime_events=[event],
                    added_metadata={
                        f"mcp.{connection.name}.status": "blocking_failure",
                    },
                )
            optional_failures.append(connection.name)
            context.runtime_events.append(event)

        if optional_failures:
            context_patch = _optional_mcp_failure_patch(
                context,
                optional_failures,
            )
            return OperatorResult.soft_failure(
                "Optional MCP servers failed: " + ", ".join(optional_failures),
                context_patch=context_patch,
            )
        return OperatorResult.ok()


class SkillFileUploadOperator:
    """Operator extracting generated skill file payloads and emitting artifacts."""

    def __init__(self, spec: OperatorSpec):
        self.spec = spec

    def supports(self, context: OperatorContext) -> bool:
        """Run when the current context contains tool or final-answer output."""
        return bool(_skill_file_upload_payloads_from_context(context))

    def execute(self, context: OperatorContext) -> OperatorResult:
        """Upload generated skill files and convert them into artifact events."""
        payloads = _skill_file_upload_payloads_from_context(context)
        if not payloads:
            return OperatorResult.ok()

        uploader = self.spec.config.get("uploader") or _default_skill_file_uploader
        path_checker = self.spec.config.get("path_checker")
        allowed_roots = _skill_upload_allowed_roots(context, self.spec.config)
        artifacts: list[dict[str, Any]] = []
        failures: list[dict[str, Any]] = []
        for payload in payloads:
            artifact, failure = _upload_skill_file_payload(
                payload,
                context=context,
                uploader=uploader,
                path_checker=path_checker,
                allowed_roots=allowed_roots,
            )
            if artifact is not None:
                artifacts.append(artifact)
            if failure is not None:
                failures.append(failure)

        runtime_events = [
            RuntimeEvent(
                type=RuntimeEventType.ARTIFACT_CREATED,
                request_id=_context_request_id(context),
                artifact=artifact,
                metadata={
                    "operator": "skill_file_upload",
                    "absolute_path": artifact.get("absolute_path"),
                },
            )
            for artifact in artifacts
        ]
        metadata = {
            "skill_file_uploads": artifacts,
            "skill_file_upload_failures": failures,
        }
        if failures:
            return OperatorResult.soft_failure(
                f"Skill file upload failed for {len(failures)} file(s).",
                runtime_events=runtime_events,
                added_metadata=metadata,
            )
        return OperatorResult.ok(
            runtime_events=runtime_events,
            added_metadata=metadata,
        )


class MemoryRetrievalOperator:
    """Operator emitting memory retrieval lifecycle events and context patches."""

    def __init__(self, spec: OperatorSpec):
        self.spec = spec

    def supports(self, context: OperatorContext) -> bool:
        """Run when memory resources or an injected retriever are available."""
        return (
            "memory.config" in context.runtime_resources
            or "memory.items" in context.runtime_resources
            or self.spec.config.get("retriever") is not None
        )

    async def execute(self, context: OperatorContext) -> OperatorResult:
        """Emit retrieval events and inject memory prompt/context entries."""
        if not _memory_enabled(context):
            return OperatorResult.ok(
                added_metadata={"memory.retrieval_operator": "disabled"}
            )

        retriever = self.spec.config.get("retriever")
        levels = _memory_retrieval_levels(context)
        start_event = _memory_lifecycle_event(
            context,
            content=self.spec.config.get("start_message", "memory_search_started"),
            status="started",
            metadata={"memory_levels": levels},
        )
        existing_status = context.runtime_resources.get("memory.retrieval_status")
        if retriever is None and existing_status == "soft_failure":
            existing_error = str(
                context.runtime_resources.get("memory.retrieval_error")
                or "memory retrieval failed"
            )
            return OperatorResult.soft_failure(
                f"Memory retrieval failed: {existing_error}",
                context_patch=_memory_retrieval_patch(
                    context,
                    memory_items=context.runtime_resources.get("memory.items") or [],
                    status="soft_failure",
                    error=existing_error,
                    levels=levels,
                ),
                runtime_events=[
                    start_event,
                    _memory_lifecycle_event(
                        context,
                        content=self.spec.config.get("fail_message", "memory_search_failed"),
                        status="soft_failure",
                        metadata={"error": existing_error, "memory_levels": levels},
                    ),
                ],
            )
        try:
            if retriever is not None:
                search_result = retriever(
                    query_text=_memory_query(context),
                    memory_config=context.runtime_resources.get("memory.config", {}),
                    tenant_id=context.runtime_resources.get("memory.tenant_id"),
                    user_id=context.runtime_resources.get("memory.user_id"),
                    agent_id=context.runtime_resources.get("memory.agent_id"),
                    memory_levels=levels,
                )
                if inspect.isawaitable(search_result):
                    search_result = await search_result
                memory_items = list(dict(search_result).get("results", []))
            else:
                memory_items = list(context.runtime_resources.get("memory.items") or [])
        except Exception as exc:
            return OperatorResult.soft_failure(
                f"Memory retrieval failed: {exc}",
                context_patch=_memory_retrieval_patch(
                    context,
                    memory_items=[],
                    status="soft_failure",
                    error=str(exc),
                    levels=levels,
                ),
                runtime_events=[
                    start_event,
                    _memory_lifecycle_event(
                        context,
                        content=self.spec.config.get("fail_message", "memory_search_failed"),
                        status="soft_failure",
                        metadata={"error": str(exc), "memory_levels": levels},
                    ),
                ],
            )

        return OperatorResult.ok(
            context_patch=_memory_retrieval_patch(
                context,
                memory_items=memory_items,
                status="ok",
                levels=levels,
            ),
            runtime_events=[
                start_event,
                _memory_lifecycle_event(
                    context,
                    content=self.spec.config.get("done_message", "memory_search_done"),
                    status="ok",
                    metadata={
                        "retrieved_count": len(memory_items),
                        "memory_levels": levels,
                    },
                ),
            ],
        )


class MemoryPersistenceOperator:
    """Operator persisting final answers into allowed memory levels."""

    def __init__(self, spec: OperatorSpec):
        self.spec = spec

    def supports(self, context: OperatorContext) -> bool:
        """Run when memory is enabled and a final answer is available."""
        return _memory_enabled(context) and _memory_final_answer(context) is not None

    async def execute(self, context: OperatorContext) -> OperatorResult:
        """Persist final answer to memory using an injected persistence function."""
        memory_levels = _memory_persistence_levels(context)
        if not memory_levels:
            return OperatorResult.ok(
                added_metadata={
                    "memory.persistence_status": "skipped",
                    "memory.persistence_reason": "no_allowed_levels",
                }
            )

        persistence_func = self.spec.config.get("persistence_func")
        if persistence_func is None:
            return OperatorResult.ok(
                added_metadata={
                    "memory.persistence_status": "skipped",
                    "memory.persistence_reason": "missing_persistence_func",
                    "memory.persistence_levels": memory_levels,
                }
            )

        try:
            persistence_result = persistence_func(
                messages=_memory_persistence_messages(context),
                memory_config=context.runtime_resources.get("memory.config", {}),
                tenant_id=context.runtime_resources.get("memory.tenant_id"),
                user_id=context.runtime_resources.get("memory.user_id"),
                agent_id=context.runtime_resources.get("memory.agent_id"),
                memory_levels=memory_levels,
            )
            if inspect.isawaitable(persistence_result):
                persistence_result = await persistence_result
            items = list(dict(persistence_result).get("results", []))
        except Exception as exc:
            return OperatorResult.soft_failure(
                f"Memory persistence failed: {exc}",
                runtime_events=[
                    _memory_lifecycle_event(
                        context,
                        content=self.spec.config.get(
                            "fail_message",
                            "memory_persistence_failed",
                        ),
                        status="soft_failure",
                        metadata={"error": str(exc), "memory_levels": memory_levels},
                    )
                ],
                added_metadata={
                    "memory.persistence_status": "soft_failure",
                    "memory.persistence_error": str(exc),
                    "memory.persistence_levels": memory_levels,
                },
            )

        return OperatorResult.ok(
            runtime_events=[
                _memory_lifecycle_event(
                    context,
                    content=self.spec.config.get("done_message", "memory_persistence_done"),
                    status="ok",
                    metadata={
                        "persisted_count": len(items),
                        "memory_levels": memory_levels,
                    },
                )
            ],
            added_metadata={
                "memory.persistence_status": "ok",
                "memory.persistence_count": len(items),
                "memory.persistence_levels": memory_levels,
            },
        )


class KnowledgeSummaryOperator:
    """Operator injecting knowledge summary into prompt and context."""

    def __init__(self, spec: OperatorSpec):
        self.spec = spec

    def supports(self, context: OperatorContext) -> bool:
        """Run when knowledge resources or a configured resolver are available."""
        return (
            "knowledge.summary" in context.runtime_resources
            or "knowledge.kb_ids" in context.runtime_resources
            or self.spec.config.get("summary_resolver") is not None
        )

    async def execute(self, context: OperatorContext) -> OperatorResult:
        """Resolve or reuse knowledge summary and patch the runtime context."""
        resolver = self.spec.config.get("summary_resolver")
        kb_ids = _knowledge_kb_ids(context)
        if resolver is None:
            summary = str(
                context.runtime_resources.get("knowledge.summary")
                or context.prompt_fragments.get("knowledge_base_summary")
                or ""
            )
            status = str(context.runtime_resources.get("knowledge.summary_status") or "ok")
            patch = _knowledge_summary_patch(
                context,
                summary=summary,
                kb_ids=kb_ids,
                status=status,
            )
            if status == "soft_failure":
                return OperatorResult.soft_failure(
                    "Knowledge summary is incomplete.",
                    context_patch=patch,
                )
            return OperatorResult.ok(context_patch=patch)

        try:
            summary = await _resolve_knowledge_summary(
                resolver,
                kb_ids=kb_ids,
                display_names=_knowledge_display_names(context),
            )
        except Exception as exc:
            fallback_summary = str(
                context.runtime_resources.get("knowledge.summary")
                or context.prompt_fragments.get("knowledge_base_summary")
                or ""
            )
            return OperatorResult.soft_failure(
                f"Knowledge summary failed: {exc}",
                context_patch=_knowledge_summary_patch(
                    context,
                    summary=fallback_summary,
                    kb_ids=kb_ids,
                    status="soft_failure",
                    error=str(exc),
                ),
            )

        return OperatorResult.ok(
            context_patch=_knowledge_summary_patch(
                context,
                summary=summary,
                kb_ids=kb_ids,
                status="ok",
            )
        )


def _mcp_connection_error(
    connection: MCPConnectionConfig,
    *,
    connector: Any,
    connection_results: dict[str, Any],
) -> str | None:
    result = connection_results.get(connection.name, True)
    if connector is not None:
        result = connector(connection)
    if result is True or result is None:
        return None
    if isinstance(result, Exception):
        return str(result)
    if isinstance(result, str):
        return result
    if result is False:
        return "connection failed"
    if isinstance(result, dict) and result.get("ok") is False:
        return str(result.get("message") or "connection failed")
    return None


def _mcp_connection_error_event(
    connection: MCPConnectionConfig,
    error_message: str,
) -> RuntimeEvent:
    return RuntimeEvent(
        type=RuntimeEventType.ERROR,
        error=error_message,
        metadata={
            "operator": "mcp_connection",
            "mcp_server": connection.name,
            "mcp_required": connection.required,
        },
    )


def _skill_file_upload_payloads_from_context(
    context: OperatorContext,
) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    for candidate in (
        context.tool_output,
        context.final_answer,
        context.metadata.get("skill_file_payloads"),
    ):
        payloads.extend(_extract_skill_file_upload_payloads(candidate))
    for event in context.runtime_events:
        payloads.extend(_extract_skill_file_upload_payloads(event.content))
        payloads.extend(_extract_skill_file_upload_payloads(event.tool_output))
        payloads.extend(_extract_skill_file_upload_payloads(event.payload))
    return _dedupe_skill_file_payloads(payloads)


def _extract_skill_file_upload_payloads(value: Any) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    if value is None:
        return payloads
    if isinstance(value, Mapping):
        if value.get("absolute_path"):
            payloads.append(dict(value))
        for nested_key in ("text", "content", "output", "message"):
            if nested_key in value:
                payloads.extend(_extract_skill_file_upload_payloads(value[nested_key]))
        return payloads
    if isinstance(value, list | tuple | set):
        for item in value:
            payloads.extend(_extract_skill_file_upload_payloads(item))
        return payloads
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="ignore")
    if isinstance(value, str):
        for payload in _extract_json_objects_from_text(value):
            if payload.get("absolute_path"):
                payloads.append(payload)
            else:
                payloads.extend(_extract_skill_file_upload_payloads(payload))
    return payloads


def _extract_json_objects_from_text(text: str) -> list[dict[str, Any]]:
    decoder = json.JSONDecoder()
    results: list[dict[str, Any]] = []
    index = 0
    while index < len(text):
        start_index = text.find("{", index)
        if start_index < 0:
            break
        try:
            payload, end_index = decoder.raw_decode(text, start_index)
        except json.JSONDecodeError:
            index = start_index + 1
            continue
        if isinstance(payload, dict):
            results.append(payload)
        index = max(end_index, start_index + 1)
    return results


def _dedupe_skill_file_payloads(
    payloads: Sequence[dict[str, Any]],
) -> list[dict[str, Any]]:
    seen_paths: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for payload in payloads:
        absolute_path = str(payload.get("absolute_path") or "").strip()
        if not absolute_path or absolute_path in seen_paths:
            continue
        seen_paths.add(absolute_path)
        deduped.append(payload)
    return deduped


def _upload_skill_file_payload(
    payload: Mapping[str, Any],
    *,
    context: OperatorContext,
    uploader: Callable[..., dict[str, Any]],
    path_checker: Callable[[str], bool] | None,
    allowed_roots: Sequence[str],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    absolute_path = str(payload.get("absolute_path") or "").strip()
    file_name = str(
        payload.get("file_name")
        or payload.get("file_path")
        or os.path.basename(absolute_path)
    )
    mime_type = str(
        payload.get("mime_type")
        or payload.get("content_type")
        or "application/octet-stream"
    )
    if not absolute_path:
        return None, {"reason": "missing_absolute_path"}
    if not _is_allowed_skill_upload_path(
        absolute_path,
        path_checker=path_checker,
        allowed_roots=allowed_roots,
    ):
        return None, {
            "reason": "unsafe_path",
            "absolute_path": absolute_path,
        }
    if not os.path.exists(absolute_path):
        return None, {
            "reason": "missing_file",
            "absolute_path": absolute_path,
        }

    try:
        file_size = os.path.getsize(absolute_path)
        with open(absolute_path, "rb") as file_obj:
            upload_result = uploader(
                file_obj=file_obj,
                file_name=file_name or os.path.basename(absolute_path),
                prefix=_skill_upload_prefix(context),
                generate_presigned_url=True,
                file_size=file_size,
            )
        if not upload_result.get("success"):
            return None, {
                "reason": "upload_failed",
                "absolute_path": absolute_path,
                "error": upload_result.get("error") or "Upload failed",
            }
        return {
            "status": "success",
            "file_name": file_name or os.path.basename(absolute_path),
            "absolute_path": absolute_path,
            "object_name": upload_result.get("object_name"),
            "preview_url": upload_result.get("presigned_url") or upload_result.get("url"),
            "url": upload_result.get("url"),
            "presigned_url": upload_result.get("presigned_url"),
            "mime_type": mime_type,
            "file_size": upload_result.get("file_size", file_size),
        }, None
    except Exception as exc:  # pragma: no cover - covered through injected failures
        return None, {
            "reason": "upload_exception",
            "absolute_path": absolute_path,
            "error": str(exc),
        }


def _is_allowed_skill_upload_path(
    absolute_path: str,
    *,
    path_checker: Callable[[str], bool] | None,
    allowed_roots: Sequence[str],
) -> bool:
    if path_checker is not None:
        return bool(path_checker(absolute_path))
    try:
        candidate_path = Path(absolute_path).resolve()
    except Exception:
        return False
    for root in allowed_roots:
        try:
            candidate_path.relative_to(Path(root).resolve())
            return True
        except ValueError:
            continue
    return False


def _skill_upload_allowed_roots(
    context: OperatorContext,
    config: Mapping[str, Any],
) -> list[str]:
    roots = config.get("allowed_roots")
    if roots is None:
        roots = context.runtime_resources.get("skill.upload_allowed_roots")
    if isinstance(roots, str):
        return [roots]
    if isinstance(roots, Sequence):
        return [str(root) for root in roots]
    return ["/mnt/nexent"]


def _skill_upload_prefix(context: OperatorContext) -> str:
    user_id = None
    if context.request is not None:
        user_id = context.request.user_id
    elif context.plan is not None:
        user_id = context.plan.run_control.user_id
    else:
        user_id = context.metadata.get("user_id")
    return f"skill-files/{user_id}" if user_id else "skill-files"


def _context_request_id(context: OperatorContext) -> str | None:
    if context.request is not None:
        return context.request.request_id
    if context.plan is not None:
        return context.plan.request_id
    return None


def _default_skill_file_uploader(**kwargs: Any) -> dict[str, Any]:
    from database.attachment_db import upload_fileobj

    return upload_fileobj(**kwargs)


def _memory_enabled(context: OperatorContext) -> bool:
    memory_config = context.runtime_resources.get("memory.config")
    user_config = context.runtime_resources.get("memory.user_config")
    enabled = _memory_config_value(user_config, "memory_switch", default=bool(memory_config))
    return bool(enabled and memory_config)


def _memory_query(context: OperatorContext) -> str:
    if context.request is not None:
        return context.request.query
    if context.plan is not None:
        return context.plan.query
    if context.model_input is not None:
        return str(context.model_input)
    return ""


def _memory_final_answer(context: OperatorContext) -> Any | None:
    if context.final_answer is not None:
        return context.final_answer
    for event in reversed(context.runtime_events):
        if event.type == RuntimeEventType.FINAL_ANSWER:
            return event.content
        if event.compat_process_type == "final_answer":
            return event.content
    return None


def _memory_retrieval_levels(context: OperatorContext) -> list[str]:
    levels = context.runtime_resources.get("memory.retrieval_levels")
    if isinstance(levels, Sequence) and not isinstance(levels, str):
        return [str(level) for level in levels]
    user_config = context.runtime_resources.get("memory.user_config")
    agent_id = str(context.runtime_resources.get("memory.agent_id") or "")
    levels = ["tenant", "agent", "user", "user_agent"]
    if _memory_config_value(user_config, "agent_share_option", default="never") == "never":
        levels = [level for level in levels if level != "agent"]
    if agent_id in _memory_string_set(
        _memory_config_value(user_config, "disable_agent_ids", default=[])
    ):
        levels = [level for level in levels if level != "agent"]
    if agent_id in _memory_string_set(
        _memory_config_value(user_config, "disable_user_agent_ids", default=[])
    ):
        levels = [level for level in levels if level != "user_agent"]
    return levels


def _memory_persistence_levels(context: OperatorContext) -> list[str]:
    user_config = context.runtime_resources.get("memory.user_config")
    agent_id = str(context.runtime_resources.get("memory.agent_id") or "")
    levels = ["agent", "user_agent"]
    if _memory_config_value(user_config, "agent_share_option", default="never") == "never":
        levels = [level for level in levels if level != "agent"]
    if agent_id in _memory_string_set(
        _memory_config_value(user_config, "disable_agent_ids", default=[])
    ):
        levels = [level for level in levels if level != "agent"]
    if agent_id in _memory_string_set(
        _memory_config_value(user_config, "disable_user_agent_ids", default=[])
    ):
        levels = [level for level in levels if level != "user_agent"]
    return levels


def _memory_config_value(
    config: Any,
    key: str,
    *,
    default: Any = None,
) -> Any:
    if config is None:
        return default
    if isinstance(config, Mapping):
        return config.get(key, default)
    return getattr(config, key, default)


def _memory_string_set(value: Any) -> set[str]:
    if value is None:
        return set()
    if isinstance(value, str):
        return {value}
    if isinstance(value, Sequence):
        return {str(item) for item in value}
    return {str(value)}


def _memory_retrieval_patch(
    context: OperatorContext,
    *,
    memory_items: Sequence[Any],
    status: str,
    levels: Sequence[str],
    error: str | None = None,
) -> dict[str, Any]:
    items = list(memory_items)
    component = {
        "type": "memory",
        "items": items,
        "query": _memory_query(context),
        "levels": list(levels),
        "retrieval_status": status,
    }
    if error:
        component["error"] = error
    context_components = [
        component
        for component in context.context_components
        if not (isinstance(component, Mapping) and component.get("type") == "memory")
    ]
    context_components.append(component)
    monitoring_metadata: dict[str, Any] = {
        "memory.retrieval_status": status,
        "memory.retrieved_count": len(items),
        "memory.retrieval_levels": list(levels),
    }
    if error:
        monitoring_metadata["memory.retrieval_error"] = error
    return {
        "prompt_fragments": {
            "memory_list": json.dumps(items, ensure_ascii=False),
        },
        "context_components": {
            "__replace__": True,
            "items": context_components,
        },
        "runtime_resources": {
            "memory.items": items,
            "memory.retrieval_status": status,
            "memory.retrieval_levels": list(levels),
            **({"memory.retrieval_error": error} if error else {}),
        },
        "monitoring_metadata": monitoring_metadata,
    }


def _memory_lifecycle_event(
    context: OperatorContext,
    *,
    content: str,
    status: str,
    metadata: Mapping[str, Any] | None = None,
) -> RuntimeEvent:
    return RuntimeEvent(
        type=RuntimeEventType.LEGACY_PROCESS,
        request_id=_context_request_id(context),
        compat_process_type="memory_search",
        content=content,
        metadata={
            "operator": "memory",
            "operator_stage": context.stage,
            "memory_status": status,
            **dict(metadata or {}),
        },
    )


def _memory_persistence_messages(context: OperatorContext) -> list[dict[str, Any]]:
    final_answer = _memory_final_answer(context)
    return [
        {
            "role": "user",
            "content": _memory_query(context),
        },
        {
            "role": "assistant",
            "content": final_answer,
        },
    ]


def _knowledge_kb_ids(context: OperatorContext) -> list[str]:
    kb_ids = context.runtime_resources.get("knowledge.kb_ids")
    if isinstance(kb_ids, str):
        return [kb_ids] if kb_ids else []
    if isinstance(kb_ids, Sequence):
        return [str(kb_id) for kb_id in kb_ids if str(kb_id)]
    return []


def _knowledge_display_names(context: OperatorContext) -> dict[str, str]:
    display_names = context.runtime_resources.get("knowledge.index_name_to_display_map")
    if isinstance(display_names, Mapping):
        return {
            str(index_name): str(display_name)
            for index_name, display_name in display_names.items()
        }
    return {}


async def _resolve_knowledge_summary(
    resolver: Callable[[str], Any],
    *,
    kb_ids: Sequence[str],
    display_names: Mapping[str, str],
) -> str:
    fragments: list[str] = []
    for kb_id in kb_ids:
        summary_result = resolver(kb_id)
        if inspect.isawaitable(summary_result):
            summary_result = await summary_result
        summary = _knowledge_summary_text(summary_result)
        display_name = display_names.get(kb_id, kb_id)
        fragments.append(f"**{display_name}**: {summary}\n\n")
    return "".join(fragments)


def _knowledge_summary_text(summary_result: Any) -> str:
    if isinstance(summary_result, Mapping):
        return str(summary_result.get("summary") or "")
    if summary_result is None:
        return ""
    return str(summary_result)


def _knowledge_summary_patch(
    context: OperatorContext,
    *,
    summary: str,
    kb_ids: Sequence[str],
    status: str,
    error: str | None = None,
) -> dict[str, Any]:
    component = {
        "type": "knowledge_summary",
        "summary": summary,
        "kb_ids": list(kb_ids),
        "status": status,
    }
    if error:
        component["error"] = error
    context_components = [
        component
        for component in context.context_components
        if not (
            isinstance(component, Mapping)
            and component.get("type") == "knowledge_summary"
        )
    ]
    context_components.append(component)
    monitoring_metadata: dict[str, Any] = {
        "knowledge.summary_status": status,
        "knowledge.summary_kb_count": len(kb_ids),
    }
    if error:
        monitoring_metadata["knowledge.summary_error"] = error
    return {
        "prompt_fragments": {"knowledge_base_summary": summary},
        "context_components": {
            "__replace__": True,
            "items": context_components,
        },
        "runtime_resources": {
            "knowledge.summary": summary,
            "knowledge.summary_status": status,
            **({"knowledge.summary_error": error} if error else {}),
        },
        "monitoring_metadata": monitoring_metadata,
    }


def _optional_mcp_failure_patch(
    context: OperatorContext,
    optional_failures: Sequence[str],
) -> dict[str, Any]:
    disabled_servers = sorted({name for name in optional_failures if name})
    patch: dict[str, Any] = {
        "runtime_resources": {
            "mcp.disabled_servers": disabled_servers,
        },
        "monitoring_metadata": {
            "mcp.optional_failures": disabled_servers,
        },
    }
    disabled = set(disabled_servers)

    filtered_tools = [
        tool
        for tool in context.tools
        if not _is_disabled_mcp_tool(tool, disabled)
    ]
    if len(filtered_tools) != len(context.tools):
        patch["tools"] = filtered_tools
        patch["monitoring_metadata"]["mcp.removed_tools"] = [
            tool.name
            for tool in context.tools
            if _is_disabled_mcp_tool(tool, disabled)
        ]

    filtered_prompt_fragments = {
        key: value
        for key, value in context.prompt_fragments.items()
        if not _is_disabled_mcp_prompt_fragment(key, value, disabled)
    }
    if len(filtered_prompt_fragments) != len(context.prompt_fragments):
        patch["prompt_fragments"] = {
            "__replace__": True,
            "items": filtered_prompt_fragments,
        }
        patch["monitoring_metadata"]["mcp.removed_prompt_fragments"] = [
            key
            for key, value in context.prompt_fragments.items()
            if _is_disabled_mcp_prompt_fragment(key, value, disabled)
        ]

    filtered_context_components = [
        component
        for component in context.context_components
        if not _is_disabled_mcp_context_component(component, disabled)
    ]
    if len(filtered_context_components) != len(context.context_components):
        patch["context_components"] = {
            "__replace__": True,
            "items": filtered_context_components,
        }
        patch["monitoring_metadata"]["mcp.removed_context_components"] = (
            len(context.context_components) - len(filtered_context_components)
        )

    return patch


def _is_disabled_mcp_tool(tool: ToolSpec, disabled_servers: set[str]) -> bool:
    source = tool.source.value if hasattr(tool.source, "value") else str(tool.source)
    return source == ToolSource.MCP.value and bool(tool.usage in disabled_servers)


def _is_disabled_mcp_prompt_fragment(
    key: str,
    value: Any,
    disabled_servers: set[str],
) -> bool:
    return _mcp_key_matches_disabled_server(key, disabled_servers) or _mcp_value_matches_disabled_server(
        value,
        disabled_servers,
    )


def _is_disabled_mcp_context_component(
    component: Any,
    disabled_servers: set[str],
) -> bool:
    return _mcp_value_matches_disabled_server(component, disabled_servers)


def _mcp_key_matches_disabled_server(
    key: str,
    disabled_servers: set[str],
) -> bool:
    normalized_key = key.lower()
    for server in disabled_servers:
        normalized_server = server.lower()
        if normalized_key == normalized_server:
            return True
        for prefix in (
            f"mcp.{normalized_server}",
            f"mcp:{normalized_server}",
            f"mcp/{normalized_server}",
            f"mcp_{normalized_server}",
        ):
            if normalized_key.startswith(prefix):
                return True
    return False


def _mcp_value_matches_disabled_server(
    value: Any,
    disabled_servers: set[str],
) -> bool:
    if hasattr(value, "model_dump"):
        value = value.model_dump()
    if isinstance(value, Mapping):
        source = _normalized_mapping_value(value, "source")
        if source == ToolSource.MCP.value:
            if _mapping_server_value_matches(value, disabled_servers):
                return True
        if _mapping_server_value_matches(value, disabled_servers):
            return _mapping_has_mcp_marker(value)
        metadata = value.get("metadata")
        if metadata is not None and _mcp_value_matches_disabled_server(metadata, disabled_servers):
            return True
        return any(
            _mcp_value_matches_disabled_server(item, disabled_servers)
            for key, item in value.items()
            if key in {"mcp", "mcp_server", "server", "server_name", "usage"}
        )
    if isinstance(value, list | tuple | set):
        return any(
            _mcp_value_matches_disabled_server(item, disabled_servers)
            for item in value
        )
    return False


def _normalized_mapping_value(value: Mapping[str, Any], key: str) -> str | None:
    raw_value = value.get(key)
    if raw_value is None:
        return None
    return str(raw_value).lower()


def _mapping_server_value_matches(
    value: Mapping[str, Any],
    disabled_servers: set[str],
) -> bool:
    server_keys = (
        "mcp_server",
        "mcp_server_name",
        "server",
        "server_name",
        "usage",
    )
    for key in server_keys:
        server_value = value.get(key)
        if server_value is None:
            continue
        if str(server_value) in disabled_servers:
            return True
    return False


def _mapping_has_mcp_marker(value: Mapping[str, Any]) -> bool:
    source = _normalized_mapping_value(value, "source")
    type_name = _normalized_mapping_value(value, "type")
    kind = _normalized_mapping_value(value, "kind")
    return (
        source == ToolSource.MCP.value
        or type_name == ToolSource.MCP.value
        or kind == ToolSource.MCP.value
        or any(str(key).startswith("mcp") for key in value)
    )
