# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Persist a main Agent sample through the real Ops producer and fact writer."""

import asyncio
import json
import os
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
from ops.monitoring.search import DAILY, FACTS, install_templates
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
                    connection.execute(text(f"DELETE FROM {table} WHERE tenant_id=:tenant"), {"tenant": tenant})
        finally:
            store.engine.dispose()


async def _submit_and_read(service, tenant, event):
    emit_fact(event)
    return await _apply_and_read(service, tenant)


async def _apply_and_read(service, tenant):
    async with asyncio.timeout(15):
        while not service.apply_batch(tenant, "agent"):
            await asyncio.sleep(0.05)
    hits = service.es.search(
        index=f"{FACTS}-*", query={"term": {"fact_kind": "agent"}}, track_total_hits=True,
    )["hits"]
    assert hits["total"]["value"] == 1
    return hits["hits"][0]


@pytest.mark.asyncio
async def test_agent_start_finish_and_replay(isolated_monitoring):
    service, tenant = isolated_monitoring
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


@pytest.mark.asyncio
async def test_real_root_agent_capture_survives_sse_reconnect(isolated_monitoring, model_peer, monkeypatch):
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
        finally:
            release.set()
            worker.cancel()
            await asyncio.gather(worker, return_exceptions=True)
            await threads.shutdown(timeout=8)
            set_fact_sink(sink)
