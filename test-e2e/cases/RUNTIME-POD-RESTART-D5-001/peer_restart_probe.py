# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Prepare and inspect case-owned evaluation runs and the peer-restart workspace."""

from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
import json
from pathlib import Path
import sys
from time import monotonic, sleep
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener
from uuid import UUID, uuid5

from sqlalchemy import select, text

from contracts.constants.environment import AGENT_WORKSPACE_ROOT, POSTGRES_HOST
from gateway.identity.downstream import IDENTITY_HEADER, sign_identity
from gateway.identity.internal_tokens import generate_internal_runtime_jwt
from infrastructure.rdb.client import get_db_session
from management.db.agent.models import AgentInfo
from management.db.evaluation.models import AgentEvaluation, AgentEvaluationCase, Evaluator
from management.db.evaluation.runs import (
    create_agent_evaluation, create_agent_evaluation_cases, update_agent_evaluation_status,
)
from management.db.evaluation.sets import create_evaluation_set, get_evaluation_set_cases_all, insert_evaluation_set_cases
from management.db.execution.models import ExecutionReservation
from management.db.execution.repository import lock_admission_scope
from management.services.evaluation.scoring import validate_code_evaluator


EVALUATOR = "Restart fixture exact match"
RESTART_TAG = "restart-eval"
ADMISSION_TAGS = {"admission-eval-race": "race", "admission-eval-lost-claim": "claim"}
WORKER_TAGS = tuple(f"admission-eval-worker-{index}" for index in range(1, 7))
QUEUED_TAG = "admission-eval-backlog"
OVERFLOW_TAG = "admission-eval-overflow"
SUBMISSION_TAGS = (*WORKER_TAGS, QUEUED_TAG, OVERFLOW_TAG)
LOST_CLAIM_REASON = "Case changed the pending status while the conditional claim was waiting"
CODE = '''def evaluate(query, expected, actual, runtime_events, **kwargs):
    return {"score": 1.0 if expected == actual else 0.0, "reason": "Exact answer match"}
'''


def fixture_identity(token):
    return str(uuid5(token, "owner:user")), str(uuid5(token, "owner:tenant"))


def evaluation_query(token, tag):
    if tag != RESTART_TAG and tag not in ADMISSION_TAGS and tag not in SUBMISSION_TAGS:
        raise ValueError("Unknown evaluation fixture tag")
    return f"runtime-stream:{token.hex}:{tag}"


def seed_evaluation(token, agent_id, model_id, tag=RESTART_TAG):
    query = evaluation_query(token, tag)
    owner, tenant = fixture_identity(token)
    validate_code_evaluator(CODE)
    with get_db_session() as session:
        agent, = session.scalars(select(AgentInfo).where(
            AgentInfo.agent_id == agent_id, AgentInfo.tenant_id == tenant, AgentInfo.version_no == 1,
            AgentInfo.created_by == owner, AgentInfo.delete_flag == "N",
        ))
        assert model_id in agent.model_ids
        name = EVALUATOR if tag == RESTART_TAG else f"Admission exact match: {tag}"
        evaluator = Evaluator(tenant_id=tenant, name=name, evaluator_type="code", code=CODE, status="PUBLISHED",
                              pass_threshold=1.0, created_by=owner, updated_by=owner, delete_flag="N")
        session.add(evaluator)
        session.flush()
        evaluator_id = evaluator.evaluator_id
    title = "Disposable Runtime restart dataset" if tag == RESTART_TAG else f"Disposable {tag} dataset"
    definition = create_evaluation_set(tenant, title, None, None, owner)
    set_id = definition["evaluation_set_id"]
    assert insert_evaluation_set_cases(tenant, set_id, [{
        "inputs": {"query": query},
        "label": {"answer": f"stream-tail:{tag}:结束🌊"},
    }], owner) == 1
    cases = get_evaluation_set_cases_all(set_id, tenant)
    assert len(cases) == 1
    run = create_agent_evaluation(tenant, agent_id, 1, set_id, 1, model_id, owner,
                                  evaluator_config={"evaluator_ids": [evaluator_id]})
    evaluation_id = run["agent_evaluation_id"]
    assert create_agent_evaluation_cases(tenant, evaluation_id, cases, owner) == 1
    return evaluation_id


