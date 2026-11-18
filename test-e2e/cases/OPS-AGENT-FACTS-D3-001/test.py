# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Persist a main Agent sample through the real Ops producer and fact writer."""

import asyncio
import json
import os
from datetime import date, datetime, time, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Event, Thread
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4
from zoneinfo import ZoneInfo

import httpx
import pytest
from elasticsearch import Elasticsearch
from fastapi import FastAPI
from sqlalchemy import text

from nexent.core.agents.contracts.config import AgentConfig, ModelConfig
from nexent.core.agents.contracts.run import AgentRunInfo
from nexent.core.agents.orchestration.entry import agent_run
from nexent.core.concurrency import LanePolicy, ThreadManager
from nexent.core.utils.observer import MessageObserver
from nexent.monitor import AgentRunMetadata, MonitoringConfig, agent_monitoring_context, get_monitoring_manager
from nexent.monitor.facts import emit_fact, get_fact_sink, set_fact_sink
from nexent.monitor.local_content import local_capture_enabled
from ops.monitoring import runtime
from ops.monitoring.contracts import stable_key
from ops.monitoring.search import DAILY, FACTS, filters, install_templates
from ops.monitoring.service import Monitoring
from ops.monitoring.store import BATCH, DAY


pytestmark = [pytest.mark.case_id("OPS-AGENT-FACTS-D3-001"), pytest.mark.stage("D3")]


@pytest.fixture
def isolated_monitoring(monkeypatch):
    pg_host = os.environ.get("OPS_MONITORING_TEST_POSTGRES_HOST")
    pg_db = os.environ.get("OPS_MONITORING_TEST_POSTGRES_DB")
    es_host = os.environ.get("OPS_MONITORING_TEST_ES_HOST")
    if not (pg_host and pg_db and es_host and os.environ.get("OPS_MONITORING_TEST_ISOLATED") == "1"):
        pytest.skip("A disposable migrated Ops PostgreSQL and clean Elasticsearch pair are required")

    for key, value in {
        "OPS_MONITORING_ENABLED": True,
        "OPS_MONITORING_TIMEZONE": "UTC",
        "OPS_POSTGRES_HOST": pg_host,
        "OPS_POSTGRES_PORT": int(os.environ.get("OPS_MONITORING_TEST_POSTGRES_PORT", "5432")),
        "OPS_POSTGRES_DB": pg_db,
        "OPS_POSTGRES_USER": os.environ.get("OPS_MONITORING_TEST_POSTGRES_USER", "postgres"),
        "OPS_POSTGRES_PASSWORD": os.environ.get("OPS_MONITORING_TEST_POSTGRES_PASSWORD"),
    }.items():
        monkeypatch.setattr(runtime, key, value)

    tenant = f"agent-sample-{uuid4().hex}"
    store = runtime.control_store()
    try:
        store.verify_schema()
        with Elasticsearch(es_host, request_timeout=10) as es:
            assert not es.indices.get(index="monitoring-*", allow_no_indices=True)
            assert not es.options(ignore_status=404).indices.get_index_template(
                name="monitoring-*"
            ).get("index_templates", [])
            try:
                install_templates(es, 0, runtime.MONITORING_KINDS.values())
                yield Monitoring(store, es, ZoneInfo("UTC"), runtime.MONITORING_KINDS), tenant
            finally:
                for index in es.indices.get(index="monitoring-*", allow_no_indices=True):
                    es.indices.delete(index=index)
                for template in (FACTS, DAILY):
                    es.options(ignore_status=404).indices.delete_index_template(name=template)
    finally:
        try:
            with store.engine.begin() as connection:
                for table in (BATCH, DAY):
                    connection.execute(text(f"DELETE FROM {table} WHERE tenant_id IN (:tenant, :other)"),
                                       {"tenant": tenant, "other": f"{tenant}-other"})
        finally:
            store.engine.dispose()


async def _submit_and_read(service, tenant, event):
    emit_fact(event)
    return await _apply_and_read(service, tenant)


async def _wait_for_agent_batch(service, tenant):
    async with asyncio.timeout(15):
        while not service.apply_batch(tenant, "agent"):
            await asyncio.sleep(0.05)


