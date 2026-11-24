# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Atomic submission, claim, completion and cancellation of development experiments."""

import json
import time
from uuid import uuid4

from sqlalchemy import text

from contracts.constants.environment import EVOLUTION_MAX_RUNNING_TRIALS_PER_TENANT
from contracts.errors.codes import ErrorCode
from contracts.errors.exceptions import AppException
from infrastructure.rdb.client import get_db_session
from management.db.evaluation.replay_cases import task_digest


# Prior experiments have no overall deadline. PostgreSQL is the clock shared by all workers.
_DEADLINE = "e.create_time + make_interval(secs => (e.plan->'budget'->>'max_elapsed_seconds')::integer)"
_RUNNING = """SELECT count(*) FROM nexent.evolution_trial_t active
              JOIN nexent.evolution_experiment_t owner USING (experiment_id)
              WHERE active.status='running' AND owner.tenant_id=e.tenant_id"""


def previous_submission(tenant, user, request):
    with get_db_session() as session:
        row = session.execute(text("""
            SELECT experiment_id, request_digest FROM nexent.evolution_experiment_t
            WHERE tenant_id=:tenant AND created_by=:creator AND request_id=:key
        """), dict(tenant=tenant, creator=user, key=request.request_id)).one_or_none()
        if row is None:
            return None
        if row.request_digest != task_digest(request.model_dump()):
            raise AppException(ErrorCode.COMMON_VALIDATION_ERROR, "Experiment request ID already used")
        return row.experiment_id


def submit(tenant, user, request, plan):
    params = dict(tenant=tenant, creator=user, agent=request.agent_id, version=request.version_no,
                  key=request.request_id, digest=task_digest(request.model_dump()), plan=json.dumps(plan, ensure_ascii=False))
    with get_db_session() as session:
        eid = session.scalar(text("""
            INSERT INTO nexent.evolution_experiment_t
                (tenant_id, created_by, agent_id, version_no, request_id, request_digest, plan)
            VALUES (:tenant, :creator, :agent, :version, :key, :digest, CAST(:plan AS jsonb))
            ON CONFLICT DO NOTHING RETURNING experiment_id
        """), params)
        if eid is None:
            existing = session.execute(text("""
                SELECT experiment_id, request_digest FROM nexent.evolution_experiment_t
                WHERE tenant_id=:tenant AND created_by=:creator AND request_id=:key
            """), params).one()
            if existing.request_digest != params["digest"]:
                raise AppException(ErrorCode.COMMON_VALIDATION_ERROR, "Experiment request ID already used")
            return existing.experiment_id
        if request.suggestion_id is not None:
            link = {**params, "sid": request.suggestion_id, "eid": eid}
            suggestion = session.execute(text("""
                SELECT s.experiment_id FROM nexent.evolution_suggestion_t s
                JOIN nexent.conversation_record_t c ON c.conversation_id=s.conversation_id
                    AND c.created_by=s.submitter_id AND c.delete_flag='N'
                WHERE s.suggestion_id=:sid AND s.tenant_id=:tenant AND s.agent_id=:agent AND s.version_no=:version
                  AND s.status='submitted' FOR UPDATE OF s
            """), link).one_or_none()
            # Check after obtaining the row lock so a concurrent submitter's committed trial rows are visible.
            if suggestion is None or (suggestion.experiment_id is not None and session.scalar(text("""
                SELECT EXISTS (SELECT 1 FROM nexent.evolution_trial_t
                    WHERE experiment_id=:previous AND status IN ('running','pending'))
            """), {"previous":suggestion.experiment_id})):
                raise AppException(ErrorCode.COMMON_VALIDATION_ERROR, "Suggestion unavailable or already being evaluated")
            session.execute(text("""UPDATE nexent.evolution_suggestion_t SET experiment_id=:eid,update_time=now()
                WHERE suggestion_id=:sid"""), link)
        session.execute(text("""
            INSERT INTO nexent.evolution_trial_t (experiment_id, case_id, variant) VALUES (:eid, :case, :variant)
        """), [dict(eid=eid, case=int(case), variant=v) for case in plan["cases"] for v in plan["snapshots"]])
        return eid


