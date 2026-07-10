import os
import sys
from dataclasses import dataclass, field
from typing import Any

import pytest

backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../backend"))
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

from consts import const
from services.agent_runtime.assembly import (
    AssemblyError,
    CapabilityContributionConflictError,
    CapabilityProviderDependencyError,
    DuplicateCapabilityProviderError,
    DuplicateToolIdentifierError,
    MissingRootAgentError,
    assemble_agent_run_plan,
    default_capability_providers,
    initialize_assembly_state,
    merge_capability_contribution,
    resolve_assembly_version,
    sort_capability_providers,
)
from services.agent_runtime.models import (
    AgentRunRequestContext,
    AgentSpec,
    AssemblyState,
    CapabilityContribution,
    PromptBundle,
    RuntimeWarningInfo,
    ToolSource,
    ToolSpec,
    OperatorSpec,
)
from services.agent_runtime.operators import OperatorRegistry, OperatorResult


@dataclass
class Provider:
    name: str
    priority: int = 100
    depends_on: tuple[str, ...] = ()
    contribution: CapabilityContribution | None = None
    calls: list[str] = field(default_factory=list)

    def contribute(
        self,
        request: AgentRunRequestContext,
        state: AssemblyState,
    ) -> CapabilityContribution | None:
        self.calls.append(self.name)
        _ = (request, state)
        return self.contribution or CapabilityContribution()


class PatchOperator:
    def __init__(self, spec: OperatorSpec):
        self.spec = spec

    def supports(self, context):
        _ = context
        return True

    def execute(self, context):
        _ = context
        return self.spec.config["result"]


def _request(**overrides: Any) -> AgentRunRequestContext:
    payload = {
        "request_id": "req-1",
        "runtime_provider": const.AGENT_RUNTIME_PROVIDER_SMOLAGENTS,
        "agent_id": 10,
        "conversation_id": 20,
        "query": "hello",
        "history": [],
        "minio_files": [],
        "user_id": "user-1",
        "tenant_id": "tenant-1",
        "language": "zh",
        "is_debug": False,
    }
    payload.update(overrides)
    return AgentRunRequestContext(**payload)


def _root_agent(**overrides: Any) -> AgentSpec:
    payload = {
        "agent_id": 10,
        "name": "root",
        "description": "Root agent",
        "model_name": "main_model",
        "max_steps": 5,
        "prompt": PromptBundle(fragments={"base": "answer clearly"}),
    }
    payload.update(overrides)
    return AgentSpec(**payload)


def test_resolve_assembly_version_uses_explicit_version_first():
    request = _request(version_no=7, is_debug=True)

    assert resolve_assembly_version(request, lambda *_: 3) == 7


def test_resolve_assembly_version_uses_debug_draft_without_resolver():
    request = _request(version_no=None, is_debug=True)

    assert resolve_assembly_version(request) == 0


def test_resolve_assembly_version_uses_current_published_for_normal_run():
    request = _request(version_no=None, is_debug=False)

    assert resolve_assembly_version(request, lambda agent_id, tenant_id: 12) == 12


def test_resolve_assembly_version_fails_when_published_version_missing():
    request = _request(version_no=None, is_debug=False)

    with pytest.raises(AssemblyError, match="current published version"):
        resolve_assembly_version(request, lambda *_: None)


def test_initialize_assembly_state_carries_request_identity_and_agent_record():
    request = _request(version_no=4)

    state = initialize_assembly_state(
        request,
        version_no=4,
        agent_record={"name": "root"},
    )

    assert state.version_no == 4
    assert state.agent_record == {
        "agent_id": 10,
        "tenant_id": "tenant-1",
        "version_no": 4,
        "name": "root",
    }


def test_default_capability_providers_follow_documented_order():
    assert [provider.name for provider in default_capability_providers()] == [
        "model",
        "sub-agent",
        "tool",
        "knowledge",
        "skill",
        "memory",
        "mcp",
        "context",
        "plugin",
    ]


