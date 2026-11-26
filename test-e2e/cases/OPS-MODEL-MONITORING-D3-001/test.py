# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Run a real SDK request, replay its observations and read Ops publication."""

import json
import os
import subprocess
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from shutil import which
from threading import Thread
from types import SimpleNamespace
from typing import Literal
from unittest.mock import Mock
from uuid import uuid4
from zoneinfo import ZoneInfo

import psycopg2
import pytest
from elasticsearch import Elasticsearch
from fastapi.testclient import TestClient
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from psycopg2 import sql
from sqlalchemy import URL, create_engine, text
from sqlalchemy.exc import OperationalError

from nexent.core.model_service.contracts import ModelMessage, ModelRequest
from nexent.core.model_service.profiles.composition import compose_provider_model_policy
from nexent.core.model_service.profiles.contracts import VersionedReference
from nexent.core.model_service.profiles.outlet_resolution import construct_resolved_model_profile
from nexent.core.model_service.profiles.resolved_profile import ConnectionRules, ContextConfiguration, OutletConnection
from nexent.core.model_service.profiles.resolver import load_profile_catalog
from nexent.core.model_service.registry import AuthenticationRegistry, model_service_references
from nexent.core.model_service.service import ModelService
from nexent.monitor.facts import set_fact_sink
from nexent.monitor.monitoring import LLMTokenTracker
from ops.api import application as ops_application
from ops.api import monitoring as monitoring_api
from ops.monitoring import query
from ops.monitoring.contracts import Fact, MonitoringKind, stable_key
from ops.monitoring.model import MODEL_MONITORING, summarize
from infrastructure.monitoring.runtime import Producer
from ops.monitoring.search import DAILY, FACTS, PointInTime, filters, install_templates, partition, snapshot
from ops.monitoring.service import Monitoring, bulk_write
from ops.monitoring.store import DAY, ControlStore
from management.services.permission.identity.session import authenticate
from permissions import rbac
from permissions.models import CurrentUser


pytestmark = [pytest.mark.case_id("OPS-MODEL-MONITORING-D3-001"), pytest.mark.stage("D3")]


@pytest.fixture
def upstream():
    requests = []

    class Peer(BaseHTTPRequestHandler):
        def do_POST(self):
            requests.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            failure = len(requests) == 1
            payload = {"error": {"message": "service unavailable"}} if failure else {
                "choices": [{"index": 0, "message": {"role": "assistant", "content": "OK"},
                             "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 8, "completion_tokens": 2, "total_tokens": 10},
            }
            body = json.dumps(payload).encode()
            self.send_response(503 if failure else 200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    with ThreadingHTTPServer(("127.0.0.1", 0), Peer) as server:
        thread = Thread(target=server.serve_forever)
        thread.start()
        try:
            yield f"http://127.0.0.1:{server.server_port}/v1", requests
        finally:
            server.shutdown()
            thread.join(5)
            assert not thread.is_alive()


@pytest.fixture
def ops_store():
    host = os.environ.get("OPS_MONITORING_TEST_POSTGRES_HOST")
    es_host = os.environ.get("OPS_MONITORING_TEST_ES_HOST")
    if not (host and es_host and os.environ.get("OPS_MONITORING_TEST_ISOLATED") == "1"):
        pytest.skip("An isolated Ops PostgreSQL and Elasticsearch pair is required")
    project = Path(__file__).resolve().parents[3]
    database = f"ops_{uuid4().hex}"
    admin = psycopg2.connect(host=host, dbname="postgres", user="postgres")
    admin.autocommit = True
    es = Elasticsearch(es_host, request_timeout=10)
    engine = create_engine(URL.create("postgresql+psycopg2", username="postgres", host=host, database=database))
    original_indexes = set(es.indices.get(index="monitoring-*", allow_no_indices=True))
    original_templates = {entry["name"] for entry in es.options(ignore_status=404).indices.get_index_template(
        name="monitoring-*"
    ).get("index_templates", [])}
    assert not original_indexes and not original_templates, "Expected a disposable empty monitoring namespace"
    try:
        with admin.cursor() as cursor:
            cursor.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))
        migration_env = {**os.environ, "POSTGRES_HOST": host, "POSTGRES_USER": "postgres", "POSTGRES_PORT": "5432",
                         "OPS_POSTGRES_DB": database, "POSTGRES_DB": "nexent"}
        if which("psql"):
            # Host has a PostgreSQL client: run the migration script directly.
            subprocess.run(["bash", str(project / "deploy/common/run-ops-sql-migrations.sh")], check=True,
                           timeout=120, env=migration_env, stdout=subprocess.DEVNULL)
        else:
            # No host client: run the script inside a throwaway postgres container
            # (the image already ships psql and bash); the published host port is
            # reachable from containers as host.docker.internal on Docker Desktop.
            subprocess.run(
                ["docker", "run", "--rm", "-v", f"{project}:/repo",
                 "-e", "POSTGRES_HOST=host.docker.internal", "-e", "POSTGRES_USER=postgres",
                 "-e", f"OPS_POSTGRES_DB={database}", "-e", "POSTGRES_DB=nexent",
                 "postgres:16", "bash", "/repo/deploy/common/run-ops-sql-migrations.sh"],
                check=True, timeout=120, env=migration_env, stdout=subprocess.DEVNULL,
            )
        kinds = {"model": MODEL_MONITORING}
        install_templates(es, 0, kinds.values())
        yield Monitoring(ControlStore(engine), es, ZoneInfo("UTC"), kinds)
    finally:
        engine.dispose()
        for index in es.indices.get(index="monitoring-*", allow_no_indices=True):
            es.indices.delete(index=index)
        for name in ("monitoring-facts", "monitoring-daily"):
            es.options(ignore_status=404).indices.delete_index_template(name=name)
        es.close()
        with admin.cursor() as cursor:
            cursor.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(database)))
        admin.close()