async def _apply_and_read(service, tenant):
    await _wait_for_agent_batch(service, tenant)
    hits = service.es.search(
        index=f"{FACTS}-*", query={"term": {"fact_kind": "agent"}}, track_total_hits=True,
    )["hits"]
    assert hits["total"]["value"] == 1
    return hits["hits"][0]


def _run_across_midnight(tenant):
    run_id = str(uuid4())
    started = {
        "tenant_id": tenant, "fact_kind": "agent", "fact_id": run_id, "call_context_id": run_id,
        "agent_run_id": run_id, "root_run_id": run_id, "agent_id": 21, "agent_version_no": 3,
        "is_root": True, "initiator_group_ids": [12, 13], "started_at": "2026-10-31T23:59:59.800Z",
        "record_revision": 1, "outcome": "started",
    }
    finished = dict(
        started, record_revision=2, outcome="succeeded", ended_at="2026-11-01T00:00:00.150Z", duration_ms=350
    )
    return started, finished


@pytest.mark.asyncio
async def test_agent_start_finish_and_replay(isolated_monitoring):
    service, tenant = isolated_monitoring
    started, finished = _run_across_midnight(tenant)
    run_id = started["fact_id"]
    async with runtime.producer_lifespan():
        first = await _submit_and_read(service, tenant, started)
        terminal = await _submit_and_read(service, tenant, finished)
        replay = await _submit_and_read(service, tenant, finished)

    for hit in (first, terminal, replay):
        assert hit["_index"] == "monitoring-facts-2026.10"
        assert hit["_id"] == stable_key(tenant, "agent", run_id)
        assert hit["_source"]["agent_run_id"] == hit["_source"]["fact_id"] == run_id
        assert hit["_source"]["agent_version_no"] == 3
        assert hit["_source"]["is_root"] is True
    assert first["_source"]["record_revision"] == 1
    assert first["_source"]["outcome"] == "started"
    assert "duration_ms" not in first["_source"]
    assert terminal["_source"]["record_revision"] == 2
    assert terminal["_source"]["outcome"] == "succeeded"
    assert terminal["_source"]["duration_ms"] == 350
    assert terminal["_source"]["write_version"] > first["_source"]["write_version"]
    assert replay["_source"] == terminal["_source"]
    assert not service.es.indices.exists(index="monitoring-facts-2026.11")
    with service.store.engine.connect() as connection:
        batch_states = connection.scalars(
            text(f"SELECT batch_state FROM {BATCH} WHERE tenant_id=:tenant ORDER BY write_version"),
            {"tenant": tenant},
        ).all()
    assert batch_states == ["confirmed", "confirmed", "confirmed"]


def _published_agent_day(service, tenant, day):
    with service.publication_snapshot(tenant, "agent", day, day) as (states, point):
        state, = states
        publish_id = str(state["publish_id"])
        row, = point.documents(filters(
            tenant_id=tenant, fact_kind="agent", statistic_date=day.isoformat(), publish_id=publish_id,
        ))
    return state, row


@pytest.mark.asyncio
async def test_agent_daily_publication_switches_only_after_success(isolated_monitoring, monkeypatch):
    service, tenant = isolated_monitoring
    started, finished = _run_across_midnight(tenant)
    day = date(2026, 10, 31)

    def interrupt_publication(*_):
        raise RuntimeError("Interrupt publication before the pointer switch")

    async with runtime.producer_lifespan():
        await _submit_and_read(service, tenant, started)
        service.publish(tenant, "agent")
        original, initial = _published_agent_day(service, tenant, day)
        assert original["source_revision"] == original["published_source_revision"] > 0
        assert initial["execution_count"] == 1
        assert initial["duration_sum_ms"] == initial["duration_sample_count"] == 0

        await _submit_and_read(service, tenant, finished)
        with monkeypatch.context() as patch:
            patch.setattr(service.store, "publish", interrupt_publication)
            with pytest.raises(RuntimeError, match="before the pointer switch"):
                service.publish(tenant, "agent")
        candidates = service.es.count(
            index=f"{DAILY}-*", query=filters(tenant_id=tenant, fact_kind="agent", statistic_date=day.isoformat()),
        )["count"]
        assert candidates == 2
        pending, retained = _published_agent_day(service, tenant, day)
        assert pending["source_revision"] > original["source_revision"]
        assert pending["published_source_revision"] == original["published_source_revision"]
        assert pending["publish_id"] == original["publish_id"] and retained == initial

        service.tick()
        published, current = _published_agent_day(service, tenant, day)
        assert published["publish_id"] != original["publish_id"]
        assert published["published_source_revision"] == pending["source_revision"]
        assert current["statistic_date"] == day.isoformat()
        assert current["agent_id"] == started["agent_id"] and current["initiator_group_ids"] == [12, 13]
        assert current["execution_count"] == 1
        assert current["duration_sample_count"] == 1 and current["duration_sum_ms"] == 350
        assert service.es.count(index=f"{DAILY}-*", query=filters(
            tenant_id=tenant, fact_kind="agent", statistic_date="2026-11-01",
        ))["count"] == 0

        await _submit_and_read(service, tenant, finished)
        service.tick()
        assert _published_agent_day(service, tenant, day) == (published, current)


