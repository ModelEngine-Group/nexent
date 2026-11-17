# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Keep runtime time context separate from the captured user query."""

import asyncio
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import Request

from .test_agent_subscription_lifecycle import lifecycle as lifecycle
from .test_core_service_slimming import dependency, load_source


@pytest.fixture
def run_context(monkeypatch):
    manager = SimpleNamespace(bind_agent_context=Mock(side_effect=lambda value: value))
    memory = Mock(return_value=SimpleNamespace(user_config=SimpleNamespace(memory_switch=False)))
    dependency(monkeypatch, "infrastructure.observability.bootstrap", monitoring_manager=manager)
    dependency(monkeypatch, "nexent.monitor.local_content", local_capture_enabled=lambda _manager: False)
    dependency(monkeypatch, "management.services.configuration.user.memory", build_memory_context=memory)
    dependency(
        monkeypatch, "management.services.monitor.identity",
        resolve_monitoring_user_email=lambda *_args: "user@example.test",
    )
    module = load_source(
        monkeypatch, "backend/management/services/agent/context.py", "trajectory_user_query_context",
    )
    monkeypatch.setattr(module, "AgentRunMetadata", SimpleNamespace)
    return SimpleNamespace(module=module, manager=manager, memory=memory)


@pytest.mark.asyncio
@pytest.mark.parametrize("debug", [False, True], ids=["chat", "debug"])
@pytest.mark.parametrize("query,zone,language,marker", [
    ("计算1到20", "Asia/Shanghai", "zh", "[当前时间:"),
    ("Calculate 1 to 20", "UTC", "en", "[Current time:"),
    ("  原始输入\n", None, "zh", None),
    ("计算1到20", "invalid/zone", "zh", None),
    ("", "Asia/Shanghai", "zh", None),
    ("用户提供的日期\n\n[当前时间: 2026-01-01 00:00:00]", "Asia/Shanghai", "zh", None),
])
async def test_stream_captures_query_before_runtime_time(
    lifecycle, run_context, monkeypatch, query, zone, language, marker, debug,
):
    env = lifecycle
    env.request.query = query
    env.request.is_debug = debug
    monkeypatch.setattr(env.service, "prepend_current_time", run_context.module.prepend_current_time)
    monkeypatch.setattr(env.service, "build_agent_run_context", run_context.module.build_agent_run_context)
    monkeypatch.setattr(env.service, "_resolve_user_tenant_language", lambda **_kwargs: ("u", "t", language))
    executed_queries = []

    async def source(request, **_kwargs):
        executed_queries.append(request.query)
        env.channel.complete()
        env.future.set_result(None)
        yield "data: answer\n\n"

    monkeypatch.setattr(env.service, "generate_stream", source)
    headers = [(b"x-user-timezone", zone.encode())] if zone else []
    response = await env.service.run_agent_stream(
        env.request, Request({"type": "http", "headers": headers}), "u",
    )
    _chunks = [chunk async for chunk in response.body_iterator]
    tasks = list(env.service._agent_stream_producer_tasks)
    if tasks:
        await asyncio.wait_for(asyncio.gather(*tasks), timeout=1)
    run_context.manager.bind_agent_context.assert_called_once()
    metadata = run_context.manager.bind_agent_context.call_args.args[0]
    assert metadata.query == query
    assert executed_queries == [env.request.query]
    if marker:
        assert env.request.query.startswith(query + "\n\n" + marker)
        assert env.request.query != query
    else:
        assert env.request.query == query


@pytest.mark.parametrize("options,expected", [
    ({}, "execution query"),
    ({"user_query": None}, "execution query"),
    ({"user_query": "用户输入"}, "用户输入"),
    ({"user_query": ""}, ""),
])
def test_run_context_original_query_and_background_fallback(run_context, options, expected):
    request = SimpleNamespace(
        agent_id=1, conversation_id=123, query="execution query",
        is_debug=False, history=[], minio_files=[],
    )
    result = run_context.module.build_agent_run_context(request, "u", "t", "zh", extra_metadata={}, **options)
    assert result.metadata.query == expected
    assert request.query == "execution query"


def test_run_context_preparation_error_does_not_bind_query(run_context):
    run_context.memory.side_effect = RuntimeError("controlled preparation failure")
    request = SimpleNamespace(agent_id=1, query="execution query", is_debug=False)
    with pytest.raises(RuntimeError, match="controlled preparation failure"):
        run_context.module.build_agent_run_context(
            request, "u", "t", "zh", extra_metadata={}, user_query="用户输入",
        )
    run_context.manager.bind_agent_context.assert_not_called()
    assert request.query == "execution query"
