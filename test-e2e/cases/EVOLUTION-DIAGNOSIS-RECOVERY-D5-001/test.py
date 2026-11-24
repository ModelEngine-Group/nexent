# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Restart the real Management recovery loop against a signed Runtime and owned database."""

import asyncio
import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import text

from evolution_online_http import initialize_diagnosis_schema, seed_diagnosis_turn, serve
from local_auth_http import native_runtime, runtime

ROOT = Path(__file__).resolve().parents[3]
TENANT = "tenant-native"
OWNER = "restart-diagnosis-owner"
SIGNING = "online-recovery-fixture-signing-key"
BEFORE_DISPATCH = 31
AFTER_RECEIPT = 32


async def run_worker(env, phase, batch):
    process = await asyncio.create_subprocess_exec(
        sys.executable, str(Path(__file__).resolve()), phase, str(batch),
        env=env, cwd=ROOT, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    try:
        _, logs = await asyncio.wait_for(process.communicate(), timeout=45)
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()
    return process.returncode, logs.decode(errors="replace")


@pytest.mark.stage("D5")
@pytest.mark.case_id("EVOLUTION-DIAGNOSIS-RECOVERY-D5-001")
@pytest.mark.asyncio
async def test_management_recovers_online_diagnosis(runtime, monkeypatch):
    from contracts.constants import environment
    from infrastructure.model_adapter import get_adapter_from_config
    from infrastructure.rdb.client import db_client, get_db_session
    from infrastructure.system_configuration.runtime import load_system_configuration
    from management.db.conversation import evolution_review as registrar, prepared_turn
    from nexent.core.concurrency import shutdown_fallback_thread_manager
    from runtime.agentos.middleware import AgentOSMiddleware
    from runtime.agentos.model import create_model_router
    from runtime.model.service import ModelService

    _, _, _, models = runtime
    engine = db_client.engine
    initialize_diagnosis_schema(engine, models.TableBase.metadata)
    with get_db_session() as session:
        session.add(models.UserAccount(user_id=OWNER, user_roles=["USER"], delete_flag="N"))
        session.add(models.UserTenant(user_id=OWNER, tenant_id=TENANT, user_role="USER", delete_flag="N"))
    monkeypatch.setenv("NO_PROXY", "127.0.0.1")
    monkeypatch.setattr(environment, "JWT_SECRET", SIGNING)
    monkeypatch.setattr(environment, "GATEWAY_SIGNING_SECRET", SIGNING)
    metering = json.dumps({TENANT: {"model_id": 11, "daily_tokens": 1000, "daily_micros": 1000,
                                   "models": {"11": {"max_input_tokens": 40, "max_output_tokens": 20,
                                                      "input_micros_per_million": 1000000,
                                                      "output_micros_per_million": 1000000}}}})
    monkeypatch.setattr(environment, "EVOLUTION_DIAGNOSIS_METERING", metering)
    load_system_configuration()

    def scalar(statement, **params):
        with engine.connect() as conn:
            return conn.scalar(text(statement), params)

    def proof(turn, batch):
        with engine.connect() as conn:
            values = conn.execute(text("""
                SELECT r.diagnosis, r.observation, r.observation_state, r.diagnosis_attempt_id,
                       a.completed_at, c.reported_micros, b.result
                FROM nexent.evolution_review_turn_t r
                JOIN nexent.evolution_review_batch_t b USING (batch_id)
                LEFT JOIN nexent.evolution_generation_attempt_t a ON a.attempt_id=r.diagnosis_attempt_id
                LEFT JOIN nexent.evolution_model_charge_t c ON c.attempt_id=a.attempt_id
                WHERE r.turn_id=:turn AND r.batch_id=:batch
            """), dict(turn=turn, batch=batch)).mappings().one()
            return dict(values)

    provider = FastAPI()
    call_count = 0

    @provider.post("/v1/chat/completions")
    async def complete(request: Request):
        nonlocal call_count
        call_count += 1
        payload = await request.json()
        content = json.dumps({"finding": "requirements_missed", "evidence": ["request", "answer"], "missing": []})
        usage = {"prompt_tokens": 6, "completion_tokens": 4, "total_tokens": 10}
        result = {"id": "diagnosis", "model": "diagnosis-recovery-fixture", "created": 1, "usage": usage}
        if not payload.get("stream"):
            return {**result, "object": "chat.completion", "choices": [
                {"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}]}
        result.update(object="chat.completion.chunk", choices=[
            {"index": 0, "delta": {"role": "assistant", "content": content}, "finish_reason": "stop"}])
        return StreamingResponse(iter([f"data: {json.dumps(result)}\n\n", "data: [DONE]\n\n"]),
                                 media_type="text/event-stream")

    try:
        async with serve(provider) as model_url:
            record = {"tenant_id": TENANT, "delete_flag": "N", "model_name": "diagnosis-recovery-fixture",
                      "model_type": "llm", "model_factory": "openai", "base_url": f"{model_url}/v1",
                      "api_key": "synthetic", "update_time": "2026-01-01T00:00:00"}
            api = FastAPI(root_path="/api")
            api.add_middleware(AgentOSMiddleware)
            api.include_router(create_model_router(ModelService(
                lambda model, scope: record if (model, scope) == (11, TENANT) else None, get_adapter_from_config)))
            async with serve(api) as runtime_url:
                child_env = {**os.environ, "PYTHONPATH": os.pathsep.join(str(path) for path in (
                    ROOT / "backend", ROOT / "sdk", ROOT, ROOT / "test-e2e/infra/automation")),
                    "ENABLE_TELEMETRY": "false", "JWT_SECRET": SIGNING, "GATEWAY_SIGNING_SECRET": SIGNING,
                    "RUNTIME_SERVICE_URL": runtime_url, "NEXENT_EVOLUTION_DIAGNOSIS_METERING": metering}
                for index, phase in enumerate(("unsent", "sent", "withdrawn"), start=1):
                    first_chat = index * 10
                    turns = [seed_diagnosis_turn(engine, chat, TENANT, OWNER, rating="N" if chat == first_chat else None)
                             for chat in range(first_chat, first_chat + 5)]
                    registrar.enqueue_review_batches()
                    batch = scalar("SELECT batch_id FROM nexent.evolution_review_turn_t WHERE turn_id=:id", id=turns[0])
                    assert batch is not None
                    calls_before = call_count
                    exit_code, logs = await run_worker(child_env, phase, batch)
                    assert exit_code == (AFTER_RECEIPT if phase == "sent" else BEFORE_DISPATCH), logs
                    initial = proof(turns[0], batch)
                    old_attempt = initial["diagnosis_attempt_id"]
                    assert old_attempt and initial["diagnosis"] is None and initial["completed_at"] is None
                    assert initial["reported_micros"] == (10 if phase == "sent" else None)
                    assert call_count == calls_before + (phase == "sent")
                    if phase == "withdrawn":
                        prepared_turn.evolution_setting(first_chat, OWNER, TENANT, False, revoke=True)
                    # Advance just the failed worker's leases, leaving the original user grant in place.
                    with engine.begin() as conn:
                        conn.execute(text("""UPDATE nexent.evolution_review_turn_t
                            SET diagnosis_lease_until=clock_timestamp() WHERE turn_id=:id AND diagnosis_lease_until IS NOT NULL"""),
                                     {"id": turns[0]})
                        conn.execute(text("""UPDATE nexent.evolution_generation_attempt_t SET lease_until=clock_timestamp()
                            WHERE attempt_id=:id"""), {"id": old_attempt})

                    exit_code, logs = await run_worker(child_env, "resume", batch)
                    assert exit_code == 0, logs
                    recovered = proof(turns[0], batch)
                    summary = recovered["result"]
                    assert summary["reviewed"] == (4 if phase == "withdrawn" else 5)
                    assert summary["excluded"] == (1 if phase == "withdrawn" else 0)
                    assert scalar("SELECT count(*) FROM nexent.evolution_review_turn_t WHERE batch_id=:batch",
                                  batch=batch) == 5
                    assert scalar("SELECT count(*) FROM nexent.evolution_review_batch_t") == index
                    assert call_count == calls_before + (phase != "withdrawn")
                    if phase == "unsent":
                        assert recovered["diagnosis_attempt_id"] != old_attempt
                        assert recovered["diagnosis"]["status"] == "needs_review" and recovered["reported_micros"] == 10
                        assert summary["findings"][0]["turn_ids"] == [turns[0]]
                    elif phase == "sent":
                        assert recovered["diagnosis_attempt_id"] == old_attempt and recovered["completed_at"]
                        assert recovered["diagnosis"]["reason"] == "model_interrupted"
                        assert recovered["diagnosis"]["usage"]["reported_micros"] == 10
                    else:
                        assert recovered["observation_state"] == "revoked"
                        assert recovered["observation"] is None and recovered["diagnosis"] is None
                assert scalar("SELECT count(*) FROM nexent.evolution_model_charge_t WHERE review_turn_id IS NOT NULL") == 2
                assert scalar("SELECT count(*) FROM nexent.agent_execution_t") == 0
    finally:
        await shutdown_fallback_thread_manager()


async def worker(phase, batch):
    from contextlib import nullcontext

    from infrastructure.rdb.client import db_client
    from infrastructure.system_configuration.runtime import load_system_configuration
    from management.services.agent.prepared_turn import prepared_turn_lifespan
    from management.services.evaluation import online_diagnosis
    from nexent.core.concurrency import shutdown_fallback_thread_manager

    async def before_dispatch(**_):
        os._exit(BEFORE_DISPATCH)

    def after_receipt(_job, _result, attempt):
        assert attempt is not None
        os._exit(AFTER_RECEIPT)

    fault = (patch.object(online_diagnosis.queue, "finish", after_receipt) if phase == "sent" else
             patch.object(online_diagnosis, "invoke_chat_prompt", before_dispatch) if phase != "resume" else nullcontext())
    load_system_configuration()
    try:
        with fault:
            async with prepared_turn_lifespan(), asyncio.timeout(35):
                while True:
                    if phase == "resume":
                        with db_client.engine.connect() as conn:
                            complete = conn.scalar(text("""
                                SELECT b.status='completed' AND NOT EXISTS (
                                    SELECT 1 FROM nexent.evolution_review_turn_t r WHERE r.batch_id=b.batch_id
                                      AND r.observation_state NOT IN ('expired','revoked') AND r.diagnosis IS NULL)
                                FROM nexent.evolution_review_batch_t b WHERE b.batch_id=:batch
                            """), dict(batch=batch))
                        if complete:
                            return
                    await asyncio.sleep(0.15)
    finally:
        await shutdown_fallback_thread_manager()
        db_client.engine.dispose()


if __name__ == "__main__":
    asyncio.run(worker(sys.argv[1], int(sys.argv[2])))
