# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Operational outcomes for ordinary sessions of a published business Agent."""

from sqlalchemy import text

from contracts.constants.constants import ASSET_OWNER_ROLE, ASSET_OWNER_TENANT_ID, DEFAULT_TENANT_ID
from contracts.errors.codes import ErrorCode
from contracts.errors.exceptions import AppException
from infrastructure.rdb.client import get_db_session
from management.db.evaluation.releases import _require


def release_monitoring(tenant, actor, lock):
    with get_db_session() as session:
        release = (
            session.execute(
                text("""
            SELECT agent_id,base_version,new_version,published_at,
              greatest(published_at,now()-interval '7 days') AS since,now() AS until
            FROM nexent.evolution_release_t WHERE tenant_id=:tenant AND lock_id=:lock
        """),
                {"tenant": tenant, "lock": lock},
            )
            .mappings()
            .one_or_none()
        )
        if not release:
            raise AppException(ErrorCode.COMMON_RESOURCE_NOT_FOUND)
        _require(session, tenant, release["agent_id"], actor)
        scope = {
            **release,
            "tenant": tenant,
            "asset_role": ASSET_OWNER_ROLE,
            "asset_tenant": ASSET_OWNER_TENANT_ID,
            "default_tenant": DEFAULT_TENANT_ID,
        }
        rows = session.execute(_OUTCOMES, scope).mappings().all()
        events = (
            session.execute(
                text("""SELECT action,actor,reason,created_at
            FROM nexent.evolution_release_event_t WHERE lock_id=:lock ORDER BY created_at,action"""),
                {"lock": lock},
            )
            .mappings()
            .all()
        )
        return {
            "since": release["since"],
            "until": release["until"],
            "versions": [dict(r) for r in rows],
            "events": [dict(r) for r in events],
        }


