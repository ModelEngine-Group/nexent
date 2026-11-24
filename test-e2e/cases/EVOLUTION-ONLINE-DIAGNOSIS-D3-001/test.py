# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Prove consent and cost fencing over the actual signed model path."""

import asyncio
import json
import socket
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

import pytest
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import text

from local_auth_http import native_runtime, runtime


@asynccontextmanager
async def serve(app):
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(app, lifespan="off", log_level="error"))
        task = asyncio.create_task(server.serve(sockets=[listener]))
        try:
            async with asyncio.timeout(5):
                while not server.started:
                    if task.done():
                        await task
                        raise RuntimeError("Fixture server exited during startup")
                    await asyncio.sleep(0.01)
            yield f"http://127.0.0.1:{port}"
        finally:
            server.should_exit = True
            await asyncio.wait_for(task, 8)


@pytest.mark.stage("D3")
@pytest.mark.case_id("EVOLUTION-ONLINE-DIAGNOSIS-D3-001")
@pytest.mark.asyncio
async def test_online_diagnosis(runtime, monkeypatch):
    from contracts.agentos import ChatOptions
    from contracts.constants import environment
    from contracts.errors.exceptions import RuntimeUpstreamError
    from contracts.evolution_metering import diagnosis_budget
    from infrastructure.model_adapter import get_adapter_from_config
    from infrastructure.rdb.client import db_client, get_db_session
    from infrastructure.system_configuration.runtime import load_system_configuration
    from management.clients.model import invoke_chat_prompt
    from management.db.conversation import evolution_diagnosis as queue, evolution_review as registrar
    from management.services.evaluation import online_diagnosis
    from nexent.core.concurrency import shutdown_fallback_thread_manager
    from ops.services.trajectory.evolution import observation
    from runtime.agentos.middleware import AgentOSMiddleware
    from runtime.agentos.model import create_model_router
    from runtime.model.service import ModelService

    _, _, _, models = runtime
    tenant, owner = "tenant-native", "online-owner"
    foreign_tenant, foreign_owner = "tenant-online-secondary", "secondary-owner"
    monkeypatch.setenv("NO_PROXY", "127.0.0.1")
    monkeypatch.setattr(environment, "JWT_SECRET", "online-diagnosis-pilot-test-signing")
    monkeypatch.setattr(environment, "GATEWAY_SIGNING_SECRET", "online-diagnosis-pilot-test-signing")
    monkeypatch.setattr(environment, "EVOLUTION_CONFIRMATION_BUCKET", "")
    load_system_configuration()
    engine = db_client.engine
    models.TableBase.metadata.create_all(engine)
    migrations = Path(__file__).resolve().parents[3] / "deploy/sql/migrations"
    with engine.begin() as conn, conn.connection.driver_connection.cursor() as cursor:
        for name in ("003_conversation_run_admission", "004_agent_execution", "006_prepared_conversation_turn",
                     "011_trajectory", "015_conversation_evolution", "018_evolution_replay_cases",
                     "019_evolution_experiments", "021_evolution_online_reviews",
                     "028_evolution_confirmation_suites", "029_evolution_confirmation_locks",
                     "030_evolution_confirmation_results", "041_evolution_generation_attempts",
                     "043_evolution_model_charges", "044_evolution_evaluation_metering",
                     "045_evolution_confirmation_metering", "046_evolution_online_diagnosis"):
            cursor.execute((migrations / f"v2.9.0_{name}.sql").read_text(encoding="utf8"))
    with get_db_session() as session:
        for scope, identity in ((tenant, owner), (foreign_tenant, foreign_owner)):
            session.add(models.UserAccount(user_id=identity, user_roles=["USER"], delete_flag="N"))
            session.add(models.UserTenant(user_id=identity, tenant_id=scope, user_role="USER", delete_flag="N"))

    def seed(chat, *, node=None, rating=None, ordinal=1, scope=tenant, identity=owner):
        query, reply = (("Private fixture expected a ticket ID", "Private fixture output omitted ticket ID")
                        if ordinal == 1 else ("你漏了一项", "Post-correction reply"))
        facts = observation({"request": query, "opinion_flag": rating}, [node] if node else [], "complete")
        index = 2*(ordinal-1)
        params = dict(chat=chat, tenant=scope, owner=identity, source=chat*10+index, reply=chat*10+index+1,
                      ordinal=ordinal, index=index, run=uuid4().hex,
                      trajectory=str(uuid4()), query=query, answer=reply, rating=rating, facts=json.dumps(facts))
        with engine.begin() as conn:
            conn.execute(text("""
                INSERT INTO nexent.conversation_record_t (conversation_id,created_by,updated_by,delete_flag)
                    VALUES (:chat,:owner,:owner,'N') ON CONFLICT DO NOTHING;
                INSERT INTO nexent.conversation_message_t (message_id,conversation_id,message_index,message_role,
                    message_content,opinion_flag,created_by,updated_by,delete_flag)
                    VALUES (:source,:chat,:index,'user',:query,NULL,:owner,:owner,'N'),
                           (:reply,:chat,:index+1,'assistant',:answer,:rating,:owner,:owner,'N');
                INSERT INTO nexent.conversation_run_admission_t (scope_sha256,request_sha256,tenant_id,run_id,
                    conversation_id,created_by,updated_by,prepared_assistant_id,evolution_source_message_id,evolution_grant_epoch,
                    evolution_valid_until,delete_flag)
                    VALUES (:run,:run,:tenant,:run,:chat,:owner,:owner,:reply,:source,0,now()+interval '1 day','N');
                INSERT INTO nexent.trajectory_execution_t (trajectory_id,conversation_id,turn_no,agent_id,agentos_run_id,
                    agent_version_no,status,created_by,updated_by,delete_flag)
                    VALUES (:trajectory,:chat,:ordinal,7,:run,1,'success',:owner,:owner,'N');
            """), params)
            return conn.scalar(text("""
                INSERT INTO nexent.evolution_review_turn_t
                  (tenant_id,agent_id,agent_version_no,conversation_id,source_message_id,trajectory_id,owner_id,run_id,
                   grant_epoch,valid_until,observation_state,observation)
                VALUES (:tenant,7,1,:chat,:source,:trajectory,:owner,:run,0,now()+interval '1 day','observed',CAST(:facts AS jsonb))
                RETURNING turn_id
            """), params)

    def scalar(sql, **params):
        with engine.connect() as conn:
            return conn.scalar(text(sql), params)

    def report(turn):
        return scalar("SELECT diagnosis FROM nexent.evolution_review_turn_t WHERE turn_id=:id", id=turn)

    def configure(limit):
        config = dict(model_id=11, daily_tokens=1000, daily_micros=limit, models={"11": dict(
                max_input_tokens=40,max_output_tokens=20,input_micros_per_million=1000000,
                output_micros_per_million=1000000)})
        monkeypatch.setattr(environment, "EVOLUTION_DIAGNOSIS_METERING",
                            json.dumps({tenant: config, foreign_tenant: {**config, "daily_micros":75}}))

    configure(75)
    provider = FastAPI()
    calls = []
    finding = {"finding": "requirements_missed", "evidence": ["request", "answer"], "missing": []}

    @provider.post("/v1/chat/completions")
    async def complete(request: Request):
        calls.append(await request.json())
        result = finding if len(calls) != 2 else {**finding, "evidence": ["invented_reference"]}
        reply = {
            "id": "diagnosis", "object": "chat.completion", "model": "diagnosis-fixture", "created": 1,
            "choices": [{"index": 0, "message": {"role": "assistant", "content": json.dumps(result)},
                         "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 6, "completion_tokens": 4, "total_tokens": 10},
        }
        if not calls[-1].get("stream"):
            return reply
        chunk = {**reply, "object": "chat.completion.chunk",
                 "choices": [{"index": 0, "delta": {"role": "assistant", "content": json.dumps(result)},
                              "finish_reason": "stop"}]}
        return StreamingResponse(iter([f"data: {json.dumps(chunk)}\n\n", "data: [DONE]\n\n"]),
                                 media_type="text/event-stream")

    try:
        async with serve(provider) as provider_url:
            record = {"tenant_id":tenant,"delete_flag":"N","model_name":"diagnosis-fixture","model_type":"llm",
                      "model_factory":"openai","base_url":f"{provider_url}/v1","api_key":"synthetic",
                      "update_time":"2026-11-24T00:00:00"}
            api = FastAPI(root_path="/api")
            api.add_middleware(AgentOSMiddleware)
            api.include_router(create_model_router(ModelService(lambda model, scope: {**record, "tenant_id":scope}
                if model==11 and scope in {tenant,foreign_tenant} else None, get_adapter_from_config)))
            async with serve(api) as runtime_url:
                monkeypatch.setattr(environment, "RUNTIME_SERVICE_URL", runtime_url)
                bad = seed(1, rating="N")
                assert await online_diagnosis.work_once()
                first = report(bad)
                assert first["status"] == "needs_review" and first["direction"] == "prompt", first
                assert first["evidence"] == ["message:10", "message:11"] and first["model_id"] == 11
                assert first["template_version"] == "online-diagnosis-v1"
                assert first["usage"]["reported_input"] == 6 and first["usage"]["reported_micros"] == 10
                assert "Private fixture" not in json.dumps(first)
                assert len(calls) == 1 and calls[0]["max_tokens"] == 20
                assert "Private fixture expected" in json.dumps(calls[0]["messages"])

                tool = dict(kind="tool", name="read_ticket", status="failed",
                            source={"trace_id":"a"*32,"span_id":"b"*16})
                failed = seed(2, node=tool)
                seed(3, node={**tool, "status":"completed"}, rating="Y")
                seed(4, node={**tool, "status":"completed"}, rating="Y")
                seed(5)
                registrar.enqueue_review_batches()
                while await online_diagnosis.work_once():
                    pass
                registrar.complete_review_batches()
                assert report(bad) == first and report(failed)["reason"] == "tool_failure"
                merged = scalar("SELECT result FROM nexent.evolution_review_batch_t")
                assert merged["reviewed"] == 5 and len(calls) == 1
                assert merged["reference_workflows"][0]["tools"] == ["read_ticket"]
                assert {entry["reason"] for entry in merged["findings"]} == {"requirements_missed", "tool_failure"}

                wrong = seed(6, rating="N")
                await online_diagnosis.work_once()
                assert report(wrong)["reason"] == "invalid_model_output" and not report(wrong).get("evidence")
                capped = seed(7, rating="N")
                await online_diagnosis.work_once()
                assert report(capped)["reason"] == "model_budget_exceeded" and len(calls) == 2
                foreign = seed(100, rating="N", scope=foreign_tenant, identity=foreign_owner)
                assert await online_diagnosis.work_once()
                assert report(foreign)["status"] == "needs_review" and len(calls) == 3

                configure(400)
                revoked = seed(8, rating="N")
                job = queue.claim()
                assert job["turn_id"] == revoked and queue.read_evidence(job)["request"]
                attempt = queue.authorize_model(job, None, diagnosis_budget(tenant), online_diagnosis.TEMPLATE_VERSION)
                seed(80, rating="N")
                assert queue.claim() is None, "A second worker cannot claim in the same tenant"
                with engine.begin() as conn:
                    conn.execute(text("""UPDATE nexent.conversation_record_t SET evolution_grant_epoch=1
                                         WHERE conversation_id IN (8,80)"""))
                with pytest.raises(RuntimeUpstreamError) as stopped:
                    await invoke_chat_prompt(model_id=11, system_prompt="diagnose", user_prompt="synthetic",
                        user_id=owner, tenant_id=tenant, diagnosis_attempt=attempt, options=ChatOptions(max_output_tokens=20))
                assert stopped.value.status_code == 429 and len(calls) == 3
                assert not queue.finish(job, first, attempt) and report(revoked) is None

                original = seed(9)
                corrected = seed(9, ordinal=2)
                assert await online_diagnosis.work_once()
                assert report(corrected)["status"] == "needs_review"
                assert report(corrected)["evidence"] == ["message:90", "message:91"]
                evidence = json.loads(calls[-1]["messages"][-1]["content"])["evidence"]
                assert evidence["correction"]["text"] == "你漏了一项"
                assert "Post-correction" not in json.dumps(evidence)
                with engine.begin() as conn:
                    conn.execute(text("UPDATE nexent.evolution_review_turn_t SET valid_until=now()-interval '1 second' WHERE turn_id=:id"),
                                 {"id":original})
                registrar.enqueue_review_batches()
                assert report(corrected) == {"status": "needs_evidence", "reason": "authorization_changed"}

                restart = seed(10, rating="N")
                claim = queue.claim()
                assert claim["turn_id"] == restart
                live = queue.authorize_model(claim, None, diagnosis_budget(tenant), online_diagnosis.TEMPLATE_VERSION)
                await invoke_chat_prompt(model_id=11, system_prompt="diagnose", user_prompt="synthetic",
                    user_id=owner, tenant_id=tenant, diagnosis_attempt=live, options=ChatOptions(max_output_tokens=20))
                with engine.begin() as conn:
                    conn.execute(text("UPDATE nexent.evolution_review_turn_t SET diagnosis_lease_until=now()-interval '1 second' WHERE turn_id=:id"),
                                 {"id":restart})
                assert await online_diagnosis.work_once()
                assert report(restart)["reason"] == "model_interrupted" and report(restart)["usage"]["reported_micros"] == 10
                assert not queue.finish(claim, first, live)
                assert len(calls) == 5 and not await online_diagnosis.work_once()
                assert scalar("SELECT count(*) FROM nexent.evolution_model_charge_t WHERE review_turn_id IS NOT NULL") == 5
                assert scalar("SELECT count(*) FROM nexent.agent_execution_t") == 0
    finally:
        await shutdown_fallback_thread_manager()
