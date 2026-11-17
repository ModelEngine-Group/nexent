# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Real-provider regression for the omitted-observer Dreaming failure."""

import asyncio
import time
from uuid import uuid4

import pytest

from shared.cases import case_params
from shared.case_evidence import write_case_evidence
from shared.factories.model import owned_configured_model
from shared.factories.tenant import isolated_accounts
from shared.http import MODEL_TIMEOUT, assert_status, client


@pytest.mark.parametrize("case", case_params("D3", ["AGT-DREAMING-SEMANTIC-01"]))
@pytest.mark.asyncio
async def test_real_dreaming_semantic_summary(case):
    async with isolated_accounts(["tenant_a_admin"]) as accounts:
        identity = accounts["tenant_a_admin"]
        async with owned_configured_model(identity, case["id"], "llm"):
            async with owned_configured_model(identity, case["id"], "embedding"):
                async with client("config", token=identity.access_token, timeout=MODEL_TIMEOUT) as api:
                    listing = await api.get("/model/list")
                    assert_status(listing, 200)
                    models = listing.json()["data"]
                    defaults = await api.post("/model/backfill_defaults", json={
                        "display_names": [model["display_name"] for model in models]})
                    assert_status(defaults, 200)
                    embedding = await api.get("/memory/config/embedding-status")
                    assert_status(embedding, 200)
                    assert embedding.json()["configured"] is True
                    bootstrap = await api.get("/agent/workbench/bootstrap")
                    assert_status(bootstrap, 200)
                    agent_id = str(bootstrap.json()["data"]["generic_agent"]["agent_id"])
                    marker = "DREAM-" + uuid4().hex[:12]
                    sources = [f"User always uses Chinese for {marker} release reports.",
                               f"User requires verified backups before every {marker} database migration."]
                    source_ids = []
                    for content in sources:
                        created = await api.post("/memory/records", json={
                            "layer": "agent", "memory_type": "short_term", "agent_id": agent_id,
                            "content": content, "idempotency_key": uuid4().hex})
                        assert_status(created, 200)
                        assert created.json()["indexed"] is True
                        source_ids.append(str(created.json()["memory_id"]))
                    schedule = await api.put("/memory/dreaming/schedule", json={
                        "enabled": False, "rule_type": "CRON", "timezone": "Asia/Shanghai",
                        "cron_expr": "0 3 * * *", "min_score": 0,
                        "min_recall_count": 0, "min_unique_queries": 0})
                    assert_status(schedule, 200)
                    queued = await api.post("/memory/dreaming/run", json={})
                    assert_status(queued, 202)
                    run_id = queued.json()["run_id"]
                    deadline = time.monotonic() + 180
                    while time.monotonic() < deadline:
                        response = await api.get("/memory/dreaming/audit", params={"run_id": run_id, "limit": 1})
                        assert_status(response, 200)
                        rows = response.json()
                        if rows and rows[0]["status"] in {"completed", "failed", "skipped"}:
                            audit = rows[0]
                            break
                        await asyncio.sleep(2)
                    else:
                        pytest.fail("Owned Dreaming run did not terminate")
                    active = await api.get("/memory/long-term/user")
                    assert_status(active, 200)
                    version = active.json().get("version") or {}
                    write_case_evidence("dreaming-semantic", {
                        "run_id": run_id, "audit": audit, "version": version,
                        "expected_evidence_ids": source_ids})
                    assert audit["status"] == "completed", audit
                    assert audit["promoted_count"] == 2
                    assert version["is_active"] is True
                    assert version["generation_audit"]["status"] == "summarized", version["generation_audit"]
                    assert version["fallback_details"]["used"] is False
                    assert set(version["evidence_ids"]) == set(source_ids)
                    assert marker in version["content"]
                    assert "Chinese" in version["content"] or "中文" in version["content"]
                    assert "backup" in version["content"].lower() or "备份" in version["content"]
