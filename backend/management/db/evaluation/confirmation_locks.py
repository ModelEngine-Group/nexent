# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Atomic transition from an eligible development candidate to an independent comparison."""

import json
from contextlib import contextmanager

from sqlalchemy import text

from contracts.errors.codes import ErrorCode
from contracts.errors.exceptions import AppException
from contracts.evolution_sources import task_digest
from infrastructure.rdb.client import get_db_session
from management.db.evaluation.confirmation import require_curator


@contextmanager
def nomination_evidence(tenant, eid, plan_digest):
    params = {"tenant":tenant, "eid":eid}
    with get_db_session() as session:
        plan = session.scalar(text("""
            SELECT plan FROM nexent.evolution_experiment_t
             WHERE tenant_id=:tenant AND experiment_id=:eid AND NOT cancelled FOR UPDATE
        """), params)
        if not plan or task_digest(plan) != plan_digest or not plan["request"].get("screening"):
            raise AppException(ErrorCode.COMMON_VALIDATION_ERROR, "Experiment is cancelled or its frozen plan changed")
        rows = session.execute(text("""
            SELECT case_id,variant,status,receipt_id,result FROM nexent.evolution_trial_t
             WHERE experiment_id=:eid ORDER BY trial_id FOR SHARE
        """), params).mappings()
        pairs = {}
        for row in rows:
            pairs.setdefault(row["case_id"], {})[row["variant"]] = row
        yield session, plan, pairs


def save_nomination(session, eid, editor, recipe):
    digest = task_digest(recipe)
    params = {"eid":eid, "digest":digest, "recipe":json.dumps(recipe), "editor":editor}
    stored = session.scalar(text("""
        INSERT INTO nexent.evolution_confirmation_candidate_t (experiment_id,digest,recipe,submitted_by)
        VALUES (:eid,:digest,CAST(:recipe AS jsonb),:editor) ON CONFLICT DO NOTHING RETURNING digest
    """), params)
    if stored is None:
        stored = session.scalar(text("SELECT digest FROM nexent.evolution_confirmation_candidate_t WHERE experiment_id=:eid"), params)
    if stored != digest:
        raise AppException(ErrorCode.COMMON_VALIDATION_ERROR, "This experiment already nominated a different recipe")
    return {"experiment_id":eid,"candidate_digest":digest}


def lock_inputs(tenant, curator, suite_id, request):
    with get_db_session() as session:
        row = session.execute(text("""
            SELECT e.agent_id,e.version_no,e.plan,c.submitted_by,c.digest,c.recipe
              FROM nexent.evolution_confirmation_suite_t s JOIN nexent.evolution_experiment_t e
                ON (e.tenant_id,e.agent_id,e.version_no)=(s.tenant_id,s.agent_id,s.version_no)
              JOIN nexent.evolution_confirmation_candidate_t c USING (experiment_id)
             WHERE s.suite_id=:suite AND s.tenant_id=:tenant AND s.digest=:suite_digest AND e.experiment_id=:eid
               AND NOT e.cancelled AND c.digest=:digest
        """), {"suite":suite_id,"tenant":tenant,"suite_digest":request.suite_digest,
               "eid":request.experiment_id,"digest":request.candidate_digest}).mappings().one_or_none()
        if not row:
            raise AppException(ErrorCode.COMMON_RESOURCE_NOT_FOUND)
        require_curator(session, tenant, row["agent_id"], curator)
        return dict(row)


