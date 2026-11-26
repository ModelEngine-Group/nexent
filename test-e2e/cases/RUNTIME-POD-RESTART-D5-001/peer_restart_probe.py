# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Prepare and inspect case-owned evaluation runs and the peer-restart workspace."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import sys
from time import monotonic, sleep
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener
from uuid import UUID, uuid5

from fastapi import HTTPException
from sqlalchemy import select, text

from contracts.constants.environment import POSTGRES_HOST
from infrastructure.rdb.client import get_db_session
from management.db.agent.models import AgentInfo
from management.db.evaluation.models import AgentEvaluation, AgentEvaluationCase, Evaluator
from management.db.evaluation.runs import (
    create_agent_evaluation, create_agent_evaluation_cases, update_agent_evaluation_status,
)
from management.db.evaluation.sets import create_evaluation_set, get_evaluation_set_cases_all, insert_evaluation_set_cases
from management.services.evaluation.dispatch import dispatch_agent_evaluation_run
from management.services.evaluation.scoring import validate_code_evaluator
from management.thread_management import config_thread_manager


EVALUATOR = "Restart fixture exact match"
RESTART_TAG = "restart-eval"
ADMISSION_TAGS = {"admission-eval-race": "race", "admission-eval-lost-claim": "claim"}
WORKER_TAGS = tuple(f"admission-eval-worker-{index}" for index in range(1, 7))
QUEUED_TAGS = tuple(f"admission-eval-queue-{index}" for index in range(1, 13))
OVERFLOW_TAG = "admission-eval-overflow"
SUBMISSION_TAGS = (*WORKER_TAGS, *QUEUED_TAGS, OVERFLOW_TAG)
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
        return {"run": {"id": run.agent_evaluation_id, "status": run.status, "progress": run.progress_done,
                        "score": run.score_overall, "error": run.error_message},
                "case": {"id": evaluation_case.agent_evaluation_case_id, "status": evaluation_case.status,
                         "predict": evaluation_case.predict, "score": evaluation_case.score,
                         "error": evaluation_case.error_message}}


def serve_evaluation(token):
    owner, tenant = fixture_identity(token)
    config_thread_manager.start()

    class Handler(BaseHTTPRequestHandler):
        def respond(self, status, data):
            raw = json.dumps(data).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):
            if self.path == "/ready":
                self.respond(200, {"ready": True})
            elif self.path == "/lane":
                snapshot = asdict(config_thread_manager.snapshot())
                lane, = (item for item in snapshot["lanes"] if item["name"] == "evaluation")
                self.respond(200, {**lane, "rejected_count": snapshot["rejected_count"]})
            else:
                self.respond(404, {})

        def do_POST(self):
            size = int(self.headers.get("Content-Length", 0))
            if self.path != "/evaluate" or not 0 < size <= 96:
                self.respond(404, {})
                return
            request = json.loads(self.rfile.read(size))
            evaluation_id, tag = request["id"], request["tag"]
            read_evaluation(token, evaluation_id, tag)
            try:
                response = dispatch_agent_evaluation_run(evaluation_id, owner, tenant)
            except HTTPException as exc:
                self.respond(exc.status_code, {"detail": exc.detail})
            else:
                self.respond(202, response)

    with ThreadingHTTPServer(("127.0.0.1", 8091), Handler) as server:
        server.serve_forever()


def fixture_request(path, data=None):
    request = Request(f"http://127.0.0.1:8091/{path}", data)
    try:
        response = build_opener(ProxyHandler({})).open(request, timeout=55)
    except HTTPError as exc:
        response = exc
    with response:
        return {"status": response.status, "body": json.load(response), "retry_after": response.headers.get("Retry-After")}


def request_evaluation(evaluation_id, tag):
    return fixture_request("evaluate", json.dumps({"id": evaluation_id, "tag": tag}).encode())


def post_evaluation(evaluation_id, tag):
    response = request_evaluation(evaluation_id, tag)
    assert response["status"] == 202, response
    return response["body"]


def submit_evaluation_batch(token, mode, evaluation_ids):
    tags = {"workers": WORKER_TAGS, "queue": QUEUED_TAGS, "overflow": (OVERFLOW_TAG,)}[mode]
    assert len(evaluation_ids) == len(tags) and len(set(evaluation_ids)) == len(tags)
    runs = tuple(zip(tags, evaluation_ids, strict=True))
    for tag, identifier in runs:
        initial = read_evaluation(token, identifier, tag)
        assert initial["run"]["status"] == initial["case"]["status"] == "PENDING"
    if len(runs) == 1:
        tag, evaluation_id = runs[0]
        return [request_evaluation(evaluation_id, tag)]
    with ThreadPoolExecutor(max_workers=len(runs)) as executor:
        return list(executor.map(lambda run: request_evaluation(run[1], run[0]), runs))


