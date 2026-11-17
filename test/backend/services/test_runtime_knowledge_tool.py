# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Runtime SDK calls use typed standard knowledge retrieval, never a vector driver."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from contracts.agentos_knowledge import KnowledgeSearchHit
from runtime.knowledge_base.sdk_tool import RuntimeKnowledgeTool


def test_sdk_bridge_preserves_reference_identity_and_has_no_storage_adapter():
    hit = KnowledgeSearchHit(knowledge_id=1, file_id="a" * 32, file_version=2, chunk_id="chunk", content="fact",
                             filename="report.txt", score=.8, score_kind="runtime.hybrid", location={"page_number": 2})
    search = SimpleNamespace(search=AsyncMock(return_value=[hit]))
    bridge = RuntimeKnowledgeTool(search, rerank_model=None)
    result = bridge(query="query", index_names=["kb"], search_mode="accurate", top_k=3)
    row, = result["results"]
    assert row["file_ref"] == {"knowledge_id": 1, "file_id": "a" * 32, "file_version": 2}
    assert row["content"] == "fact" and row["location"] == {"page_number": 2}
    assert row["path_or_url"] == "" and result["total"] == 1
    assert search.search.await_args.kwargs["rerank_model"] is None


def test_sdk_bridge_does_not_retry_or_fallback_on_failure():
    search = SimpleNamespace(search=AsyncMock(side_effect=RuntimeError("controlled")))
    bridge = RuntimeKnowledgeTool(search, rerank_model=None)
    with pytest.raises(RuntimeError, match="controlled"):
        bridge(query="query", index_names=["kb"], search_mode="semantic", top_k=3)
    assert search.search.await_count == 1


def test_sdk_bridge_registers_and_releases_run_cancellation():
    from nexent.core.concurrency.cancellation import RunCancellationScope, RunTerminated

    scope = RunCancellationScope()
    scope.cancel()
    search = SimpleNamespace(search=AsyncMock())
    with pytest.raises(RunTerminated):
        RuntimeKnowledgeTool(search)(query="query", index_names=["kb"], search_mode="hybrid", top_k=3,
                                     cancellation_scope=scope)
    search.search.assert_not_awaited()


def test_active_query_cancellation_exits_and_does_not_start_another_query():
    from nexent.core.concurrency.cancellation import RunCancellationScope, RunTerminated

    scope, closed = RunCancellationScope(), []

    async def blocked(*args, **kwargs):
        try:
            scope.cancel()
            await asyncio.Event().wait()
        finally:
            closed.append(True)

    search = SimpleNamespace(search=AsyncMock(side_effect=blocked))
    with pytest.raises(RunTerminated):
        RuntimeKnowledgeTool(search)(query="query", index_names=["kb"], search_mode="hybrid", top_k=3,
                                     cancellation_scope=scope)
    assert closed == [True] and search.search.await_count == 1


def test_real_sdk_preserves_citation_identity_in_search_content():
    from nexent.core.utils.observer import ProcessType
    from runtime.knowledge_base.tool import KnowledgeBaseSearchTool

    hit = KnowledgeSearchHit(knowledge_id=1, file_id="a" * 32, file_version=2, chunk_id="chunk", content="fact",
                             filename="report.txt", score=.8, score_kind="runtime.hybrid", location={"page_number": 2})
    search = SimpleNamespace(search=AsyncMock(return_value=[hit]))
    events = []
    tool = KnowledgeBaseSearchTool(index_names=["kb"], search_mode="accurate", top_k=3)
    tool.searcher = RuntimeKnowledgeTool(search)
    tool.observer = SimpleNamespace(add_message=lambda *event: events.append(event))
    output = tool.forward("query")
    assert "fact" in output and "[[a1]]" in output
    event, = [event for event in events if event[1] == ProcessType.SEARCH_CONTENT]
    reference, = json.loads(event[2])
    assert reference["cite_index"] == 1 and reference["tool_sign"] == "a"
    assert reference["file_ref"] == {"knowledge_id": 1, "file_id": "a" * 32, "file_version": 2}
    assert reference["location"] == {"page_number": 2}
    assert reference["url"] == "" and not hasattr(tool, "vdb_core")
