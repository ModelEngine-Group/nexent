# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Check D5 performance result accounting without starting a shared deployment."""

import asyncio
import json
from pathlib import Path
import runpy
from unittest.mock import patch

import httpx
import pytest
from fastapi import FastAPI

ROOT = Path(__file__).resolve().parents[3]
LOAD = runpy.run_path(str(ROOT / "cases/PERF-02/load.py"))
UPGRADE = runpy.run_path(str(ROOT / "cases/DB-MIGRATION-D5-001/upgrade.py"))
AGENT = {"agent_id": 1, "model_id": 100}


def test_upgrade_deadline_covers_multiple_steps():
    with patch("time.monotonic", side_effect=[100, 101, 399.5, 400]):
        deadline = UPGRADE["Deadline"](300)
        assert deadline.remaining() == 299
        assert deadline.remaining() == 0.5
        with pytest.raises(TimeoutError, match="Upgrade deadline exhausted"):
            deadline.remaining()


def test_migration_receipts_require_all_files_to_finish(tmp_path):
    log = tmp_path / "migration.log"
    log.write_text("[sql-migrations] apply __init.sql\n"
                   "[sql-migrations] skip old.sql\n[sql-migrations] timing old.sql 0\n"
                   "[sql-migrations] apply new.sql\n", encoding="utf-8")
    receipts = UPGRADE["migration_receipt"](log)
    assert receipts == {"old.sql": {"action": "skip", "elapsed_ms": 0}, "new.sql": {"action": "apply"}}
    expected = {"old.sql": "old-checksum", "new.sql": "new-checksum"}
    ledger = {key: (value, "applied") for key, value in expected.items()}
    check = UPGRADE["check_catalog"]
    with pytest.raises(AssertionError, match="Missing completion timing"):
        check(expected, ledger, receipts, ledger)
    receipts["new.sql"]["elapsed_ms"] = 12
    with pytest.raises(AssertionError, match="Unexpected skip"):
        check(expected, ledger, receipts, {})
    with pytest.raises(AssertionError, match="every manifest entry"):
        check(expected, ledger, {"old.sql": receipts["old.sql"]}, ledger)
    check(expected, ledger, receipts, ledger)


@pytest.mark.asyncio
@pytest.mark.parametrize("wrong,duplicates,outcome", [
    (False, False, "PASS"),
    (True, False, "ANSWER_MARKER_MISMATCH"),
    (False, True, "INVALID_TERMINAL_COUNT"),
])
async def test_stream_requires_own_marker_and_exactly_one_terminal(wrong, duplicates, outcome):
    def handle(request):
        payload = json.loads(request.content)
        assert payload["model_id"] == AGENT["model_id"]
        marker = payload["query"].split()[-1].rstrip(".")
        if wrong:
            marker = "D5PERF_012345abcdef"
        answer = {"type": "final_answer", "content": marker, "depth": 0}
        frame = "data: " + json.dumps(answer) + "\n\n"
        terminal = 'event: agentos_terminal\ndata: {"status": "completed"}\n\n'
        return httpx.Response(200, text=frame * (2 if duplicates else 1) + terminal)

    async with httpx.AsyncClient(base_url="http://fixture.invalid/api/", transport=httpx.MockTransport(handle)) as api:
        result = await LOAD["request_chat"](api, AGENT, 2)
    assert result["outcome"] == outcome


def test_load_receipt_distinguishes_client_concurrency_from_runtime():
    measure = LOAD["summarize"](50, [{"client_in_flight": 50, "runtime_active": 19, "waiting_estimate": 31}],
                               [{"outcome": "PASS", "first": 0.5, "elapsed": 0.9}, {"outcome": "TIMEOUT"}])
    assert (measure["client_peak"], measure["execution_peak"], measure["waiting_estimate_peak"]) == (50, 19, 31)
    assert measure["success_rate"] == 0.5