def test_sort_capability_providers_uses_dependencies_before_priority():
    providers = [
        Provider(name="tool", priority=10, depends_on=("model",)),
        Provider(name="model", priority=100),
        Provider(name="context", priority=1, depends_on=("tool",)),
    ]

    assert [provider.name for provider in sort_capability_providers(providers)] == [
        "model",
        "tool",
        "context",
    ]


def test_sort_capability_providers_rejects_duplicates():
    with pytest.raises(DuplicateCapabilityProviderError, match="Duplicate"):
        sort_capability_providers([
            Provider(name="tool"),
            Provider(name=" TOOL "),
        ])


def test_sort_capability_providers_rejects_missing_dependency():
    with pytest.raises(CapabilityProviderDependencyError, match="missing provider 'model'"):
        sort_capability_providers([Provider(name="tool", depends_on=("model",))])


def test_sort_capability_providers_rejects_cycles():
    providers = [
        Provider(name="a", depends_on=("b",)),
        Provider(name="b", depends_on=("a",)),
    ]

    with pytest.raises(CapabilityProviderDependencyError, match="cycle detected"):
        sort_capability_providers(providers)


def test_merge_capability_contribution_appends_tools_and_metadata():
    state = AssemblyState()
    first_tool = ToolSpec(name="search", class_name="SearchTool", source=ToolSource.LOCAL)
    second_tool = ToolSpec(name="read", class_name="ReadTool", source=ToolSource.SKILL)
    warning = RuntimeWarningInfo(code="soft", message="continued")

    merge_capability_contribution(
        state,
        CapabilityContribution(
            root_agent=_root_agent(),
            tools_by_agent={"root": [first_tool]},
            prompt_fragments={"knowledge": "summary"},
            context_components=[{"type": "memory"}],
            runtime_resources={"knowledge.document_paths": ["/doc"]},
            monitoring_metadata={"provider": "knowledge"},
            warnings=[warning],
        ),
    )
    merge_capability_contribution(
        state,
        CapabilityContribution(tools_by_agent={"root": [second_tool]}),
    )

    assert [tool.name for tool in state.tools_by_agent["root"]] == ["search", "read"]
    assert state.prompt_fragments["knowledge"] == "summary"
    assert state.context_components == [{"type": "memory"}]
    assert state.runtime_resources["knowledge.document_paths"] == ["/doc"]
    assert state.monitoring_metadata["provider"] == "knowledge"
    assert state.warnings == [warning]


def test_merge_capability_contribution_rejects_prompt_conflicts():
    state = AssemblyState(prompt_fragments={"skills": "old"})

    with pytest.raises(CapabilityContributionConflictError, match="prompt fragment"):
        merge_capability_contribution(
            state,
            CapabilityContribution(prompt_fragments={"skills": "new"}),
        )


def test_merge_capability_contribution_rejects_runtime_resource_conflicts():
    state = AssemblyState(runtime_resources={"mcp.docs.headers": {"Authorization": "old"}})

    with pytest.raises(CapabilityContributionConflictError, match="runtime resource"):
        merge_capability_contribution(
            state,
            CapabilityContribution(
                runtime_resources={"mcp.docs.headers": {"Authorization": "new"}},
            ),
        )


def test_merge_capability_contribution_rejects_duplicate_tool_identifier():
    state = AssemblyState()
    merge_capability_contribution(
        state,
        CapabilityContribution(
            tools_by_agent={"root": [ToolSpec(name="search", class_name="SearchTool")]},
        ),
    )

    with pytest.raises(DuplicateToolIdentifierError, match="search"):
        merge_capability_contribution(
            state,
            CapabilityContribution(
                tools_by_agent={"root": [ToolSpec(name="SEARCH", class_name="OtherTool")]},
            ),
        )


