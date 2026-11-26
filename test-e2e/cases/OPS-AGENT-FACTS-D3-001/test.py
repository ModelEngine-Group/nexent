# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Persist a main Agent sample through the real Ops producer and fact writer."""

import asyncio
import json
import os
from datetime import date, datetime, time, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Event, Thread
from time import monotonic_ns
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4
from zoneinfo import ZoneInfo

import httpx
import pytest
from elasticsearch import Elasticsearch
from fastapi import FastAPI
from sqlalchemy import event, insert, text
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateSchema

from nexent.core.agents.contracts.config import AgentConfig, ModelConfig
from nexent.core.agents.contracts.run import AgentRunInfo
from nexent.core.agents.orchestration.entry import agent_run
from nexent.core.concurrency import LanePolicy, ThreadManager
from nexent.core.utils.observer import MessageObserver, ProcessType
from nexent.monitor import AgentRunMetadata, MonitoringConfig, agent_monitoring_context, get_monitoring_manager
from nexent.monitor.facts import emit_fact, get_fact_sink, set_fact_sink
from nexent.monitor.local_content import local_capture_enabled
from infrastructure.monitoring import runtime as collector
from infrastructure.monitoring import store as batch_store
from ops.monitoring import runtime
from ops.monitoring.contracts import stable_key
from ops.monitoring.search import DAILY, DAILY_FIELDS, FACTS, filters, install_templates, mapping
from ops.monitoring.service import Monitoring
from ops.monitoring.store import BATCH, DAY


pytestmark = [pytest.mark.case_id("OPS-AGENT-FACTS-D3-001"), pytest.mark.stage("D3")]


@pytest.fixture(autouse=True)
def owned_working_directory(tmp_path, monkeypatch):
    """Keep legacy relative runtime logs inside the case-owned temporary directory."""
    monkeypatch.chdir(tmp_path)


@pytest.fixture
def first_answer_clock(monkeypatch):
    """Observe real clock reads inside the first answer event without replacing timing."""
    from nexent.monitor import agent_fact, get_agent_monitoring_context

    reads, answers = {}, {}
    original_emit = MessageObserver._emit

    def clock():
        instant = monotonic_ns()
        context = get_agent_monitoring_context()
        reads.setdefault(context.monitoring_run_id, []).append(instant)
        return instant

    def output(observer, process_type, content, **kwargs):
        context = get_agent_monitoring_context()
        before = monotonic_ns()
        result = original_emit(observer, process_type, content, **kwargs)
        if (context is not None and process_type in {ProcessType.FINAL_ANSWER, ProcessType.MODEL_OUTPUT}
                and isinstance(content, str) and content.strip()):
            answers.setdefault(context.monitoring_run_id, (before, monotonic_ns()))
        return result

    monkeypatch.setattr(agent_fact, "monotonic_ns", clock)
    monkeypatch.setattr(MessageObserver, "_emit", output)
    return reads, answers


def _assert_first_answer_clock(clock, terminal):
    reads, answers = clock
    run_id = terminal["agent_run_id"]
    started, answered, *ended = reads[run_id]
    before, after = answers[run_id]
    assert before <= answered <= after
    assert terminal["ttft_ms"] == (answered - started) // 1_000_000
    assert ended == []


def test_bulk_model_batch_failures_preserve_scoped_status(isolated_monitoring, record_property):
    """Compare bulk reads to the retained predicate through the actual PostgreSQL driver."""
    service, tenant = isolated_monitoring
    store = service.store
    peer = tenant + "-other"
    first, last = date(2026, 11, 18), date(2026, 11, 19)
    before, after = first - timedelta(days=1), last + timedelta(days=1)
    scenarios = [
        ("queued", "write_failed", "model", [first], "N", True),
        ("pending", "write_failed", "model", [last], "N", True),
        ("queued", "write_failed", "model", [], "N", True),
        ("confirmed", "write_failed", "model", [first], "N", False),
        ("pending", None, "model", [first], "N", False),
        ("pending", "write_failed", "agent", [first], "N", False),
        ("pending", "write_failed", "model", [before], "N", False),
        ("pending", "write_failed", "model", [after], "N", False),
        ("pending", "write_failed", "model", [first], "Y", False),
        ("pending", "write_failed", "model", [before, last, after], "N", True),
    ]
    for state, error, kind, dates, deleted, failed in scenarios:
        with store.engine.begin() as conn:
            conn.execute(text(f"DELETE FROM {BATCH} WHERE tenant_id=ANY(:tenants)"),
                         {"tenants": [tenant, peer]})
            conn.execute(text(f"""
                INSERT INTO {BATCH}
                    (batch_id, tenant_id, fact_kind, batch_state, affected_dates, last_error_code, delete_flag)
                VALUES (:id, :tenant, :kind, :state, CAST(:dates AS date[]), :error, :deleted)
            """), [
                {"id": uuid4(), "tenant": tenant, "kind": kind, "state": state, "dates": dates,
                 "error": error, "deleted": deleted},
                {"id": uuid4(), "tenant": peer, "kind": "model", "state": "pending", "dates": [first],
                 "error": "write_failed", "deleted": "N"},
            ])
        expected = {scope for scope in (tenant, peer) if store.has_failed_batches(scope, "model", first, last)}
        assert expected == ({tenant, peer} if failed else {peer})
        statements = []

        def observe(_conn, _cursor, statement, _parameters, _context, _many):
            statements.append(statement)

        event.listen(store.engine, "before_cursor_execute", observe)
        try:
            assert store.failed_batch_tenants({tenant, peer}, "model", first, last) == expected
            assert len(statements) == 1 and BATCH in statements[0]
            statements.clear()
            assert store.failed_batch_tenants(set(), "model", first, last) == set()
            assert statements == []
            assert store.failed_batch_tenants({tenant}, "model", first, last) == ({tenant} if failed else set())
            assert len(statements) == 1
        finally:
            event.remove(store.engine, "before_cursor_execute", observe)
        with store.engine.connect() as conn:
            assert conn.execute(text(f"SELECT count(*) FROM {BATCH} WHERE tenant_id=ANY(:tenants)"),
                                {"tenants": [tenant, peer]}).scalar_one() == 2
    record_property("failure_predicate_scenarios", len(scenarios))
    record_property("bulk_failure_sql_count", 1)


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
        "POSTGRES_HOST": pg_host,
        "POSTGRES_PORT": int(os.environ.get("OPS_MONITORING_TEST_POSTGRES_PORT", "5432")),
        "POSTGRES_DB": "nexent",
        "OPS_POSTGRES_DB": pg_db,
        "POSTGRES_USER": os.environ.get("OPS_MONITORING_TEST_POSTGRES_USER", "postgres"),
        "NEXENT_POSTGRES_PASSWORD": os.environ.get("OPS_MONITORING_TEST_POSTGRES_PASSWORD"),
    }.items():
        monkeypatch.setattr(collector if key.startswith("OPS_MONITORING_") else batch_store, key, value)

    tenant = f"agent-sample-{uuid4().hex}"
    store = runtime.control_store()
    catalog_tables = []
    from infrastructure.rdb import agent_monitoring
    from management.db.agent.models import AgentInfo
    from management.db.model.models import ModelRecord
    from ops.monitoring import query

    try:
        store.verify_schema()
        with store.engine.begin() as connection:
            connection.execute(CreateSchema(AgentInfo.__table__.schema, if_not_exists=True))
            for model in (AgentInfo, ModelRecord):
                model.__table__.create(connection)
                catalog_tables.append(model.__table__)
        monkeypatch.setattr(query, "get_db_session", lambda: Session(store.engine))
        monkeypatch.setattr(agent_monitoring, "get_db_session", lambda: Session(store.engine))
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
                for table in reversed(catalog_tables):
                    table.drop(connection)
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


def _successful_metrics(count, average, samples, ttft=None, ttft_samples=None):
    return {"execution_count": count, "avg_duration_ms": average, "duration_sample_count": samples,
            "succeeded_count": count, "failed_count": 0, "success_rate": 1.0 if count else None,
            "avg_ttft_ms": ttft, "ttft_sample_count": int(ttft is not None) if ttft_samples is None else ttft_samples}


@pytest.mark.asyncio
async def test_agent_start_finish_and_replay(isolated_monitoring):
    service, tenant = isolated_monitoring
    started, finished = _run_across_midnight(tenant)
    run_id = started["fact_id"]
    async with collector.producer_lifespan():
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
    finished["ttft_ms"] = 150

    def interrupt_publication(*_):
        raise RuntimeError("Interrupt publication before the pointer switch")

    async with collector.producer_lifespan():
        await _submit_and_read(service, tenant, started)
        service.publish(tenant, "agent")
        original, initial = _published_agent_day(service, tenant, day)
        assert original["source_revision"] == original["published_source_revision"] > 0
        assert initial["execution_count"] == 1
        assert initial["duration_sum_ms"] == initial["duration_sample_count"] == 0
        assert initial["succeeded_count"] == initial["failed_count"] == 0
        assert initial["ttft_sum_ms"] == initial["ttft_sample_count"] == 0

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
        assert current["succeeded_count"] == 1 and current["failed_count"] == 0
        assert (current["ttft_sum_ms"], current["ttft_sample_count"]) == (150, 1)
        assert service.es.count(index=f"{DAILY}-*", query=filters(
            tenant_id=tenant, fact_kind="agent", statistic_date="2026-11-01",
        ))["count"] == 0

        await _submit_and_read(service, tenant, finished)
        service.tick()
        assert _published_agent_day(service, tenant, day) == (published, current)


@pytest.fixture
def model_peer(request):
    received = []
    release = Event()

    class ModelPeer(BaseHTTPRequestHandler):
        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            received.append(payload)
            if getattr(request, "param", None) == "failed":
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": {"message": "controlled", "type": "invalid_request_error"}}).encode())
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            if not release.wait(20):
                return
            reasoning = {"id": "reasoning", "object": "chat.completion.chunk", "created": 1, "model": "model",
                         "choices": [{"index": 0, "delta": {"reasoning_content": "internal reasoning"}}]}
            self.wfile.write(f"data: {json.dumps(reasoning)}\n\n".encode())
            self.wfile.flush()
            content = "<final_answer>ops-agent-ready</final_answer>"
            if getattr(request, "param", None) in {"children", "tokens", "children_traced"}:
                model = payload["model"]
                if model == "child-model":
                    content = "<final_answer>child-ready</final_answer>"
                elif sum(item["model"] == model for item in received) == 1:
                    content = '<code>\nchild(task="first")\nchild(task="second")\n</code>'
            chunk = {
                "id": "ops-agent-model", "object": "chat.completion.chunk", "created": 1,
                "model": "model", "choices": [{"index": 0, "finish_reason": "stop",
                                               "delta": {"content": content}}],
            }
            if getattr(request, "param", None) == "tokens":
                ordinal = sum(item["model"] == model for item in received)
                usage = ({1: (10, 2, 12), 2: (20, 3, 23)} if model == "model" else {1: (100, 0, 100)})
                if ordinal in usage:
                    chunk["usage"] = dict(zip(("prompt_tokens", "completion_tokens", "total_tokens"), usage[ordinal]))
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
    from contracts.agentos import BODY_KEY, PRINCIPAL_KEY
    from nexent.core.concurrency import ManagedTaskSpec
    from runtime.agentos import legacy_resume, resume

    monkeypatch.setattr(legacy_resume, "read_legacy_resume_state", lambda *_: (False, ("streaming", None)))
    monkeypatch.setattr(legacy_resume, "agent_run_manager", SimpleNamespace(get_agent_run_info=lambda *_: info))
    monkeypatch.setattr(legacy_resume, "streaming_channel_manager", SimpleNamespace(get_channel=lambda *_, **__: channel))
    monkeypatch.setattr(legacy_resume.runtime_state_service, "get_run_state_async", AsyncMock(return_value={}))

    async def control_io(task, function, *args, lane, owner, **kwargs):
        return await threads.run(lane, ManagedTaskSpec(task, owner), function, *args, **kwargs)

    monkeypatch.setattr(legacy_resume, "run_blocking", control_io)
    app = FastAPI()

    @app.middleware("http")
    async def owned_identity(request, call_next):
        # Authentication has separate signed-protocol coverage; retain the real lifecycle and replay handlers.
        request.scope[PRINCIPAL_KEY] = SimpleNamespace(user_id=info.user_id, tenant_id=tenant)
        request.scope[BODY_KEY] = await request.body()
        return await call_next(request)

    app.include_router(resume.create_run_lifecycle_router())
    return app


