# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Check resource search input through the NL2Agent HTTP and MCP runtime."""

import json
import socket
from contextlib import contextmanager
from unittest.mock import AsyncMock
from urllib.parse import urlparse

import pytest
from sqlalchemy import inspect, select

from management.db.models import AgentInfo
from model_controls.runtime import runtime_fixture
from management.services.agent import nl2agent as nl2agent_service

pytestmark = [pytest.mark.case_id("NL2A-INPUT-D3-001"), pytest.mark.stage("D3")]


def draft_rows(runtime):
    with runtime.storage["sessions"]() as session:
        statement = select(AgentInfo).where(AgentInfo.agent_id == runtime.agent_id)
        return [
            tuple(getattr(row, column.name) for column in AgentInfo.__table__.columns)
            for row in session.scalars(statement)
        ]


def search(runtime, requirements):
    actions = iter([
        f"<code>print(nl2a_search_installed_resources(agent_id={runtime.agent_id}, "
        f"requirements={requirements!r}))</code>",
        f"<code>print(nl2a_search_uninstalled_resources(agent_id={runtime.agent_id}, "
        f"requirements={requirements!r}, exclude_refs=[]))</code>",
        "<final_answer>Fixture search finished.</final_answer>",
    ])
    runtime.provider.responder = lambda body: next(actions) if body.get("stream") else "Fixture search"
    response = runtime.post("/api/agent/nl2agent/run", query="Only recommend resources for these capabilities.")
    assert response.status_code == 200, response.text
    events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
    assert events[-1]["type"] == "final_answer"
    assert not any(event["type"] in {"error", "nl2a_state"} for event in events)
    assert runtime.runs[-1].stop_event.is_set()
    assert next(actions, None) is None
    receipts = []
    for event in events:
        if event["type"] == "execution_logs":
            try:
                receipt = json.loads(event["content"])
            except (TypeError, ValueError):
                continue
            if isinstance(receipt, dict) and receipt.get("status") in {"success", "error"}:
                receipts.append(receipt)
    assert len(receipts) == 2, events
    return receipts


@contextmanager
def owned_runtime(monkeypatch):
    runtime = None
    try:
        with runtime_fixture(monkeypatch) as runtime:
            yield runtime
    finally:
        if runtime is not None:
            assert not inspect(runtime.storage["engine"]).has_schema(runtime.storage["schema"])
            assert not runtime.provider.thread.is_alive()
            for run in runtime.runs:
                assert run.thread_future.done()
                mcp = urlparse(run.mcp_host[0]["url"])
                with socket.socket() as client:
                    client.settimeout(1)
                    assert client.connect_ex((mcp.hostname, mcp.port)) != 0


def test_search_reports_limit_and_accepts_complete_batch(monkeypatch):
    monkeypatch.setattr(nl2agent_service, "_load_installed_resource_catalog", AsyncMock(return_value=[]))
    monkeypatch.setattr(nl2agent_service, "_load_internal_uninstalled_resource_catalog", AsyncMock(return_value=[]))
    # The legacy run preparation also reads installed resources. Observe search
    # dispatch separately from that read to prove that invalid tools never search.
    installed = AsyncMock(wraps=nl2agent_service.search_installed_resources_impl)
    installable = AsyncMock(wraps=nl2agent_service.search_uninstalled_resources_impl)
    monkeypatch.setattr(nl2agent_service, "search_installed_resources_impl", installed)
    monkeypatch.setattr(nl2agent_service, "search_uninstalled_resources_impl", installable)
    requirements = [{"requirement_id": f"req-{i}", "query": f"Capability {i}"} for i in range(9)]

    with owned_runtime(monkeypatch) as runtime:
        before = draft_rows(runtime)
        assert len(before) == 1
        for receipt in search(runtime, requirements):
            assert receipt["status"] == "error"
            assert receipt["code"] == "requirements_limit_exceeded"
            assert receipt["retryable"] is False
            assert receipt["max_requirements"] == 8
        installed.assert_not_awaited()
        installable.assert_not_awaited()
        assert draft_rows(runtime) == before

        supported = requirements[:8]
        for receipt in search(runtime, supported):
            assert receipt == {
                "status": "success",
                "candidates": [],
                "uncovered_requirement_ids": [item["requirement_id"] for item in supported],
            }
        installed.assert_awaited_once()
        installable.assert_awaited_once()
        assert draft_rows(runtime) == before


def test_search_reads_later_repository_pages_and_rejects_stalled_cursor(monkeypatch):
    from management.services.repository.mcp import service as mcp_repository
    from management.services.skill import transfer
    from services import skill_repository_service

    page_calls = []
    cursor_calls = []
    stall = False

    def skill_page(tenant_id, *, user_id, status, page, page_size):
        assert tenant_id and user_id and status == "shared" and page_size == 100
        page_calls.append(page)
        ids = range(1 + 100 * (page - 1), min(1 + 100 * page, 302))
        return {
            "items": [{"skill_repository_id": i, "name": "rain-sensor" if i == 301 else "filler"}
                      for i in ids],
            "pagination": {"total_pages": 4},
        }

    async def mcp_page(*, tenant_id, user_id, cursor, limit):
        assert tenant_id and user_id and limit == 100
        cursor_calls.append(cursor)
        start = int(cursor or "0")
        ids = range(start + 1, min(start + 101, 302))
        return {
            "items": [{
                "marketId": i, "name": "tide-monitor" if i == 301 else "filler",
                "transportType": "url", "serverUrl": "https://fixture.invalid/mcp",
            } for i in ids],
            "nextCursor": "100" if stall else str(start + 100) if start < 300 else None,
        }

    monkeypatch.setattr(nl2agent_service, "_load_installed_resource_catalog", AsyncMock(return_value=[]))
    monkeypatch.setattr(transfer, "get_official_skills_with_status", lambda **kwargs: [])
    monkeypatch.setattr(skill_repository_service, "list_skill_repository_listings_impl", skill_page)
    monkeypatch.setattr(mcp_repository, "list_community_mcp_services", mcp_page)
    requirements = [
        {"requirement_id": "rain", "query": "rain-sensor", "resource_name_hint": "rain-sensor"},
        {"requirement_id": "tide", "query": "tide-monitor", "resource_name_hint": "tide-monitor"},
    ]

    with owned_runtime(monkeypatch) as runtime:
        before = draft_rows(runtime)
        _, receipt = search(runtime, requirements)
        assert receipt["status"] == "success"
        assert receipt["uncovered_requirement_ids"] == []
        assert {item["candidate_ref"] for item in receipt["candidates"]} == {
            "tenant_skill_repository:301", "tenant_mcp_repository:301",
        }
        assert page_calls == [1, 2, 3, 4]
        assert cursor_calls == [None, "100", "200", "300"]
        assert draft_rows(runtime) == before

        stall = True
        cursor_calls.clear()
        _, receipt = search(runtime, requirements)
        assert receipt["status"] == "error"
        assert receipt["code"] == "resource_search_failed"
        assert receipt["retryable"] is True
        assert receipt["candidates"] == []
        assert cursor_calls == [None, "100"]
        assert draft_rows(runtime) == before
