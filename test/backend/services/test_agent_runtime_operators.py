import json
import os
import sys
from typing import Any

import pytest

backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../backend"))
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

from consts import const
from services.agent_runtime.events import RuntimeEvent, RuntimeEventType
from services.agent_runtime.models import (
    AgentRunPlan,
    AgentSpec,
    MCPConnectionConfig,
    OperatorSpec,
    PromptBundle,
    RunControl,
    ToolSpec,
    ToolSource,
)
from services.agent_runtime.operators import (
    OPERATOR_STAGES,
    DuplicateOperatorError,
    KnowledgeSummaryOperator,
    MCPConnectionOperator,
    MemoryPersistenceOperator,
    MemoryRetrievalOperator,
    OperatorContext,
    OperatorPatchError,
    OperatorRegistry,
    OperatorResult,
    OperatorRunner,
    SkillFileUploadOperator,
    UnknownOperatorError,
)


class ConfigOperator:
    def __init__(self, spec: OperatorSpec, calls: list[str]):
        self.spec = spec
        self.calls = calls

    def supports(self, context: OperatorContext) -> bool:
        _ = context
        return self.spec.config.get("supports", True)

    def execute(self, context: OperatorContext) -> OperatorResult:
        self.calls.append(self.spec.name)
        result = self.spec.config.get("result")
        if isinstance(result, OperatorResult):
            return result
        return OperatorResult.ok(
            context_patch={
                "metadata": {
                    f"executed.{self.spec.name}": context.stage,
                }
            }
        )


def _operator_registry(calls: list[str]) -> OperatorRegistry:
    registry = OperatorRegistry()
    for name in ("first", "second", "skip", "soft", "block", "on_error", "bad_patch"):
        registry.register(name, lambda spec, calls=calls: ConfigOperator(spec, calls))
    return registry


def _plan() -> AgentRunPlan:
    return AgentRunPlan(
        request_id="req-1",
        runtime_provider=const.AGENT_RUNTIME_PROVIDER_SMOLAGENTS,
        query="hello",
        model_config_list=[],
        root_agent=AgentSpec(
            agent_id=1,
            name="root",
            model_name="main_model",
            max_steps=5,
            prompt=PromptBundle(fragments={"base": "prompt"}),
        ),
        run_control=RunControl(request_id="req-1", user_id="user-1"),
        runtime_resources={"existing": "resource"},
        monitoring_metadata={"agent_id": 1},
    )


