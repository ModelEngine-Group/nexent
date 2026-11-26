# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Prove Management-resolved initiator groups reach published, group-filtered MCP statistics."""

import json
import os
import shutil
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4
from zoneinfo import ZoneInfo

import httpx
import psycopg2
import pytest
from elasticsearch import Elasticsearch
from fastapi.testclient import TestClient
from psycopg2 import sql
from sqlalchemy import URL, create_engine

from contracts.agent import NL2SkillRunRequest
from contracts.agentos import PreparedAgentRun, PreparedSkillCreatorRun, RunInput, RunModelBinding
from infrastructure.agentos_identity import ServicePrincipal
from infrastructure.monitoring.facts import FACT_MODELS
from infrastructure.monitoring.runtime import Producer
from management.services.agent import context as agent_context
from management.services.permission.identity.session import authenticate
from management.services.skill import creation as skill_creation
from nexent.core.agents.resources.mcp import ManagedMCPToolCollection
from nexent.core.concurrency import LanePolicy, RunCancellationScope, ThreadManager
from nexent.monitor import get_agent_monitoring_context
from nexent.monitor.facts import set_fact_sink
from ops.api import application as ops_application
from ops.api import monitoring as monitoring_api
from ops.monitoring.runtime import MONITORING_KINDS
from ops.monitoring.search import install_templates
from ops.monitoring.service import Monitoring
from ops.monitoring.store import ControlStore
from permissions import rbac
from permissions.models import CurrentUser
from runtime.agentos import prepared_run


pytestmark = [pytest.mark.case_id("OPS-MCP-TOOL-MONITORING-D3-002"), pytest.mark.stage("D3")]

STUB_PORT = 19233
TOOL_TIMEOUT_SECONDS = 2.0
TENANT = "tenant-under-test"
ACTOR = ServicePrincipal("public-user", TENANT)
GROUP_ID = 5

MODEL_SCOPE = {
    "model": RunModelBinding(model_id=11, alias="llm", revision="revision-1"),
    "input_budget": 512,
    "context_window_tokens": 1024,
}


def _stub_mcp_app():
    """Build a real MCP streamable-http application (FastMCP; pinned transport)."""
    from fastmcp import FastMCP

    mcp = FastMCP("stub-mcp-group-attribution")

    @mcp.tool
    def echo_tool(text: str) -> str:
        return f"echo:{text}"

    return mcp.http_app(path="/mcp")


