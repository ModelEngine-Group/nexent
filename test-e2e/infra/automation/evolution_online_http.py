# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Synthetic completed turns and loopback servers for online diagnosis acceptance."""

import asyncio
import json
import socket
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

import uvicorn
from sqlalchemy import text


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


def initialize_diagnosis_schema(engine, metadata):
    metadata.create_all(engine)
    migrations = Path(__file__).resolve().parents[3] / "deploy/sql/migrations"
    with engine.begin() as conn, conn.connection.driver_connection.cursor() as cursor:
        for name in ("003_conversation_run_admission", "004_agent_execution", "006_prepared_conversation_turn",
                     "011_trajectory", "015_conversation_evolution", "018_evolution_replay_cases",
                     "019_evolution_experiments", "021_evolution_online_reviews", "028_evolution_confirmation_suites",
                     "029_evolution_confirmation_locks", "030_evolution_confirmation_results",
                     "041_evolution_generation_attempts", "043_evolution_model_charges", "044_evolution_evaluation_metering",
                     "045_evolution_confirmation_metering", "046_evolution_online_diagnosis"):
            cursor.execute((migrations / f"v2.9.0_{name}.sql").read_text(encoding="utf8"))


def seed_diagnosis_turn(engine, chat, tenant, owner, *, node=None, rating=None, ordinal=1):
    from ops.services.trajectory.evolution import observation

    query, reply = (("Private fixture expected a ticket ID", "Private fixture output omitted ticket ID")
                    if ordinal == 1 else ("你漏了一项", "Post-correction reply"))
    facts = observation({"request": query, "opinion_flag": rating}, [node] if node else [], "complete")
    index = 2 * (ordinal - 1)
    params = dict(chat=chat, tenant=tenant, owner=owner, source=chat*10+index, reply=chat*10+index+1,
                  ordinal=ordinal, index=index, run=uuid4().hex, trajectory=str(uuid4()), query=query, answer=reply,
                  rating=rating, facts=json.dumps(facts))
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