def lock_comparison(tenant, curator, suite_id, request, recipe):
    params = {"suite":suite_id,"tenant":tenant,"eid":request.experiment_id,"curator":curator}
    policy = request.policy.model_dump()
    digest = task_digest([tenant, suite_id, request.suite_digest, request.experiment_id, request.candidate_digest, policy])
    with get_db_session() as session:
        row = session.execute(text("""
            SELECT s.agent_id,s.digest AS suite_digest,s.manifest,c.digest AS candidate_digest,c.recipe,e.cancelled
              FROM nexent.evolution_confirmation_suite_t s JOIN nexent.evolution_experiment_t e
                ON (e.tenant_id,e.agent_id,e.version_no)=(s.tenant_id,s.agent_id,s.version_no)
              JOIN nexent.evolution_confirmation_candidate_t c USING (experiment_id)
             WHERE s.suite_id=:suite AND s.tenant_id=:tenant AND e.experiment_id=:eid
               FOR UPDATE OF s FOR SHARE OF e,c
        """), params).mappings().one_or_none()
        if not row:
            raise AppException(ErrorCode.COMMON_RESOURCE_NOT_FOUND)
        require_curator(session, tenant, row["agent_id"], curator)
        if (row["cancelled"] or row["candidate_digest"] != request.candidate_digest
                or task_digest(recipe) != request.candidate_digest or row["recipe"] != recipe
                or row["suite_digest"] != request.suite_digest or task_digest(row["manifest"]) != request.suite_digest):
            raise AppException(ErrorCode.COMMON_VALIDATION_ERROR, "Candidate, experiment or independent suite changed")
        cases = row["manifest"]["cases"]
        if max(request.policy.minimum_valid_pairs, sum(request.policy.family_minimums.values())) > len(cases):
            raise AppException(ErrorCode.COMMON_VALIDATION_ERROR, "The suite is too small for the declared coverage")
        existing = session.execute(text("""
            SELECT lock_id,digest FROM nexent.evolution_confirmation_lock_t WHERE suite_id=:suite
        """), params).mappings().one_or_none()
        if existing:
            if digest != existing["digest"]:
                raise AppException(ErrorCode.COMMON_VALIDATION_ERROR, "The suite is already locked to another comparison")
            return dict(existing)
        lock_id = session.scalar(text("""
            INSERT INTO nexent.evolution_confirmation_lock_t (suite_id,experiment_id,digest,policy,locked_by)
            VALUES (:suite,:eid,:digest,CAST(:policy AS jsonb),:curator) RETURNING lock_id
        """), {**params,"digest":digest,"policy":json.dumps(policy)})
        keys = sorted({source for case in cases for source in case["sources"]})
        reserved = session.scalar(text("""
            WITH claimed AS (
                INSERT INTO nexent.evolution_confirmation_used_source_t (tenant_id,agent_id,source_key,lock_id)
                SELECT :tenant,:agent,k,:lock FROM unnest(CAST(:keys AS text[])) AS src(k)
                ORDER BY k ON CONFLICT DO NOTHING RETURNING 1
            ) SELECT count(*) FROM claimed
        """), {**params,"agent":row["agent_id"],"keys":keys,"lock":lock_id})
        if reserved != len(keys):
            raise AppException(ErrorCode.COMMON_VALIDATION_ERROR, "Independent material is already assigned to a comparison")
        return {"lock_id":lock_id,"digest":digest}


def locked_protocol(tenant, curator, lock_id):
    with get_db_session() as session:
        row = session.execute(text("""
            SELECT l.lock_id,l.digest,l.policy,l.experiment_id,l.suite_id,s.manifest,s.digest AS suite_digest,
                   e.agent_id,e.version_no,e.cancelled,c.digest AS candidate_digest,c.recipe
              FROM nexent.evolution_confirmation_lock_t l JOIN nexent.evolution_confirmation_suite_t s USING (suite_id)
              JOIN nexent.evolution_experiment_t e ON e.experiment_id=l.experiment_id
                  AND (e.tenant_id,e.agent_id,e.version_no)=(s.tenant_id,s.agent_id,s.version_no)
              JOIN nexent.evolution_confirmation_candidate_t c ON c.experiment_id=l.experiment_id
             WHERE s.tenant_id=:tenant AND l.lock_id=:id FOR SHARE OF l,s,c,e
        """), {"tenant":tenant,"id":lock_id}).mappings().one_or_none()
        if not row:
            raise AppException(ErrorCode.COMMON_RESOURCE_NOT_FOUND)
        require_curator(session, tenant, row["agent_id"], curator)
        expected = task_digest([tenant,row["suite_id"],row["suite_digest"],row["experiment_id"],row["candidate_digest"],row["policy"]])
        if (row["cancelled"] or expected != row["digest"] or task_digest(row["recipe"]) != row["candidate_digest"]
                or task_digest(row["manifest"]) != row["suite_digest"]):
            raise AppException(ErrorCode.COMMON_VALIDATION_ERROR, "The locked comparison is no longer available")
        return {k:row[k] for k in ("lock_id","digest","policy","experiment_id","suite_id","suite_digest",
                                   "agent_id","version_no","candidate_digest","recipe")}