async def _verify_ops_query(service, tenant, day, duration_ms, monkeypatch, ttft_ms):
    from management.services.permission.identity import session as auth
    from contracts.constants import environment

    monkeypatch.setattr(environment, "TRAJECTORY_READ_ENABLED", False)
    monkeypatch.setattr(environment, "MONITORING_PROVIDER", "otlp")
    from ops.api import application
    from management.db.agent.models import AgentInfo
    from permissions import rbac

    other = f"{tenant}-other"
    previous = day - timedelta(days=1)
    fixtures = [
        (tenant, previous, 21, [12, 13], 200),
        (tenant, day, 22, [12], 500),
        (tenant, day, 21, [99], 600),
        (other, day, 21, [12, 13], 800),
    ]
    fixtures.extend((tenant, day, number, [12], 100 + number) for number in range(24, 31))
    fixtures.append((tenant, day, 30, [12], 130))
    for scope, statistic_day, agent_id, groups, duration in fixtures:
        _, fact = _run_across_midnight(scope)
        instant = datetime.combine(statistic_day, time.min, timezone.utc)
        emit_fact(dict(
            fact, started_at=instant.isoformat(), ended_at=(instant + timedelta(milliseconds=duration)).isoformat(),
            agent_id=agent_id, initiator_group_ids=groups, duration_ms=duration,
        ))
        await _wait_for_agent_batch(service, scope)
    service.tick()
    with service.store.engine.begin() as connection:
        for scope, number, version, flag in [
            (tenant, 21, 0, "N"), (tenant, 21, 3, "N"), (tenant, 22, 0, "N"),
            (tenant, 23, 0, "N"), (tenant, 24, 0, "Y"), (other, 41, 0, "N"),
        ]:
            connection.execute(insert(AgentInfo).values(
                tenant_id=scope, agent_id=number, version_no=version, delete_flag=flag,
                name=f"internal-{number}", display_name=f"Agent {number}", model_ids=[7], group_ids="12,13",
            ))

    principals = {
        "Bearer ops": ("operator", tenant, "OPS"),
        "Bearer admin": ("administrator", tenant, "SU"),
        "Bearer user": ("regular-user", tenant, "USER"),
    }
    monkeypatch.setattr(auth, "get_current_user_context", principals.__getitem__)
    monkeypatch.setattr(rbac, "_ROLE_PERMISSIONS", {"OPS": {"ops.dashboard:read"}, "SU": {"ops.dashboard:read"}})
    monkeypatch.setattr(rbac, "_INITIALIZED", True)
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
        assert observed["data"] == _successful_metrics(1, duration_ms, 1, ttft_ms)
        assert observed["data_as_of"] and observed["coverage_state"] == "covered" and not observed["is_stale"]
        assert (await get(selection)).json() == observed

        group_filtered = await get(dict(selection, group_ids=[99]))
        assert group_filtered.json()["data"] == _successful_metrics(1, 600, 1)
        agent_filtered = await get(dict(selection, agent_id=22))
        assert agent_filtered.json()["data"] == _successful_metrics(1, 500, 1)
        dates = await get(dict(selection, start_date=previous.isoformat()))
        assert dates.json()["data"] == _successful_metrics(2, (duration_ms + 200) / 2, 2, ttft_ms)
        zero = (await get(dict(selection, group_ids=[555]))).json()
        assert zero["coverage_state"] == "covered"
        assert zero["data"] == _successful_metrics(0, None, 0)
        missing_day = (previous - timedelta(days=1)).isoformat()
        uncovered = (await get(dict(selection, start_date=missing_day, end_date=missing_day))).json()
        assert uncovered["coverage_state"] == "uncovered" and uncovered["data_as_of"] is None
        assert uncovered["data"] == dict.fromkeys(observed["data"])

        assert (await get(dict(selection, tenant_id=other))).status_code == 403
        assert (await get(selection, actor="user")).status_code == 403
        assert (await get(selection, actor=None)).status_code == 401
        other_only = await get(dict(selection, tenant_id=other), actor="admin")
        assert other_only.json()["data"] == _successful_metrics(1, 800, 1)
        all_tenants = await get(selection, actor="admin")
        assert all_tenants.json()["data"] == _successful_metrics(2, (duration_ms + 800) / 2, 2, ttft_ms)
        views = await _verify_agent_views(client, service, selection, tenant, other, previous, duration_ms, ttft_ms)
    return actual.request.url.raw_path.decode("ascii"), observed, views


async def _verify_agent_views(client, service, selection, tenant, other, previous, duration_ms, ttft_ms):
    base = "/ops/v1/monitoring/agents"

    async def get(suffix="", params=None, actor="ops"):
        headers = {"Authorization": f"Bearer {actor}"} if actor else {}
        return await client.get(base + suffix, params=params or selection, headers=headers)

    listing = (await get()).json()
    root, = listing["data"]["items"]
    assert listing["data"]["current_agent_count"] == listing["data"]["total"] == 1
    assert root["name"] == "internal-21" and root["display_name"] == "Agent 21"
    assert root["configured_group_ids"] == [12, 13] and root["model_ids"] == [7]
    assert root["metrics"] == _successful_metrics(1, duration_ms, 1, ttft_ms)
    own = {key: value for key, value in selection.items() if key != "agent_id"}
    full = (await get(params=own)).json()["data"]
    assert full["current_agent_count"] == 3 and full["total"] == 10
    by_id = {item["agent_id"]: item for item in full["items"]}
    assert by_id[23]["metrics"]["execution_count"] == 0 and by_id[23]["metrics"]["avg_duration_ms"] is None
    assert by_id[24]["is_current"] is False and by_id[24]["metrics"]["execution_count"] == 1
    ranked = (await get("/rankings", own)).json()["data"]
    assert [item["agent_id"] for item in ranked] == [30, 21, 22, 24, 25]
    paged = (await get(params=dict(own, page=2, page_size=2))).json()["data"]
    assert [item["agent_id"] for item in paged["items"]] == [22, 24]
    assert paged["total"] == full["total"]
    for term in ("INTERNAL-21", "AGENT 21"):
        found = (await get(params=dict(own, search=term))).json()["data"]
        assert [item["agent_id"] for item in found["items"]] == [21]
        assert found["current_agent_count"] == 3
    series = (await get("/trends", dict(selection, start_date=previous.isoformat()))).json()["data"]
    assert [item["execution_count"] for item in series] == [1, 1]
    assert [item["avg_duration_ms"] for item in series] == [200, duration_ms]
    assert all(item["coverage_state"] == "covered" for item in series)
    for suffix in ("", "/trends", "/rankings"):
        assert (await get(suffix, dict(selection, tenant_id=other))).status_code == 403
        assert (await get(suffix, actor="user")).status_code == 403
        assert (await get(suffix, actor=None)).status_code == 401
        peer = (await get(suffix, dict(selection, tenant_id=other), "admin")).json()["data"]
        metrics = peer["items"][0]["metrics"] if suffix == "" else peer[0].get("metrics", peer[0])
        assert metrics["execution_count"] == 1 and metrics["avg_duration_ms"] == 800
    global_rows = (await get(actor="admin")).json()["data"]["items"]
    assert {(item["tenant_id"], item["agent_id"]) for item in global_rows} == {(tenant, 21), (other, 21)}
    global_series = (await get("/trends", dict(selection, start_date=previous.isoformat()), "admin")).json()["data"]
    assert [item["coverage_state"] for item in global_series] == ["partial", "covered"]
    assert [item["execution_count"] for item in global_series] == [1, 2]
    zero = (await get(params=dict(own, group_ids=[555]))).json()["data"]
    assert zero["current_agent_count"] == zero["total"] == 3
    assert all(item["metrics"] == _successful_metrics(0, None, 0)
               for item in zero["items"])
    missing = (previous - timedelta(days=1)).isoformat()
    unavailable = (await get("/trends", dict(selection, start_date=missing, end_date=missing))).json()["data"]
    assert unavailable[0]["execution_count"] is None and unavailable[0]["coverage_state"] == "uncovered"
    _, update = _run_across_midnight(tenant)
    instant = datetime.fromisoformat(selection["start_date"]).replace(tzinfo=timezone.utc)
    emit_fact(dict(update, started_at=instant.isoformat(), ended_at=(instant + timedelta(milliseconds=250)).isoformat(),
                   duration_ms=250))
    await _wait_for_agent_batch(service, tenant)
    stale = (await get()).json()
    assert stale["is_stale"] and stale["data"]["items"][0]["metrics"] == root["metrics"]
    service.tick()
    current = (await get()).json()
    assert not current["is_stale"]
    assert current["data"]["items"][0]["metrics"] == _successful_metrics(2, (duration_ms + 250) / 2, 2, ttft_ms)
    return {"directory": listing, "rankings": ranked, "trends": series, "after_publication": current}


@pytest.mark.asyncio
async def test_real_root_agent_capture_survives_sse_reconnect(
    isolated_monitoring, model_peer, monkeypatch, record_property, first_answer_clock,
):
    from contracts.agentos import AgentOperation
    from infrastructure.agent_stream_channels import StreamingChannel, runtime_state_service

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

    async with collector.producer_lifespan():
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
                        AgentOperation.RESUME_LEGACY.value,
                        json={"conversation_id": info.conversation_id},
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
            _assert_first_answer_clock(first_answer_clock, finished)
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
            assert 0 <= finished["ttft_ms"] == terminal["_source"]["ttft_ms"] <= finished["duration_ms"]
            assert terminal["_source"]["ended_at"] >= terminal["_source"]["started_at"]
            assert not service.apply_batch(tenant, "agent")

            day = date.fromisoformat(terminal["_source"]["statistic_date"])
            service.tick()
            state, daily = _published_agent_day(service, tenant, day)
            assert state["source_revision"] == state["published_source_revision"]
            assert daily["execution_count"] == daily["duration_sample_count"] == 1
            assert daily["duration_sum_ms"] == finished["duration_ms"]
            assert daily["ttft_sum_ms"] == finished["ttft_ms"] and daily["ttft_sample_count"] == 1
            request_path, response_body, views = await _verify_ops_query(
                service, tenant, day, finished["duration_ms"], monkeypatch, finished["ttft_ms"],
            )
            record_property("agent_summary_request", request_path)
            record_property("agent_summary_response", json.dumps(response_body))
            record_property("agent_views_response", json.dumps(views))
        finally:
            release.set()
            worker.cancel()
            await asyncio.gather(worker, return_exceptions=True)
            await threads.shutdown(timeout=8)
            set_fact_sink(sink)