@pytest.fixture
def stub_mcp():
    import uvicorn

    server = uvicorn.Server(uvicorn.Config(_stub_mcp_app(), host="127.0.0.1", port=STUB_PORT, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(50):
        try:
            if httpx.get(f"http://127.0.0.1:{STUB_PORT}/mcp", timeout=1).status_code < 500:
                break
        except Exception:
            time.sleep(0.2)
    else:
        raise RuntimeError("Stub MCP server never became ready")
    try:
        yield f"http://127.0.0.1:{STUB_PORT}/mcp"
    finally:
        server.should_exit = True
        thread.join(5)


@pytest.fixture
def manager():
    manager = ThreadManager("ops-mcp-group-attribution-d3", {
        "mcp-session": LanePolicy("mcp-session", 1, 0),
        "model-tool-io": LanePolicy("model-tool-io", 1, 1),
    })
    manager.start()
    try:
        yield manager
    finally:
        import asyncio

        asyncio.run(manager.shutdown(timeout=3))


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
            subprocess.run(["bash", str(project / "deploy/common/run-ops-sql-migrations.sh")], check=True,
                           timeout=120, env=migration_env, stdout=subprocess.DEVNULL)
        else:
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


def _open_collection(manager, url):
    return ManagedMCPToolCollection(
        manager=manager, server_parameters=[{"url": url, "transport": "streamable-http"}],
        cancellation_scope=RunCancellationScope(), tool_timeout_seconds=TOOL_TIMEOUT_SECONDS,
        close_timeout_seconds=3.0,
    )


def _bind_runtime_stubs(monkeypatch, runner):
    """Stub the admission and journal boundaries while keeping the real metadata binding in scope."""
    info = SimpleNamespace(
        attempt_outcome="completed", thread_future=None, workspace_path=None,
        agent_config=SimpleNamespace(pre_run_tool_events=[]), observer=SimpleNamespace(),
    )

    async def control_io(_task, callback, *args, **_kwargs):
        return callback(*args)

    stubs = {
        "load_prepared_run": AsyncMock(return_value=info),
        "agent_run_manager": Mock(),
        "_control_io": control_io,
        "mark_running": Mock(return_value=True),
        "release_prepared_run": Mock(),
        "discard_prepared_workspace": Mock(),
        "agent_run": runner,
    }
    for name, value in stubs.items():
        monkeypatch.setattr(prepared_run, name, value)
    return SimpleNamespace(info=info)


async def test_initiator_group_attribution_publication(ops_store, stub_mcp, manager, monkeypatch):
    observations = []
    producer = Producer(ops_store.store, ops_store.zone, FACT_MODELS)

    def sink(event):
        observations.append(event)
        producer.emit(event)

    set_fact_sink(sink)
    try:
        # -- Case step 1: the real Management preparation resolves the initiator's
        # tenant groups and attaches them to the prepared payload contract. The
        # identity group store is stubbed at the data boundary.
        monkeypatch.setattr(agent_context, "OPS_MONITORING_ENABLED", True)
        monkeypatch.setattr(
            "management.db.identity.group.query_group_ids_by_user_in_tenant", lambda *_args: [GROUP_ID]
        )
        monkeypatch.setattr(skill_creation, "prepare_creator_model", lambda *_args: dict(MODEL_SCOPE))
        monkeypatch.setattr(skill_creation, "build_evaluation_input", lambda *_args: RunInput(query="build"))
        creator_payload = skill_creation.prepare_nl2skill_snapshot(
            NL2SkillRunRequest(query="build"), ACTOR.user_id, TENANT, "en",
        )
        assert creator_payload.initiator_group_ids == [GROUP_ID]
        roundtrip = PreparedSkillCreatorRun.model_validate_json(creator_payload.model_dump_json())
        assert roundtrip.initiator_group_ids == [GROUP_ID]

        # -- Case step 2: the conversation payload carries the same contract field
        # Management attaches; the real Runtime binding turns it into the run
        # metadata that monitoring facts read, and the agent stream performs one
        # real MCP tool call inside that bound context.
        payload = PreparedAgentRun.model_validate({
            "mode": "nexent", "conversation_id": 42, "run_id": "c" * 32,
            "resource": {"agent_id": 7, "version_no": 3, "name": "test", "description": "", "prompt_templates": {}},
            "models": {"llm": {"model_id": 11, "alias": "llm", "revision": "revision-1"}},
            "input": {"query": "question"},
            "initiator_group_ids": [GROUP_ID],
        })
        seen = []

        async def runner(info, **_kwargs):
            seen.append(get_agent_monitoring_context())
            with _open_collection(manager, stub_mcp) as collection:
                tools = {tool.name: tool for tool in collection.tools}
                tools["echo_tool"].forward(text="group-probe")
            yield json.dumps({"type": "final_answer", "content": "done"})

        _bind_runtime_stubs(monkeypatch, runner)
        status = await prepared_run._run_snapshot(
            payload, ACTOR, prepared_run.RunIdentity(TENANT, ACTOR.user_id, 42, payload.run_id), Mock(),
        )
        assert status == "completed"
        assert seen[0].monitoring_group_ids == (GROUP_ID,)
        terminal = [fact for fact in observations if fact["record_revision"] == 2]
        assert len(terminal) == 1 and terminal[0]["tool_name"] == "echo_tool"
        assert terminal[0]["initiator_group_ids"] == (GROUP_ID,)

        # -- Case step 3: publish and read the statistics back through the
        # group-filtered monitoring API.
        for batch in producer.drain():
            ops_store.store.enqueue(*batch)
        assert ops_store.apply_batch(TENANT, "mcp_tool")
        ops_store.publish(TENANT, "mcp_tool")
        day = datetime.fromisoformat(terminal[0]["started_at"]).astimezone(ops_store.zone).date()

        monkeypatch.setattr(ops_application, "OPS_MONITORING_ENABLED", True)
        monkeypatch.setattr("ops.lifespan.config.OPS_MONITORING_ENABLED", False)
        app = ops_application.create_app()
        app.state.monitoring = ops_store
        app.dependency_overrides[authenticate] = lambda: CurrentUser("operator", TENANT, "OPS")
        monkeypatch.setattr(rbac, "_ROLE_PERMISSIONS", {"OPS": {"ops.dashboard:read", "ops.dashboard:update"}})
        monkeypatch.setattr(rbac, "_INITIALIZED", True)
        monkeypatch.setattr(monitoring_api, "JWT_SECRET", "isolated-monitoring-jwt-secret")
        with TestClient(app) as client:
            interval = {"start_date": day.isoformat(), "end_date": day.isoformat()}
            route = "/api/ops/v1/monitoring/mcp-tools/summary"
            assert client.get(route, params={**interval, "group_ids": GROUP_ID}).json()["data"]["request_count"] == 1
            missed = client.get(route, params={**interval, "group_ids": 99}).json()["data"]
            assert missed["request_count"] == 0 and missed["tool_count"] == 0
            assert client.get(route, params=interval).json()["data"]["request_count"] == 1
    finally:
        set_fact_sink(None)