def read_evaluation(token, evaluation_id, tag=RESTART_TAG):
    query = evaluation_query(token, tag)
    owner, tenant = fixture_identity(token)
    with get_db_session() as session:
        run, = session.scalars(select(AgentEvaluation).where(
            AgentEvaluation.agent_evaluation_id == evaluation_id, AgentEvaluation.tenant_id == tenant,
            AgentEvaluation.created_by == owner, AgentEvaluation.delete_flag == "N",
        ))
        evaluation_case, = session.scalars(select(AgentEvaluationCase).where(
            AgentEvaluationCase.agent_evaluation_id == evaluation_id, AgentEvaluationCase.tenant_id == tenant,
            AgentEvaluationCase.created_by == owner, AgentEvaluationCase.delete_flag == "N",
        ))
        assert evaluation_case.inputs["query"] == query
        reservations = session.scalars(select(ExecutionReservation).where(
            ExecutionReservation.tenant_id == tenant, ExecutionReservation.user_id == owner,
            ExecutionReservation.execution_key == f"evaluation:{evaluation_id}",
            ExecutionReservation.execution_kind == "evaluation", ExecutionReservation.delete_flag == "N",
        ))
        return {"run": {"id": run.agent_evaluation_id, "status": run.status, "progress": run.progress_done,
                        "score": run.score_overall, "error": run.error_message},
                "case": {"id": evaluation_case.agent_evaluation_case_id, "status": evaluation_case.status,
                         "predict": evaluation_case.predict, "score": evaluation_case.score,
                         "error": evaluation_case.error_message},
                "reservations": [{"id": row.execution_id, "status": row.status, "owner": row.owner_instance_id,
                                  "epoch": row.maintenance_epoch, "error": row.error_code} for row in reservations]}


def request_evaluation(token, evaluation_id, port):
    assert port in (5014, 5015)
    owner, tenant = fixture_identity(token)
    request = Request(f"http://127.0.0.1:{port}/api/agent-evaluations/internal/run",
                      json.dumps({"agent_evaluation_id": evaluation_id}).encode(), headers={
                          "Content-Type": "application/json",
                          "Authorization": f"Bearer {generate_internal_runtime_jwt(owner, tenant)}",
                      }, method="POST")
    try:
        response = build_opener(ProxyHandler({})).open(request, timeout=55)
    except HTTPError as exc:
        response = exc
    with response:
        return {"status": response.status, "body": json.load(response), "retry_after": response.headers.get("Retry-After")}


def post_evaluation(token, evaluation_id, port):
    response = request_evaluation(token, evaluation_id, port)
    assert response["status"] == 202, response
    return response["body"]


def evaluation_lane(token, port):
    assert port in (5014, 5015)
    owner, tenant = fixture_identity(token)
    path = "/internal/thread-capacity"
    identity = sign_identity({"user_id": owner, "tenant_id": tenant, "kind": "session"}, "runtime", "GET", path, b"")
    request = Request(f"http://127.0.0.1:{port}{path}", headers={IDENTITY_HEADER: identity})
    with build_opener(ProxyHandler({})).open(request, timeout=8) as response:
        snapshot = json.load(response)
    lane, = (item for item in snapshot["lanes"] if item["name"] == "evaluation")
    return {**lane, "rejected_count": snapshot["rejected_count"]}


def submit_evaluation_batch(token, mode, evaluation_ids, port):
    if mode == "workers" and len(evaluation_ids) == len(WORKER_TAGS) and len(set(evaluation_ids)) == len(WORKER_TAGS):
        runs = tuple(zip(WORKER_TAGS, evaluation_ids))
    elif mode == "queue" and len(evaluation_ids) == 1:
        runs = ((QUEUED_TAG, evaluation_ids[0]),) * 12
    elif mode == "overflow" and len(evaluation_ids) == 1:
        runs = ((OVERFLOW_TAG, evaluation_ids[0]),)
    else:
        raise ValueError("Unknown or unbounded evaluation submission group")

    for tag, identifier in set(runs):
        initial = read_evaluation(token, identifier, tag)
        assert initial["run"]["status"] == initial["case"]["status"] == "PENDING" and not initial["reservations"]
    if len(runs) == 1:
        return [request_evaluation(token, runs[0][1], port)]
    with ThreadPoolExecutor(max_workers=len(runs)) as executor:
        return list(executor.map(lambda run: request_evaluation(token, run[1], port), runs))


