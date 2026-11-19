# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""UT-BE-DPR-SUM-META-03 exercise routing summaries and owned worker cancellation."""

import asyncio
from threading import Event
from time import monotonic
from types import SimpleNamespace

import pytest
from management.services.agent.preparation import resources
from management.services.knowledge_base import summary_metadata
from management.services.knowledge_base.summary_metadata import run_summary_metadata
from nexent.core.concurrency import (
    LanePolicy,
    ThreadManager,
    clear_default_thread_manager,
    set_default_thread_manager,
)
from nexent.storage.errors import DeadlineExceeded, OperationCancelled
from nexent.storage.models import OperationContext

from infrastructure.agentos_identity import ServicePrincipal


def tool(names, display=None, kind="KnowledgeBaseSearchTool"):
    return SimpleNamespace(
        class_name=kind,
        metadata={
            "allowed_index_names": names,
            "index_name_to_display_map": display or {},
        },
    )


def test_only_effective_first_whitelist_with_display_names_and_actual_actor(mocker):
    actor = ServicePrincipal("reader", "tenant-a")
    context = OperationContext("routing-unit", monotonic() + 10)
    read = mocker.patch.object(resources, "SummaryMetadata").return_value.read
    read.side_effect = [{"summary": "First"}, {"summary": None}]
    result = resources._build_effective_knowledge_base_summary(
        [
            tool([], kind="Other"),
            tool(["one", "two"], {"one": "One"}),
            tool(["ignored"]),
        ],
        actor,
        context=context,
    )
    assert result == (
        [
            {"index_name": "one", "display_name": "One", "summary": "First"},
            {"index_name": "two", "display_name": "two", "summary": "None"},
        ],
        False,
    )
    assert [call.args for call in read.call_args_list] == [
        ("one", actor),
        ("two", actor),
    ]
    assert all(call.kwargs["context"] is context for call in read.call_args_list)


@pytest.mark.parametrize("include_empty", [False, True])
def test_empty_scope_never_restores_configured_indices(mocker, include_empty):
    factory = mocker.patch.object(resources, "SummaryMetadata")
    context = OperationContext("empty-routing", monotonic() + 10)
    assert resources._build_effective_knowledge_base_summary(
        [tool([]), tool(["ignored"])],
        ServicePrincipal("reader", "tenant-a"),
        context=context,
        include_empty_message=include_empty,
    ) == ([], include_empty)
    factory.assert_not_called()


def test_old_per_summary_failure_keeps_other_routing_data(mocker, caplog):
    read = mocker.patch.object(resources, "SummaryMetadata").return_value.read
    read.side_effect = [ValueError("unavailable"), {"summary": "Second"}]
    context = OperationContext("partial-routing", monotonic() + 10)
    result = resources._build_effective_knowledge_base_summary(
        [tool(["one", "two"])], ServicePrincipal("reader", "tenant-a"), context=context
    )
    assert result == (
        [{"index_name": "two", "display_name": "two", "summary": "Second"}],
        False,
    )
    assert "one" in caplog.text and read.call_count == 2


@pytest.mark.parametrize("error", [DeadlineExceeded(), OperationCancelled()])
def test_parent_cancellation_and_deadline_abort_routing(mocker, error):
    read = mocker.patch.object(resources, "SummaryMetadata").return_value.read
    read.side_effect = error
    with pytest.raises(type(error)):
        resources._build_effective_knowledge_base_summary(
            [tool(["one", "two"])],
            ServicePrincipal("reader", "tenant-a"),
            context=OperationContext("cancel-routing", monotonic() + 10),
        )
    assert read.call_count == 1


@pytest.fixture
async def manager():
    value = ThreadManager(
        service_name="summary-unit",
        lane_policies={"control-io": LanePolicy("control-io", 1, 4)},
    )
    value.start()
    set_default_thread_manager(value)
    try:
        yield value
    finally:
        assert not (await value.shutdown(timeout=3)).stuck_execution_ids
        clear_default_thread_manager(value)