def dispatch_evaluation(token, evaluation_id):
    before = read_evaluation(token, evaluation_id)
    assert before["run"]["status"] == before["case"]["status"] == "PENDING"
    return post_evaluation(evaluation_id, RESTART_TAG)


GATE_READY = text("""
    SELECT EXISTS (
        SELECT 1 FROM pg_locks AS held JOIN pg_stat_activity AS actor USING (pid)
        WHERE actor.datname = current_database() AND actor.application_name = :marker
          AND held.granted AND held.locktype = 'relation' AND held.mode = 'RowShareLock'
          AND held.relation = to_regclass(:evaluation_table)
    )
""")
CLAIM_WAITERS = text("""
    SELECT DISTINCT waiting.pid
    FROM pg_locks AS waiting JOIN pg_locks AS claim ON claim.pid = waiting.pid
    WHERE NOT waiting.granted AND pg_backend_pid() = ANY(pg_blocking_pids(waiting.pid))
      AND claim.locktype = 'relation' AND claim.granted AND claim.mode = 'RowExclusiveLock'
      AND claim.relation = to_regclass(:evaluation_table)
""")


def evaluation_gate(token, evaluation_id, tag, action):
    mode = ADMISSION_TAGS[tag]
    marker = f"rs-eval:{token.hex}:{evaluation_id}:{mode}"
    owner, tenant = fixture_identity(token)
    initial = read_evaluation(token, evaluation_id, tag)
    assert initial["run"]["status"] == initial["case"]["status"] == "PENDING"
    with get_db_session() as session:
        parameters = {"marker": marker, "evaluation_table": AgentEvaluation.__table__.fullname}
        if action == "admission-ready":
            return {"ready": session.scalar(GATE_READY, parameters)}

        session.execute(text("SELECT set_config('application_name', :marker, true)"), {"marker": marker})
        assert session.scalar(select(AgentEvaluation.status).where(
            AgentEvaluation.agent_evaluation_id == evaluation_id, AgentEvaluation.tenant_id == tenant,
            AgentEvaluation.created_by == owner, AgentEvaluation.delete_flag == "N",
        ).with_for_update()) == "PENDING"
        expected_waiters = 2 if mode == "race" else 1

        deadline = monotonic() + 45
        while monotonic() < deadline:
            count = len(session.scalars(CLAIM_WAITERS, parameters).all())
            if count == expected_waiters:
                if mode == "claim":
                    update_agent_evaluation_status(evaluation_id, tenant, "FAILED", updated_by=owner,
                                                   error_message=LOST_CLAIM_REASON, expected_status="PENDING",
                                                   db_session=session)
                return {"waiting_claimants": count, "mode": mode}
            assert count < expected_waiters, "An unexpected worker entered the case-owned evaluation gate"
            sleep(0.1)
        raise AssertionError("Management dispatch did not reach the owned PostgreSQL claim")


def observe(raw_token, action, *arguments):
    token = UUID(hex=raw_token)
    if token.hex != raw_token or POSTGRES_HOST not in {
        "nexent-postgresql", "nexent-postgresql.nexent", "nexent-postgresql.nexent.svc",
        "nexent-postgresql.nexent.svc.cluster.local",
    }:
        raise ValueError("The evaluation probe requires the case-owned database")
    if action == "serve-evaluation" and not arguments:
        return serve_evaluation(token)
    if action == "seed-evaluation" and len(arguments) in {2, 3}:
        agent_id, model_id, *tags = arguments
        return seed_evaluation(token, int(agent_id), int(model_id), *tags)
    if action == "dispatch-evaluation" and len(arguments) == 1:
        return dispatch_evaluation(token, int(arguments[0]))
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
            return request_evaluation(evaluation_id, tag)
        return evaluation_gate(token, evaluation_id, tag, action)
    if action == "submission-seed" and len(arguments) == 2:
        agent_id, model_id = map(int, arguments)
        return {tag: seed_evaluation(token, agent_id, model_id, tag) for tag in SUBMISSION_TAGS}
    if action == "submission-lane" and not arguments:
        return fixture_request("lane")["body"]
    if action == "submission-dispatch" and arguments:
        mode, *identifiers = arguments
        return submit_evaluation_batch(token, mode, tuple(map(int, identifiers)))
    if action == "submission-read" and len(arguments) in range(2, 2 * len(SUBMISSION_TAGS) + 1, 2):
        pairs = dict(zip(arguments[::2], map(int, arguments[1::2])))
        if len(pairs) * 2 != len(arguments) or not pairs.keys() <= set(SUBMISSION_TAGS):
            raise ValueError("Unknown or duplicate case-owned evaluation labels")
        return {tag: read_evaluation(token, identifier, tag) for tag, identifier in pairs.items()}
    raise ValueError("Unknown peer restart probe operation")


if __name__ == "__main__":
    print("SCALING_PEER_RESTART " + json.dumps(observe(*sys.argv[1:])))
