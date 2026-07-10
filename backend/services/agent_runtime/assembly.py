"""Run assembly orchestration for framework-neutral agent runtime plans."""

from __future__ import annotations

import inspect
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from .models import (
    AgentRunPlan,
    AgentRunRequestContext,
    AgentSpec,
    AssemblyState,
    CapabilityContribution,
    PromptBundle,
    RunControl,
    RuntimeWarningInfo,
    ToolSpec,
)
from .operators import (
    OperatorContext,
    OperatorRegistry,
    OperatorRunner,
    apply_operator_context_to_plan,
    default_operator_registry,
)
from .tool_schema import assert_agent_run_plan_framework_neutral


DEFAULT_PROVIDER_ORDER = (
    "model",
    "sub-agent",
    "tool",
    "knowledge",
    "skill",
    "memory",
    "mcp",
    "context",
    "plugin",
)


class AssemblyError(ValueError):
    """Base error for run assembly failures."""


class DuplicateCapabilityProviderError(AssemblyError):
    """Raised when multiple providers use the same name."""


class CapabilityProviderDependencyError(AssemblyError):
    """Raised when provider dependencies are missing or cyclic."""


class CapabilityContributionConflictError(AssemblyError):
    """Raised when provider contributions cannot be merged safely."""


class DuplicateToolIdentifierError(CapabilityContributionConflictError):
    """Raised when multiple model-visible tools share identifiers."""


class MissingRootAgentError(AssemblyError):
    """Raised when providers do not assemble a root agent."""


class CapabilityProvider(Protocol):
    """Provider contract used by the Run Assembly Layer."""

    name: str
    priority: int
    depends_on: Sequence[str]

    def contribute(
        self,
        request: AgentRunRequestContext,
        state: AssemblyState,
    ) -> CapabilityContribution | None:
        """Return declarative capability contributions for this request."""


@dataclass(frozen=True)
class NoOpCapabilityProvider:
    """Default placeholder provider used until concrete providers are migrated."""

    name: str
    priority: int
    depends_on: tuple[str, ...] = ()

    def contribute(
        self,
        request: AgentRunRequestContext,
        state: AssemblyState,
    ) -> CapabilityContribution:
        """Return an empty contribution."""
        _ = (request, state)
        return CapabilityContribution()


CurrentVersionResolver = Callable[[int, str], int | None]


def default_capability_providers() -> list[NoOpCapabilityProvider]:
    """Return default provider placeholders in the documented order."""
    return [
        NoOpCapabilityProvider(name=name, priority=index * 100)
        for index, name in enumerate(DEFAULT_PROVIDER_ORDER)
    ]


def resolve_assembly_version(
    request: AgentRunRequestContext,
    current_version_resolver: CurrentVersionResolver | None = None,
) -> int | None:
    """Resolve request version using explicit, debug draft, then published rules."""
    if request.version_no is not None:
        return request.version_no
    if request.is_debug:
        return 0

    resolver = current_version_resolver or _default_current_version_resolver
    version_no = resolver(request.agent_id, request.tenant_id)
    if version_no is None:
        raise AssemblyError(
            f"Could not resolve current published version for agent {request.agent_id}."
        )
    return version_no


def initialize_assembly_state(
    request: AgentRunRequestContext,
    *,
    version_no: int | None,
    agent_record: dict[str, Any] | None = None,
) -> AssemblyState:
    """Create the mutable assembly draft for a request."""
    base_agent_record = {
        "agent_id": request.agent_id,
        "tenant_id": request.tenant_id,
        "version_no": version_no,
    }
    if agent_record:
        base_agent_record.update(agent_record)
    return AssemblyState(agent_record=base_agent_record, version_no=version_no)


def sort_capability_providers(
    providers: Iterable[CapabilityProvider],
) -> list[CapabilityProvider]:
    """Sort providers by dependencies and priority, failing fast on invalid graphs."""
    provider_by_name: dict[str, CapabilityProvider] = {}
    for provider in providers:
        provider_name = _normalize_provider_name(provider.name)
        if provider_name in provider_by_name:
            raise DuplicateCapabilityProviderError(
                f"Duplicate capability provider name: {provider_name}."
            )
        provider_by_name[provider_name] = provider

    for provider_name, provider in provider_by_name.items():
        for dependency_name in _provider_dependencies(provider):
            if dependency_name not in provider_by_name:
                raise CapabilityProviderDependencyError(
                    f"Capability provider '{provider_name}' depends on missing provider "
                    f"'{dependency_name}'."
                )

    sorted_providers: list[CapabilityProvider] = []
    remaining = set(provider_by_name)
    satisfied: set[str] = set()
    while remaining:
        ready = [
            provider_by_name[name]
            for name in remaining
            if set(_provider_dependencies(provider_by_name[name])).issubset(satisfied)
        ]
        if not ready:
            cycle_members = ", ".join(sorted(remaining))
            raise CapabilityProviderDependencyError(
                f"Capability provider dependency cycle detected: {cycle_members}."
            )
        ready.sort(key=lambda provider: (getattr(provider, "priority", 100), provider.name))
        provider = ready[0]
        provider_name = _normalize_provider_name(provider.name)
        sorted_providers.append(provider)
        remaining.remove(provider_name)
        satisfied.add(provider_name)

    return sorted_providers