async def test_worker_returns_value_and_cancels_owned_context(manager):
    contexts = []

    def value(context):
        contexts.append(context)
        context.remaining()
        return "result"

    assert await run_summary_metadata("read", value) == "result"
    assert contexts[0].cancelled.is_set()


async def test_root_timeout_logs_once_and_stops_worker(manager, mocker, caplog):
    original = summary_metadata.OperationContext
    mocker.patch.object(
        summary_metadata,
        "OperationContext",
        side_effect=lambda operation, deadline, **kwargs: original(
            operation, monotonic() + 0.05, **kwargs
        ),
    )
    exited = Event()

    def wait(context):
        try:
            context.cancelled.wait(1)
            context.remaining()
        finally:
            exited.set()

    with pytest.raises(DeadlineExceeded):
        await run_summary_metadata("read", wait)
    async with asyncio.timeout(2):
        while not exited.is_set():
            await asyncio.sleep(0.01)
    warnings = [
        r for r in caplog.records if "knowledge_summary_metadata_timeout" in r.message
    ]
    assert len(warnings) == 1 and warnings[0].levelname == "WARNING"
    assert not any(r.levelname == "ERROR" for r in caplog.records)


async def test_client_cancellation_reaches_worker_without_retry(manager):
    started, exited = Event(), Event()
    contexts = []

    def wait(context):
        contexts.append(context)
        started.set()
        try:
            while not context.cancelled.wait(0.01):
                context.remaining()
            context.remaining()
        finally:
            exited.set()

    task = asyncio.create_task(run_summary_metadata("read", wait))
    async with asyncio.timeout(2):
        while not started.is_set():
            await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    async with asyncio.timeout(2):
        while not exited.is_set():
            await asyncio.sleep(0.01)
    assert len(contexts) == 1 and contexts[0].cancelled.is_set()


async def test_current_compiler_passes_actor_and_authorized_summaries_to_context(
    manager, mocker
):
    from management.services.agent.preparation import compiler

    selected = tool(["selected"], {"selected": "Selected"})
    selected.name = "knowledge_search"
    parallel = tool([], kind="ParallelExecutorTool")
    parallel.name = "parallel_executor"
    mocker.patch.object(
        compiler,
        "search_agent_info_by_agent_id",
        return_value={"name": "Agent", "model_ids": []},
    )
    mocker.patch.object(compiler, "query_sub_agent_relations", return_value=[])
    mocker.patch.object(compiler, "_get_external_a2a_agents", return_value=[])
    mocker.patch.object(compiler, "create_tool_config_list", return_value=[selected])
    mocker.patch.object(
        compiler, "build_parallel_executor_tool_config", return_value=parallel
    )
    mocker.patch.object(
        compiler,
        "build_memory_context",
        return_value=SimpleNamespace(user_config=SimpleNamespace(memory_switch=False)),
    )
    mocker.patch.object(compiler, "_get_skills_for_template", return_value=[])
    mocker.patch.object(compiler, "_get_skill_script_tools", return_value=[])
    mocker.patch.object(compiler, "load_agent_prompt_bundle", return_value=None)
    mocker.patch.object(compiler, "AgentPromptComposer")
    mocker.patch.object(compiler, "_select_agent_model_id", return_value=None)
    mocker.patch.object(compiler, "_resolve_context_budget", return_value=None)
    read = mocker.patch.object(resources, "SummaryMetadata").return_value.read
    read.return_value = {"summary": "Authorized summary"}

    class ContextReceived(Exception):
        pass

    assembled = mocker.patch.object(
        compiler, "build_context_inputs", side_effect=ContextReceived()
    )
    with pytest.raises(ContextReceived):
        await compiler.create_agent_config(
            1, "tenant-a", "reader", allow_memory_search=False
        )
    assert assembled.call_args.kwargs["knowledge_base_summaries"] == [
        {
            "index_name": "selected",
            "display_name": "Selected",
            "summary": "Authorized summary",
        }
    ]
    assert read.call_args.args[0] == "selected"
    actor = read.call_args.args[1]
    assert (actor.user_id, actor.tenant_id) == ("reader", "tenant-a")
    assert read.call_args.kwargs["context"].cancelled.is_set()