def test_operator_stages_are_fixed_lifecycle_contract():
    assert OPERATOR_STAGES == (
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


def test_operator_registry_registers_creates_and_rejects_invalid_names():
    registry = OperatorRegistry()
    registry.register(" first ", lambda spec: ConfigOperator(spec, []))

    assert registry.list_operators() == ["first"]
    assert registry.create(OperatorSpec(name="FIRST", stages={"before_run"})).spec.name == "FIRST"

    with pytest.raises(DuplicateOperatorError):
        registry.register("first", lambda spec: ConfigOperator(spec, []))
    with pytest.raises(UnknownOperatorError):
        registry.create(OperatorSpec(name="missing", stages={"before_run"}))


@pytest.mark.asyncio
async def test_operator_runner_filters_stage_and_supports_then_runs_by_priority():
    calls: list[str] = []
    specs = [
        OperatorSpec(name="second", stages={"prepare_context"}, priority=20),
        OperatorSpec(name="first", stages={"prepare_context"}, priority=10),
        OperatorSpec(name="skip", stages={"prepare_context"}, priority=5, config={"supports": False}),
        OperatorSpec(name="block", stages={"after_run"}, priority=1),
    ]
    context = OperatorContext.from_plan(stage="prepare_context", plan=_plan())

    result = await OperatorRunner(_operator_registry(calls)).run_stage(
        "prepare_context",
        context,
        specs,
    )

    assert result.status == "ok"
    assert calls == ["first", "second"]
    assert result.executed == ["first", "second"]
    assert result.skipped == ["block", "skip"]
    assert context.metadata == {
        "executed.first": "prepare_context",
        "executed.second": "prepare_context",
    }


@pytest.mark.asyncio
async def test_operator_runner_merges_patch_added_values_events_and_diagnostics():
    calls: list[str] = []
    event = RuntimeEvent(type=RuntimeEventType.TOKEN_COUNT, token_usage={"total": 5})
    tool = ToolSpec(name="audit", class_name="AuditTool")
    specs = [
        OperatorSpec(
            name="first",
            stages={"prepare_context"},
            priority=10,
            config={
                "result": OperatorResult.ok(
                    context_patch={
                        "prompt_fragments": {"knowledge": "summary"},
                        "context_components": [{"type": "knowledge"}],
                        "runtime_resources": {"knowledge.summary": "summary"},
                        "monitoring_metadata": {"operator.stage": "prepare_context"},
                    },
                    added_tools=[tool],
                    added_context_components=[{"type": "extra"}],
                    added_metadata={"operator.extra": True},
                    runtime_events=[event],
                )
            },
        )
    ]
    context = OperatorContext.from_plan(stage="prepare_context", plan=_plan())

    result = await OperatorRunner(_operator_registry(calls)).run_stage(
        "prepare_context",
        context,
        specs,
    )

    assert result.status == "ok"
    assert context.prompt_fragments["knowledge"] == "summary"
    assert context.context_components == [{"type": "knowledge"}, {"type": "extra"}]
    assert context.runtime_resources["knowledge.summary"] == "summary"
    assert context.monitoring_metadata["operator.stage"] == "prepare_context"
    assert context.monitoring_metadata["operator.extra"] is True
    assert context.added_tools == [tool]
    assert context.runtime_events == [event]
    assert context.monitoring_metadata["operator_results"][0] == {
        "operator": "first",
        "status": "ok",
        "message": None,
        "patch_keys": [
            "context_components",
            "monitoring_metadata",
            "prompt_fragments",
            "runtime_resources",
        ],
    }


@pytest.mark.asyncio
async def test_operator_runner_soft_failure_records_event_and_continues():
    calls: list[str] = []
    specs = [
        OperatorSpec(
            name="soft",
            stages={"before_run"},
            priority=10,
            config={
                "result": OperatorResult.soft_failure(
                    "memory unavailable",
                    runtime_events=[
                        RuntimeEvent(
                            type=RuntimeEventType.LEGACY_PROCESS,
                            compat_process_type="memory_search",
                            content="memory failed",
                        )
                    ],
                )
            },
        ),
        OperatorSpec(name="second", stages={"before_run"}, priority=20),
    ]
    context = OperatorContext.from_plan(stage="before_run", plan=_plan())

    result = await OperatorRunner(_operator_registry(calls)).run_stage(
        "before_run",
        context,
        specs,
    )

    assert result.status == "soft_failure"
    assert calls == ["soft", "second"]
    assert [event.type for event in context.runtime_events] == [
        RuntimeEventType.LEGACY_PROCESS,
        RuntimeEventType.ERROR,
    ]
    assert context.runtime_events[1].metadata == {
        "operator": "soft",
        "operator_stage": "before_run",
        "operator_status": "soft_failure",
    }


@pytest.mark.asyncio
async def test_operator_runner_blocking_failure_stops_stage_and_enters_on_error():
    calls: list[str] = []
    specs = [
        OperatorSpec(
            name="block",
            stages={"before_run"},
            priority=10,
            config={"result": OperatorResult.blocking_failure("required MCP failed")},
        ),
        OperatorSpec(name="second", stages={"before_run"}, priority=20),
        OperatorSpec(
            name="on_error",
            stages={"on_error"},
            priority=1,
            config={
                "result": OperatorResult.ok(
                    context_patch={"monitoring_metadata": {"on_error.called": True}}
                )
            },
        ),
    ]
    context = OperatorContext.from_plan(stage="before_run", plan=_plan())

    result = await OperatorRunner(_operator_registry(calls)).run_stage(
        "before_run",
        context,
        specs,
    )

    assert result.status == "blocking_failure"
    assert calls == ["block", "on_error"]
    assert "second" not in result.executed
    assert context.runtime_events[0].metadata == {
        "operator": "block",
        "operator_stage": "before_run",
        "operator_status": "blocking_failure",
    }


@pytest.mark.asyncio
async def test_operator_runner_rejects_illegal_context_patch():
    calls: list[str] = []
    specs = [
        OperatorSpec(
            name="bad_patch",
            stages={"prepare_context"},
            config={
                "result": OperatorResult.ok(
                    context_patch={"runtime_provider": "openjiuwen"}
                )
            },
        )
    ]
    context = OperatorContext.from_plan(stage="prepare_context", plan=_plan())

    result = await OperatorRunner(_operator_registry(calls)).run_stage(
        "prepare_context",
        context,
        specs,
    )

    assert result.status == "blocking_failure"
    assert result.results[0].status == "blocking_failure"
    assert "runtime_provider" in result.results[0].message
    assert context.runtime_resources == {"existing": "resource"}


def test_operator_patch_error_is_public_for_direct_validation():
    _ = OperatorPatchError


@pytest.mark.asyncio
async def test_mcp_connection_operator_blocks_required_connection_failure():
    registry = OperatorRegistry({
        "mcp_connection": lambda spec: MCPConnectionOperator(spec)
    })
    context = OperatorContext.from_plan(
        stage="before_run",
        plan=_plan_with_mcp_connections([
            MCPConnectionConfig(
                name="docs",
                url="https://mcp.example/sse",
                transport="sse",
                required=True,
            )
        ]),
    )

    result = await OperatorRunner(registry).run_stage(
        "before_run",
        context,
        [
            OperatorSpec(
                name="mcp_connection",
                stages={"before_run"},
                config={"connection_results": {"docs": "timeout"}},
            )
        ],
    )

    assert result.status == "blocking_failure"
    assert result.results[0].message == "Required MCP server 'docs' failed: timeout"
    assert context.runtime_events[0].metadata == {
        "operator": "mcp_connection",
        "mcp_server": "docs",
        "mcp_required": True,
    }


@pytest.mark.asyncio
async def test_mcp_connection_operator_soft_fails_optional_connection_failure():
    registry = OperatorRegistry({
        "mcp_connection": lambda spec: MCPConnectionOperator(spec)
    })
    context = OperatorContext.from_plan(
        stage="before_run",
        plan=_plan_with_mcp_connections([
            MCPConnectionConfig(
                name="optional-docs",
                url="https://mcp.example/mcp",
                transport="streamable-http",
                required=False,
            )
        ]),
    )

    result = await OperatorRunner(registry).run_stage(
        "before_run",
        context,
        [
            OperatorSpec(
                name="mcp_connection",
                stages={"before_run"},
                config={"connection_results": {"optional-docs": False}},
            )
        ],
    )

    assert result.status == "soft_failure"
    assert context.runtime_resources["mcp.disabled_servers"] == ["optional-docs"]
    assert context.monitoring_metadata["mcp.optional_failures"] == ["optional-docs"]
    assert context.runtime_events[0].metadata == {
        "operator": "mcp_connection",
        "mcp_server": "optional-docs",
        "mcp_required": False,
    }


@pytest.mark.asyncio
async def test_mcp_connection_operator_removes_optional_failed_mcp_visibility():
    registry = OperatorRegistry({
        "mcp_connection": lambda spec: MCPConnectionOperator(spec)
    })
    context = OperatorContext.from_plan(
        stage="before_run",
        plan=_plan_with_mcp_connections(
            [
                MCPConnectionConfig(
                    name="optional-docs",
                    url="https://mcp.example/mcp",
                    transport="streamable-http",
                    required=False,
                ),
                MCPConnectionConfig(
                    name="required-docs",
                    url="https://mcp.example/sse",
                    transport="sse",
                    required=True,
                ),
            ],
            tools=[
                ToolSpec(name="local_search", source=ToolSource.LOCAL),
                ToolSpec(
                    name="optional_docs_search",
                    source=ToolSource.MCP,
                    usage="optional-docs",
                    class_name="search",
                ),
                ToolSpec(
                    name="required_docs_search",
                    source=ToolSource.MCP,
                    usage="required-docs",
                    class_name="search",
                ),
            ],
            prompt_fragments={
                "base": "prompt",
                "mcp.optional-docs.summary": {
                    "source": "mcp",
                    "mcp_server": "optional-docs",
                    "content": "optional docs",
                },
                "mcp.required-docs.summary": {
                    "source": "mcp",
                    "mcp_server": "required-docs",
                    "content": "required docs",
                },
            },
            context_components=[
                {"type": "app", "content": "keep"},
                {
                    "type": "mcp",
                    "source": "mcp",
                    "mcp_server": "optional-docs",
                    "content": "optional context",
                },
                {
                    "type": "mcp",
                    "source": "mcp",
                    "mcp_server": "required-docs",
                    "content": "required context",
                },
            ],
        ),
    )

    result = await OperatorRunner(registry).run_stage(
        "before_run",
        context,
        [
            OperatorSpec(
                name="mcp_connection",
                stages={"before_run"},
                config={"connection_results": {"optional-docs": False}},
            )
        ],
    )

    assert result.status == "soft_failure"
    assert [tool.name for tool in context.tools] == [
        "local_search",
        "required_docs_search",
    ]
    assert context.prompt_fragments == {
        "base": "prompt",
        "mcp.required-docs.summary": {
            "source": "mcp",
            "mcp_server": "required-docs",
            "content": "required docs",
        },
    }
    assert context.context_components == [
        {"type": "app", "content": "keep"},
        {
            "type": "mcp",
            "source": "mcp",
            "mcp_server": "required-docs",
            "content": "required context",
        },
    ]
    assert context.runtime_resources["mcp.disabled_servers"] == ["optional-docs"]
    assert context.monitoring_metadata["mcp.optional_failures"] == ["optional-docs"]
    assert context.monitoring_metadata["mcp.removed_tools"] == [
        "optional_docs_search"
    ]
    assert context.monitoring_metadata["mcp.removed_prompt_fragments"] == [
        "mcp.optional-docs.summary"
    ]
    assert context.monitoring_metadata["mcp.removed_context_components"] == 1


@pytest.mark.asyncio
async def test_skill_file_upload_operator_uploads_payload_and_emits_artifact(tmp_path):
    registry = OperatorRegistry({
        "skill_file_upload": lambda spec: SkillFileUploadOperator(spec)
    })
    generated_file = tmp_path / "report.txt"
    generated_file.write_text("report", encoding="utf-8")
    upload_calls: list[dict[str, Any]] = []

    def fake_uploader(**kwargs: Any) -> dict[str, Any]:
        upload_calls.append({
            "file_name": kwargs["file_name"],
            "prefix": kwargs["prefix"],
            "file_size": kwargs["file_size"],
            "content": kwargs["file_obj"].read().decode("utf-8"),
        })
        return {
            "success": True,
            "object_name": "skill-files/user-1/report.txt",
            "url": "s3://bucket/skill-files/user-1/report.txt",
            "presigned_url": "https://download.example/report.txt",
            "file_size": kwargs["file_size"],
        }

    context = OperatorContext.from_plan(
        stage="after_tool_call",
        plan=_plan(),
        tool_output=(
            "created "
            + json.dumps(
                {
                    "absolute_path": str(generated_file),
                    "file_name": "report.txt",
                    "mime_type": "text/plain",
                }
            )
        ),
    )

    result = await OperatorRunner(registry).run_stage(
        "after_tool_call",
        context,
        [
            OperatorSpec(
                name="skill_file_upload",
                stages={"after_tool_call"},
                config={
                    "allowed_roots": [str(tmp_path)],
                    "uploader": fake_uploader,
                },
            )
        ],
    )

    assert result.status == "ok"
    assert upload_calls == [
        {
            "file_name": "report.txt",
            "prefix": "skill-files/user-1",
            "file_size": 6,
            "content": "report",
        }
    ]
    assert context.runtime_events[0].type == RuntimeEventType.ARTIFACT_CREATED
    assert context.runtime_events[0].artifact == {
        "status": "success",
        "file_name": "report.txt",
        "absolute_path": str(generated_file),
        "object_name": "skill-files/user-1/report.txt",
        "preview_url": "https://download.example/report.txt",
        "url": "s3://bucket/skill-files/user-1/report.txt",
        "presigned_url": "https://download.example/report.txt",
        "mime_type": "text/plain",
        "file_size": 6,
    }
    assert context.monitoring_metadata["skill_file_uploads"] == [
        context.runtime_events[0].artifact
    ]


@pytest.mark.asyncio
async def test_skill_file_upload_operator_rejects_payload_outside_allowed_roots(tmp_path):
    registry = OperatorRegistry({
        "skill_file_upload": lambda spec: SkillFileUploadOperator(spec)
    })
    generated_file = tmp_path / "report.txt"
    generated_file.write_text("report", encoding="utf-8")
    upload_calls: list[dict[str, Any]] = []
    context = OperatorContext.from_plan(
        stage="after_tool_call",
        plan=_plan(),
        tool_output={"absolute_path": str(generated_file), "file_name": "report.txt"},
    )

    result = await OperatorRunner(registry).run_stage(
        "after_tool_call",
        context,
        [
            OperatorSpec(
                name="skill_file_upload",
                stages={"after_tool_call"},
                config={
                    "allowed_roots": [str(tmp_path / "allowed")],
                    "uploader": lambda **kwargs: upload_calls.append(kwargs),
                },
            )
        ],
    )

    assert result.status == "soft_failure"
    assert upload_calls == []
    assert context.runtime_events[0].type == RuntimeEventType.ERROR
    assert context.monitoring_metadata["skill_file_uploads"] == []
    assert context.monitoring_metadata["skill_file_upload_failures"] == [
        {
            "reason": "unsafe_path",
            "absolute_path": str(generated_file),
        }
    ]


@pytest.mark.asyncio
async def test_skill_file_upload_operator_extracts_payloads_from_runtime_events(tmp_path):
    registry = OperatorRegistry({
        "skill_file_upload": lambda spec: SkillFileUploadOperator(spec)
    })
    generated_file = tmp_path / "event-report.txt"
    generated_file.write_text("event report", encoding="utf-8")
    context = OperatorContext.from_plan(
        stage="after_run",
        plan=_plan(),
        runtime_events=[
            RuntimeEvent(
                type=RuntimeEventType.LEGACY_PROCESS,
                compat_process_type="execution_logs",
                content=json.dumps({"absolute_path": str(generated_file)}),
            )
        ],
    )

    result = await OperatorRunner(registry).run_stage(
        "after_run",
        context,
        [
            OperatorSpec(
                name="skill_file_upload",
                stages={"after_run"},
                config={
                    "allowed_roots": [str(tmp_path)],
                    "uploader": lambda **kwargs: {
                        "success": True,
                        "object_name": "skill-files/user-1/event-report.txt",
                        "url": "s3://bucket/skill-files/user-1/event-report.txt",
                        "file_size": kwargs["file_size"],
                    },
                },
            )
        ],
    )

    assert result.status == "ok"
    assert context.runtime_events[-1].type == RuntimeEventType.ARTIFACT_CREATED
    assert context.runtime_events[-1].artifact["file_name"] == "event-report.txt"


@pytest.mark.asyncio
async def test_skill_file_upload_operator_soft_fails_upload_errors(tmp_path):
    registry = OperatorRegistry({
        "skill_file_upload": lambda spec: SkillFileUploadOperator(spec)
    })
    generated_file = tmp_path / "report.txt"
    generated_file.write_text("report", encoding="utf-8")
    context = OperatorContext.from_plan(
        stage="after_tool_call",
        plan=_plan(),
        tool_output={"absolute_path": str(generated_file), "file_name": "report.txt"},
    )

    result = await OperatorRunner(registry).run_stage(
        "after_tool_call",
        context,
        [
            OperatorSpec(
                name="skill_file_upload",
                stages={"after_tool_call"},
                config={
                    "allowed_roots": [str(tmp_path)],
                    "uploader": lambda **kwargs: {
                        "success": False,
                        "error": "object storage unavailable",
                    },
                },
            )
        ],
    )

    assert result.status == "soft_failure"
    assert context.monitoring_metadata["skill_file_uploads"] == []
    assert context.monitoring_metadata["skill_file_upload_failures"] == [
        {
            "reason": "upload_failed",
            "absolute_path": str(generated_file),
            "error": "object storage unavailable",
        }
    ]
    assert context.runtime_events[0].type == RuntimeEventType.ERROR


@pytest.mark.asyncio
async def test_memory_retrieval_operator_emits_events_and_patches_context():
    registry = OperatorRegistry({
        "memory_retrieval": lambda spec: MemoryRetrievalOperator(spec)
    })
    captured_kwargs: dict[str, Any] = {}

    async def retriever(**kwargs: Any) -> dict[str, Any]:
        captured_kwargs.update(kwargs)
        return {"results": [{"content": "likes concise answers"}]}

    context = OperatorContext.from_plan(
        stage="prepare_context",
        plan=_plan(),
        runtime_resources={
            "memory.config": {"provider": "mem0"},
            "memory.user_config": {
                "memory_switch": True,
                "agent_share_option": "always",
                "disable_agent_ids": [],
                "disable_user_agent_ids": [],
            },
            "memory.tenant_id": "tenant-1",
            "memory.user_id": "user-1",
            "memory.agent_id": "1",
            "memory.retrieval_levels": ["tenant", "user"],
        },
        context_components=[{"type": "app", "content": "keep"}],
    )

    result = await OperatorRunner(registry).run_stage(
        "prepare_context",
        context,
        [
            OperatorSpec(
                name="memory_retrieval",
                stages={"prepare_context"},
                config={"retriever": retriever},
            )
        ],
    )

    assert result.status == "ok"
    assert captured_kwargs["query_text"] == "hello"
    assert captured_kwargs["memory_levels"] == ["tenant", "user"]
    assert context.prompt_fragments == {
        "base": "prompt",
        "memory_list": '[{"content": "likes concise answers"}]',
    }
    assert context.context_components == [
        {"type": "app", "content": "keep"},
        {
            "type": "memory",
            "items": [{"content": "likes concise answers"}],
            "query": "hello",
            "levels": ["tenant", "user"],
            "retrieval_status": "ok",
        },
    ]
    assert [event.content for event in context.runtime_events] == [
        "memory_search_started",
        "memory_search_done",
    ]
    assert all(
        event.compat_process_type == "memory_search"
        for event in context.runtime_events
    )
    assert context.monitoring_metadata["memory.retrieval_status"] == "ok"
    assert context.runtime_resources["memory.items"] == [
        {"content": "likes concise answers"}
    ]


@pytest.mark.asyncio
async def test_memory_retrieval_operator_soft_fails_and_injects_empty_context():
    registry = OperatorRegistry({
        "memory_retrieval": lambda spec: MemoryRetrievalOperator(spec)
    })
    context = OperatorContext.from_plan(
        stage="prepare_context",
        plan=_plan(),
        runtime_resources={
            "memory.config": {"provider": "mem0"},
            "memory.user_config": {"memory_switch": True},
            "memory.tenant_id": "tenant-1",
            "memory.user_id": "user-1",
            "memory.agent_id": "1",
        },
        context_components=[{"type": "memory", "items": [{"content": "stale"}]}],
    )

    result = await OperatorRunner(registry).run_stage(
        "prepare_context",
        context,
        [
            OperatorSpec(
                name="memory_retrieval",
                stages={"prepare_context"},
                config={
                    "retriever": lambda **kwargs: (_ for _ in ()).throw(
                        RuntimeError("mem0 down")
                    )
                },
            )
        ],
    )

    assert result.status == "soft_failure"
    assert context.prompt_fragments["memory_list"] == "[]"
    assert context.context_components == [
        {
            "type": "memory",
            "items": [],
            "query": "hello",
            "levels": ["tenant", "user", "user_agent"],
            "retrieval_status": "soft_failure",
            "error": "mem0 down",
        }
    ]
    assert [event.content for event in context.runtime_events[:2]] == [
        "memory_search_started",
        "memory_search_failed",
    ]
    assert context.runtime_events[2].type == RuntimeEventType.ERROR
    assert context.monitoring_metadata["memory.retrieval_status"] == "soft_failure"


@pytest.mark.asyncio
async def test_knowledge_summary_operator_patches_prompt_and_context():
    registry = OperatorRegistry({
        "knowledge_summary": lambda spec: KnowledgeSummaryOperator(spec)
    })
    context = OperatorContext.from_plan(
        stage="prepare_context",
        plan=_plan(),
        runtime_resources={
            "knowledge.kb_ids": ["kb-index"],
            "knowledge.index_name_to_display_map": {"kb-index": "Handbook"},
        },
        context_components=[{"type": "app", "content": "keep"}],
    )

    result = await OperatorRunner(registry).run_stage(
        "prepare_context",
        context,
        [
            OperatorSpec(
                name="knowledge_summary",
                stages={"prepare_context"},
                config={
                    "summary_resolver": lambda index_name: {
                        "summary": "Product facts"
                    }
                },
            )
        ],
    )

    assert result.status == "ok"
    assert context.prompt_fragments["knowledge_base_summary"] == (
        "**Handbook**: Product facts\n\n"
    )
    assert context.context_components == [
        {"type": "app", "content": "keep"},
        {
            "type": "knowledge_summary",
            "summary": "**Handbook**: Product facts\n\n",
            "kb_ids": ["kb-index"],
            "status": "ok",
        },
    ]
    assert context.runtime_resources["knowledge.summary_status"] == "ok"
    assert context.monitoring_metadata["knowledge.summary_status"] == "ok"


@pytest.mark.asyncio
async def test_knowledge_summary_operator_soft_fails_resolver_errors():
    registry = OperatorRegistry({
        "knowledge_summary": lambda spec: KnowledgeSummaryOperator(spec)
    })
    context = OperatorContext.from_plan(
        stage="prepare_context",
        plan=_plan(),
        runtime_resources={
            "knowledge.kb_ids": ["kb-index"],
            "knowledge.summary": "**Handbook**: stale summary\n\n",
        },
    )

    result = await OperatorRunner(registry).run_stage(
        "prepare_context",
        context,
        [
            OperatorSpec(
                name="knowledge_summary",
                stages={"prepare_context"},
                config={
                    "summary_resolver": lambda index_name: (_ for _ in ()).throw(
                        RuntimeError("summary down")
                    )
                },
            )
        ],
    )

    assert result.status == "soft_failure"
    assert context.prompt_fragments["knowledge_base_summary"] == (
        "**Handbook**: stale summary\n\n"
    )
    assert context.context_components == [
        {
            "type": "knowledge_summary",
            "summary": "**Handbook**: stale summary\n\n",
            "kb_ids": ["kb-index"],
            "status": "soft_failure",
            "error": "summary down",
        }
    ]
    assert context.monitoring_metadata["knowledge.summary_status"] == "soft_failure"
    assert context.monitoring_metadata["knowledge.summary_error"] == "summary down"
    assert context.runtime_events[0].type == RuntimeEventType.ERROR


@pytest.mark.asyncio
async def test_memory_persistence_operator_writes_final_answer_to_allowed_levels():
    registry = OperatorRegistry({
        "memory_persistence": lambda spec: MemoryPersistenceOperator(spec)
    })
    captured_kwargs: dict[str, Any] = {}

    async def persistence_func(**kwargs: Any) -> dict[str, Any]:
        captured_kwargs.update(kwargs)
        return {"results": [{"event": "ADD", "memory": "answer"}]}

    context = OperatorContext.from_plan(
        stage="after_run",
        plan=_plan(),
        final_answer="done",
        runtime_resources={
            "memory.config": {"provider": "mem0"},
            "memory.user_config": {
                "memory_switch": True,
                "agent_share_option": "always",
                "disable_agent_ids": [],
                "disable_user_agent_ids": ["other"],
            },
            "memory.tenant_id": "tenant-1",
            "memory.user_id": "user-1",
            "memory.agent_id": "1",
        },
    )

    result = await OperatorRunner(registry).run_stage(
        "after_run",
        context,
        [
            OperatorSpec(
                name="memory_persistence",
                stages={"after_run"},
                config={"persistence_func": persistence_func},
            )
        ],
    )

    assert result.status == "ok"
    assert captured_kwargs["messages"] == [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "done"},
    ]
    assert captured_kwargs["memory_levels"] == ["agent", "user_agent"]
    assert context.runtime_events[0].content == "memory_persistence_done"
    assert context.monitoring_metadata["memory.persistence_status"] == "ok"
    assert context.monitoring_metadata["memory.persistence_count"] == 1