@pytest.mark.asyncio
async def test_assemble_agent_run_plan_returns_frozen_plan_not_assembly_state():
    root = _root_agent()
    tool = ToolSpec(name="search", source=ToolSource.KNOWLEDGE)
    providers = [
        Provider(
            name="model",
            priority=10,
            contribution=CapabilityContribution(
                root_agent=root,
                model_configs=[{"cite_name": "main_model"}],
            ),
        ),
        Provider(
            name="tool",
            priority=20,
            depends_on=("model",),
            contribution=CapabilityContribution(
                tools_by_agent={"root": [tool]},
                prompt_fragments={"knowledge": "summary"},
            ),
        ),
    ]

    plan = await assemble_agent_run_plan(
        _request(version_no=None),
        providers,
        current_version_resolver=lambda *_: 3,
    )

    assert plan.request_id == "req-1"
    assert plan.monitoring_metadata["version_no"] == 3
    assert plan.root_agent.tools == [tool]
    assert plan.root_agent.prompt.fragments == {
        "base": "answer clearly",
        "knowledge": "summary",
    }
    assert plan.model_config_list == [{"cite_name": "main_model"}]
    with pytest.raises(Exception, match="frozen"):
        plan.request_id = "other"


@pytest.mark.asyncio
async def test_assemble_agent_run_plan_requires_root_agent():
    with pytest.raises(MissingRootAgentError, match="root agent"):
        await assemble_agent_run_plan(_request(version_no=1), providers=[])


@pytest.mark.asyncio
async def test_assemble_agent_run_plan_rejects_framework_native_runtime_hints():
    NativeSmolagentsTool = type("Tool", (), {"__module__": "smolagents.tools"})
    provider = Provider(
        name="model",
        contribution=CapabilityContribution(
            root_agent=_root_agent(runtime_hints={"native_tool": NativeSmolagentsTool()}),
        ),
    )

    with pytest.raises(Exception, match="framework-native"):
        await assemble_agent_run_plan(_request(version_no=1), [provider])


@pytest.mark.asyncio
async def test_assemble_agent_run_plan_runs_prepare_context_operators():
    added_tool = ToolSpec(name="audit", class_name="AuditTool")
    provider = Provider(
        name="model",
        contribution=CapabilityContribution(
            root_agent=_root_agent(),
            operators=[
                OperatorSpec(
                    name="patch_context",
                    stages={"prepare_context"},
                    config={
                        "result": OperatorResult.ok(
                            context_patch={
                                "prompt_fragments": {"knowledge": "summary"},
                                "context_components": [{"type": "knowledge"}],
                                "runtime_resources": {"knowledge.summary": "summary"},
                                "monitoring_metadata": {"operator.stage": "prepare_context"},
                            },
                            added_tools=[added_tool],
                        )
                    },
                )
            ],
        ),
    )
    registry = OperatorRegistry({"patch_context": lambda spec: PatchOperator(spec)})

    plan = await assemble_agent_run_plan(
        _request(version_no=1),
        [provider],
        operator_registry=registry,
    )

    assert plan.root_agent.prompt.fragments["knowledge"] == "summary"
    assert plan.root_agent.prompt.context_components == [{"type": "knowledge"}]
    assert plan.root_agent.tools == [added_tool]
    assert plan.runtime_resources["knowledge.summary"] == "summary"
    assert plan.monitoring_metadata["operator.stage"] == "prepare_context"
    assert plan.monitoring_metadata["operator_results"][0]["operator"] == "patch_context"


@pytest.mark.asyncio
async def test_assemble_agent_run_plan_blocks_on_prepare_context_failure():
    provider = Provider(
        name="model",
        contribution=CapabilityContribution(
            root_agent=_root_agent(),
            operators=[
                OperatorSpec(
                    name="patch_context",
                    stages={"prepare_context"},
                    config={
                        "result": OperatorResult.blocking_failure("cannot prepare")
                    },
                )
            ],
        ),
    )
    registry = OperatorRegistry({"patch_context": lambda spec: PatchOperator(spec)})

    with pytest.raises(AssemblyError, match="cannot prepare"):
        await assemble_agent_run_plan(
            _request(version_no=1),
            [provider],
            operator_registry=registry,
        )