# Start from server-bound ordinary sessions. Count each physical execution once, including user retries.
# A binding alone cannot establish which version actually ran. Missing or conflicting receipts stay separate.
_OUTCOMES = text("""
WITH versions(v) AS (VALUES (CAST(:base_version AS integer)),(CAST(:new_version AS integer))),
runs AS (
    SELECT b.version_no AS bound,e.run_id,e.status,e.conversation_id,e.created_by,c.evolution_grant_epoch,
           e.resource_versions AS receipt,tr.n,tr.trace_agent,tr.trace_version,tr.trajectory,tr.readable,tr.duration,tr.tokens,
           a.evolution_valid_until,a.evolution_grant_epoch AS admission_epoch,a.evolution_source_message_id
    FROM nexent.evolution_session_version_t b
    JOIN nexent.conversation_record_t c ON c.conversation_id=b.conversation_id AND c.created_by=b.created_by AND c.delete_flag='N'
    JOIN nexent.agent_execution_t e ON e.tenant_id=b.tenant_id AND e.conversation_id=b.conversation_id
        AND e.created_by=b.created_by AND e.delete_flag='N'
    JOIN LATERAL (
        SELECT a.prepared_assistant_id,a.evolution_valid_until,a.evolution_grant_epoch,a.evolution_source_message_id,
               a.evolution_reply->>'business' AS business,count(*) OVER () AS matches
        FROM nexent.conversation_run_admission_t a
        WHERE a.run_id=e.run_id AND a.tenant_id=e.tenant_id AND a.created_by=e.created_by
          AND a.conversation_id=e.conversation_id AND a.delete_flag='N' AND a.prepared_assistant_id IS NOT NULL
        LIMIT 1
    ) a ON a.matches=1
    JOIN nexent.conversation_message_t m ON m.message_id=a.prepared_assistant_id AND m.conversation_id=e.conversation_id
        AND m.created_by=e.created_by AND m.message_role='assistant' AND m.message_source='CHAT' AND m.delete_flag='N'
    LEFT JOIN LATERAL (
        SELECT count(*) AS n,min(t.agent_id) AS trace_agent,min(t.agent_version_no) AS trace_version,
          min(t.trajectory_id::text) AS trajectory,bool_and(t.status IN ('success','error','cancelled')) AS readable,
          max(t.duration_ms) FILTER (WHERE t.status IN ('success','error','cancelled') AND t.duration_ms>=0 AND t.duration_ms<'Infinity'::float8) AS duration,
          max(t.total_tokens) FILTER (WHERE t.status IN ('success','error','cancelled') AND t.total_tokens>=0) AS tokens
        FROM nexent.trajectory_execution_t t
        WHERE t.agentos_run_id=e.run_id AND t.conversation_id=e.conversation_id AND t.created_by=e.created_by
          AND t.turn_no>0 AND t.delete_flag='N'
    ) tr ON true
    WHERE b.tenant_id=:tenant AND b.agent_id=:agent_id AND b.version_no IN (SELECT v FROM versions)
      AND e.create_time BETWEEN CAST(:since AS timestamp) AND CAST(:until AS timestamp)
      AND e.status IN ('completed','failed','stopped') AND a.business IS DISTINCT FROM 'false'
      AND (e.resource_versions->'agent_id' IS NULL OR e.resource_versions->'agent_id'=to_jsonb(CAST(:agent_id AS integer)))
), attributed AS (
    SELECT r.*, CASE
        WHEN receipt ? 'model_revision' THEN
            CASE WHEN receipt->'agent_id'=to_jsonb(CAST(:agent_id AS integer)) THEN
                CASE receipt->'agent_version_no' WHEN to_jsonb(CAST(:base_version AS integer)) THEN CAST(:base_version AS integer)
                     WHEN to_jsonb(CAST(:new_version AS integer)) THEN CAST(:new_version AS integer) END
            END
        WHEN n=1 AND trace_agent=:agent_id AND trace_version IN (SELECT v FROM versions) THEN trace_version
        END AS actual
    FROM runs r
), observed AS (
    SELECT r.*,actual IS NOT NULL AS verified,n=1 AND trace_agent=:agent_id AND trace_version=actual AS trace_matches
    FROM attributed r
), facts AS (
    SELECT o.*,d.observation AS diagnostic
    FROM observed o
    LEFT JOIN nexent.evolution_review_turn_t d ON o.verified AND o.trace_matches AND o.readable AND d.tenant_id=:tenant
      AND d.agent_id=:agent_id AND d.agent_version_no=o.actual AND d.owner_id=o.created_by
      AND d.source_message_id=o.evolution_source_message_id AND d.conversation_id=o.conversation_id
      AND d.run_id=o.run_id AND d.trajectory_id::text=o.trajectory
      AND d.observation_state='observed' AND d.observation->>'coverage'='complete'
      AND d.grant_epoch=o.evolution_grant_epoch AND d.grant_epoch=o.admission_epoch
      AND d.valid_until>clock_timestamp() AND o.evolution_valid_until>clock_timestamp()
      AND EXISTS (SELECT 1 FROM nexent.user_tenant_t u JOIN nexent.user_account_t acct ON acct.user_id=u.user_id AND acct.delete_flag='N' WHERE u.user_id=o.created_by AND u.delete_flag='N'
         AND coalesce(nullif(u.tenant_id,''),CASE WHEN upper(acct.user_roles[1])=:asset_role THEN :asset_tenant ELSE :default_tenant END)=:tenant)
)
SELECT v AS version_no,count(DISTINCT conversation_id) FILTER (WHERE verified) AS sessions,
    count(run_id) FILTER (WHERE verified) AS executions,
    count(run_id) FILTER (WHERE verified IS NOT TRUE) AS unverified,
    count(run_id) FILTER (WHERE verified AND actual<>bound) AS binding_mismatches,
    count(*) FILTER (WHERE verified AND status='failed') AS failed,
    count(*) FILTER (WHERE verified AND status='stopped') AS stopped,
    count(duration) FILTER (WHERE verified AND trace_matches) AS timed,
    percentile_cont(0.9) WITHIN GROUP (ORDER BY duration) FILTER (WHERE verified AND trace_matches) AS p90_ms,
    count(tokens) FILTER (WHERE verified AND trace_matches) AS metered,
    (avg(tokens) FILTER (WHERE verified AND trace_matches))::float8 AS mean_tokens,
    count(diagnostic) AS reviewed,
    count(*) FILTER (WHERE diagnostic->'signals' ? 'user_correction') AS corrected,
    count(*) FILTER (WHERE diagnostic->'signals' ? 'tool_error') AS tool_errors,
    count(*) FILTER (WHERE diagnostic->'signals' ? 'file_receipt_missing') AS missing_files,
    count(*) FILTER (WHERE diagnostic->'signals' ? 'negative_feedback') AS disliked
FROM versions LEFT JOIN facts ON coalesce(actual,bound)=v GROUP BY v ORDER BY v
""")