async def assemble_agent_run_plan(
    request: AgentRunRequestContext,
    providers: Iterable[CapabilityProvider] | None = None,
    *,
    current_version_resolver: CurrentVersionResolver | None = None,
    run_control: RunControl | None = None,
    agent_record: dict[str, Any] | None = None,
    plugin_registry: Any | None = None,
    operator_registry: OperatorRegistry | None = None,
    run_prepare_context: bool = True,
) -> AgentRunPlan:
    """Run providers and return the framework-neutral immutable run plan."""
    version_no = resolve_assembly_version(request, current_version_resolver)
    state = initialize_assembly_state(
        request,
        version_no=version_no,
        agent_record=agent_record,
    )
    provider_list = default_capability_providers() if providers is None else providers
    provider_list = _with_plugin_providers(provider_list, plugin_registry)
    for provider in sort_capability_providers(provider_list):
        contribution = provider.contribute(request, state)
        if inspect.isawaitable(contribution):
            contribution = await contribution
        if contribution is not None:
            merge_capability_contribution(state, contribution)

    plan = freeze_agent_run_plan(
        request,
        state,
        run_control=run_control,
    )
    if run_prepare_context:
        plan = await run_prepare_context_operators(
            plan,
            request=request,
            operator_registry=operator_registry,
        )
    return plan


async def run_prepare_context_operators(
    plan: AgentRunPlan,
    *,
    request: AgentRunRequestContext | None = None,
    operator_registry: OperatorRegistry | None = None,
) -> AgentRunPlan:
    """Execute prepare_context operators and return the patched plan."""
    if not plan.operators:
        return plan
    context = OperatorContext.from_plan(
        stage="prepare_context",
        plan=plan,
        request=request,
    )
    registry = operator_registry or default_operator_registry()
    result = await OperatorRunner(registry).run_stage(
        "prepare_context",
        context,
        plan.operators,
    )
    if result.status == "blocking_failure":
        message = _operator_stage_failure_message("prepare_context", result)
        raise AssemblyError(message)
    patched_plan = apply_operator_context_to_plan(plan, context)
    assert_agent_run_plan_framework_neutral(patched_plan)
    return patched_plan


def merge_capability_contribution(
    state: AssemblyState,
    contribution: CapabilityContribution,
) -> None:
    """Merge one provider contribution into the mutable assembly draft."""
    if contribution.agent_record:
        state.agent_record.update(contribution.agent_record)
    if contribution.version_no is not None:
        state.version_no = contribution.version_no
    state.model_configs.extend(contribution.model_configs)

    if contribution.root_agent is not None:
        if state.root_agent is not None and state.root_agent != contribution.root_agent:
            raise CapabilityContributionConflictError("Multiple root agents were contributed.")
        state.root_agent = contribution.root_agent
    state.managed_agents.extend(contribution.managed_agents)
    state.external_a2a_agents.extend(contribution.external_a2a_agents)

    for agent_name, tools in contribution.tools_by_agent.items():
        _append_tools_for_agent(state, agent_name, tools)

    _merge_dict_without_conflicts(
        state.prompt_fragments,
        contribution.prompt_fragments,
        conflict_label="prompt fragment",
    )
    state.context_components.extend(contribution.context_components)
    state.mcp_connections.extend(contribution.mcp_connections)
    _merge_dict_without_conflicts(
        state.runtime_resources,
        contribution.runtime_resources,
        conflict_label="runtime resource",
    )
    state.operators.extend(contribution.operators)
    state.monitoring_metadata.update(contribution.monitoring_metadata)
    state.warnings.extend(contribution.warnings)


def freeze_agent_run_plan(
    request: AgentRunRequestContext,
    state: AssemblyState,
    *,
    run_control: RunControl | None = None,
) -> AgentRunPlan:
    """Create the immutable AgentRunPlan snapshot from AssemblyState."""
    if state.root_agent is None:
        raise MissingRootAgentError("Run assembly did not produce a root agent.")

    root_agent = _attach_state_to_root_agent(state.root_agent, state)
    monitoring_metadata = dict(state.monitoring_metadata)
    monitoring_metadata.setdefault("agent_id", request.agent_id)
    monitoring_metadata.setdefault("tenant_id", request.tenant_id)
    monitoring_metadata.setdefault("version_no", state.version_no)
    if state.warnings:
        monitoring_metadata["assembly_warnings"] = [
            warning.model_dump(mode="json")
            if isinstance(warning, RuntimeWarningInfo)
            else warning
            for warning in state.warnings
        ]

    plan = AgentRunPlan(
        request_id=request.request_id,
        runtime_provider=request.runtime_provider,
        query=request.query,
        history=request.history,
        model_config_list=list(state.model_configs),
        root_agent=root_agent,
        mcp_connections=list(state.mcp_connections),
        runtime_resources=dict(state.runtime_resources),
        operators=list(state.operators),
        monitoring_metadata=monitoring_metadata,
        run_control=run_control
        or RunControl(
            request_id=request.request_id,
            user_id=request.user_id,
            conversation_id=request.conversation_id,
        ),
    )
    assert_agent_run_plan_framework_neutral(plan)
    return plan