def dispatch_evaluation(token, evaluation_id, port=5014):
    before = read_evaluation(token, evaluation_id)
    assert before["run"]["status"] == before["case"]["status"] == "PENDING" and not before["reservations"]
    return post_evaluation(token, evaluation_id, port)


GATE_READY = text("""
    SELECT EXISTS (
        SELECT 1 FROM pg_locks AS held JOIN pg_stat_activity AS actor USING (pid)
        WHERE actor.datname = current_database() AND actor.application_name = :marker
          AND held.granted AND (
            (:mode = 'race' AND held.locktype = 'advisory') OR
            (:mode = 'claim' AND held.locktype = 'relation' AND held.mode = 'RowShareLock'
             AND held.relation = to_regclass(:evaluation_table))
          )
    )
""")
RACE_WAITERS = text("""
    SELECT DISTINCT waiting.pid
    FROM pg_locks AS waiting JOIN pg_locks AS held USING (locktype, database, classid, objid, objsubid)
    WHERE held.locktype = 'advisory' AND held.pid = pg_backend_pid() AND held.granted AND NOT waiting.granted
""")
CLAIM_WAITERS = text("""
    SELECT DISTINCT waiting.pid
    FROM pg_locks AS waiting JOIN pg_locks AS insertion ON insertion.pid = waiting.pid
    WHERE NOT waiting.granted AND pg_backend_pid() = ANY(pg_blocking_pids(waiting.pid))
      AND insertion.locktype = 'relation' AND insertion.granted AND insertion.mode = 'RowExclusiveLock'
      AND insertion.relation = to_regclass(:reservation_table)
""")


def evaluation_gate(token, evaluation_id, tag, action):
    mode = ADMISSION_TAGS[tag]
    marker = f"rs-eval:{token.hex}:{evaluation_id}:{mode}"
    owner, tenant = fixture_identity(token)
    initial = read_evaluation(token, evaluation_id, tag)
    assert initial["run"]["status"] == initial["case"]["status"] == "PENDING" and not initial["reservations"]
    with get_db_session() as session:
        if action == "admission-ready":
            return {"ready": session.scalar(GATE_READY, {"marker": marker, "mode": mode,
                                                        "evaluation_table": AgentEvaluation.__table__.fullname})}

        session.execute(text("SELECT set_config('application_name', :marker, true)"), {"marker": marker})
        if mode == "race":
            lock_admission_scope(session, "execution", tenant, f"evaluation:{evaluation_id}")
            statement, parameters, expected_waiters = RACE_WAITERS, {}, 2
        else:
            assert session.scalar(select(AgentEvaluation.status).where(
                AgentEvaluation.agent_evaluation_id == evaluation_id, AgentEvaluation.tenant_id == tenant,
                AgentEvaluation.created_by == owner, AgentEvaluation.delete_flag == "N",
            ).with_for_update()) == "PENDING"
            statement, parameters, expected_waiters = CLAIM_WAITERS, {
                "reservation_table": ExecutionReservation.__table__.fullname}, 1

        deadline = monotonic() + 45
        while monotonic() < deadline:
            waiters = session.scalars(statement, parameters).all()
            if len(waiters) == expected_waiters:
                if mode == "claim":
                    update_agent_evaluation_status(evaluation_id, tenant, "FAILED", updated_by=owner,
                                                   error_message=LOST_CLAIM_REASON, expected_status="PENDING",
                                                   db_session=session)
                return {"waiting_claimants": len(waiters), "mode": mode}
            assert len(waiters) < expected_waiters, "An unexpected worker entered the case-owned evaluation gate"
            sleep(0.1)
        raise AssertionError("Real Runtime evaluation requests did not reach the owned PostgreSQL gate")