@pytest.mark.asyncio
async def test_load_tiers_reach_50_with_an_independent_request_for_each_conversation(monkeypatch):
    harness = LOAD["run_tier"].__globals__
    containers = [{"restarts": 0, "state": {"Running": True, "OOMKilled": False, "StartedAt": "fixed"}}
                  for _ in LOAD["SERVICES"]]
    monkeypatch.setitem(harness, "container_state", lambda: containers)
    monkeypatch.setitem(harness, "docker_json", lambda *args: [])
    monkeypatch.setitem(harness, "activity", lambda conversations: (0, 5))
    monkeypatch.setitem(harness, "readiness_url", lambda service: f"http://fixture.invalid/{service}/ready")
    active = set()
    peaks = []

    async def handle(request):
        data = json.loads(request.content)
        conversation = data["conversation_id"]
        assert conversation not in active
        active.add(conversation)
        peaks.append(len(active))
        await asyncio.sleep(0.025)
        active.remove(conversation)
        marker = data["query"].split()[-1].rstrip(".")
        answer = "data: " + json.dumps({"type": "final_answer", "content": marker}) + "\n\n"
        return httpx.Response(200, text=answer + 'event: agentos_terminal\ndata: {"status": "completed"}\n\n')

    async with httpx.AsyncClient(base_url="http://fixture.invalid/api/", transport=httpx.MockTransport(handle)) as api:
        async with httpx.AsyncClient(transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"model_streams": 0}),
        )) as probe:
            for target, _ in LOAD["TIERS"]:
                evidence = {}
                await LOAD["run_tier"](api, probe, "http://fixture.invalid", "http://fixture.invalid/activity",
                                      AGENT, list(range(target)), 0.2, evidence)
                assert max(peaks) == target
                assert evidence["summary"]["success_rate"] == 1
                assert evidence["summary"]["completed_conversations"] == target
                peaks.clear()
    assert not active


@pytest.mark.asyncio
@pytest.mark.parametrize("stop, stale_cursor", [(True, False), (False, False), (False, True)])
async def test_stream_recovery_scopes_control_to_the_original_run(monkeypatch, stop, stale_cursor):
    harness = LOAD["verify_stream_recovery"].__globals__
    monkeypatch.setitem(harness, "activity", lambda conversations: (0, 5))
    generation = "a" * 32

    def frame(index, data, event=None):
        return (f"id: {generation}:{index}\n" + (f"event: {event}\n" if event else "")
                + f"data: {json.dumps(data)}\n\n")

    def handle(request):
        if request.method == "GET":
            assert stop and request.url.path == f"/api/agent/stop/{generation}"
            return httpx.Response(200, json={"cancellation_requested": True})
        query = json.loads(request.content)["query"]
        if not request.url.params:
            assert query.endswith("D5PERF_HOLD") == stop
            return httpx.Response(200, text=frame(5, {"type": "start"}))
        assert request.url.params["after_event_id"] == f"{generation}:5"
        marker = query.split()[2].rstrip(".")
        answer = frame(5 if stale_cursor else 6, {"type": "final_answer", "content": marker})
        return httpx.Response(200, headers={"X-AgentOS-Run-ID": generation},
                              text=answer + frame(7, {"status": "completed"}, "agentos_terminal"))

    async with httpx.AsyncClient(base_url="http://fixture.invalid/api/", transport=httpx.MockTransport(handle)) as api:
        if stale_cursor:
            with pytest.raises(AssertionError):
                await LOAD["verify_stream_recovery"](api, AGENT, 2, stop=stop)
        else:
            await LOAD["verify_stream_recovery"](api, AGENT, 2, stop=stop)


@pytest.mark.asyncio
async def test_controlled_model_stream_echoes_its_marker_and_releases_activity():
    provider = runpy.run_path(str(ROOT / "infra/environment/services/test-assets/performance_provider.py"))
    app = FastAPI()
    app.include_router(provider["router"])
    async with httpx.AsyncClient(base_url="http://fixture.invalid", transport=httpx.ASGITransport(app=app)) as api:
        path = "/performance/owned-run"
        marker = "D5PERF_012345abcdef"
        response = await api.post(path + "/v1/chat/completions", json={
            "stream": True, "messages": [{"role": "user", "content": f"Reply with {marker}."}],
        })
        assert response.is_success and marker in response.text and "data: [DONE]" in response.text
        assert (await api.get(path + "/active")).json() == {"model_streams": 0}