def _attach_state_to_root_agent(root_agent: AgentSpec, state: AssemblyState) -> AgentSpec:
    root_tools = list(root_agent.tools)
    state_tools = list(state.tools_by_agent.get(root_agent.name, []))
    combined_tools = _merge_tool_lists(root_agent.name, root_tools, state_tools)
    prompt = _merge_prompt_bundle(root_agent.prompt, state)
    managed_agents = list(root_agent.managed_agents) + list(state.managed_agents)
    external_a2a_agents = (
        list(root_agent.external_a2a_agents) + list(state.external_a2a_agents)
    )
    return root_agent.model_copy(
        update={
            "tools": combined_tools,
            "prompt": prompt,
            "managed_agents": managed_agents,
            "external_a2a_agents": external_a2a_agents,
        },
        deep=True,
    )


def _merge_prompt_bundle(prompt: PromptBundle, state: AssemblyState) -> PromptBundle:
    fragments = dict(prompt.fragments)
    _merge_dict_without_conflicts(
        fragments,
        state.prompt_fragments,
        conflict_label="prompt fragment",
    )
    return prompt.model_copy(
        update={
            "fragments": fragments,
            "context_components": list(prompt.context_components) + list(state.context_components),
        },
        deep=True,
    )


def _append_tools_for_agent(
    state: AssemblyState,
    agent_name: str,
    tools: Sequence[ToolSpec],
) -> None:
    existing_tools = state.tools_by_agent.setdefault(agent_name, [])
    existing_tools[:] = _merge_tool_lists(agent_name, existing_tools, list(tools))


def _merge_tool_lists(
    agent_name: str,
    existing_tools: Sequence[ToolSpec],
    new_tools: Sequence[ToolSpec],
) -> list[ToolSpec]:
    known_identifiers: dict[str, str] = {}
    for tool in existing_tools:
        for identifier in _tool_identifiers(tool):
            known_identifiers[identifier] = tool.name

    merged_tools = list(existing_tools)
    for tool in new_tools:
        for identifier in _tool_identifiers(tool):
            if identifier in known_identifiers:
                raise DuplicateToolIdentifierError(
                    f"Duplicate tool identifier '{identifier}' for agent '{agent_name}'."
                )
        for identifier in _tool_identifiers(tool):
            known_identifiers[identifier] = tool.name
        merged_tools.append(tool)

    return merged_tools


def _tool_identifiers(tool: ToolSpec) -> set[str]:
    identifiers = {tool.name}
    if tool.class_name:
        identifiers.add(tool.class_name)
    return {identifier.strip().lower() for identifier in identifiers if identifier.strip()}


def _merge_dict_without_conflicts(
    target: dict[str, Any],
    incoming: dict[str, Any],
    *,
    conflict_label: str,
) -> None:
    for key, value in incoming.items():
        if key in target and target[key] != value:
            raise CapabilityContributionConflictError(
                f"Conflicting {conflict_label} contribution for key '{key}'."
            )
        target[key] = value


def _normalize_provider_name(provider_name: str) -> str:
    normalized_name = provider_name.strip().lower()
    if not normalized_name:
        raise CapabilityProviderDependencyError("Capability provider name cannot be empty.")
    return normalized_name


def _provider_dependencies(provider: CapabilityProvider) -> tuple[str, ...]:
    return tuple(
        _normalize_provider_name(dependency)
        for dependency in getattr(provider, "depends_on", ())
    )


def _with_plugin_providers(
    providers: Iterable[CapabilityProvider],
    plugin_registry: Any | None,
) -> list[CapabilityProvider]:
    provider_list = list(providers)
    if plugin_registry is None:
        return provider_list
    list_providers = getattr(plugin_registry, "list_providers", None)
    if callable(list_providers):
        provider_list.extend(list_providers())
    return provider_list


def _operator_stage_failure_message(stage: str, result: Any) -> str:
    messages = [
        operator_result.message
        for operator_result in result.results
        if operator_result.status == "blocking_failure" and operator_result.message
    ]
    if messages:
        return f"Operator stage '{stage}' failed: {messages[-1]}"
    return f"Operator stage '{stage}' failed."


def _default_current_version_resolver(agent_id: int, tenant_id: str) -> int | None:
    from database.agent_version_db import query_current_version_no

    return query_current_version_no(agent_id=agent_id, tenant_id=tenant_id)