def scope(tenant, eid):
    with get_db_session() as session:
        row = session.execute(text(f"""
            SELECT e.plan->'budget' AS budget, {_DEADLINE} AS deadline, agent_id, version_no, cancelled, plan->'request'->'screening' AS screening,
                   plan->'script_build'->'source_cases' AS script_source_cases,
                   plan->'regression_cases' AS regression_cases, plan->'request'->'components' AS components,
                   ARRAY(SELECT jsonb_object_keys(plan->'cases')) AS planned_cases,
                   ARRAY(SELECT jsonb_object_keys(plan->'snapshots')) AS planned_arms
              FROM nexent.evolution_experiment_t e WHERE tenant_id=:tenant AND experiment_id=:eid
        """), dict(tenant=tenant, eid=eid)).mappings().one_or_none()
        return dict(row) if row else None


def trials(tenant, eid):
    with get_db_session() as session:
        return [dict(row) for row in session.execute(text("""
            SELECT t.case_id, t.variant, t.status, t.receipt_id, t.result
            FROM nexent.evolution_trial_t t JOIN nexent.evolution_experiment_t e USING (experiment_id)
            WHERE e.tenant_id=:tenant AND e.experiment_id=:eid ORDER BY t.trial_id
        """), dict(tenant=tenant, eid=eid)).mappings()]


def cancel(tenant, eid):
    with get_db_session() as session:
        session.execute(text("""
            UPDATE nexent.evolution_experiment_t SET cancelled=true WHERE tenant_id=:tenant AND experiment_id=:eid
        """), dict(tenant=tenant, eid=eid))
        session.execute(text("""
            UPDATE nexent.evolution_trial_t t SET status='cancelled', lease_until=NULL
            FROM nexent.evolution_experiment_t e WHERE t.experiment_id=e.experiment_id
                AND e.tenant_id=:tenant AND e.experiment_id=:eid AND t.status IN ('pending','running')
        """), dict(tenant=tenant, eid=eid))


def claim(experiment_id=None):
    with get_db_session() as session:
        session.execute(text(f"""
            UPDATE nexent.evolution_trial_t t SET status='error', lease_until=NULL,
                   result=jsonb_build_object('error', 'experiment_time_budget_exceeded')
              FROM nexent.evolution_experiment_t e
             WHERE t.experiment_id=e.experiment_id AND t.status IN ('pending','running')
               AND {_DEADLINE} <= statement_timestamp()
        """))
        session.execute(text("""
            UPDATE nexent.evolution_trial_t SET status='error', lease_until=NULL,
                result='{"error":"worker_interrupted"}'::jsonb WHERE status='running' AND lease_until < now()
        """))
        params = {"eid": experiment_id, "limit": EVOLUTION_MAX_RUNNING_TRIALS_PER_TENANT}
        row = session.execute(text(f"""
            SELECT t.trial_id, t.case_id, t.variant, e.experiment_id, e.tenant_id, e.created_by, e.plan
            FROM nexent.evolution_trial_t t JOIN nexent.evolution_experiment_t e USING (experiment_id)
            WHERE t.status='pending' AND NOT e.cancelled AND ({_RUNNING}) < :limit
                AND (CAST(:eid AS bigint) IS NULL OR e.experiment_id=:eid) ORDER BY trial_id
            LIMIT 1 FOR UPDATE OF t SKIP LOCKED
        """), params).mappings().one_or_none()
        if not row:
            return None
        job = {**row, "receipt_id": uuid4().hex}
        # Serialize admission, then count again in a new READ COMMITTED statement.
        admitted = session.scalar(text("""
            SELECT pg_try_advisory_xact_lock(hashtextextended('evolution-trial:' || :tenant_id, 0))
        """), job)
        if not admitted:
            return None
        claim_time = time.monotonic()
        claimed = session.execute(text(f"""
            UPDATE nexent.evolution_trial_t t SET status='running', lease_until=now()+interval '120 seconds',
                receipt_id=:receipt_id, cleanup_due=now()+interval '3 minutes'
            FROM nexent.evolution_experiment_t e WHERE t.experiment_id=e.experiment_id AND t.trial_id=:trial_id
                AND NOT e.cancelled AND ({_RUNNING}) < :limit
                AND ({_DEADLINE} IS NULL OR {_DEADLINE} > statement_timestamp())
            RETURNING extract(epoch FROM ({_DEADLINE} - statement_timestamp()))::float8 AS remaining_seconds
        """), {**job, "limit": params["limit"]}).mappings().one_or_none()
        if not claimed:
            return None
        if claimed.remaining_seconds is not None:
            job["monotonic_deadline"] = claim_time + claimed.remaining_seconds
        return job


def heartbeat(job):
    with get_db_session() as session:
        return bool(session.execute(text("""
            UPDATE nexent.evolution_trial_t SET lease_until=now()+interval '120 seconds'
            WHERE trial_id=:trial_id AND receipt_id=:receipt_id AND status='running' AND lease_until >= now()
        """), job).rowcount)


