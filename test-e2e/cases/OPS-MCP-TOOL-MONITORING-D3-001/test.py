# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Run real SDK MCP transports, replay their observations and read Ops publication."""

import json
import os
import shutil
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

import httpx
import psycopg2
import pytest
from elasticsearch import Elasticsearch
from fastapi.testclient import TestClient
from nexent.consts.mcp_errors import MCPToolTimeoutError
from nexent.core.agents.resources.mcp import ManagedMCPToolCollection
from nexent.core.concurrency import LanePolicy, RunCancellationScope, ThreadManager
from nexent.monitor.facts import set_fact_sink
from nexent.monitor.monitoring import AgentRunMetadata, agent_monitoring_context
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from psycopg2 import sql
from sqlalchemy import URL, create_engine, text

from infrastructure.monitoring.facts import FACT_MODELS
from infrastructure.monitoring.runtime import Producer
from ops.api import application as ops_application
from ops.api import monitoring as monitoring_api
from ops.monitoring.mcp_tool import MCP_TOOL_MONITORING
from ops.monitoring.model import MODEL_MONITORING
from ops.monitoring.runtime import MONITORING_KINDS
from ops.monitoring.search import DAILY, FACTS, filters, install_templates, partition
from ops.monitoring.service import Monitoring
from ops.monitoring.store import ControlStore
from management.services.permission.identity.session import authenticate
from permissions import rbac
from permissions.models import CurrentUser


pytestmark = [pytest.mark.case_id("OPS-MCP-TOOL-MONITORING-D3-001"), pytest.mark.stage("D3")]

TOOL_TIMEOUT_SECONDS = 2.0
STUB_PORTS = {"served": 19231, "unlisted": 19232}


def _stub_mcp_app(with_slow_tool):
    """Build a real MCP streamable-http application (FastMCP; pinned transport)."""
    from fastmcp import FastMCP

    mcp = FastMCP(f"stub-mcp-{STUB_PORTS['served'] if with_slow_tool else STUB_PORTS['unlisted']}")

    @mcp.tool
    def echo_tool(text: str) -> str:
        return f"echo:{text}"

    if with_slow_tool:
        @mcp.tool
        def slow_tool(text: str) -> str:
            # Failing call: exceeds the caller deadline so the transport itself
            # fails.
            time.sleep(3.5)
            return "late"

        @mcp.tool
        def error_tool(text: str) -> str:
            # Protocol-level tool failure: FastMCP reports it as CallToolResult
            # with isError=true, which the adapter renders as plain content.
            raise RuntimeError("controlled-tool-error")

    return mcp.http_app(path="/mcp")


def _serve(app, port):
    import uvicorn

    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(50):
        try:
            if httpx.get(f"http://127.0.0.1:{port}/mcp", timeout=1).status_code < 500:
                return server, thread
        except Exception:
            time.sleep(0.2)
    raise RuntimeError(f"Stub MCP server on port {port} never became ready")


@pytest.fixture
def stub_mcp():
    servers = []
    for port, slow in ((STUB_PORTS["served"], True), (STUB_PORTS["unlisted"], False)):
        server, thread = _serve(_stub_mcp_app(slow), port)
        servers.append((server, thread))
    try:
        yield (f"http://127.0.0.1:{STUB_PORTS['served']}/mcp", f"http://127.0.0.1:{STUB_PORTS['unlisted']}/mcp")
    finally:
        for server, thread in servers:
            server.should_exit = True
            thread.join(5)


@pytest.fixture
def manager():
    manager = ThreadManager("ops-mcp-monitoring-d3", {
        # Two slots: a deadline-exceeded call keeps the abandoned session lane
        # busy until the stub finishes, so the next collection must not block.
        "mcp-session": LanePolicy("mcp-session", 2, 0),
        "model-tool-io": LanePolicy("model-tool-io", 1, 1),
    })
    manager.start()
    try:
        yield manager
    finally:
        import asyncio

        asyncio.run(manager.shutdown(timeout=3))


def _open_collection(manager, url):
    return ManagedMCPToolCollection(
        manager=manager, server_parameters=[{"url": url, "transport": "streamable-http"}],
        cancellation_scope=RunCancellationScope(), tool_timeout_seconds=TOOL_TIMEOUT_SECONDS,
        close_timeout_seconds=3.0,
    )


def _metadata(tenant, catalog, *, is_debug=False):
    run_id = f"run-{uuid4().hex[:12]}"
    return AgentRunMetadata(tenant_id=tenant, agent_id=7, monitoring_run_id=run_id,
                            monitoring_root_run_id="root-run", monitoring_group_ids=(5,),
                            is_debug=is_debug, monitoring_mcp_servers=catalog)


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
        migration_env = {**os.environ, "POSTGRES_HOST": host, "POSTGRES_USER": "postgres",
                         "POSTGRES_DB": "nexent", "OPS_POSTGRES_DB": database}
        if shutil.which("psql"):
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
        kinds = dict(MONITORING_KINDS)
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


