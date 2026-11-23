# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import text

from local_auth_http import native_runtime, register, runtime


@pytest.mark.case_id("EVOLUTION-REVIEW-BATCH-D3-001")
@pytest.mark.stage("D3")
def test_review_batch(runtime, tmp_path, monkeypatch):
    from infrastructure.rdb.client import db_client
    from infrastructure.system_configuration.runtime import load_system_configuration
    from infrastructure.trace.trajectory_store import CaptureIdentity, TrajectoryFileStore
    from management.db.conversation import evolution_review as registrar, prepared_turn
    from ops.db.trajectory import evolution as queue
    from ops.services.trajectory import evolution as reader
    from ops.services.trajectory.service import TrajectoryService
    from test.backend.utils.test_trajectory_file_store import request as otlp_request

    identity, _, _, models = runtime
    load_system_configuration()
    tenant, owner = "tenant-native", register(identity)["user"]["id"]
    engine = db_client.engine
    models.TableBase.metadata.create_all(engine)
    directory = Path(__file__).resolve().parents[3] / "deploy/sql/migrations"
    with engine.begin() as conn, conn.connection.driver_connection.cursor() as cursor:
        for name in ("003_conversation_run_admission", "004_agent_execution", "006_prepared_conversation_turn",
                     "011_trajectory", "015_conversation_evolution", "021_evolution_online_reviews"):
            cursor.execute((directory / f"v2.9.0_{name}.sql").read_text(encoding="utf-8"))
        for chat in (1, 2, 3):
            conn.execute(text("""INSERT INTO nexent.conversation_record_t
                (conversation_id,created_by,updated_by,delete_flag) VALUES (:chat,:owner,:owner,'N')"""),
                {"chat": chat, "owner": owner})
    store = TrajectoryFileStore(tmp_path / "archive", authorize=lambda _: None)
    service = TrajectoryService(store, None, None)
    monkeypatch.setattr(reader, "get_service", lambda: service)

    def seed(chat, ordinal, *, correction=False):
        grant = prepared_turn.evolution_setting(chat, owner, tenant)["enabled"]
        run, trajectory = uuid4().hex, str(uuid4())
        source = chat * 100 + ordinal * 2
        params = {"chat": chat, "source": source, "reply": source + 1, "owner": owner, "tenant": tenant,
                  "query": "你漏了一项" if correction else "整理会议待办", "grant": source if grant else None,
                  "run": run, "trajectory": trajectory, "ordinal": ordinal}
        with engine.begin() as conn:
            conn.execute(text("""INSERT INTO nexent.conversation_message_t
                (message_id,conversation_id,message_role,message_content,created_by,updated_by,delete_flag)
                VALUES (:source,:chat,'user',:query,:owner,:owner,'N'),(:reply,:chat,'assistant','',:owner,:owner,'N')"""), params)
            conn.execute(text("""INSERT INTO nexent.conversation_run_admission_t (scope_sha256,tenant_id,run_id,
                request_sha256,conversation_id,created_by,updated_by,prepared_assistant_id,evolution_source_message_id,
                evolution_grant_epoch,evolution_valid_until,delete_flag) VALUES (:run,:tenant,:run,:run,:chat,:owner,:owner,:reply,
                :grant,0,now()+interval '1 day','N')"""), params)
            conn.execute(text("""INSERT INTO nexent.agent_execution_t
                (run_id,conversation_id,tenant_id,status,created_by,updated_by,delete_flag)
                VALUES (:run,:chat,:tenant,'completed',:owner,:owner,'N')"""), params)
            conn.execute(text("""INSERT INTO nexent.trajectory_execution_t (trajectory_id,conversation_id,turn_no,
                agent_id,agentos_run_id,agent_version_no,status,created_by,updated_by,delete_flag)
                VALUES (:trajectory,:chat,:ordinal,7,:run,1,'success',:owner,:owner,'N')"""), params)
        actor = CaptureIdentity(tenant, owner, str(chat), "7")
        payload = otlp_request(actor, trajectory, text="synthetic meeting")
        payload["resourceSpans"][0]["scopeSpans"][0]["spans"][0]["attributes"].extend([
            {"key": "nexent.trajectory.root", "value": {"boolValue": True}},
            {"key": "agent.version_no", "value": {"intValue": "1"}},
        ])
        with store.start(actor, trajectory, str(uuid4()), source_message_id=str(source), core_type="smolagents") as writer:
            writer.append([payload], batch_id=str(uuid4()), expected_offset=0)
            writer.finish("completed")
        return source + 1

    def scalar(query):
        with engine.connect() as conn:
            return conn.scalar(text(query))

    for chat in (1, 2, 3):
        prepared_turn.evolution_setting(chat, owner, tenant, True)
    worker = reader.EvolutionReviewWorker()
    replies = []
    for i, (chat, ordinal) in enumerate(((1, 1), (1, 2), (2, 1), (3, 1), (3, 2)), start=1):
        replies.append(seed(chat, ordinal, correction=i == 1))
        registrar.enqueue_review_batches()
        if i == 1:
            assert worker.tick()
            observation = scalar("SELECT observation FROM nexent.evolution_review_turn_t")
            assert observation["coverage"] == "complete" and observation["signals"] == ["user_correction"]
        assert scalar("SELECT count(*) FROM nexent.evolution_review_batch_t") == int(i == 5)
    prepared_turn.evolution_setting(1, owner, tenant, False)
    seed(1, 3, correction=True)
    registrar.enqueue_review_batches()
    assert scalar("SELECT count(*) FROM nexent.evolution_review_turn_t WHERE batch_id IS NOT NULL") == 5
    assert scalar("SELECT count(*) FROM nexent.evolution_review_turn_t") == 5
    for _ in range(6):
        if not worker.tick():
            break
    registrar.complete_review_batches()
    result_query = "SELECT result FROM nexent.evolution_review_batch_t"
    assert scalar(result_query)["reviewed"] == 5 and scalar(result_query)["missing"] == 0
    with engine.begin() as conn:
        conn.execute(text("UPDATE nexent.conversation_message_t SET opinion_flag='N' WHERE message_id=:mid"),
                     {"mid": replies[2]})
    in_flight = queue.claim()
    assert in_flight and in_flight["conversation_id"] == 2
    prepared_turn.evolution_setting(2, owner, tenant, revoke=True)
    assert queue.messages(in_flight) is None
    queue.finish(in_flight, reader.observation({"opinion_flag": "N"}, coverage="complete"))
    registrar.complete_review_batches()
    final = scalar(result_query)
    assert final["reviewed"] == 4 and final["excluded"] == 1 and "negative_feedback" not in final["signals"]
    assert scalar("SELECT observation IS NULL FROM nexent.evolution_review_turn_t WHERE conversation_id=2")