def store_handoff(tenant, user, eid, feedback):
    params = dict(tenant=tenant, user=user, eid=eid, digest=task_digest(feedback), data=json.dumps(feedback, ensure_ascii=False))
    with get_db_session() as session:
        fid = session.scalar(text("""
            INSERT INTO nexent.evolution_feedback_handoff_t (tenant_id, created_by, experiment_id, digest, feedback)
            VALUES (:tenant,:user,:eid,:digest,CAST(:data AS jsonb)) ON CONFLICT DO NOTHING RETURNING feedback_id
        """), params)
        if fid is None:
            fid = session.execute(text("""
                SELECT feedback_id FROM nexent.evolution_feedback_handoff_t WHERE tenant_id=:tenant AND created_by=:user
                AND experiment_id=:eid AND digest=:digest
            """), params).scalar_one()
        return fid


def read_handoff(tenant, fid):
    with get_db_session() as session:
        return session.scalar(text("""
            SELECT feedback FROM nexent.evolution_feedback_handoff_t WHERE tenant_id=:tenant AND feedback_id=:fid
        """), dict(tenant=tenant, fid=fid))


def read_plan(tenant, eid, active_only=False):
    with get_db_session() as session:
        return session.scalar(text("""
            SELECT plan FROM nexent.evolution_experiment_t WHERE tenant_id=:tenant AND experiment_id=:eid
                AND (NOT :active_only OR NOT cancelled)
        """), dict(tenant=tenant, eid=eid, active_only=active_only))


def workspace_choices(tenant, agent_id, version):
    params = dict(tenant=tenant, agent=agent_id, version=version)
    queries = {
        "released_guides": """
            SELECT name, candidate_id, digest FROM nexent.evolution_release_guide_t
             WHERE tenant_id=:tenant AND agent_id=:agent AND version_no=:version ORDER BY name
        """,
        "skills": """
            SELECT s.skill_id, s.skill_name AS name FROM nexent.ag_skill_instance_t i
            JOIN nexent.ag_skill_info_t s ON s.skill_id=i.skill_id AND s.tenant_id=i.tenant_id
            WHERE i.tenant_id=:tenant AND i.agent_id=:agent AND i.version_no=:version
                AND i.enabled AND i.delete_flag='N' AND s.delete_flag='N' ORDER BY s.skill_name
        """,
        "suggestions": """
            SELECT s.suggestion_id, s.expected_behavior, s.skill_id, s.experiment_id FROM nexent.evolution_suggestion_t s
            JOIN nexent.conversation_record_t c ON c.conversation_id=s.conversation_id AND c.created_by=s.submitter_id
            WHERE s.tenant_id=:tenant AND s.agent_id=:agent AND s.version_no=:version AND s.status='submitted'
                AND c.delete_flag='N'
            ORDER BY suggestion_id DESC LIMIT 100
        """,
        "cases": """
            SELECT case_id, digest, task->>'family' AS family, left(task->>'query', 160) AS query,
                task->'expected_skill_names' AS expected_skill_names
            FROM nexent.evolution_replay_case_t WHERE tenant_id=:tenant AND agent_id=:agent AND version_no=:version
            ORDER BY case_id DESC LIMIT 200
        """,
        "candidates": """
            SELECT c.candidate_id, CASE c.resource_field WHEN 'agent.tools' THEN 'tool_set' WHEN 'agent.tool_format' THEN 'tool_mapping' ELSE 'prompt' END AS kind,
                c.resource_field AS name, c.create_time
            FROM nexent.evolution_candidate_t c
            WHERE c.tenant_id=:tenant AND c.agent_id=:agent AND c.base_version_no=:version
            UNION ALL
            SELECT s.candidate_id, CASE s.feedback->>'method' WHEN 'S1' THEN 'skill_discovery' WHEN 'S4' THEN 'skill_script' ELSE 'skill_step' END,
                s.skill_name, s.create_time FROM nexent.evolution_skill_candidate_t s
            WHERE s.tenant_id=:tenant AND (s.feedback->>'method' IS DISTINCT FROM 'S4' OR
                (s.feedback->'script_build'->>'agent'=CAST(:agent AS text)
                 AND s.feedback->'script_build'->>'version'=CAST(:version AS text))) AND EXISTS (
                SELECT 1 FROM nexent.ag_skill_instance_t i WHERE i.skill_id=s.skill_id AND i.tenant_id=:tenant
                AND i.agent_id=:agent AND i.version_no=:version AND i.enabled AND i.delete_flag='N')
            UNION ALL
            SELECT c.candidate_id, 'skill_new', c.name, c.created_at FROM nexent.evolution_new_skill_candidate_t c
            WHERE c.tenant_id=:tenant AND c.agent_id=:agent AND c.version_no=:version
            UNION ALL
            SELECT b.build_id, 'tool_build', f.feedback->>'tool_name', b.created_at
            FROM nexent.evolution_tool_build_t b
            JOIN nexent.evolution_feedback_handoff_t f ON f.feedback_id=b.feedback_id AND f.tenant_id=b.tenant_id
            JOIN LATERAL (
                SELECT report->>'status' AS status FROM nexent.evolution_tool_build_run_t r
                WHERE r.build_id=b.build_id ORDER BY run_id DESC LIMIT 1
            ) latest ON latest.status='passed'
            WHERE b.tenant_id=:tenant AND f.feedback->>'method'='T4'
              AND f.feedback->>'agent_id'=CAST(:agent AS text) AND f.feedback->>'version_no'=CAST(:version AS text)
            ORDER BY create_time DESC LIMIT 200
        """,
        "experiments": """
            SELECT e.experiment_id, e.create_time, plan->'request'->>'candidate_type' AS candidate_type,
                   (plan->'request'->>'candidate_id')::bigint AS candidate_id,
                   (plan->'request'->>'candidate_id' IS NOT NULL AND plan->'request'->>'candidate_type' IN ('prompt','skill_discovery','skill_step','tool_set') AND NOT e.cancelled AND
                    NOT EXISTS (SELECT 1 FROM nexent.evolution_trial_t t WHERE t.experiment_id=e.experiment_id
                                AND t.status IN ('running','pending','cancelled')) AND
                    EXISTS (SELECT 1 FROM nexent.evolution_trial_t t JOIN nexent.evolution_trial_t b
                                USING (experiment_id, case_id) WHERE t.experiment_id=e.experiment_id
                                AND t.variant='result' AND b.variant='base' AND t.status IN ('pass','fail')
                                AND b.status IN ('pass','fail') AND t.receipt_id IS NOT NULL AND b.receipt_id IS NOT NULL))
                       AS eligible_component
              FROM nexent.evolution_experiment_t e
             WHERE tenant_id=:tenant AND agent_id=:agent AND version_no=:version ORDER BY experiment_id DESC LIMIT 100
        """,
    }
    with get_db_session() as session:
        return {name: [dict(row) for row in session.execute(text(query), params).mappings()] for name, query in queries.items()}