def _flush(producer, service, tenant):
    for batch in producer.drain():
        service.store.enqueue(*batch)
    assert service.apply_batch(tenant, "mcp_tool")
    service.publish(tenant, "mcp_tool")


def _matching_documents(service, prefix, target_day, kind, **terms):
    return service.es.count(
        index=partition(prefix, target_day),
        query=filters(tenant_id="tenant-under-test", fact_kind=kind, statistic_date=target_day.isoformat(), **terms),
    )["count"]


def test_mcp_tool_call_publication(ops_store, stub_mcp, manager, monkeypatch):
    stub_url, unlisted_url = stub_mcp
    tenant = "tenant-under-test"
    tracer_provider = TracerProvider(shutdown_on_exit=False)
    exporter = InMemorySpanExporter()
    tracer_provider.add_span_processor(SimpleSpanProcessor(exporter))
    tracer = tracer_provider.get_tracer("ops-mcp-monitoring-integration")

    producer = Producer(ops_store.store, ops_store.zone, FACT_MODELS)
    observations = []

    def sink(event):
        observations.append(event)
        producer.emit(event)

    set_fact_sink(sink)
    try:
        # -- Case step 1: the catalog-resolved endpoint serves one succeeding and
        # one failing (deadline-exceeded) call; facts carry the resolved identity.
        catalog = [{"url": stub_url, "mcp_server_id": 3, "mcp_server_name": "stub",
                    "mcp_server_type": "container"}]
        metadata = _metadata(tenant, catalog)
        spans = {}
        with _open_collection(manager, stub_url) as collection:
            tools = {tool.name: tool for tool in collection.tools}
            assert set(tools) == {"echo_tool", "slow_tool", "error_tool"}
            with tracer.start_as_current_span("agent.tool.echo_tool") as echo_span:
                with agent_monitoring_context(metadata):
                    tools["echo_tool"].forward(text="probe-payload")
            spans["echo_tool"] = echo_span
            with tracer.start_as_current_span("agent.tool.error_tool") as error_span:
                with agent_monitoring_context(metadata):
                    error_result = tools["error_tool"].forward(text="probe-payload")
            # The Agent still receives the rendered content, not an exception.
            assert "controlled-tool-error" in str(error_result)
            spans["error_tool"] = error_span
            # The deadline-exceeded call closes the collection, so it runs last.
            with tracer.start_as_current_span("agent.tool.slow_tool") as slow_span:
                with agent_monitoring_context(metadata):
                    with pytest.raises(MCPToolTimeoutError):
                        tools["slow_tool"].forward(text="probe-payload")
            spans["slow_tool"] = slow_span
        _flush(producer, ops_store, tenant)
        # Statistic day mirrors the backend projection: started_at in the service zone.
        day = datetime.fromisoformat(observations[0]["started_at"]).astimezone(ops_store.zone).date()
        terminal = {fact["tool_name"]: fact for fact in observations if fact["record_revision"] == 2}
        assert {name: fact["outcome"] for name, fact in terminal.items()} == {
            "echo_tool": "succeeded", "slow_tool": "failed", "error_tool": "failed"}
        assert terminal["slow_tool"]["error_category"] == "TIMEOUT"
        assert terminal["error_tool"]["error_category"] == "TOOL_ERROR"
        assert all(fact["mcp_server_id"] == 3 and fact["mcp_server_name"] == "stub"
                   and fact["mcp_server_type"] == "container" for fact in terminal.values())
        assert all(fact["initiator_group_ids"] == (5,) for fact in terminal.values())
        assert all(fact["duration_ms"] >= 0 for fact in terminal.values())
        assert all("probe-payload" not in json.dumps(fact) and "echo:" not in json.dumps(fact)
                   for fact in observations)
        assert _matching_documents(ops_store, FACTS, day, "mcp_tool") == 3

        # -- Case step 2: tenant-scoped endpoints agree with the stored facts.
        monkeypatch.setattr(ops_application, "OPS_MONITORING_ENABLED", True)
        monkeypatch.setattr("ops.lifespan.config.OPS_MONITORING_ENABLED", False)
        app = ops_application.create_app()
        app.state.monitoring = ops_store
        app.dependency_overrides[authenticate] = lambda: CurrentUser("operator", tenant, "OPS")
        monkeypatch.setattr(rbac, "_ROLE_PERMISSIONS", {"OPS": {"ops.dashboard:read", "ops.dashboard:update"}})
        monkeypatch.setattr(rbac, "_INITIALIZED", True)
        monkeypatch.setattr(monitoring_api, "JWT_SECRET", "isolated-monitoring-jwt-secret")
        with TestClient(app) as client:
            interval = {"start_date": day.isoformat(), "end_date": day.isoformat()}
            route = "/api/ops/v1/monitoring/mcp-tools/summary"
            response = client.get(route, params=interval)
            assert response.status_code == 200
            data = response.json()["data"]
            assert data["request_count"] == 3
            assert data["service_count"] == 1 and data["active_services"] == 1
            # The deadline-exceeded call still counts as an attempt (its started
            # revision is published), so both tools are active.
            assert data["tool_count"] == 3 and data["active_tools"] == 3
            assert data["error_count"] == 2
            assert client.get(route.removeprefix("/api"), params=interval).json() == response.json()
            assert client.get(route, params={**interval, "tenant_id": "someone-else"}).status_code == 403
            tools_list = client.get("/api/ops/v1/monitoring/mcp-tools", params={
                **interval, "dimension": "services"}).json()["data"]["items"]
            assert tools_list[0]["mcp_server_name"] == "stub"
            assert tools_list[0]["active_tools"] == 3
            # Initiator-group attribution: the same window filtered by the
            # initiator's group returns the calls and other groups see nothing.
            grouped = client.get(route, params={**interval, "group_ids": 5}).json()["data"]
            assert grouped["request_count"] == 3 and grouped["tool_count"] == 3
            missed = client.get(route, params={**interval, "group_ids": 99}).json()["data"]
            assert missed["request_count"] == 0 and missed["tool_count"] == 0

        # -- Case step 3: replaying the confirmed batch does not inflate anything.
        replay = json.dumps([event for event in observations], separators=(",", ":"))
        ops_store.store.enqueue(uuid4(), tenant, "mcp_tool", replay, [])
        assert ops_store.apply_batch(tenant, "mcp_tool")
        ops_store.publish(tenant, "mcp_tool")
        assert _matching_documents(ops_store, FACTS, day, "mcp_tool") == 3
        assert _matching_documents(ops_store, DAILY, day, "mcp_tool") == 3

        # -- Case step 4: the same invocation as a debug run stays silent.
        with _open_collection(manager, stub_url) as collection:
            tools = {tool.name: tool for tool in collection.tools}
            with agent_monitoring_context(_metadata(tenant, catalog, is_debug=True)):
                tools["echo_tool"].forward(text="probe-payload")
        for batch in producer.drain():
            ops_store.store.enqueue(*batch)
        # Debug calls are inert: no batch may land in the control store.
        assert not ops_store.apply_batch(tenant, "mcp_tool")
        assert _matching_documents(ops_store, FACTS, day, "mcp_tool") == 3
        assert len(observations) == 6  # exactly the three facts from case step 1

        # -- Case step 5: an endpoint absent from the catalog degrades to unknown.
        missing_catalog = _metadata(tenant, [{"url": stub_url, "mcp_server_id": 3,
                                              "mcp_server_name": "stub", "mcp_server_type": "container"}])
        with _open_collection(manager, unlisted_url) as collection:
            tools = {tool.name: tool for tool in collection.tools}
            with agent_monitoring_context(missing_catalog):
                tools["echo_tool"].forward(text="probe-payload")
        _flush(producer, ops_store, tenant)
        unknown_facts = [fact for fact in observations
                         if fact.get("mcp_server_type") == "unknown" and fact["record_revision"] == 2]
        assert len(unknown_facts) == 1
        assert unknown_facts[0]["mcp_server_id"] is None and unknown_facts[0]["tool_name"] == "echo_tool"
        assert _matching_documents(ops_store, FACTS, day, "mcp_tool") == 4

        # -- Case step 6: stored facts share identity and measurements with spans.
        fact_by_tool = {}
        for fact in observations:
            if fact["record_revision"] == 2 and fact["mcp_server_id"] == 3:
                fact_by_tool[fact["tool_name"]] = fact
        for name, span in spans.items():
            context = span.get_span_context()
            assert fact_by_tool[name]["trace_id"] == f"{context.trace_id:032x}"
            assert fact_by_tool[name]["span_id"] == f"{context.span_id:016x}"
        assert fact_by_tool["echo_tool"]["outcome"] == "succeeded"
        assert fact_by_tool["slow_tool"]["outcome"] == "failed"
        assert fact_by_tool["error_tool"]["outcome"] == "failed"

        # -- Case step 7: blocked Elasticsearch writes surface as staleness.
        late_metadata = _metadata(tenant, catalog)
        with _open_collection(manager, stub_url) as collection:
            tools = {tool.name: tool for tool in collection.tools}
            with agent_monitoring_context(late_metadata):
                tools["echo_tool"].forward(text="probe-payload")
        for batch in producer.drain():
            ops_store.store.enqueue(*batch)
        fact_index = partition(FACTS, day)
        ops_store.es.indices.put_settings(index=fact_index, settings={"index.blocks.write": True})
        try:
            with pytest.raises(RuntimeError, match="Monitoring bulk item failed"):
                ops_store.apply_batch(tenant, "mcp_tool")
            stale = client.get("/api/ops/v1/monitoring/mcp-tools/summary", params=interval).json()
            assert stale["is_stale"] is True
        finally:
            ops_store.es.indices.put_settings(index=fact_index, settings={"index.blocks.write": False})
        assert ops_store.apply_batch(tenant, "mcp_tool")
        ops_store.publish(tenant, "mcp_tool")
        recovered = client.get("/api/ops/v1/monitoring/mcp-tools/summary", params=interval).json()
        assert recovered["is_stale"] is False
        assert recovered["data"]["request_count"] == 5
    finally:
        set_fact_sink(None)
