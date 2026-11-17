# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Persist a main Agent sample through the real Ops producer and fact writer."""

import asyncio
import os
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from elasticsearch import Elasticsearch
from sqlalchemy import text

from nexent.monitor.facts import emit_fact
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
    async with asyncio.timeout(15):
        while not service.apply_batch(tenant, "agent"):
            await asyncio.sleep(0.05)
    hits = service.es.search(index=f"{FACTS}-*", track_total_hits=True)["hits"]
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