def finish(job, status, result):
    with get_db_session() as session:
        return bool(session.execute(text(f"""
            UPDATE nexent.evolution_trial_t t SET
                status=CASE WHEN {_DEADLINE} <= statement_timestamp() THEN 'error' ELSE :status END,
                result=CASE WHEN {_DEADLINE} <= statement_timestamp()
                            THEN jsonb_build_object('error','experiment_time_budget_exceeded') ELSE CAST(:result AS jsonb) END,
                lease_until=NULL
            FROM nexent.evolution_experiment_t e WHERE t.experiment_id=e.experiment_id
                AND t.trial_id=:trial_id AND t.receipt_id=:receipt_id AND t.status='running' AND t.lease_until >= now()
        """), {**job, "status": status, "result": json.dumps(result, ensure_ascii=False, allow_nan=False)}).rowcount)


def claim_cleanup():
    with get_db_session() as session:
        row = session.execute(text("""
            SELECT t.trial_id, t.receipt_id, e.created_by, c.task->'attachments' AS files
            FROM nexent.evolution_trial_t t JOIN nexent.evolution_replay_case_t c USING (case_id)
            JOIN nexent.evolution_experiment_t e USING (experiment_id)
            WHERE t.status NOT IN ('pending','running') AND t.cleanup_due <= now()
            ORDER BY t.cleanup_due LIMIT 1 FOR UPDATE OF t SKIP LOCKED
        """)).mappings().one_or_none()
        if row:
            session.execute(text("""
                UPDATE nexent.evolution_trial_t SET cleanup_due=now()+interval '3 minutes' WHERE trial_id=:trial_id
            """), dict(row))
        return dict(row) if row else None


def complete_cleanup(trial_id, receipt_id):
    with get_db_session() as session:
        session.execute(text("""
            UPDATE nexent.evolution_trial_t SET cleanup_due=NULL WHERE trial_id=:trial AND receipt_id=:receipt
        """), dict(trial=trial_id, receipt=receipt_id))