def _mixed_result_events(tenant):
    plans = [
        (0, 21, "succeeded", True), (0, 21, "cancelled", True),
        (0, 21, "unknown", True), (0, 21, "started", False),
        (1, 21, "succeeded", True), (1, 21, "failed", True),
        (1, 21, "failed", True), (1, 21, "timed_out", True),
        (0, 22, "failed", True), (1, 22, "succeeded", True), (1, 22, "cancelled", True),
        (0, 23, "started", False), (1, 23, "cancelled", True),
        (1, 23, "unknown", True), (1, 23, "unknown", False),
        (1, 24, "timed_out", False),
    ]
    roots = {offset: uuid4().hex for offset in (0, 1)}
    events = []
    for offset, agent_id, outcome, ended in plans:
        run_id = roots[offset] if agent_id == 21 and outcome == "succeeded" else uuid4().hex
        instant = datetime(2026, 11, 1, tzinfo=timezone.utc) + timedelta(days=offset)
        started = {
            "tenant_id": tenant, "fact_kind": "agent", "fact_id": run_id, "call_context_id": run_id,
            "agent_run_id": run_id, "root_run_id": roots[offset] if agent_id == 22 else run_id,
            "agent_id": agent_id, "is_root": agent_id != 22, "initiator_group_ids": [12, 13],
            "started_at": instant.isoformat(), "record_revision": 1, "outcome": "started",
        }
        if agent_id == 22:
            started["parent_run_id"] = roots[offset]
        terminal = dict(started, record_revision=2, outcome=outcome) if outcome != "started" else started
        if ended:
            terminal.update(ended_at=(instant + timedelta(milliseconds=10)).isoformat(), duration_ms=10)
        events.append((started, terminal))
    return events


@pytest.mark.asyncio
async def test_mixed_agent_results_merge_across_days_and_replay(isolated_monitoring, monkeypatch, record_property):
    from contracts.constants import environment
    from management.services.permission.identity import session as auth
    from management.db.agent.models import AgentInfo
    from permissions import rbac

    service, tenant = isolated_monitoring
    legacy = {"tenant_id": tenant, "fact_kind": "agent", "agent_id": 99, "statistic_date": "2026-11-01",
              "publish_id": "legacy", "execution_count": 1, "duration_sum_ms": 10, "duration_sample_count": 1}
    old_fields = {**DAILY_FIELDS, **dict.fromkeys(("execution_count", "duration_sum_ms", "duration_sample_count"), "long")}
    service.es.indices.put_index_template(name=DAILY, index_patterns=[f"{DAILY}-*"], priority=200,
                                          template={"mappings": mapping(old_fields)})
    index = f"{DAILY}-2026.11"
    service.es.index(index=index, id="legacy", document=legacy, refresh="wait_for")
    assert "succeeded_count" not in service.es.indices.get_mapping(index=index)[index]["mappings"]["properties"]
    install_templates(service.es, 0, runtime.MONITORING_KINDS.values())
    upgraded = service.es.indices.get_mapping(index=index)[index]["mappings"]["properties"]
    assert upgraded["succeeded_count"]["type"] == upgraded["failed_count"]["type"] == "long"
    assert service.es.get(index=index, id="legacy")["_source"] == legacy

    events = _mixed_result_events(tenant)
    async with collector.producer_lifespan():
        for started, terminal in events:
            emit_fact(started)
            if terminal is not started:
                emit_fact(terminal)
        await _wait_for_agent_batch(service, tenant)
        async with asyncio.timeout(15):
            while True:
                service.tick()
                result = service.es.search(index=f"{FACTS}-*", size=100, query=filters(tenant_id=tenant))
                sources = {hit["_source"]["fact_id"]: hit["_source"] for hit in result["hits"]["hits"]}
                if len(sources) == len(events) and all(sources[final["fact_id"]]["outcome"] == final["outcome"]
                                                       for _, final in events):
                    break
                await asyncio.sleep(0.1)
        with service.store.engine.begin() as connection:
            for number in (21, 22, 23, 24):
                connection.execute(insert(AgentInfo).values(
                    agent_id=number, version_no=0, tenant_id=tenant, name=f"result-{number}", delete_flag="N",
                ))
        monkeypatch.setattr(environment, "TRAJECTORY_READ_ENABLED", False)
        monkeypatch.setattr(environment, "MONITORING_PROVIDER", "otlp")
        from ops.api import application

        monkeypatch.setattr(application, "OPS_MONITORING_ENABLED", True)
        monkeypatch.setattr(auth, "get_current_user_context", lambda _: ("operator", tenant, "OPS"))
        monkeypatch.setattr(rbac, "_ROLE_PERMISSIONS", {"OPS": {"ops.dashboard:read"}})
        monkeypatch.setattr(rbac, "_INITIALIZED", True)
        app = application.create_app()
        app.state.monitoring = service
        params = {"start_date": "2026-11-01", "end_date": "2026-11-02", "group_ids": [12, 13]}
        base = "/ops/v1/monitoring/agents"
        expected = {21: (8, 2, 3, 0.4), 22: (3, 1, 1, 0.5), 23: (4, 0, 0, None), 24: (1, 0, 1, 0)}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://ops",
                                     headers={"Authorization": "Bearer ops"}) as client:
            async def read(suffix="/summary", **selection):
                response = await client.get(base + suffix, params={**params, **selection})
                assert response.status_code == 200
                return response.json()

            summaries = {}
            for number, values in expected.items():
                summaries[number] = await read(agent_id=number)
                metrics = summaries[number]["data"]
                assert tuple(metrics[field] for field in ("execution_count", "succeeded_count", "failed_count", "success_rate")) == values
            assert summaries[24]["data"]["duration_sample_count"] == 0
            assert summaries[24]["data"]["avg_duration_ms"] is None
            directory = (await read(""))["data"]
            assert directory["current_agent_count"] == directory["total"] == 4
            assert {row["agent_id"]: row["metrics"] for row in directory["items"]} == {
                number: body["data"] for number, body in summaries.items()
            }
            trend = (await read("/trends", agent_id=21))["data"]
            assert [(row["succeeded_count"], row["failed_count"], row["success_rate"]) for row in trend] == [
                (1, 0, 1), (1, 3, 0.25),
            ]
            assert summaries[21]["data"]["success_rate"] != sum(row["success_rate"] for row in trend) / 2
            zero = await read(group_ids=[555])
            assert zero["coverage_state"] == "covered"
            assert zero["data"]["succeeded_count"] == zero["data"]["failed_count"] == 0
            assert zero["data"]["success_rate"] is None
            combined = await read()
            assert (combined["data"]["succeeded_count"], combined["data"]["failed_count"],
                    combined["data"]["success_rate"]) == (3, 5, 0.375)
            for _, terminal in events:
                emit_fact(terminal)
            await _wait_for_agent_batch(service, tenant)
            service.tick()
            replay = service.es.search(index=f"{FACTS}-*", size=100, query=filters(tenant_id=tenant))
            assert {hit["_source"]["fact_id"]: hit["_source"] for hit in replay["hits"]["hits"]} == sources
            assert await read() == combined
            assert (await read("/trends", agent_id=21))["data"] == trend
            assert (await read(""))["data"] == directory
            for number in expected:
                assert await read(agent_id=number) == summaries[number]
        record_property("success_rate_verification", json.dumps({"agents": summaries, "root_trend": trend,
                                                                 "combined": combined, "covered_zero": zero}))