def workspace_digest(token):
    owner, _ = fixture_identity(token)
    base = Path(AGENT_WORKSPACE_ROOT)
    mount = Path("/mnt/nexent")
    mountpoints = {line.split()[4] for line in Path("/proc/self/mountinfo").read_text(encoding="utf-8").splitlines()}
    if str(mount) not in mountpoints or not base.is_relative_to(mount) or base.resolve() != base:
        raise RuntimeError("The workspace probe requires the test's shared mount")
    records = []
    for attachment in (base / owner).glob("*/inputs/000_peer-restart-input.txt"):
        run_id = attachment.parents[1].name
        if attachment.resolve() != attachment or not attachment.is_file() or UUID(hex=run_id).hex != run_id:
            raise RuntimeError("The workspace probe only reads regular fixture run paths")
        data = f"runtime-peer-restart:{token.hex}\n".encode()
        with attachment.open("rb") as stream:
            actual = stream.read(len(data) + 1)
        assert actual == data, "The live attachment workspace content changed"
        records.append({"run_id": run_id, "sha256": sha256(actual).hexdigest()})
    if not records:
        return None
    record, = records
    return record


def observe(raw_token, action, *arguments, runtime_port=5014):
    token = UUID(hex=raw_token)
    if token.hex != raw_token or POSTGRES_HOST not in {
        "nexent-postgresql", "nexent-postgresql.nexent", "nexent-postgresql.nexent.svc",
        "nexent-postgresql.nexent.svc.cluster.local",
    }:
        raise ValueError("The restart probe requires the case-owned database")
    if action == "seed-evaluation" and len(arguments) in {2, 3}:
        agent_id, model_id, *tags = arguments
        return seed_evaluation(token, int(agent_id), int(model_id), *tags)
    if action == "dispatch-evaluation" and len(arguments) == 1:
        return dispatch_evaluation(token, int(arguments[0]), port=runtime_port)
    if action == "read-evaluation" and len(arguments) == 1:
        return read_evaluation(token, int(arguments[0]))
    if action in {"admission-gate", "admission-ready", "admission-dispatch", "admission-read"} and len(arguments) == 2:
        raw_id, tag = arguments
        evaluation_id = int(raw_id)
        if tag not in ADMISSION_TAGS or evaluation_id < 1:
            raise ValueError("Admission requires an owned evaluation run")
        if action == "admission-read":
            return read_evaluation(token, evaluation_id, tag)
        if action == "admission-dispatch":
            read_evaluation(token, evaluation_id, tag)
            return post_evaluation(token, evaluation_id, runtime_port)
        return evaluation_gate(token, evaluation_id, tag, action)
    if action == "submission-seed" and len(arguments) == 2:
        agent_id, model_id = map(int, arguments)
        return {tag: seed_evaluation(token, agent_id, model_id, tag) for tag in SUBMISSION_TAGS}
    if action == "submission-lane" and not arguments:
        return evaluation_lane(token, runtime_port)
    if action == "submission-dispatch" and arguments:
        mode, *identifiers = arguments
        return submit_evaluation_batch(token, mode, tuple(map(int, identifiers)), runtime_port)
    if action == "submission-read" and len(arguments) in range(2, 2 * len(SUBMISSION_TAGS) + 1, 2):
        pairs = dict(zip(arguments[::2], map(int, arguments[1::2])))
        if len(pairs) * 2 != len(arguments) or not pairs.keys() <= set(SUBMISSION_TAGS):
            raise ValueError("Unknown or duplicate case-owned evaluation labels")
        return {tag: read_evaluation(token, identifier, tag) for tag, identifier in pairs.items()}
    if action == "workspace" and not arguments:
        return workspace_digest(token)
    raise ValueError("Unknown peer restart probe operation")


if __name__ == "__main__":
    print("SCALING_PEER_RESTART " + json.dumps(observe(*sys.argv[1:])))