@pytest.fixture
def model_peer():
    received = []
    release = Event()

    class ModelPeer(BaseHTTPRequestHandler):
        def do_POST(self):
            received.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            if not release.wait(20):
                return
            chunk = {
                "id": "ops-agent-model", "object": "chat.completion.chunk", "created": 1,
                "model": "model", "choices": [{"index": 0, "finish_reason": "stop",
                                               "delta": {"content": "<final_answer>ops-agent-ready</final_answer>"}}],
            }
            self.wfile.write(f"data: {json.dumps(chunk)}\n\ndata: [DONE]\n\n".encode())

    with ThreadingHTTPServer(("127.0.0.1", 0), ModelPeer) as server:
        worker = Thread(target=server.serve_forever)
        worker.start()
        try:
            yield f"http://127.0.0.1:{server.server_port}/v1", received, release
        finally:
            release.set()
            server.shutdown()
            worker.join(timeout=5)
            assert not worker.is_alive()


def _resume_app(info, tenant, channel, threads, monkeypatch):
    from management.services.agent import subscription
    from runtime.api.agent import execution as api

    monkeypatch.setattr(api, "get_current_user_id", lambda _: (info.user_id, tenant))
    monkeypatch.setattr(subscription, "get_conversation_service", lambda **_: {"conversation_id": info.conversation_id})
    monkeypatch.setattr(subscription, "update_conversation_chat_mode_service", Mock())
    monkeypatch.setattr(subscription, "get_latest_assistant_message", lambda *_: {"message_id": 1, "status": "streaming"})
    monkeypatch.setattr(subscription, "get_last_unit_for_message", lambda _: None)
    monkeypatch.setattr(subscription, "agent_run_manager", SimpleNamespace(get_agent_run_info=lambda **_: info))
    monkeypatch.setattr(subscription, "streaming_channel_manager", SimpleNamespace(get_channel=lambda *_, **__: channel))
    monkeypatch.setattr(subscription.runtime_state_service, "get_run_state_async", AsyncMock(return_value={}))
    monkeypatch.setattr(subscription, "runtime_thread_manager", threads)
    app = FastAPI()
    app.include_router(api.agent_runtime_router)
    return app