@pytest.mark.asyncio
@pytest.mark.parametrize("model_peer", ["children", "tokens", "children_traced"], indirect=True)
async def test_real_parent_and_child_facts_publish_and_replay(
    isolated_monitoring, model_peer, monkeypatch, record_property, request, first_answer_clock, tmp_path,
):
    from contracts.constants import environment
    from management.services.permission.identity import session as auth
    from management.db.agent.models import AgentInfo
    from permissions import rbac

    service, tenant = isolated_monitoring
    token_run = request.node.callspec.params["model_peer"] == "tokens"
    base, requests, release = model_peer
    release.set()
    manager = get_monitoring_manager()
    monkeypatch.setattr(manager, "_config", MonitoringConfig(enable_telemetry=False, provider="local_file"))
    assert not manager.is_enabled and not local_capture_enabled(manager)
    child = AgentConfig(name="child", agent_id=22, version_no=4, description="Controlled child",
                        model_name="child", tools=[], max_steps=2)
    info = AgentRunInfo(
        query="Delegate twice to the child", observer=MessageObserver(),
        agent_config=AgentConfig(name="root", agent_id=21, version_no=3, description="Controlled parent",
                                 model_name="model", tools=[], worker_agents=[child], max_steps=3),
        model_config_list=[ModelConfig(cite_name=alias, model_name=model, url=base, api_key="synthetic")
                           for alias, model in (("model", "model"), ("child", "child-model"))],
        stop_event=Event(), tenant_id=tenant, user_id="owner", conversation_id=124,
        workspace_run_id=uuid4().hex, history=[],
    )
    metadata = AgentRunMetadata(tenant_id=tenant, agent_id=21, is_debug=False, monitoring_group_ids=(12, 13),
                                user_id="owner", conversation_id=124)
    threads = ThreadManager("ops-agent-children", {
        lane: LanePolicy(lane, 2, 4)
        for lane in ("agent-run", "model-tool-io", "sandbox", "control-io", "background-service")
    })
    events = []
    model_events = []
    async with collector.producer_lifespan():
        sink = get_fact_sink()

        def capture(event):
            if event["fact_kind"] == "agent":
                events.append(dict(event))
            elif event["fact_kind"] == "model":
                model_events.append(dict(event))
            sink(event)

        set_fact_sink(capture)
        threads.start()
        trajectory = None
        try:
            trajectory = _child_trajectory(threads, manager, monkeypatch, tmp_path,
                                           enabled=request.node.callspec.params["model_peer"] == "children_traced")
            with agent_monitoring_context(metadata):
                async with asyncio.timeout(30):
                    async for _ in agent_run(info, thread_manager=threads):
                        pass
            assert info.attempt_outcome == "completed"
            assert [item["model"] for item in requests].count("model") == 2
            assert [item["model"] for item in requests].count("child-model") == 2
            starts = {event["fact_id"]: event for event in events if event["record_revision"] == 1}
            terminals = {event["fact_id"]: event for event in events if event["record_revision"] == 2}
            assert len(events) == 6 and len(starts) == len(terminals) == 3
            root = terminals[info.workspace_run_id]
            for terminal in terminals.values():
                _assert_first_answer_clock(first_answer_clock, terminal)
            children = [event for event in terminals.values() if not event["is_root"]]
            assert root["agent_id"] == 21 and len(children) == 2
            assert len({event["fact_id"] for event in children}) == 2
            assert all(event["parent_run_id"] == event["root_run_id"] == root["fact_id"] for event in children)
            assert all(event["agent_id"] == 22 and event["agent_version_no"] == 4 for event in children)
            for run_id, event in terminals.items():
                assert event["agent_run_id"] == run_id and event["outcome"] == "succeeded"
                assert event["started_at"] == starts[run_id]["started_at"] and event["duration_ms"] > 0
                assert event["tenant_id"] == tenant and event["initiator_group_ids"] == (12, 13)
                assert root["started_at"] <= event["started_at"] <= event["ended_at"] <= root["ended_at"]
            assert root["duration_ms"] >= sum(event["duration_ms"] for event in children)
            trajectory.verify(terminals)
            async with asyncio.timeout(15):
                while True:
                    if token_run:
                        while service.apply_batch(tenant, "agent") or service.apply_batch(tenant, "model"):
                            pass
                        service.publish(tenant, "agent")
                    else:
                        service.tick()
                    hits = service.es.search(index=f"{FACTS}-*", query=filters(tenant_id=tenant, fact_kind="agent"))
                    sources = {hit["_id"]: hit["_source"] for hit in hits["hits"]["hits"]}
                    if len(sources) == 3 and all(source["record_revision"] == 2 for source in sources.values()):
                        break
                    await asyncio.sleep(0.1)
            assert set(sources) == {stable_key(tenant, "agent", run_id) for run_id in terminals}
            for event in terminals.values():
                source = sources[stable_key(tenant, "agent", event["fact_id"])]
                assert source["duration_ms"] == event["duration_ms"] and source["outcome"] == "succeeded"
                if not event["is_root"]:
                    assert source["parent_run_id"] == source["root_run_id"] == root["fact_id"]
            for event in terminals.values():
                emit_fact(event)
                await _wait_for_agent_batch(service, tenant)
            if token_run:
                service.publish(tenant, "agent")
            else:
                service.tick()
            replayed = service.es.search(index=f"{FACTS}-*", query=filters(tenant_id=tenant, fact_kind="agent"))
            assert {hit["_id"]: hit["_source"] for hit in replayed["hits"]["hits"]} == sources
            day = date.fromisoformat(root["started_at"][:10])
            with service.publication_snapshot(tenant, "agent", day, day) as (states, point):
                state, = states
                daily = list(point.documents(filters(tenant_id=tenant, fact_kind="agent", publish_id=str(state["publish_id"]))))
            assert state["source_revision"] == state["published_source_revision"]
            by_agent = {row["agent_id"]: row for row in daily}
            assert by_agent[21]["execution_count"] == by_agent[21]["duration_sample_count"] == 1
            assert by_agent[21]["duration_sum_ms"] == root["duration_ms"]
            assert by_agent[22]["execution_count"] == by_agent[22]["duration_sample_count"] == 2
            assert by_agent[22]["duration_sum_ms"] == sum(event["duration_ms"] for event in children)
            for number, row in by_agent.items():
                measured = [event for event in terminals.values() if event["agent_id"] == number]
                assert row["ttft_sum_ms"] == sum(event["ttft_ms"] for event in measured)
                assert row["ttft_sample_count"] == len(measured)
                assert all(0 <= event["ttft_ms"] <= event["duration_ms"] for event in measured)
            with service.store.engine.begin() as connection:
                for number in (21, 22):
                    connection.execute(insert(AgentInfo).values(
                        agent_id=number, version_no=0, tenant_id=tenant, name=f"agent-{number}", delete_flag="N",
                    ))
            monkeypatch.setattr(environment, "TRAJECTORY_READ_ENABLED", False)
            monkeypatch.setattr(environment, "MONITORING_PROVIDER", "otlp")
            from ops.api import application

            monkeypatch.setattr(application, "OPS_MONITORING_ENABLED", True)
            monkeypatch.setattr(auth, "get_current_user_context", lambda _: ("operator", tenant, "OPS"))
            monkeypatch.setattr(rbac, "_ROLE_PERMISSIONS", {"OPS": {"ops.dashboard:read"}})
            monkeypatch.setattr(rbac, "_INITIALIZED", True)
            app = application.create_app()
            app.state.monitoring = service
            params = {"start_date": day.isoformat(), "end_date": day.isoformat(), "group_ids": [12, 13]}
            expected = {number: _successful_metrics(row["execution_count"],
                        row["duration_sum_ms"] / row["duration_sample_count"], row["duration_sample_count"],
                        row["ttft_sum_ms"] / row["ttft_sample_count"], row["ttft_sample_count"])
                        for number, row in by_agent.items()}
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://ops",
                                         headers={"Authorization": "Bearer ops"}) as client:
                for number in (21, 22):
                    response = await client.get("/ops/v1/monitoring/agents/summary", params=dict(params, agent_id=number))
                    assert response.status_code == 200 and response.json()["data"] == expected[number]
                listing = (await client.get("/ops/v1/monitoring/agents", params=params)).json()["data"]
                assert listing["current_agent_count"] == listing["total"] == 2
                assert {item["agent_id"]: item["metrics"] for item in listing["items"]} == expected
                summary = (await client.get("/ops/v1/monitoring/agents/summary", params=params)).json()
                assert summary["data"]["execution_count"] == summary["data"]["duration_sample_count"] == 3
                assert summary["data"]["avg_duration_ms"] == sum(event["duration_ms"] for event in terminals.values()) / 3
                assert summary["data"]["succeeded_count"] == 3 and summary["data"]["failed_count"] == 0
                assert summary["data"]["success_rate"] == 1
                assert summary["data"]["avg_ttft_ms"] == sum(event["ttft_ms"] for event in terminals.values()) / 3
                assert summary["data"]["ttft_sample_count"] == 3
                trend = (await client.get("/ops/v1/monitoring/agents/trends", params=params)).json()["data"]
                assert len(trend) == 1 and all(trend[0][key] == value for key, value in summary["data"].items())
                if token_run:
                    evidence = await _verify_real_agent_tokens(client, service, tenant, day, terminals, model_events)
                    record_property("agent_token_verification", json.dumps(evidence))
                else:
                    record_property("agent_ttft_verification", json.dumps(
                        await _verify_agent_ttft_history(client, service, tenant, day)))
            record_property("parent_child_metrics", json.dumps({"agents": expected, "combined": summary}))
        finally:
            if trajectory is not None:
                trajectory.close()
            await threads.shutdown(timeout=8)
            set_fact_sink(sink)


async def _verify_agent_ttft_history(client, service, tenant, day):
    """Publish controlled missing and zero samples beside real parent/child runs."""
    previous = day - timedelta(days=1)
    _, base = _run_across_midnight(tenant)
    events = []
    for statistic_day, timing, group, number in [
        (previous, 100, 77, 23), (day, 300, 77, 23), (day, 300, 77, 23), (day, 300, 77, 23),
        (day, 0, 77, 23), (day, None, 77, 23), (day, None, 78, 24), (day, 0, 79, 25),
    ]:
        run_id = uuid4().hex
        instant = datetime.combine(statistic_day, time.max, timezone.utc)
        fact = dict(base, fact_id=run_id, call_context_id=run_id, agent_run_id=run_id, root_run_id=run_id,
                    agent_id=number, initiator_group_ids=[group], started_at=instant.isoformat(),
                    ended_at=(instant + timedelta(milliseconds=350)).isoformat())
        if timing is not None:
            fact["ttft_ms"] = timing
        events.append(fact)
        emit_fact(fact)
    await _wait_for_agent_batch(service, tenant)
    while service.apply_batch(tenant, "agent"):
        pass
    service.publish(tenant, "agent")
    base_path = "/ops/v1/monitoring/agents"
    params = {"start_date": previous.isoformat(), "end_date": day.isoformat(), "agent_id": 23, "group_ids": [77]}

    async def read(suffix="/summary", **selection):
        response = await client.get(base_path + suffix, params={**params, **selection})
        assert response.status_code == 200
        return response.json()

    overall = await read()
    assert (overall["data"]["avg_ttft_ms"], overall["data"]["ttft_sample_count"]) == (200, 5)
    trend = (await read("/trends"))["data"]
    assert [(row["avg_ttft_ms"], row["ttft_sample_count"]) for row in trend] == [(100, 1), (225, 4)]
    assert (await read(start_date=day.isoformat()))["data"]["avg_ttft_ms"] == 225
    item, = (await read(""))["data"]["items"]
    assert item["metrics"] == overall["data"]
    missing = (await read(agent_id=24, group_ids=[78]))["data"]
    assert missing["avg_ttft_ms"] is None and missing["ttft_sample_count"] == 0
    zero = (await read(agent_id=25, group_ids=[79]))["data"]
    assert zero["avg_ttft_ms"] == 0 and zero["ttft_sample_count"] == 1
    assert (await client.get(base_path + "/summary", params={**params, "tenant_id": tenant + "-other"})).status_code == 403
    for fact in events:
        emit_fact(fact)
    await _wait_for_agent_batch(service, tenant)
    while service.apply_batch(tenant, "agent"):
        pass
    service.publish(tenant, "agent")
    assert await read() == overall
    assert (await read("/trends"))["data"] == trend
    return {"combined": overall, "days": trend, "missing": missing, "zero": zero}


async def _wait_for_model_batch(service, tenant):
    async with asyncio.timeout(15):
        while not service.apply_batch(tenant, "model"):
            await asyncio.sleep(0.05)


