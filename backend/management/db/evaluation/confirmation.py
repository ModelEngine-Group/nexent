# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Exclusive material partitions and immutable manifests from the independent evaluator."""

import json

from sqlalchemy import text

from contracts.errors.codes import ErrorCode
from contracts.errors.exceptions import AppException
from contracts.evolution_sources import example_source_keys, task_digest
from contracts.roles import has_any_role
from infrastructure.rdb.client import get_db_session


def _membership(session, tenant, user):
    return session.scalar(text("""
        SELECT a.user_roles FROM nexent.user_account_t a JOIN nexent.user_tenant_t u USING (user_id)
         WHERE u.tenant_id=:tenant AND u.user_id=:user AND a.delete_flag='N' AND u.delete_flag='N'
         FOR SHARE OF a,u
    """), {"tenant":tenant, "user":user})


def set_curator(tenant, agent, actor, grant):
    with get_db_session() as session:
        if not has_any_role(_membership(session, tenant, actor), {"ADMIN", "SU"}):
            raise AppException(ErrorCode.COMMON_FORBIDDEN)
        if grant.enabled and not _membership(session, tenant, grant.user_id):
            raise AppException(ErrorCode.COMMON_FORBIDDEN)
        session.execute(text("""
            INSERT INTO nexent.evolution_confirmation_curator_t (tenant_id,agent_id,user_id,enabled,updated_by)
            VALUES (:tenant,:agent,:user,:enabled,:actor)
            ON CONFLICT (tenant_id,agent_id,user_id) DO UPDATE SET
                enabled=EXCLUDED.enabled, updated_by=EXCLUDED.updated_by, update_time=clock_timestamp()
            WHERE evolution_confirmation_curator_t.enabled IS DISTINCT FROM EXCLUDED.enabled
        """), {"tenant":tenant,"agent":agent,"user":grant.user_id,"actor":actor,"enabled":grant.enabled})


def _overlap():
    return AppException(ErrorCode.COMMON_VALIDATION_ERROR, "The materials overlap another evaluation partition")


def require_curator(session, tenant, agent, user):
    if not _membership(session, tenant, user) or not session.scalar(text("""
        SELECT enabled FROM nexent.evolution_confirmation_curator_t
         WHERE tenant_id=:tenant AND agent_id=:agent AND user_id=:user FOR SHARE
    """), {"tenant":tenant, "agent":agent, "user":user}):
        raise AppException(ErrorCode.COMMON_FORBIDDEN)


def _reserve(session, tenant, agent, keys, partition):
    # Both writers take unique-index locks in the same order. A conflict rolls back the entire task or suite.
    params = {"tenant":tenant, "agent":agent, "keys":sorted(keys), "partition":partition}
    count = session.scalar(text("""
        WITH reserved AS (
            INSERT INTO nexent.evolution_partition_source_t (tenant_id,agent_id,source_key,partition_name)
            SELECT :tenant,:agent,k,:partition FROM unnest(CAST(:keys AS text[])) AS src(k) ORDER BY k
            ON CONFLICT (tenant_id,agent_id,source_key) DO UPDATE SET partition_name=EXCLUDED.partition_name
              WHERE evolution_partition_source_t.partition_name=EXCLUDED.partition_name
            RETURNING 1
        ) SELECT count(*) FROM reserved
    """), params)
    if count != len(keys):
        raise _overlap()


def require_development_partition(session, tenant, agent, task):
    _reserve(session, tenant, agent, example_source_keys(task), "development")


def register_suite(tenant, user, manifest):
    agent, version = manifest.agent_id, manifest.version_no
    public = manifest.canonical()
    digest = task_digest(public)
    params = {"tenant":tenant,"agent":agent,"version":version,"digest":digest,"user":user}
    with get_db_session() as session:
        require_curator(session, tenant, agent, user)
        existing = text("""
            SELECT suite_id FROM nexent.evolution_confirmation_suite_t
             WHERE tenant_id=:tenant AND agent_id=:agent AND version_no=:version AND digest=:digest
        """)
        suite = session.scalar(existing, params)
        if suite is not None:
            return {"suite_id":suite, "digest":digest, "case_count":len(public["cases"])}
        keys = {source for case in manifest.cases for source in case.sources}
        _reserve(session, tenant, agent, keys, "confirmation")
        # Cases recorded before the partition index was deployed must participate too.
        rows = session.execute(text("""
            SELECT task->>'query' AS query, task->>'source_group' AS source_group, task->'attachments' AS attachments,
                   task->'trace_source' AS trace_source,
                   jsonb_build_object('initial',task->'file_state'->'initial') AS file_state
              FROM nexent.evolution_replay_case_t WHERE tenant_id=:tenant AND agent_id=:agent AND NOT source_partitioned
        """).execution_options(yield_per=256), params).mappings()
        try:
            if any(keys.intersection(example_source_keys(row)) for row in rows):
                raise _overlap()
        finally:
            rows.close()
        suite = session.scalar(text("""
            INSERT INTO nexent.evolution_confirmation_suite_t (tenant_id,agent_id,version_no,digest,manifest,created_by)
            VALUES (:tenant,:agent,:version,:digest,CAST(:manifest AS jsonb),:user)
            ON CONFLICT DO NOTHING RETURNING suite_id
        """), {**params,"manifest":json.dumps(public)})
        if suite is None:
            suite = session.execute(existing, params).scalar_one()
    return {"suite_id":suite, "digest":digest, "case_count":len(public["cases"])}