async def _verify_ops_query(service, tenant, day, duration_ms, monkeypatch):
    from gateway.authentication import auth
    from ops.api import application
    from ops.monitoring import query
    from permissions import rbac

    other = f"{tenant}-other"
    previous = day - timedelta(days=1)
    fixtures = [
        (tenant, previous, 21, [12, 13], 200),
        (tenant, day, 22, [12], 500),
        (tenant, day, 21, [99], 600),
        (other, day, 21, [12, 13], 800),
    ]
    for scope, statistic_day, agent_id, groups, duration in fixtures:
        _, fact = _run_across_midnight(scope)
        instant = datetime.combine(statistic_day, time.min, timezone.utc)
        emit_fact(dict(
            fact, started_at=instant.isoformat(), ended_at=(instant + timedelta(milliseconds=duration)).isoformat(),
            agent_id=agent_id, initiator_group_ids=groups, duration_ms=duration,
        ))
        await _wait_for_agent_batch(service, scope)
    service.tick()

    principals = {
        "Bearer ops": ("operator", tenant, "OPS"),
        "Bearer admin": ("administrator", tenant, "SU"),
        "Bearer user": ("regular-user", tenant, "USER"),
    }
    monkeypatch.setattr(auth, "get_current_user_context", principals.__getitem__)
    monkeypatch.setattr(rbac, "_ROLE_PERMISSIONS", {"OPS": {"ops.dashboard:read"}, "SU": {"ops.dashboard:read"}})
    monkeypatch.setattr(rbac, "_INITIALIZED", True)
    monkeypatch.setattr(query, "agent_catalog_tenants", lambda _: {tenant, other})
    monkeypatch.setattr(application, "OPS_MONITORING_ENABLED", True)
    app = application.create_app()
    app.state.monitoring = service
    selection = {"start_date": day.isoformat(), "end_date": day.isoformat(), "group_ids": [12, 13], "agent_id": 21}

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://ops") as client:
        async def get(params, actor="ops"):
            headers = {"Authorization": f"Bearer {actor}"} if actor else {}
            return await client.get("/ops/v1/monitoring/agents/summary", params=params, headers=headers)

        actual = await get(dict(selection, tenant_id=tenant))
        assert actual.status_code == 200
        observed = actual.json()
        assert observed["data"] == {"execution_count": 1, "avg_duration_ms": duration_ms, "duration_sample_count": 1}
        assert observed["data_as_of"] and observed["coverage_state"] == "covered" and not observed["is_stale"]
        assert (await get(selection)).json() == observed

        group_filtered = await get(dict(selection, group_ids=[99]))
        assert group_filtered.json()["data"] == {
            "execution_count": 1, "avg_duration_ms": 600, "duration_sample_count": 1,
        }
        agent_filtered = await get(dict(selection, agent_id=22))
        assert agent_filtered.json()["data"] == {
            "execution_count": 1, "avg_duration_ms": 500, "duration_sample_count": 1,
        }
        dates = await get(dict(selection, start_date=previous.isoformat()))
        assert dates.json()["data"] == {
            "execution_count": 2, "avg_duration_ms": (duration_ms + 200) / 2, "duration_sample_count": 2,
        }
        zero = (await get(dict(selection, group_ids=[555]))).json()
        assert zero["coverage_state"] == "covered"
        assert zero["data"] == {"execution_count": 0, "avg_duration_ms": None, "duration_sample_count": 0}
        missing_day = (previous - timedelta(days=1)).isoformat()
        uncovered = (await get(dict(selection, start_date=missing_day, end_date=missing_day))).json()
        assert uncovered["coverage_state"] == "uncovered" and uncovered["data_as_of"] is None
        assert uncovered["data"] == dict.fromkeys(observed["data"])

        assert (await get(dict(selection, tenant_id=other))).status_code == 403
        assert (await get(selection, actor="user")).status_code == 403
        assert (await get(selection, actor=None)).status_code == 401
        other_only = await get(dict(selection, tenant_id=other), actor="admin")
        assert other_only.json()["data"] == {
            "execution_count": 1, "avg_duration_ms": 800, "duration_sample_count": 1,
        }
        all_tenants = await get(selection, actor="admin")
        assert all_tenants.json()["data"] == {
            "execution_count": 2, "avg_duration_ms": (duration_ms + 800) / 2, "duration_sample_count": 2,
        }
    return actual.request.url.raw_path.decode("ascii"), observed