async def _verify_real_agent_tokens(client, service, tenant, day, agent_ends, model_events):
    model_ends = [event for event in model_events if event["record_revision"] == 2]
    assert len(model_events) == 8 and len({event["fact_id"] for event in model_ends}) == 4
    assert [event["agent_id"] for event in model_ends].count(21) == 2
    assert [event["agent_id"] for event in model_ends].count(22) == 2
    root_id, = [event["fact_id"] for event in agent_ends.values() if event["is_root"]]
    for event in model_ends:
        assert event["agent_id"] == agent_ends[event["agent_run_id"]]["agent_id"]
        assert event["root_run_id"] == root_id and event["initiator_group_ids"] == (12, 13)
    assert sorted(event["total_tokens"] for event in model_ends if event["agent_id"] == 21) == [12, 23]
    child = [event for event in model_ends if event["agent_id"] == 22]
    assert sum("total_tokens" in event for event in child) == 1
    assert next(event for event in child if "total_tokens" in event)["output_tokens"] == 0
    async with asyncio.timeout(15):
        while True:
            while service.apply_batch(tenant, "model"):
                pass
            hits = service.es.search(index=f"{FACTS}-*", size=100, query=filters(tenant_id=tenant, fact_kind="model"))
            sources = {hit["_source"]["fact_id"]: hit["_source"] for hit in hits["hits"]["hits"]}
            if len(sources) == 4 and all(source["record_revision"] == 2 for source in sources.values()):
                break
            await asyncio.sleep(0.1)
    for event in model_ends:
        source = sources[event["fact_id"]]
        assert source["agent_run_id"] == event["agent_run_id"] and source["agent_id"] == event["agent_id"]
        for field in ("input_tokens", "output_tokens", "total_tokens"):
            assert source.get(field) == event.get(field)
    params = {"start_date": day.isoformat(), "end_date": day.isoformat(), "group_ids": [12, 13]}
    base = "/ops/v1/monitoring/agents"

    async def read(suffix="/summary", **selection):
        response = await client.get(base + suffix, params={**params, **selection})
        assert response.status_code == 200
        return response.json()

    unpublished = await read()
    assert unpublished["tokens"] == dict.fromkeys(("input_tokens", "output_tokens", "total_tokens"))
    assert unpublished["token_status"]["coverage_state"] == "uncovered"
    assert unpublished["token_status"]["is_stale"] and not unpublished["is_stale"]
    service.publish(tenant, "model")
    published = await read()
    assert published["data"] == unpublished["data"] and published["data_as_of"] == unpublished["data_as_of"]
    assert published["tokens"]["input_tokens"]["value"] == "130"
    assert published["tokens"]["output_tokens"]["value"] == "5"
    assert published["tokens"]["total_tokens"] == {
        "value": "135", "known_count": 3, "eligible_count": 4, "coverage_rate": 0.75,
    }
    assert not published["token_status"]["is_stale"]
    assert published["token_status"]["data_as_of"] != published["data_as_of"]
    parent_usage = (await read(agent_id=21))["tokens"]["total_tokens"]
    child_usage = (await read(agent_id=22))["tokens"]["total_tokens"]
    assert parent_usage == {"value": "35", "known_count": 2, "eligible_count": 2, "coverage_rate": 1.0}
    assert child_usage == {"value": "100", "known_count": 1, "eligible_count": 2, "coverage_rate": 0.5}
    model_response = await client.get("/ops/v1/monitoring/models/summary", params=params)
    assert model_response.status_code == 200
    model_summary = model_response.json()
    assert model_summary["data"]["request_count"] == 4
    assert {field: model_summary["data"][field] for field in ("input_tokens", "output_tokens", "total_tokens")} == (
        published["tokens"]
    )
    assert {key: model_summary[key] for key in ("data_as_of", "coverage_state", "is_stale")} == published["token_status"]
    assert (await client.get("/ops/v1/monitoring/models/summary",
                             params=dict(params, tenant_id=tenant + "-other"))).status_code == 403
    with service.publication_snapshot(tenant, "model", day, day) as (states, point):
        state, = states
        daily = list(point.documents(filters(tenant_id=tenant, fact_kind="model", publish_id=str(state["publish_id"]))))
    assert {(row["agent_id"], row["request_count"], row["total_tokens_sum"], row["total_tokens_known_count"])
            for row in daily} == {(21, 2, 35, 2), (22, 2, 100, 1)}
    assert all(row["has_agent_run"] for row in daily)
    for event in model_ends:
        emit_fact(event)
    await _wait_for_model_batch(service, tenant)
    service.publish(tenant, "model")
    assert await read() == published
    assert (await client.get("/ops/v1/monitoring/models/summary", params=params)).json() == model_summary
    replay = service.es.search(index=f"{FACTS}-*", size=100, query=filters(tenant_id=tenant, fact_kind="model"))
    assert {hit["_source"]["fact_id"]: hit["_source"] for hit in replay["hits"]["hits"]} == sources
    previous = day - timedelta(days=1)
    anchor = datetime.combine(day, time.min, timezone.utc) - timedelta(milliseconds=100)
    extras = [dict(model_ends[0], fact_id=uuid4().hex, call_context_id=uuid4().hex,
                   agent_id=24, agent_run_id=uuid4().hex, root_run_id=uuid4().hex,
                   started_at=anchor.isoformat(), ended_at=(anchor + timedelta(milliseconds=200)).isoformat(),
                   duration_ms=200, input_tokens=5, output_tokens=2, total_tokens=7)]
    for identity in ({"agent_id": None, "agent_run_id": None}, {"agent_id": 21, "agent_run_id": None},
                     {"agent_id": None, "agent_run_id": uuid4().hex}, {"initiator_group_ids": [99]}):
        extras.append(dict(model_ends[0], fact_id=uuid4().hex, call_context_id=uuid4().hex,
                           input_tokens=999, output_tokens=999, total_tokens=1998, **identity))
    for event in extras:
        emit_fact(event)
    await _wait_for_model_batch(service, tenant)
    while service.apply_batch(tenant, "model"):
        pass
    stale = await read(start_date=previous.isoformat())
    assert stale["tokens"]["total_tokens"]["value"] == "135" and stale["token_status"]["is_stale"]
    assert stale["data_as_of"] == published["data_as_of"]
    service.publish(tenant, "model")
    final = await read(start_date=previous.isoformat())
    assert final["tokens"]["total_tokens"] == {
        "value": "142", "known_count": 4, "eligible_count": 5, "coverage_rate": 0.8,
    }
    assert not final["token_status"]["is_stale"]
    assert (await read())["tokens"] == published["tokens"]
    prior = await read(start_date=previous.isoformat(), end_date=previous.isoformat())
    assert prior["tokens"]["total_tokens"]["value"] == "7"
    assert (await read(agent_id=24, start_date=previous.isoformat()))["tokens"] == prior["tokens"]
    directory = (await read("", start_date=previous.isoformat()))["data"]
    assert directory["current_agent_count"] == 2 and directory["total"] == 3
    token_only, = [item for item in directory["items"] if item["agent_id"] == 24]
    assert token_only["is_current"] is False and token_only["metrics"] is None
    assert token_only["tokens"]["total_tokens"]["value"] == "7"
    assert sum(int(item["tokens"]["total_tokens"]["value"]) for item in directory["items"]) == 142
    trends = (await read("/trends", start_date=previous.isoformat()))["data"]
    assert [item["tokens"]["total_tokens"]["value"] for item in trends] == ["7", "135"]
    assert [item["token_status"]["coverage_state"] for item in trends] == ["partial", "covered"]
    zero = await read(group_ids=[555])
    assert zero["tokens"]["total_tokens"] == {"value": "0", "known_count": 0, "eligible_count": 0, "coverage_rate": None}
    assert zero["token_status"]["coverage_state"] == "covered"
    missing = previous - timedelta(days=1)
    assert (await read(start_date=missing.isoformat(), end_date=missing.isoformat()))["tokens"]["total_tokens"] is None
    assert (await client.get(base + "/summary", params=dict(params, tenant_id=tenant + "-other"))).status_code == 403
    return {"unpublished": unpublished, "published": published, "stale": stale, "final": final,
            "parent": parent_usage, "child": child_usage, "trends": trends, "zero": zero}


@pytest.mark.asyncio
@pytest.mark.parametrize("model_peer", ["normal", "failed", "cancelled", "cross_day", "trajectory_off",
                                      "prepare_failure"], indirect=True)
async def test_complete_main_timing_matches_raw_trajectory_and_published_queries(
    isolated_monitoring, model_peer, monkeypatch, tmp_path, record_property, request,
):
    """Exercise the real worker, OTLP file writer, ES publication and authorized HTTP reads."""
    from infrastructure.trace.trajectory_processor import LocalTrajectoryProcessor
    from infrastructure.trace.trajectory_store import TrajectoryFileStore
    from management.services.permission.identity import session as auth
    from nexent.core.concurrency import ManagedThreadSpec
    from nexent.monitor import get_agent_monitoring_context
    from nexent.monitor import phase_capture
    from nexent.monitor.run_timing import RunTiming
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.sampling import ALWAYS_ON
    from permissions import rbac

    service, tenant = isolated_monitoring
    base, requests, release = model_peer
    mode = request.node.callspec.params["model_peer"]
    enabled = mode != "trajectory_off"
    directory = tmp_path / "trajectory"
    TrajectoryFileStore.provision(directory)
    store = TrajectoryFileStore(directory, authorize=lambda _: None)
    processor = LocalTrajectoryProcessor(store, get_agent_monitoring_context)
    threads = ThreadManager("main-timing", {
        lane: LanePolicy(lane, 2, 3)
        for lane in ("agent-run", "model-tool-io", "sandbox", "control-io", "background-service")
    })
    provider = TracerProvider(sampler=processor.wrap_sampler(ALWAYS_ON), shutdown_on_exit=False)
    provider.add_span_processor(processor)
    manager = get_monitoring_manager()
    monkeypatch.setattr(manager, "_config", MonitoringConfig(
        enable_telemetry=enabled, provider="local_file", local_span_processor=processor, export_metrics=False,
    ))
    monkeypatch.setattr(manager, "_tracer", provider.get_tracer("main-timing"))
    if mode == "cross_day":
        instants = iter((1793491199000000000, 1793491200100000000, 1793491200200000000))
        monkeypatch.setattr(phase_capture, "RunTiming", lambda: RunTiming(utc_clock_ns=lambda: next(instants)))

    @phase_capture.capture_preparation
    async def prepare():
        await asyncio.sleep(0.01)
        return AgentRunInfo(
            query="Run the controlled main Agent", observer=MessageObserver(),
            agent_config=AgentConfig(
                name="root", description="Controlled Agent",
                model_name="model", agent_core="missing_core" if mode == "prepare_failure" else "smolagents",
                agent_id=21, version_no=3, tools=[], max_steps=2,
            ),
            model_config_list=[ModelConfig(cite_name="model", model_name="model", url=base, api_key="synthetic")],
            stop_event=Event(), user_id="owner", tenant_id=tenant, conversation_id=123,
            workspace_run_id=uuid4().hex, history=[],
        )

    info = await prepare()
    metadata = AgentRunMetadata(
        tenant_id=tenant, agent_id=21, user_id=info.user_id, conversation_id=123,
        monitoring_group_ids=(12, 13),
    )
    observations = []

    async def consume():
        with agent_monitoring_context(metadata):
            async for _ in agent_run(info, thread_manager=threads):
                pass

    threads.start()
    processor.start(threads, ManagedThreadSpec("trajectory-writer", "main-timing", close_hook=processor.request_stop))
    try:
        async with collector.producer_lifespan():
            sink = get_fact_sink()

            def capture(event):
                if event["fact_kind"] == "agent":
                    observations.append(dict(event))
                sink(event)

            set_fact_sink(capture)
            worker = asyncio.create_task(consume())
            try:
                if mode not in {"failed", "prepare_failure"}:
                    async with asyncio.timeout(15):
                        while not requests:
                            assert not worker.done(), "Worker exited before the model HTTP request"
                            await asyncio.sleep(0.02)
                    if mode == "cancelled":
                        info.cancellation_scope.cancel()
                    release.set()
                async with asyncio.timeout(20):
                    await asyncio.gather(worker, return_exceptions=True)
                    await asyncio.wrap_future(info.thread_future)
            except Exception:
                if mode not in {"failed", "prepare_failure"}:
                    raise
            finally:
                release.set()
                if not worker.done():
                    worker.cancel()
                    await asyncio.gather(worker, return_exceptions=True)
            assert info.thread_future.done()
            result = info.run_timing.finish()
            assert result.run_id == info.workspace_run_id and result.duration_ms >= 10
            assert processor.force_flush(5000)
            raw = [
                span for path in directory.rglob("*.otlp.jsonl") for line in path.read_text().splitlines()
                for resource in json.loads(line)["resourceSpans"] for scope in resource["scopeSpans"]
                for span in scope["spans"] if span["name"] == "agent.run"
            ]
            if enabled:
                root, = raw
                attrs = {item["key"]: next(iter(item["value"].values())) for item in root["attributes"]}
                assert int(root["startTimeUnixNano"]) == result.started_at_ns
                assert int(root["endTimeUnixNano"]) == result.ended_at_ns
                assert int(attrs["nexent.duration_ms"]) == result.duration_ms
                assert attrs["nexent.agent_run_id"] == info.workspace_run_id
            else:
                assert raw == [] and not local_capture_enabled(manager)
            if mode == "prepare_failure":
                assert observations == [] and requests == []
                assert result.execution_started_at is None and info.attempt_outcome == "failed"
                assert not service.apply_batch(tenant, "agent")
                record_property("main_timing", json.dumps({"mode": mode, "duration_ms": result.duration_ms,
                                                         "execution_count": 0, "raw_span": enabled}))
                return
            assert len(requests) == 1
            start, finish = observations
            assert [item["record_revision"] for item in observations] == [1, 2]
            for key in ("fact_id", "agent_run_id", "root_run_id", "call_context_id"):
                assert start[key] == finish[key] == result.run_id
            assert start["started_at"] == finish["started_at"] == result.started_at.isoformat()
            assert start["execution_started_at"] == finish["execution_started_at"] == (
                result.execution_started_at.isoformat()
            )
            assert finish["ended_at"] == result.ended_at.isoformat() and finish["duration_ms"] == result.duration_ms
            outcome = {"failed": "failed", "cancelled": "cancelled"}.get(mode, "succeeded")
            assert finish["outcome"] == outcome
            hit = await _apply_and_read(service, tenant)
            day = result.execution_started_at.date()
            assert hit["_source"]["duration_ms"] == result.duration_ms
            assert hit["_source"]["statistic_date"] == day.isoformat()
            assert hit["_index"] == f"{FACTS}-{day:%Y.%m}"
            if mode == "cross_day":
                assert result.started_at.date() == date(2026, 10, 31) and day == date(2026, 11, 1)
                assert not service.es.indices.exists(index=f"{FACTS}-2026.10")
            service.tick()
            original = _published_agent_day(service, tenant, day)
            _, daily = original
            assert daily["execution_count"] == daily["duration_sample_count"] == 1
            assert daily["duration_sum_ms"] == result.duration_ms
            assert daily["succeeded_count"] == int(outcome == "succeeded")
            assert daily["failed_count"] == int(outcome == "failed")
            assert daily["ttft_sample_count"] == int("ttft_ms" in finish)
            await _submit_and_read(service, tenant, finish)
            service.tick()
            assert _published_agent_day(service, tenant, day) == original
            monkeypatch.setattr(auth, "get_current_user_context", lambda _: ("operator", tenant, "OPS"))
            monkeypatch.setattr(rbac, "_ROLE_PERMISSIONS", {"OPS": {"ops.dashboard:read"}})
            monkeypatch.setattr(rbac, "_INITIALIZED", True)
            from ops.api import application

            monkeypatch.setattr(application, "OPS_MONITORING_ENABLED", True)
            app = application.create_app()
            app.state.monitoring = service
            params = {"start_date": day.isoformat(), "end_date": day.isoformat(), "agent_id": 21,
                      "group_ids": [12, 13]}
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://ops") as client:
                response = await client.get("/ops/v1/monitoring/agents/summary", params=params,
                                            headers={"Authorization": "Bearer ops"})
                assert response.status_code == 200
                metrics = response.json()["data"]
                assert metrics["execution_count"] == metrics["duration_sample_count"] == 1
                assert metrics["avg_duration_ms"] == result.duration_ms
                assert metrics["succeeded_count"] == int(outcome == "succeeded")
                assert metrics["failed_count"] == int(outcome == "failed")
                assert metrics["avg_ttft_ms"] == finish.get("ttft_ms")
            record_property("main_timing", json.dumps({
                "mode": mode, "run_id": result.run_id, "duration_ms": result.duration_ms,
                "started_at": start["started_at"], "execution_started_at": start["execution_started_at"],
                "ended_at": finish["ended_at"], "es_index": hit["_index"], "raw_span": enabled,
                "query": metrics, "replay_count": 1,
            }))
            set_fact_sink(sink)
    finally:
        processor.shutdown()
        provider.shutdown()
        await threads.shutdown(timeout=8)
        assert threads.snapshot().active_count == 0