def model_profile(root, tenant):
    catalog = load_profile_catalog()
    refs = dict(model_service_references())
    policy = compose_provider_model_policy(
        catalog, provider_key="alibaba-cn", request_model_id="qwen3.5-plus", model_profile_key=None,
        base_bindings={key: value[0].model_dump() for key, value in refs.items() if key != "parameter_transform"},
        base_instruction=VersionedReference(ref="system_only_v1", version=1),
        registered_references=refs, submitted_values={"enable_thinking": False},
    )
    return construct_resolved_model_profile(
        policy, catalog, tenant_id=tenant, display_name="controlled peer", model_type="llm", provider_id="alibaba",
        connection=OutletConnection(base_url=root, ssl_verify=True, timeout_seconds=5, concurrency_limit=1,
                                    credential_ref={"kind": "model_record", "model_id": None}),
        connection_rules=ConnectionRules(credential_kind="model_record", relative_path="chat/completions",
                                         method="POST", headers={}),
        context_configuration=ContextConfiguration(output_reserve_tokens=None, tokenizer_family=None,
                                                   capacity_source="profile", capability_profile_version=None),
        registered_references=refs,
    )


def enqueue_facts(service, events):
    producer = Producer(service.store, service.zone, {kind: definition.fact_model for kind, definition in service.kinds.items()})
    for event in events:
        producer.emit(event)
    for batch in producer.drain():
        service.store.enqueue(*batch)


