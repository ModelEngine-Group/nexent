# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import asyncio
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import text

from local_auth_http import native_runtime, register, runtime


@pytest.mark.case_id("EVOLUTION-REVIEW-BATCH-D3-001")
@pytest.mark.stage("D3")
def test_review_batch(runtime, tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "ops", None)
    from contracts.constants import environment as config
    from contracts.evolution import ReplayCaseRequest
    from contracts.errors.exceptions import AppException
    from infrastructure.rdb.client import db_client, get_db_session
    from infrastructure.system_configuration.runtime import load_system_configuration
    from infrastructure.trace.trajectory_store import CaptureIdentity, TrajectoryFileStore, timestamp
    from management.db.conversation import evolution_observation as queue
    from management.db.conversation import evolution_review as registrar, prepared_turn
    from management.db.conversation.repository import update_message_opinion
    from management.services.evaluation import online_observation as reader
    from management.services.evaluation import business_sets
    from management.db.evaluation.sets import get_evaluation_set, list_evaluation_sets
    from management.services.evaluation.replay_cases import freeze_development_case, preview_trace_case
    from nexent.core.concurrency import LanePolicy, ThreadManager
    from test.backend.utils.test_trajectory_file_store import request as otlp_request

    identity, _, _, models = runtime
    load_system_configuration()
    tenant, owner = "tenant-native", register(identity)["user"]["id"]
    engine = db_client.engine
    models.TableBase.metadata.create_all(engine)
    directory = Path(__file__).resolve().parents[3] / "deploy/sql/migrations"
    with engine.begin() as conn, conn.connection.driver_connection.cursor() as cursor:
        for name in ("003_conversation_run_admission", "004_agent_execution", "006_prepared_conversation_turn",
                     "011_trajectory", "015_conversation_evolution", "018_evolution_replay_cases", "021_evolution_online_reviews",
                     "028_evolution_confirmation_suites", "041_evolution_generation_attempts",
                     "043_evolution_model_charges", "046_evolution_online_diagnosis", "052_business_evaluation_sets"):
            cursor.execute((directory / f"v2.9.0_{name}.sql").read_text(encoding="utf-8"))
        for chat in (1, 2, 3, 4):
            conn.execute(text("""INSERT INTO nexent.conversation_record_t
                (conversation_id,created_by,updated_by,delete_flag) VALUES (:chat,:owner,:owner,'N')"""),
                {"chat": chat, "owner": owner})
    with get_db_session() as session:
        for version in (0, 1):
            session.add(models.AgentInfo(agent_id=7, version_no=version, tenant_id=tenant,
                name="meeting-actions", created_by=owner, updated_by=owner, delete_flag="N", ingroup_permission="PRIVATE"))
            session.flush()
    store = TrajectoryFileStore(tmp_path / "archive", authorize=lambda _: None)
    monkeypatch.setattr(config, "TRAJECTORY_ROOT_DIR", str(store.root))
    monkeypatch.setattr(config, "TRAJECTORY_STORAGE_MODE", "single_node")
    monkeypatch.setattr(config, "MONITORING_PROVIDER", "local_file")
    monkeypatch.setattr(config, "TRAJECTORY_READ_ENABLED", False)

    def seed(chat, ordinal, *, correction=False, query="整理会议待办"):
        grant = prepared_turn.evolution_setting(chat, owner, tenant)["enabled"]
        run, trajectory = uuid4().hex, str(uuid4())
        source = chat * 100 + ordinal * 2
        params = {"chat": chat, "source": source, "reply": source + 1, "owner": owner, "tenant": tenant,
                  "query": "你漏了一项" if correction else query, "grant": source if grant else None,
                  "run": run, "trajectory": trajectory, "ordinal": ordinal}
        with engine.begin() as conn:
            conn.execute(text("""INSERT INTO nexent.conversation_message_t
                (message_id,conversation_id,message_index,message_role,message_content,created_by,updated_by,delete_flag)
                VALUES (:source,:chat,(:ordinal-1)*2,'user',:query,:owner,:owner,'N'),
                       (:reply,:chat,(:ordinal-1)*2+1,'assistant','',:owner,:owner,'N')"""), params)
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

    async def observe_first_turn():
        lane = LanePolicy(name="background-service", max_workers=1, max_queue_size=0)
        manager = ThreadManager("management-observation-test", {lane.name: lane})
        manager.start()
        try:
            async with reader.observation_lifespan(manager), asyncio.timeout(12):
                while (observation := scalar("SELECT observation FROM nexent.evolution_review_turn_t")) is None:
                    await asyncio.sleep(0.1)
                return observation
        finally:
            await manager.shutdown(timeout=5)

    for chat in (1, 2, 3):
        prepared_turn.evolution_setting(chat, owner, tenant, True)
    worker = reader.create_review_worker(config)
    replies = []
    for i, (chat, ordinal) in enumerate(((1, 1), (1, 2), (2, 1), (3, 1), (3, 2)), start=1):
        replies.append(seed(chat, ordinal, correction=i in (1, 5)))
        registrar.enqueue_review_batches()
        if i == 1:
            observation = asyncio.run(observe_first_turn())
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
    turn = scalar("SELECT turn_id FROM nexent.evolution_review_turn_t WHERE conversation_id=2")
    with engine.begin() as conn, conn.connection.driver_connection.cursor() as cursor:
        conn.execute(text("UPDATE nexent.evolution_review_turn_t SET observation=observation-'case_outline' WHERE turn_id=:turn"),
                     {"turn": turn})
        cursor.execute((directory / "v2.9.0_027_evolution_trace_case_outline.sql").read_text(encoding="utf-8"))
    assert scalar(result_query) is None and worker.tick()
    registrar.complete_review_batches()
    assert scalar(result_query)["reviewed"] == 5
    draft = preview_trace_case(tenant, owner, 7, 1, turn)
    assert draft["query"] == "整理会议待办" and draft["attachment_count"] == draft["tool_count"] == 0
    case = ReplayCaseRequest(agent_id=7, version_no=1, family="meeting actions", query="整理以下合成材料中的待办",
                             expected="事项、负责人和来源", trace={"turn_id":turn, "purpose":"reproduce",
                                 "inputs_reviewed":True, "draft_digest":draft["draft_digest"]})
    saved = freeze_development_case(case, owner, tenant)
    assert freeze_development_case(case, owner, tenant) == saved
    task = scalar("SELECT task FROM nexent.evolution_replay_case_t")
    assert task["query"] == case.query and task["expected"] == case.expected
    assert task["trace_source"]["trajectory_id"] == draft["trajectory_id"] and draft["query"] not in str(task)
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
    with pytest.raises(AppException):
        preview_trace_case(tenant, owner, 7, 1, turn)
    with pytest.raises(AppException):
        freeze_development_case(case, owner, tenant)
    assert scalar("SELECT count(*) FROM nexent.evolution_replay_case_t") == 1
    corrected_turn = scalar("SELECT max(turn_id) FROM nexent.evolution_review_turn_t WHERE conversation_id=3")
    original = preview_trace_case(tenant, owner, 7, 1, corrected_turn, use_previous_task=True)
    assert original["query"] == "整理会议待办" and original["correction_query"] == "你漏了一项"
    assert original["task_turn_id"] != original["turn_id"] == corrected_turn
    corrected = case.model_copy(update={"query":original["query"], "trace":case.trace.model_copy(update={
        "turn_id":corrected_turn, "draft_digest":original["draft_digest"], "use_previous_task":True})})
    confirmed = freeze_development_case(corrected, owner, tenant)
    with engine.begin() as conn:
        task = conn.scalar(text("SELECT task FROM nexent.evolution_replay_case_t WHERE case_id=:id"), {"id":confirmed["case_id"]})
        assert "你漏了一项" not in str(task) and task["trace_source"]["correction_trajectory_id"] == original["correction_trajectory_id"]
        conn.execute(text("UPDATE nexent.evolution_review_turn_t SET valid_until=now() WHERE turn_id=:id"),
                     {"id":original["task_turn_id"]})
    with pytest.raises(AppException):
        freeze_development_case(corrected, owner, tenant)
    assert preview_trace_case(tenant, owner, 7, 1, corrected_turn)["query"] == "你漏了一项"
    prepared_turn.evolution_setting(4, owner, tenant, True)
    seed(4, 1, query="先列出议题")
    original_reply = seed(4, 2, query="为这些议题补上来源")
    seed(4, 3, correction=True)
    registrar.enqueue_review_batches()
    while worker.tick():
        pass
    end = scalar("SELECT max(turn_id) FROM nexent.evolution_review_turn_t WHERE conversation_id=4")
    draft = preview_trace_case(tenant, owner, 7, 1, end, use_previous_task=True, preceding_turns=1)
    assert [part["query"] for part in draft["segments"]] == ["先列出议题", "为这些议题补上来源"]
    assert draft["correction_query"] == "你漏了一项"
    trace = {"turn_id":end, "purpose":"reproduce", "inputs_reviewed":True, "use_previous_task":True,
             "preceding_turns":1, "draft_digest":draft["draft_digest"]}
    request = ReplayCaseRequest(agent_id=7, version_no=1, family="two turns", query="列出合成议题",
                                expected="附来源", followups=[{"query":"为这些议题补上来源"}], trace=trace,
                                new_evaluation_set_name="议题专项")
    saved = freeze_development_case(request, owner, tenant)
    assert freeze_development_case(request, owner, tenant) == saved
    with engine.begin() as conn:
        frozen = conn.scalar(text("SELECT task FROM nexent.evolution_replay_case_t WHERE case_id=:id"), {"id":saved["case_id"]})
        assert len(frozen["trace_source"]["turn_sources"]) == 2 and "你漏了一项" not in str(frozen)
        conn.execute(text("UPDATE nexent.evolution_review_turn_t SET valid_until=now() WHERE turn_id=:id"),
                     {"id":draft["segments"][0]["task_turn_id"]})
    with pytest.raises(AppException):
        freeze_development_case(request, owner, tenant)
    assert preview_trace_case(tenant, owner, 7, 1, end, True)["query"] == "为这些议题补上来源"

    source = draft["task_turn_id"]
    actor = CaptureIdentity(tenant, owner, "4", "7")
    with store._session(actor) as archive:
        manifest = archive.read_json("meta.json")
        run = next(item for item in manifest["runs"] if item["trajectory_id"] == draft["trajectory_id"])
        run["expires_at"] = timestamp(datetime.now(timezone.utc) - timedelta(seconds=1))
        store._save_manifest(archive, manifest)
    with engine.begin() as conn:
        conn.execute(text("""UPDATE nexent.evolution_review_turn_t SET diagnosis_source_turn_id=:source,
            diagnosis='{"status":"needs_review","reason":"requirements_missed"}'::jsonb WHERE turn_id=:end"""),
            {"source": source, "end": end})
    # The grant is active, but its cited archive can no longer be read.
    assert update_message_opinion(original_reply, "N", user_id=owner, tenant_id=tenant)
    while worker.tick():
        pass
    with pytest.raises(AppException):
        preview_trace_case(tenant, owner, 7, 1, end, True)
    registrar.enqueue_review_batches()
    reviews = {row["turn_id"]: row for row in registrar.recent_reviews(tenant, 7, 1)}
    assert reviews[source]["state"] == "missing"
    assert reviews[end]["diagnosis"] == {"status": "needs_evidence", "reason": "trajectory_expired"}
    with engine.begin() as conn:
        conn.execute(text("UPDATE nexent.trajectory_execution_t SET status='expired' WHERE trajectory_id=:trace"),
                     {"trace": draft["trajectory_id"]})
    reviews = {row["turn_id"]: row for row in registrar.recent_reviews(tenant, 7, 1)}
    assert reviews[source]["signals"] == []
    assert reviews[source]["diagnosis"] == {"status": "needs_evidence", "reason": "trajectory_expired"}

    set_id = saved["evaluation_set_id"]
    manual = freeze_development_case(ReplayCaseRequest(
        agent_id=7, version_no=1, family="manual", query="核对议题数量", expected="两个",
        evaluation_set_id=set_id,
    ), owner, tenant)
    summary = business_sets.add_business_set_cases(tenant, owner, 7, set_id, [saved["case_id"], manual["case_id"]])
    assert summary["case_count"] == 2
    assert [row["from_trace"] for row in business_sets.read_business_set(tenant, owner, 7, set_id)["cases"]] == [True, False]
    assert set_id not in {row["evaluation_set_id"] for row in list_evaluation_sets(tenant)}
    with pytest.raises(AppException):
        get_evaluation_set(set_id, tenant)
    with pytest.raises(AppException):
        business_sets.read_business_set(tenant, owner, 8, set_id)
    with pytest.raises(AppException):
        business_sets.add_business_set_cases(tenant, owner, 7, set_id, [saved["case_id"], 999999])

    with get_db_session() as session:
        session.add(models.AgentInfo(agent_id=7, version_no=2, tenant_id=tenant, name="meeting-actions",
                                     created_by=owner, updated_by=owner, delete_flag="N", ingroup_permission="PRIVATE"))
    selected = business_sets.select_business_set(tenant, owner, 7, 2, set_id)
    assert [row["digest"] for row in selected] == [saved["digest"], manual["digest"]]
    assert all(row["version_no"] == 2 for row in selected)
    with engine.connect() as conn:
        cloned = conn.scalar(text("SELECT task FROM nexent.evolution_replay_case_t WHERE case_id=:id"),
                             {"id": selected[0]["case_id"]})
    assert cloned == frozen
    business_sets.remove_business_set_case(tenant, owner, 7, set_id, saved["case_id"])
    assert business_sets.select_business_set(tenant, owner, 7, 2, set_id) == [selected[1]]