@pytest.mark.asyncio
async def test_agent_list_sorts_filtered_published_resource_totals(isolated_monitoring, monkeypatch, record_property):
    """Order actual multi-day publications through the authorized HTTP list before paging."""
    from contracts.constants import environment
    from management.db.agent.models import AgentInfo
    from management.services.permission.identity import session as auth
    from permissions import rbac

    service, tenant = isolated_monitoring
    peer = tenant + "-other"
    first, last = date(2026, 11, 18), date(2026, 11, 19)
    # Each row owns independent attempts; None represents an actual missing usage sample.
    plans = [
        (tenant, first, 21, 12, ["succeeded"], [4]),
        (tenant, last, 21, 12, ["failed"] * 3, [10]),
        (tenant, first, 22, 12, ["succeeded", "failed"], [12]),
        (tenant, last, 23, 12, ["succeeded", "failed"], [14, None]),
        (tenant, last, 24, 12, ["cancelled"], [None]),
        (tenant, last, 25, 12, ["failed"], [0]),
        (tenant, last, 26, 12, ["cancelled"], [0]),
        (peer, last, 11, 12, ["succeeded", "failed"], [14]),
        (tenant, last, 22, 99, ["succeeded"], [999]),
        (tenant, last + timedelta(days=1), 22, 12, ["succeeded"], [999]),
    ]
    events = []
    for scope, day, agent, group, results, usages in plans:
        instant = datetime.combine(day, time(12), timezone.utc)
        runs = []
        for outcome in results:
            _, fact = _run_across_midnight(scope)
            fact.update(agent_id=agent, initiator_group_ids=[group], outcome=outcome,
                        started_at=instant.isoformat(), ended_at=(instant + timedelta(milliseconds=10)).isoformat(),
                        duration_ms=10)
            events.append(fact)
            runs.append(fact["fact_id"])
        for value in usages:
            identity = uuid4().hex
            fact = {"tenant_id": scope, "fact_kind": "model", "fact_id": identity, "call_context_id": identity,
                    "agent_id": agent, "agent_run_id": runs[0], "root_run_id": runs[0],
                    "model_type": "llm", "initiator_group_ids": [group], "record_revision": 2,
                    "started_at": instant.isoformat(), "ended_at": (instant + timedelta(milliseconds=5)).isoformat(),
                    "outcome": "succeeded", "duration_ms": 5}
            if value is not None:
                fact.update(input_tokens=value, output_tokens=0, total_tokens=value)
            events.append(fact)
    with service.store.engine.begin() as connection:
        for scope, numbers in ((tenant, range(21, 27)), (peer, [11])):
            for number in numbers:
                connection.execute(insert(AgentInfo).values(
                    tenant_id=scope, agent_id=number, version_no=0, delete_flag="N",
                    name=f"sort-{number}", group_ids="12,99",
                ))

    async with collector.producer_lifespan():
        for fact in events:
            emit_fact(fact)
        async with asyncio.timeout(20):
            while True:
                for scope in (tenant, peer):
                    for kind in ("agent", "model"):
                        while service.apply_batch(scope, kind):
                            pass
                count = service.es.count(index=f"{FACTS}-*", ignore_unavailable=True)["count"]
                if count == len(events):
                    break
                await asyncio.sleep(0.1)
        for scope in (tenant, peer):
            for kind in ("agent", "model"):
                service.publish(scope, kind)

    monkeypatch.setattr(environment, "TRAJECTORY_READ_ENABLED", False)
    monkeypatch.setattr(environment, "MONITORING_PROVIDER", "otlp")
    from ops.api import application

    monkeypatch.setattr(application, "OPS_MONITORING_ENABLED", True)
    principals = {"Bearer ops": ("operator", tenant, "OPS"), "Bearer admin": ("admin", tenant, "SU")}
    monkeypatch.setattr(auth, "get_current_user_context", principals.__getitem__)
    monkeypatch.setattr(rbac, "_ROLE_PERMISSIONS", {"OPS": {"ops.dashboard:read"}, "SU": {"ops.dashboard:read"}})
    monkeypatch.setattr(rbac, "_INITIALIZED", True)
    app = application.create_app()
    app.state.monitoring = service
    selection = {"start_date": first.isoformat(), "end_date": last.isoformat(), "group_ids": [12]}
    expected = {
        ("total_tokens", False): [25, 26, 22, 21, 23, 24],
        ("total_tokens", True): [21, 23, 22, 25, 26, 24],
        ("success_rate", False): [25, 21, 22, 23, 24, 26],
        ("success_rate", True): [22, 23, 21, 25, 24, 26],
    }
    evidence = {}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://ops") as client:
        async def read(actor="ops", suffix="", **params):
            return await client.get("/ops/v1/monitoring/agents" + suffix, params={**selection, **params},
                                    headers={"Authorization": f"Bearer {actor}"})

        for (metric, descending), order in expected.items():
            response = await read(sort_by=metric, descending=descending)
            assert response.status_code == 200
            body = response.json()
            rows = body["data"]["items"]
            assert [row["agent_id"] for row in rows] == order
            assert {row["tenant_id"] for row in rows} == {tenant}
            assert body["data"]["total"] == body["data"]["current_agent_count"] == 6
            lookup = {row["agent_id"]: row for row in rows}
            assert lookup[21]["tokens"]["total_tokens"]["value"] == "14"
            assert lookup[21]["metrics"]["success_rate"] == 0.25
            assert lookup[22]["metrics"]["success_rate"] == 0.5
            assert lookup[23]["tokens"]["total_tokens"]["coverage_rate"] == 0.5
            assert lookup[24]["tokens"]["total_tokens"]["value"] is None
            assert lookup[24]["tokens"]["total_tokens"]["known_count"] == 0
            assert lookup[24]["tokens"]["total_tokens"]["eligible_count"] == 1
            assert lookup[24]["metrics"]["success_rate"] is None
            assert lookup[25]["tokens"]["total_tokens"]["value"] == "0"
            assert lookup[25]["metrics"]["success_rate"] == 0
            paged = []
            for page in (1, 2):
                part = await read(sort_by=metric, descending=descending, page=page, page_size=3)
                assert part.status_code == 200
                assert part.json() == (await read(
                    sort_by=metric, descending=descending, page=page, page_size=3,
                )).json()
                paged.extend(part.json()["data"]["items"])
            assert paged == rows
            evidence[f"{metric}:{descending}"] = body

        # Date and group changes must select statistics before computing the sort key.
        prior = (await read(sort_by="total_tokens", end_date=first.isoformat())).json()["data"]["items"]
        assert [row["agent_id"] for row in prior][:2] == [22, 21]
        prior_rates = (await read(sort_by="success_rate", end_date=first.isoformat())).json()["data"]["items"]
        assert [row["agent_id"] for row in prior_rates][:2] == [21, 22]
        group = (await read(sort_by="total_tokens", group_ids=[99])).json()["data"]["items"]
        assert group[0]["agent_id"] == 22 and group[0]["tokens"]["total_tokens"]["value"] == "999"
        for metric in ("total_tokens", "success_rate"):
            single = await read(sort_by=metric, agent_id=21)
            assert single.status_code == 200 and single.json()["data"]["total"] == 1
            assert single.json()["data"]["items"][0]["tokens"]["total_tokens"]["value"] == "14"
            assert (await read(sort_by=metric, tenant_id=peer)).status_code == 403
            foreign = await read("admin", sort_by=metric, tenant_id=peer)
            assert foreign.status_code == 200
            assert {(row["tenant_id"], row["agent_id"]) for row in foreign.json()["data"]["items"]} == {(peer, 11)}
        global_tokens = (await read("admin", sort_by="total_tokens")).json()["data"]["items"]
        assert [(row["tenant_id"], row["agent_id"]) for row in global_tokens][:3] == [
            (tenant, 21), (tenant, 23), (peer, 11),
        ]
        global_rates = (await read("admin", sort_by="success_rate")).json()["data"]["items"]
        assert [(row["tenant_id"], row["agent_id"]) for row in global_rates][:3] == [
            (tenant, 22), (tenant, 23), (peer, 11),
        ]
        count_ranking = await read(suffix="/rankings")
        assert count_ranking.status_code == 200
        assert count_ranking.json() == (await read(suffix="/rankings", metric="execution_count")).json()
        assert [row["agent_id"] for row in count_ranking.json()["data"]] == [21, 22, 23, 24, 25]
        assert "token_status" not in count_ranking.json()
        assert all("success_sample_count" not in row["metrics"] for row in count_ranking.json()["data"])
        ranks = {}
        for metric, order in (("total_tokens", [21, 23, 22, 25, 26]), ("success_rate", [22, 23, 21, 25])):
            response = await read(suffix="/rankings", metric=metric)
            assert response.status_code == 200
            body = response.json()
            assert [row["agent_id"] for row in body["data"]] == order
            lookup = {row["agent_id"]: row for row in evidence[f"{metric}:True"]["data"]["items"]}
            for row in body["data"]:
                if metric == "total_tokens":
                    assert row == lookup[row["agent_id"]]
                else:
                    assert row["metrics"]["success_rate"] == lookup[row["agent_id"]]["metrics"]["success_rate"]
                    assert row["metrics"]["success_sample_count"] == {21: 4, 22: 2, 23: 2, 25: 1}[row["agent_id"]]
            if metric == "total_tokens":
                assert body["token_status"] == evidence["total_tokens:True"]["token_status"]
            else:
                assert "token_status" not in body
            prior = await read(suffix="/rankings", metric=metric, end_date=first.isoformat())
            assert prior.status_code == 200
            assert [row["agent_id"] for row in prior.json()["data"]] == (
                [22, 21] if metric == "total_tokens" else [21, 22]
            )
            grouped = await read(suffix="/rankings", metric=metric, group_ids=[99])
            assert grouped.status_code == 200
            assert [row["agent_id"] for row in grouped.json()["data"]] == [22]
            for number, eligible in ((21, True), (24, False), (25, True)):
                single = await read(suffix="/rankings", metric=metric, agent_id=number)
                assert single.status_code == 200
                assert [row["agent_id"] for row in single.json()["data"]] == ([number] if eligible else [])
            assert (await read(suffix="/rankings", metric=metric, tenant_id=peer)).status_code == 403
            foreign = await read("admin", suffix="/rankings", metric=metric, tenant_id=peer)
            assert foreign.status_code == 200
            assert [(row["tenant_id"], row["agent_id"]) for row in foreign.json()["data"]] == [(peer, 11)]
            global_rank = await read("admin", suffix="/rankings", metric=metric)
            assert global_rank.status_code == 200
            assert [(row["tenant_id"], row["agent_id"]) for row in global_rank.json()["data"]][:3] == (
                [(tenant, 21), (tenant, 23), (peer, 11)] if metric == "total_tokens"
                else [(tenant, 22), (tenant, 23), (peer, 11)]
            )
            assert body == (await read(suffix="/rankings", metric=metric)).json()
            ranks[metric] = body
        record_property("agent_rankings", json.dumps(ranks))
    record_property("agent_list_sorting", json.dumps(evidence))


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["normal_traced", "normal_untraced", "root_failed", "child_failed", "cancelled"])
async def test_actual_jiuwen_agent_monitoring_pipeline(
    isolated_monitoring, monkeypatch, tmp_path, record_property, first_answer_clock, mode,
):
    """Keep Jiuwen Runner, model service and the monitoring pipeline real."""
    import importlib.metadata
    from shared.jiuwen_peer import model_config, provider
    from management.services.permission.identity import session as auth
    from nexent.core.agents.factory import AgentCoreFactory
    from nexent.core.agents.cores.jiuwen.adapter import JiuwenAdapter
    from permissions import rbac

    assert importlib.metadata.version("openjiuwen") == "0.1.19"
    service, tenant = isolated_monitoring
    selected, native = [], []
    create, prepare = AgentCoreFactory.create, JiuwenAdapter.prepare

    def observed_create(info, **kwargs):
        adapter = create(info, **kwargs)
        assert isinstance(adapter, JiuwenAdapter)
        selected.append(adapter)
        return adapter

    def observed_prepare(adapter):
        prepare(adapter)
        assert type(adapter.native_agent).__module__.startswith("openjiuwen.")
        native.append(type(adapter.native_agent).__qualname__)

    monkeypatch.setattr(AgentCoreFactory, "create", observed_create)
    monkeypatch.setattr(JiuwenAdapter, "prepare", observed_prepare)
    with provider(mode) as (base, requests, child_started, release):
        child = AgentConfig(agent_core="jiuwen", name="child", agent_id=22, version_no=4,
                            description="Controlled child", model_name="child", tools=[], max_steps=3)
        info = AgentRunInfo(
            query="Delegate twice and then answer", observer=MessageObserver(), stop_event=Event(),
            agent_config=AgentConfig(agent_core="jiuwen", name="root", agent_id=21, version_no=3,
                                     description="Controlled root", model_name="root", tools=[],
                                     worker_agents=[child], max_steps=3),
            model_config_list=[model_config(base, tenant, role, number) for role, number in
                               (("root", 7), ("child", 8))],
            tenant_id=tenant, user_id="owner", conversation_id=126, workspace_run_id=uuid4().hex, history=[],
        )
        metadata = AgentRunMetadata(tenant_id=tenant, user_id="owner", conversation_id=126, agent_id=21,
                                    monitoring_group_ids=(12, 13))
        threads = ThreadManager("jiuwen-monitoring", {
            lane: LanePolicy(lane, 4, 4)
            for lane in ("agent-run", "model-tool-io", "sandbox", "control-io", "background-service", "mcp-session")
        })
        threads.start()
        trajectory = _child_trajectory(threads, get_monitoring_manager(), monkeypatch, tmp_path,
                                       enabled=mode != "normal_untraced")
        agents, models = [], []
        try:
            async with collector.producer_lifespan():
                sink = get_fact_sink()

                def capture(event):
                    (agents if event["fact_kind"] == "agent" else models).append(dict(event))
                    sink(event)

                set_fact_sink(capture)

                async def consume():
                    with agent_monitoring_context(metadata):
                        async for _ in agent_run(info, thread_manager=threads):
                            pass

                execution = asyncio.create_task(consume())
                try:
                    if mode == "cancelled":
                        async with asyncio.timeout(20):
                            while not child_started.is_set():
                                assert not execution.done(), "Jiuwen exited before calling the child model"
                                await asyncio.sleep(0.02)
                        info.cancellation_scope.cancel()
                        release.set()
                    async with asyncio.timeout(30):
                        await asyncio.gather(execution, return_exceptions=True)
                        await asyncio.gather(asyncio.wrap_future(info.thread_future), return_exceptions=True)
                finally:
                    release.set()
                    if not execution.done():
                        info.cancellation_scope.cancel()
                        await asyncio.gather(execution, return_exceptions=True)
                normal = mode.startswith("normal")
                root_completed = normal or mode == "child_failed"
                assert info.attempt_outcome == (
                    "completed" if root_completed else "stopped" if mode == "cancelled" else "failed"
                )
                if root_completed:
                    assert info.run_result.final_content == "root-ready"
                starts = {item["fact_id"]: item for item in agents if item["record_revision"] == 1}
                terminals = {item["fact_id"]: item for item in agents if item["record_revision"] == 2}
                assert starts.keys() == terminals.keys() and len(agents) == 2 * len(terminals)
                root = terminals[info.workspace_run_id]
                root_timing = info.run_timing.finish()
                assert root["started_at"] == root_timing.started_at.isoformat()
                assert root["ended_at"] == root_timing.ended_at.isoformat()
                assert root["duration_ms"] == root_timing.duration_ms
                assert root["outcome"] == (
                    "succeeded" if root_completed else "cancelled" if mode == "cancelled" else "failed"
                )
                children = [item for item in terminals.values() if not item["is_root"]]
                assert root["agent_id"] == 21 and len(selected) == len(native) == len(terminals)
                if normal:
                    assert len(children) == 2
                    assert [item["role"] for item in requests].count("root") == 2
                    assert [item["role"] for item in requests].count("child") == 2
                elif mode == "root_failed":
                    assert children == [] and len(requests) == 1 and root["outcome"] == "failed"
                else:
                    assert children and all(item["outcome"] == ("cancelled" if mode == "cancelled" else "failed")
                                            for item in children)
                    if mode == "child_failed":
                        assert len(children) == 2 and len(requests) == 4
                for key, terminal in terminals.items():
                    assert terminal["started_at"] == starts[key]["started_at"]
                    assert terminal["execution_started_at"] == starts[key]["execution_started_at"]
                    assert terminal["duration_ms"] >= 0
                    if normal:
                        assert terminal["outcome"] == "succeeded"
                        _assert_first_answer_clock(first_answer_clock, terminal)
                    elif terminal["is_root"] and root_completed:
                        _assert_first_answer_clock(first_answer_clock, terminal)
                    else:
                        assert terminal.get("ttft_ms") is None
                    if not terminal["is_root"]:
                        assert terminal["parent_run_id"] == terminal["root_run_id"] == info.workspace_run_id
                        assert terminal["agent_id"] == 22
                raw = trajectory.verify(terminals)
                async with asyncio.timeout(15):
                    while True:
                        service.apply_batch(tenant, "agent")
                        hits = service.es.search(index=f"{FACTS}-*", query=filters(
                            tenant_id=tenant, fact_kind="agent"), size=100)["hits"]["hits"]
                        if len(hits) == len(terminals) and all(hit["_source"]["record_revision"] == 2 for hit in hits):
                            break
                        await asyncio.sleep(0.05)
                for hit in hits:
                    fact = terminals[hit["_source"]["fact_id"]]
                    assert all(hit["_source"].get(field) == fact.get(field) for field in
                               ("duration_ms", "ttft_ms", "outcome", "agent_run_id", "parent_run_id"))
                service.publish(tenant, "agent")
                day = datetime.fromisoformat(root["execution_started_at"]).date()
                from management.db.agent.models import AgentInfo

                with service.store.engine.begin() as connection:
                    for number, outlet in ((21, 7), (22, 8)):
                        connection.execute(insert(AgentInfo).values(
                            tenant_id=tenant, agent_id=number, version_no=0, delete_flag="N",
                            name=f"jiuwen-{number}", model_ids=[outlet], group_ids="12,13",
                        ))
                monkeypatch.setattr(auth, "get_current_user_context", lambda _: ("operator", tenant, "OPS"))
                monkeypatch.setattr(rbac, "_ROLE_PERMISSIONS", {"OPS": {"ops.dashboard:read"}})
                monkeypatch.setattr(rbac, "_INITIALIZED", True)
                from ops.api import application

                monkeypatch.setattr(application, "OPS_MONITORING_ENABLED", True)
                app = application.create_app()
                app.state.monitoring = service
                params = {"start_date": day.isoformat(), "end_date": day.isoformat(), "group_ids": [12, 13]}
                metrics = {}
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://ops",
                                             headers={"Authorization": "Bearer ops"}) as client:
                    for number in {item["agent_id"] for item in terminals.values()}:
                        response = await client.get("/ops/v1/monitoring/agents/summary",
                                                    params=dict(params, agent_id=number))
                        assert response.status_code == 200
                        values = response.json()["data"]
                        facts = [item for item in terminals.values() if item["agent_id"] == number]
                        assert values["execution_count"] == values["duration_sample_count"] == len(facts)
                        assert values["avg_duration_ms"] == sum(item["duration_ms"] for item in facts) / len(facts)
                        successes = sum(item["outcome"] == "succeeded" for item in facts)
                        failures = sum(item["outcome"] == "failed" for item in facts)
                        assert (values["succeeded_count"], values["failed_count"]) == (successes, failures)
                        assert values["success_rate"] == (successes / (successes + failures)
                                                          if successes + failures else None)
                        answers = [item["ttft_ms"] for item in facts if item.get("ttft_ms") is not None]
                        assert values["avg_ttft_ms"] == (sum(answers) / len(answers) if answers else None)
                        metrics[number] = values
                    states = service.store.states(tenant, "agent", day, day)
                    for terminal in terminals.values():
                        emit_fact(terminal)
                    await _wait_for_agent_batch(service, tenant)
                    service.publish(tenant, "agent")
                    assert service.store.states(tenant, "agent", day, day) == states
                    for number, values in metrics.items():
                        replay = await client.get("/ops/v1/monitoring/agents/summary",
                                                  params=dict(params, agent_id=number))
                        assert replay.status_code == 200 and replay.json()["data"] == values
                    actual_model_facts = [dict(item) for item in models if item["record_revision"] == 2]
                    token_evidence = await _verify_real_agent_tokens(
                        client, service, tenant, day, terminals, models) if normal else None
                record_property("jiuwen_pipeline", json.dumps({
                    "mode": mode, "core": "jiuwen", "version": "0.1.19", "native_agents": native,
                    "requests": [{"role": item["role"], "stream": item["stream"]} for item in requests],
                    "metrics": metrics, "raw": raw,
                    "agent_facts": list(terminals.values()), "model_facts": actual_model_facts,
                    "root_timing": {"run_id": root_timing.run_id, "duration_ms": root_timing.duration_ms,
                                    "started_at": root["started_at"], "ended_at": root["ended_at"]},
                    "tokens": token_evidence["published"]["tokens"] if token_evidence else None,
                }))
                set_fact_sink(sink)
        finally:
            trajectory.close()
            await threads.shutdown(timeout=8)
            assert threads.snapshot().active_count == 0