def test_model_attempt_publication(ops_store, upstream, monkeypatch):
    root, requests = upstream
    tenant = f"tenant-{uuid4().hex}"
    auth = AuthenticationRegistry()
    tracer_provider = TracerProvider(shutdown_on_exit=False)
    exporter = InMemorySpanExporter()
    tracer_provider.add_span_processor(SimpleSpanProcessor(exporter))
    manager = SimpleNamespace(
        _config=SimpleNamespace(provider="local_file", export_traces=True),
        is_enabled=True, tracer=tracer_provider.get_tracer("ops-monitoring-integration"),
        add_span_event=Mock(), set_span_attributes=Mock(), set_openinference_output=Mock(), record_llm_metrics=Mock(),
    )
    manager.trace_llm_request = lambda *args, **kwargs: manager.tracer.start_as_current_span("logical")
    manager.create_token_tracker = lambda model, span: LLMTokenTracker(manager, model, span)
    model = ModelService(lambda profile: auth.sender_for(profile, lambda *_: "disposable-test"), monitoring=manager)
    profile = model_profile(root, tenant)
    request = ModelRequest(request_id=uuid4().hex, outlet_id=None, config_revision=profile.config_revision,
                           messages=[ModelMessage(semantic_role="user", content_parts=[{"type": "text", "text": "OK"}])])
    observations = []
    set_fact_sink(observations.append)
    try:
        result = model.invoke(request, profile)
        attempts = [span for span in exporter.get_finished_spans() if span.name == "model.attempt"]
    finally:
        set_fact_sink(None)
        tracer_provider.shutdown()
    assert result.usage.total_tokens == 10
    assert len(requests) == 2
    assert [row["outcome"] for row in observations] == ["started", "failed", "started", "succeeded"]
    assert observations[0]["fact_id"] != observations[2]["fact_id"]
    started = datetime.fromisoformat(observations[0]["started_at"]).astimezone(timezone.utc)
    day = started.date()
    next_day = day + timedelta(days=1)
    next_day_fact = {**observations[0], "fact_id": "next-day-attempt",
                     "started_at": (started + timedelta(days=1)).isoformat()}
    enqueue_facts(ops_store, [*observations, next_day_fact])

    def lose_confirmation(es, writes, *, external):
        bulk_write(es, writes, external=external)
        raise RuntimeError("Inject a lost bulk confirmation")

    with monkeypatch.context() as patch:
        patch.setattr("ops.monitoring.service.bulk_write", lose_confirmation)
        with pytest.raises(RuntimeError, match="lost bulk confirmation"):
            ops_store.apply_batch(tenant, "model")
        assert not ops_store.store.states(tenant, "model", day, day)

    assert ops_store.apply_batch(tenant, "model")
    ops_store.publish(tenant, "model")
    for attempt, event in zip(attempts, observations[1::2], strict=True):
        doc_id = stable_key(tenant, "model", event["fact_id"])
        document = ops_store.es.get(index=partition(FACTS, day), id=doc_id)["_source"]
        assert document["fact_id"] == attempt.attributes["nexent.model_attempt.fact_id"]
        assert document["trace_id"] == f"{attempt.context.trace_id:032x}"
        assert document["span_id"] == f"{attempt.context.span_id:016x}"
        assert document["duration_ms"] == attempt.attributes["nexent.duration_ms"]
        assert document["outcome"] == attempt.attributes["nexent.model_attempt.outcome"]
        assert document.get("total_tokens") == attempt.attributes.get("llm.token_count.total")
        assert not ({"input.value", "output.value", "nexent.raw.value"} & document.keys())
    monkeypatch.setattr(query, "model_catalog", lambda _: [])

    def read(scope):
        rows, _, _, _ = query.read_models(ops_store, tenant=scope, start=day, end=day,
                                          groups=[], model_id=None, model_type=None)
        return summarize(rows)

    expected = read(tenant)
    assert expected["request_count"] == 2
    assert expected["error_count"] == 1
    assert expected["total_tokens"] == {"value": "10", "known_count": 1, "eligible_count": 2, "coverage_rate": 0.5}
    enqueue_facts(ops_store, observations[-1:])
    ops_store.tick()
    assert read(tenant) == expected
    assert read("other-tenant")["request_count"] == 0
    assert not ops_store.store.states(tenant, "mcp_tool", day, day)

    class SyntheticToolFact(Fact):
        fact_kind: Literal["mcp_tool"] = "mcp_tool"
        tool_key: str

    def count_tools(documents):
        counts = {}
        for document in documents:
            key = document["statistic_date"], document["tool_key"]
            counts[key] = counts.get(key, 0) + 1
        for (statistic_date, tool_key), count in counts.items():
            yield stable_key(statistic_date, tool_key), {
                "statistic_date": statistic_date, "tool_key": tool_key, "tool_call_count": count,
            }

    mcp = {key: value for key, value in observations[-1].items() if key in Fact.model_fields}
    mcp.update(fact_kind="mcp_tool", tool_key="search")
    before = ops_store.store.states(tenant, "model", day, day)[0]["publish_id"]
    assert ops_store.store.states(tenant, "model", next_day, next_day)[0]["publish_id"] == before
    ops_store.kinds["mcp_tool"] = MonitoringKind(
        SyntheticToolFact, count_tools, fact_fields={"tool_key": "keyword"},
        daily_fields={"tool_key": "keyword", "tool_call_count": "long"},
    )
    install_templates(ops_store.es, 0, ops_store.kinds.values())
    enqueue_facts(ops_store, [mcp])
    assert ops_store.apply_batch(tenant, "mcp_tool")
    ops_store.publish(tenant, "mcp_tool")
    tool_publication = ops_store.store.states(tenant, "mcp_tool", day, day)[0]["publish_id"]
    assert tool_publication != before
    response = ops_store.es.search(
        index=partition(DAILY, day),
        query=filters(tenant_id=tenant, fact_kind="mcp_tool", publish_id=str(tool_publication), tool_key="search"),
    )
    assert [hit["_source"]["tool_call_count"] for hit in response["hits"]["hits"]] == [1]
    assert ops_store.store.states(tenant, "model", day, day)[0]["publish_id"] == before

    monkeypatch.setattr(ops_application, "OPS_MONITORING_ENABLED", True)
    monkeypatch.setattr("ops.lifespan.config.OPS_MONITORING_ENABLED", False)
    app = ops_application.create_app()
    app.state.monitoring = ops_store
    app.dependency_overrides[authenticate] = lambda: CurrentUser("operator", tenant, "OPS")
    monkeypatch.setattr(rbac, "_ROLE_PERMISSIONS", {"OPS": {"ops.dashboard:read", "ops.dashboard:update"}})
    monkeypatch.setattr(rbac, "_INITIALIZED", True)
    monkeypatch.setattr(monitoring_api, "JWT_SECRET", "isolated-monitoring-integration-jwt-secret")
    with TestClient(app) as client:
        route = "/api/ops/v1/monitoring/models/summary"
        interval = {"start_date": day.isoformat(), "end_date": day.isoformat()}
        response = client.get(route, params=interval)
        assert response.status_code == 200
        assert response.json()["data"]["request_count"] == 2
        assert client.get(route.removeprefix("/api"), params=interval).json() == response.json()
        assert client.get(route, params={**interval, "tenant_id": "someone-else"}).status_code == 403
        previous_day = (day - timedelta(days=1)).isoformat()
        across_gap = {**interval, "start_date": previous_day}
        base = "/api/ops/v1/monitoring/models"
        trend = client.get(f"{base}/trends", params=across_gap).json()
        assert trend["coverage_state"] == "partial"
        assert [point["statistic_date"] for point in trend["data"]] == [previous_day, day.isoformat()]
        assert trend["data"][0]["request_count"] is None
        assert trend["data"][0]["total_tokens"] is None
        assert trend["data"][1]["request_count"] == 2
        missing_refresh = client.post(f"{base}/refresh", json=across_gap)
        assert missing_refresh.status_code == 409
        assert missing_refresh.json()["message"] == {
            "code": "MONITORING_DATES_UNCOVERED", "missing_dates": [previous_day],
        }

        refresh = client.post(f"{base}/refresh", json=interval)
        assert refresh.status_code == 202
        refresh_path = f"{base}/refreshes/{refresh.json()['data']['refresh_id']}"
        assert client.get(refresh_path).json()["data"]["status"] == "completed"

        new_fact = {**observations[-1], "fact_id": "another-attempt", "call_context_id": "another-call",
                    "model_id": 7}
        enqueue_facts(ops_store, [new_fact])
        other_date = {"start_date": previous_day, "end_date": previous_day}

        def fail_before_staging(*_args):
            raise RuntimeError("Elasticsearch unavailable before staging")

        with monkeypatch.context() as patch:
            patch.setattr("ops.monitoring.service.existing_fact", fail_before_staging)
            with pytest.raises(RuntimeError, match="before staging"):
                ops_store.apply_batch(tenant, "model")
            assert client.get(route, params=interval).json()["is_stale"] is True
            assert client.get(route, params=other_date).json()["is_stale"] is False

        fact_index = partition(FACTS, day)
        ops_store.es.indices.put_settings(index=fact_index, settings={"index.blocks.write": True})
        try:
            with pytest.raises(RuntimeError, match="Monitoring bulk item failed"):
                ops_store.apply_batch(tenant, "model")
            stale = client.get(route, params=interval).json()
            assert stale["is_stale"] is True
            assert stale["data"]["request_count"] == 2
            assert client.get(route, params=other_date).json()["is_stale"] is False
        finally:
            ops_store.es.indices.put_settings(index=fact_index, settings={"index.blocks.write": False})
        assert ops_store.apply_batch(tenant, "model")

        def matching_documents(prefix, target_day, kind, **terms):
            return ops_store.es.count(
                index=partition(prefix, target_day),
                query=filters(tenant_id=tenant, fact_kind=kind, statistic_date=target_day.isoformat(), **terms),
            )["count"]

        documents = PointInTime.documents
        sweep_due = ops_store._cleanup_at
        with monkeypatch.context() as patch:
            @contextmanager
            def locked_snapshot(es, indexes):
                patch.setattr("ops.monitoring.service.snapshot", snapshot)
                with pytest.raises(OperationalError) as blocked, ops_store.store.engine.begin() as conn:
                    conn.execute(text(f"""
                        SELECT publish_id FROM {DAY}
                        WHERE tenant_id=:tenant AND fact_kind='model' AND statistic_date=:day
                        FOR UPDATE NOWAIT
                    """), {"tenant": tenant, "day": day})
                assert blocked.value.orig.pgcode == "55P03"
                with snapshot(es, indexes) as point:
                    yield point

            def publish_and_clean_during_read(point, selection):
                patch.setattr(PointInTime, "documents", documents)
                patch.setattr("ops.monitoring.service.monotonic", lambda: sweep_due)
                ops_store.tick()
                ops_store.tick()
                ops_store.es.indices.refresh(index=f"{DAILY}-*")
                assert matching_documents(DAILY, day, "model", publish_id=str(before)) == 0
                return documents(point, selection)

            patch.setattr(PointInTime, "documents", publish_and_clean_during_read)
            patch.setattr("ops.monitoring.service.snapshot", locked_snapshot)
            in_flight = client.get(route, params=interval)
            assert in_flight.status_code == 200
            assert in_flight.json()["data"]["request_count"] == 2

        current = ops_store.store.states(tenant, "model", day, day)[0]["publish_id"]
        assert current != before
        assert matching_documents(DAILY, day, "model", publish_id=str(current)) >= 1
        assert matching_documents(DAILY, next_day, "model", publish_id=str(before)) == 1
        assert matching_documents(DAILY, day, "mcp_tool", publish_id=str(tool_publication)) == 1
        assert matching_documents(FACTS, day, "model") == 3
        restored = client.get(route, params=interval).json()
        assert restored["is_stale"] is False
        assert restored["data"]["request_count"] == 3
        payloads = {}
        for suffix in ("", "/summary", "/rankings", "/trends"):
            response = client.get(f"{base}{suffix}", params=interval)
            assert response.status_code == 200
            payloads[suffix] = response.json()["data"]
        assert payloads[""]["items"][0]["model_id"] == 7
        assert payloads["/rankings"][0]["metrics"]["request_count"] == 1
        assert payloads["/summary"]["request_count"] == payloads["/trends"][0]["request_count"] == 3

        # Replay a batch enqueued before statistic dates were recorded at ingestion.
        ops_store.store.enqueue(uuid4(), tenant, "model", json.dumps([new_fact]), [])
        with monkeypatch.context() as patch:
            patch.setattr("ops.monitoring.service.existing_fact", fail_before_staging)
            with pytest.raises(RuntimeError, match="before staging"):
                ops_store.apply_batch(tenant, "model")
            assert client.get(route, params=other_date).json()["is_stale"] is True
            assert not ops_store.store.has_failed_batches("other-tenant", "model", day, day)
            assert not ops_store.store.has_failed_batches(tenant, "mcp_tool", day, day)
        assert ops_store.apply_batch(tenant, "model")
        assert client.get(route, params=other_date).json()["is_stale"] is False