@pytest.mark.asyncio
async def test_real_root_agent_capture_survives_sse_reconnect(
    isolated_monitoring, model_peer, monkeypatch, record_property,
):
    from infrastructure.streaming.channels import StreamingChannel, runtime_state_service

    service, tenant = isolated_monitoring
    base, requests, release = model_peer
    manager = get_monitoring_manager()
    monkeypatch.setattr(manager, "_config", MonitoringConfig(enable_telemetry=False, provider="local_file"))
    assert not manager.is_enabled and not local_capture_enabled(manager)
    monkeypatch.setattr(runtime_state_service, "append_stream_event_async", AsyncMock())
    info = AgentRunInfo(
        query="Run the controlled main Agent", observer=MessageObserver(),
        agent_config=AgentConfig(name="root", description="Controlled Agent", model_name="model",
                                 agent_id=21, version_no=3, tools=[], max_steps=2),
        model_config_list=[ModelConfig(cite_name="model", model_name="model", url=base, api_key="synthetic")],
        stop_event=Event(), user_id="owner", tenant_id=tenant, conversation_id=123,
        workspace_run_id=uuid4().hex, history=[],
    )
    metadata = AgentRunMetadata(
        tenant_id=tenant, agent_id=21, user_id=info.user_id, conversation_id=info.conversation_id,
        is_debug=False, monitoring_group_ids=(12, 13),
    )
    channel = StreamingChannel(str(info.conversation_id), info.user_id)
    threads = ThreadManager("ops-agent-facts", {
        lane: LanePolicy(lane, 2, 3) for lane in ("agent-run", "model-tool-io", "sandbox", "control-io")
    })
    app = _resume_app(info, tenant, channel, threads, monkeypatch)
    observations = []

    async def forward():
        try:
            with agent_monitoring_context(metadata):
                async for chunk in agent_run(info, thread_manager=threads):
                    await channel.publish(f"data: {chunk}\n\n")
        finally:
            channel.complete(info.attempt_outcome or "failed")

    async with runtime.producer_lifespan():
        sink = get_fact_sink()

        def capture(event):
            if event["fact_kind"] == "agent":
                observations.append(dict(event))
            sink(event)

        set_fact_sink(capture)
        threads.start()
        worker = asyncio.create_task(forward())
        try:
            async with asyncio.timeout(10):
                while not requests:
                    assert not worker.done(), "Agent worker exited before dispatching the model request"
                    await asyncio.sleep(0.05)
            first = await _apply_and_read(service, tenant)
            assert first["_source"]["outcome"] == "started"
            assert [event["record_revision"] for event in observations] == [1]
            assert not worker.done()

            former_connection = channel.subscribe_with_history()
            try:
                async with asyncio.timeout(5):
                    first_frame = await anext(former_connection)
            finally:
                await former_connection.aclose()
            assert not channel.has_subscribers

            submit = Mock(wraps=threads.submit)
            monkeypatch.setattr(threads, "submit", submit)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://runtime") as client:
                async with asyncio.TaskGroup() as tasks:
                    resumed = tasks.create_task(client.post(
                        "/agent/run?resume=true",
                        json={"query": info.query, "agent_id": 21, "conversation_id": info.conversation_id},
                    ))
                    async with asyncio.timeout(5):
                        while not channel.has_subscribers:
                            assert not resumed.done(), "Runtime returned before subscribing to the existing stream"
                            await asyncio.sleep(0.05)
                    release.set()
            response = resumed.result()
            async with asyncio.timeout(10):
                await worker
            assert not any(call.args[0] == "agent-run" for call in submit.call_args_list)
            assert response.status_code == 200
            assert response.headers["X-Stream-Status"] == "resumed"
            assert first_frame in response.text
            assert "ops-agent-ready" in response.text
            assert '"status": "completed"' in response.text
            assert len(requests) == 1
            assert info.attempt_outcome == "completed"

            terminal = await _apply_and_read(service, tenant)
            started, finished = observations
            assert [event["record_revision"] for event in observations] == [1, 2]
            for key in ("fact_id", "agent_run_id", "root_run_id", "call_context_id"):
                assert started[key] == finished[key] == info.workspace_run_id
            assert started["started_at"] == finished["started_at"]
            assert started["initiator_group_ids"] == finished["initiator_group_ids"] == (12, 13)
            assert first["_id"] == terminal["_id"] == stable_key(tenant, "agent", info.workspace_run_id)
            assert first["_index"] == terminal["_index"]
            assert terminal["_source"]["record_revision"] == 2
            assert terminal["_source"]["outcome"] == finished["outcome"] == "succeeded"
            assert terminal["_source"]["duration_ms"] == finished["duration_ms"] > 0
            assert terminal["_source"]["ended_at"] >= terminal["_source"]["started_at"]
            assert not service.apply_batch(tenant, "agent")

            day = date.fromisoformat(terminal["_source"]["statistic_date"])
            service.tick()
            state, daily = _published_agent_day(service, tenant, day)
            assert state["source_revision"] == state["published_source_revision"]
            assert daily["execution_count"] == daily["duration_sample_count"] == 1
            assert daily["duration_sum_ms"] == finished["duration_ms"]
            request_path, response_body = await _verify_ops_query(service, tenant, day, finished["duration_ms"], monkeypatch)
            record_property("agent_summary_request", request_path)
            record_property("agent_summary_response", json.dumps(response_body))
        finally:
            release.set()
            worker.cancel()
            await asyncio.gather(worker, return_exceptions=True)
            await threads.shutdown(timeout=8)
            set_fact_sink(sink)