def _child_trajectory(threads, manager, monkeypatch, directory, *, enabled):
    """Own real local OTLP capture and verify each child against its exact frozen clock."""
    from infrastructure.trace.trajectory_processor import LocalTrajectoryProcessor
    from infrastructure.trace.trajectory_store import TrajectoryFileStore
    from nexent.core.concurrency import ManagedThreadSpec
    from nexent.monitor import get_agent_monitoring_context
    from nexent.monitor.run_timing import RunTiming
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.sampling import ALWAYS_ON

    directory = directory / "child-trajectory"
    TrajectoryFileStore.provision(directory)
    processor = LocalTrajectoryProcessor(TrajectoryFileStore(directory, authorize=lambda _: None),
                                         get_agent_monitoring_context)
    provider = TracerProvider(sampler=processor.wrap_sampler(ALWAYS_ON), shutdown_on_exit=False)
    provider.add_span_processor(processor)
    monkeypatch.setattr(manager, "_config", MonitoringConfig(
        enable_telemetry=enabled, provider="local_file", local_span_processor=processor, export_metrics=False,
    ))
    monkeypatch.setattr(manager, "_tracer", provider.get_tracer("child-complete-timing"))
    processor.start(threads, ManagedThreadSpec("trajectory-writer", "child-timing", close_hook=processor.request_stop))
    clocks = []

    def clock(**kwargs):
        result = RunTiming(**kwargs)
        clocks.append(result)
        return result

    monkeypatch.setattr("nexent.core.agents.resources.subagents.RunTiming", clock)

    def verify(terminals):
        assert processor.force_flush(5000)
        raw = [span for path in directory.rglob("*.otlp.jsonl") for line in path.read_text().splitlines()
               for resource in json.loads(line)["resourceSpans"] for scope in resource["scopeSpans"]
               for span in scope["spans"] if span["name"].startswith("agent.subagent.") or span["name"] == "agent.run"]
        children = {key: value for key, value in terminals.items() if not value["is_root"]}
        assert len(clocks) == len({id(item) for item in clocks}) == len(children)
        assert {item.run_id for item in clocks} == set(children)
        by_id = {}
        for span in raw:
            attributes = {item["key"]: next(iter(item["value"].values())) for item in span["attributes"]}
            by_id[attributes["nexent.agent_run_id"]] = (span, attributes)
        child_spans = {key for key, (span, _) in by_id.items() if span["name"].startswith("agent.subagent.")}
        assert child_spans == (set(children) if enabled else set())
        assert len([span for span in raw if span["name"].startswith("agent.subagent.")]) == len(child_spans)
        for key, fact in terminals.items():
            if not fact["is_root"] or not enabled:
                continue
            span, attributes = by_id[key]
            for field, wire in (("started_at", "startTimeUnixNano"), ("ended_at", "endTimeUnixNano")):
                delta = datetime.fromisoformat(fact[field]) - datetime(1970, 1, 1, tzinfo=timezone.utc)
                expected = ((delta.days * 86400 + delta.seconds) * 1_000_000 + delta.microseconds) * 1000
                assert int(span[wire]) == expected
            assert int(attributes["nexent.duration_ms"]) == fact["duration_ms"]
        for timing in clocks:
            result = timing.finish()
            fact = children[result.run_id]
            assert fact["started_at"] == result.started_at.isoformat()
            assert fact["ended_at"] == result.ended_at.isoformat()
            assert fact["execution_started_at"] == result.execution_started_at.isoformat()
            assert fact["duration_ms"] == result.duration_ms
            if enabled:
                span, attributes = by_id[result.run_id]
                assert int(span["startTimeUnixNano"]) == result.started_at_ns
                assert int(span["endTimeUnixNano"]) == result.ended_at_ns
                assert int(attributes["nexent.duration_ms"]) == result.duration_ms
        return [{"run_id": timing.run_id, "duration_ms": timing.finish().duration_ms,
                 "raw_span": enabled} for timing in clocks]

    def close():
        processor.shutdown()
        provider.shutdown()

    return SimpleNamespace(verify=verify, close=close)