@pytest.mark.asyncio
async def test_memory_persistence_operator_soft_fails_write_errors():
    registry = OperatorRegistry({
        "memory_persistence": lambda spec: MemoryPersistenceOperator(spec)
    })
    context = OperatorContext.from_plan(
        stage="after_run",
        plan=_plan(),
        final_answer="done",
        runtime_resources={
            "memory.config": {"provider": "mem0"},
            "memory.user_config": {
                "memory_switch": True,
                "agent_share_option": "always",
                "disable_agent_ids": [],
                "disable_user_agent_ids": [],
            },
            "memory.tenant_id": "tenant-1",
            "memory.user_id": "user-1",
            "memory.agent_id": "1",
        },
    )

    result = await OperatorRunner(registry).run_stage(
        "after_run",
        context,
        [
            OperatorSpec(
                name="memory_persistence",
                stages={"after_run"},
                config={
                    "persistence_func": lambda **kwargs: (_ for _ in ()).throw(
                        RuntimeError("write failed")
                    )
                },
            )
        ],
    )

    assert result.status == "soft_failure"
    assert context.runtime_events[0].content == "memory_persistence_failed"
    assert context.runtime_events[1].type == RuntimeEventType.ERROR
    assert context.monitoring_metadata["memory.persistence_status"] == "soft_failure"
    assert context.monitoring_metadata["memory.persistence_error"] == "write failed"


def _plan_with_mcp_connections(
    mcp_connections: list[MCPConnectionConfig],
    *,
    tools: list[ToolSpec] | None = None,
    prompt_fragments: dict[str, Any] | None = None,
    context_components: list[Any] | None = None,
) -> AgentRunPlan:
    plan = _plan()
    prompt = plan.root_agent.prompt.model_copy(
        update={
            "fragments": (
                prompt_fragments
                if prompt_fragments is not None
                else plan.root_agent.prompt.fragments
            ),
            "context_components": (
                context_components
                if context_components is not None
                else plan.root_agent.prompt.context_components
            ),
        },
        deep=True,
    )
    root_agent = plan.root_agent.model_copy(
        update={
            "tools": tools if tools is not None else plan.root_agent.tools,
            "prompt": prompt,
        },
        deep=True,
    )
    return plan.model_copy(
        update={
            "mcp_connections": mcp_connections,
            "root_agent": root_agent,
        },
        deep=True,
    )