@pytest.mark.asyncio
@pytest.mark.parametrize("model_peer", ["failed", "cancelled", "trajectory_off"], indirect=True)
async def test_child_complete_timing_outcomes_publish_and_replay(
    isolated_monitoring, model_peer, monkeypatch, tmp_path, request, record_property,
):
    """Run an actual child Core under an owning parent trace and persist its terminal result."""
    from contextlib import contextmanager
    from management.services.permission.identity import session as auth
    from nexent.core.agents.orchestration.children import child_run_info, invoke_child
    from nexent.core.agents.resources.subagents import SubAgentDefinition, SubAgentToolWrapper
    from nexent.core.concurrency import ManagedTaskSpec, RunCancellationScope
    from nexent.monitor.run_timing import RunTiming
    from permissions import rbac

    service, tenant = isolated_monitoring
    base, requests, release = model_peer
    mode = request.node.callspec.params["model_peer"]
    parent_id = uuid4().hex
    parent_clock = RunTiming(run_id=parent_id)
    config = AgentConfig(name="child", agent_id=22, description="Controlled child", model_name="model",
                         tools=[], max_steps=2)
    parent = AgentRunInfo(query="Run child", observer=MessageObserver(), agent_config=config,
                          model_config_list=[ModelConfig(cite_name="model", model_name="model", url=base,
                                                         api_key="synthetic")],
                          stop_event=Event(), history=[], user_id="owner", tenant_id=tenant, conversation_id=125,
                          run_timing=parent_clock)
    cancellation = RunCancellationScope(Event())
    infos = []

    @contextmanager
    def invocation():
        info = child_run_info(parent, config, cancellation)
        assert info.run_timing is None
        infos.append(info)
        yield lambda task: invoke_child(info, task)

    wrapper = SubAgentToolWrapper(SubAgentDefinition("child", "Controlled"), parent.observer, agent_id=22,
                                  invocation_factory=invocation)
    metadata = AgentRunMetadata(tenant_id=tenant, user_id="owner", conversation_id=125, agent_id=21,
                                monitoring_run_id=parent_id, monitoring_root_run_id=parent_id,
                                monitoring_group_ids=(12, 13))
    threads = ThreadManager("child-outcomes", {
        lane: LanePolicy(lane, 2, 3)
        for lane in ("agent-run", "model-tool-io", "sandbox", "control-io", "background-service")
    })
    threads.start()
    manager = get_monitoring_manager()
    trajectory = _child_trajectory(threads, manager, monkeypatch, tmp_path, enabled=mode != "trajectory_off")
    events = []
    try:
        async with collector.producer_lifespan():
            sink = get_fact_sink()

            def capture(event):
                if event["fact_kind"] == "agent":
                    events.append(dict(event))
                sink(event)

            set_fact_sink(capture)

            def execute():
                with agent_monitoring_context(metadata):
                    parent_clock.start()
                    with manager.start_agent_run(metadata, run_timing=parent_clock):
                        return wrapper(task="Produce an answer")

            execution = threads.submit("agent-run", ManagedTaskSpec("child", "child-timing"), execute)
            async with asyncio.timeout(20):
                while not requests:
                    assert not execution.future.done()
                    await asyncio.sleep(0.02)
                if mode == "cancelled":
                    cancellation.cancel()
                release.set()
                result, = await asyncio.gather(asyncio.wrap_future(execution.future), return_exceptions=True)
            if mode == "trajectory_off":
                assert not isinstance(result, BaseException)
            else:
                assert isinstance(result, BaseException)
            start, terminal = events
            outcome = {"failed": "failed", "cancelled": "cancelled", "trajectory_off": "succeeded"}[mode]
            assert terminal["outcome"] == outcome and len(requests) == 1
            for field in ("agent_run_id", "root_run_id", "parent_run_id", "started_at", "execution_started_at"):
                assert start[field] == terminal[field]
            assert terminal["parent_run_id"] == terminal["root_run_id"] == parent_id
            assert infos[0].run_timing is not parent_clock and infos[0].run_timing.run_id == terminal["fact_id"]
            raw = trajectory.verify({terminal["fact_id"]: terminal})
            hit = await _apply_and_read(service, tenant)
            assert hit["_source"]["duration_ms"] == terminal["duration_ms"]
            day = datetime.fromisoformat(terminal["execution_started_at"]).date()
            assert hit["_source"]["statistic_date"] == day.isoformat()
            service.tick()
            original = _published_agent_day(service, tenant, day)
            _, row = original
            assert row["execution_count"] == row["duration_sample_count"] == 1
            assert row["duration_sum_ms"] == terminal["duration_ms"]
            assert row["succeeded_count"] == int(outcome == "succeeded")
            assert row["failed_count"] == int(outcome == "failed")
            await _submit_and_read(service, tenant, terminal)
            service.tick()
            assert _published_agent_day(service, tenant, day) == original
            monkeypatch.setattr(auth, "get_current_user_context", lambda _: ("operator", tenant, "OPS"))
            monkeypatch.setattr(rbac, "_ROLE_PERMISSIONS", {"OPS": {"ops.dashboard:read"}})
            monkeypatch.setattr(rbac, "_INITIALIZED", True)
            from ops.api import application

            monkeypatch.setattr(application, "OPS_MONITORING_ENABLED", True)
            app = application.create_app()
            app.state.monitoring = service
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://ops") as client:
                response = await client.get("/ops/v1/monitoring/agents/summary",
                                            params={"start_date": day.isoformat(), "end_date": day.isoformat(),
                                                    "agent_id": 22, "group_ids": [12, 13]},
                                            headers={"Authorization": "Bearer ops"})
                assert response.status_code == 200
                metrics = response.json()["data"]
                assert metrics["execution_count"] == metrics["duration_sample_count"] == 1
                assert metrics["avg_duration_ms"] == terminal["duration_ms"]
                assert metrics["succeeded_count"] == int(outcome == "succeeded")
                assert metrics["failed_count"] == int(outcome == "failed")
                assert metrics["avg_ttft_ms"] == terminal.get("ttft_ms")
            record_property("child_timing", json.dumps({"mode": mode, "raw": raw, "metrics": metrics,
                                                        "replay_count": 1}))
            set_fact_sink(sink)
    finally:
        release.set()
        cancellation.cancel()
        trajectory.close()
        await threads.shutdown(timeout=8)
        assert threads.snapshot().active_count == 0
