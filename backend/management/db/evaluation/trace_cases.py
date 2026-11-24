# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Read the authorized source at preview and again inside the case-insert transaction."""
import json

from sqlalchemy import text

from contracts.errors.codes import ErrorCode
from contracts.errors.exceptions import AppException
from infrastructure.rdb.conversation_state import tenant_membership_matches
from management.db.evaluation.replay_cases import task_digest


def _authorized_source(session, tenant, agent, version, turn):
    source = session.execute(text("""
        SELECT r.owner_id, r.conversation_id, r.trajectory_id::text, r.grant_epoch, r.observation,
               m.message_content AS query, m.minio_files, m.message_index
          FROM nexent.evolution_review_turn_t r
          JOIN nexent.conversation_record_t c ON c.conversation_id=r.conversation_id
               AND c.created_by=r.owner_id AND c.evolution_grant_epoch=r.grant_epoch AND c.delete_flag='N'
          JOIN nexent.conversation_run_admission_t a ON a.tenant_id=r.tenant_id AND a.run_id=r.run_id
               AND a.conversation_id=r.conversation_id AND a.created_by=r.owner_id AND a.delete_flag='N'
               AND a.evolution_source_message_id=r.source_message_id AND a.evolution_grant_epoch=r.grant_epoch
          JOIN nexent.trajectory_execution_t t ON t.trajectory_id=r.trajectory_id AND t.agentos_run_id=a.run_id
               AND t.conversation_id=c.conversation_id AND t.agent_id=r.agent_id
               AND t.agent_version_no=r.agent_version_no AND t.created_by=r.owner_id AND t.delete_flag='N'
               AND t.status<>'expired'
          JOIN nexent.conversation_message_t m ON m.message_id=r.source_message_id AND m.conversation_id=c.conversation_id
               AND m.created_by=r.owner_id AND m.message_role='user' AND m.message_source='CHAT' AND m.delete_flag='N'
         WHERE r.tenant_id=:tenant AND r.agent_id=:agent AND r.agent_version_no=:version AND r.turn_id=:turn
           AND r.observation_state='observed' AND r.observation->>'coverage'='complete'
           AND r.valid_until > clock_timestamp() AND a.evolution_valid_until > clock_timestamp()
         FOR SHARE OF c,r,a,m,t
    """), dict(tenant=tenant, agent=agent, version=version, turn=turn)).mappings().one_or_none()
    if not source or not tenant_membership_matches(session, source["owner_id"], tenant):
        raise AppException(ErrorCode.COMMON_RESOURCE_NOT_FOUND, "Authorized source turn is unavailable")
    return source


def _preceding(session, tenant, source):
    if source["message_index"] is None:
        raise AppException(ErrorCode.COMMON_RESOURCE_NOT_FOUND, "Preceding turn is unavailable")
    # Do not skip an unapproved, deleted, ambiguous, or different-version turn to find an older task.
    candidates = session.execute(text("""
        SELECT m.message_id, r.turn_id FROM nexent.conversation_message_t m
         LEFT JOIN nexent.evolution_review_turn_t r ON r.source_message_id=m.message_id
              AND r.conversation_id=m.conversation_id AND r.tenant_id=:tenant
         WHERE m.conversation_id=:chat AND m.message_index=:idx AND m.message_role='user'
         LIMIT 2
    """), {"tenant": tenant, "chat": source["conversation_id"],
           "idx": source["message_index"] - 2}).mappings().all()
    if len(candidates) != 1 or candidates[0]["turn_id"] is None:
        raise AppException(ErrorCode.COMMON_RESOURCE_NOT_FOUND, "Authorized preceding task is unavailable")
    return candidates[0]["turn_id"]


def _single_draft(session, tenant, user, agent, version, turn, use_previous_task=False):
    source = _authorized_source(session, tenant, agent, version, turn)
    source_turn = turn
    correction = None
    if use_previous_task:
        correction = source
        if "user_correction" not in correction["observation"]["signals"] or correction["message_index"] is None:
            raise AppException(ErrorCode.COMMON_VALIDATION_ERROR, "No preceding task is identified for this correction")
        source_turn = _preceding(session, tenant, correction)
        source = _authorized_source(session, tenant, agent, version, source_turn)
    outline = source["observation"].get("case_outline")
    if outline is None:
        raise AppException(ErrorCode.COMMON_VALIDATION_ERROR, "Source turn lacks tool coverage for replay")
    try:
        files = json.loads(source["minio_files"]) if source["minio_files"] else []
        if files is None:
            files = []
    except (ValueError, TypeError):
        files = None
    attachment_count = len(files) if isinstance(files, list) else None
    labels = []
    if source["owner_id"] == user and attachment_count is not None:
        for file in files[:32]:
            name = file.get("name") if isinstance(file, dict) else None
            labels.append(name[:240] if isinstance(name, str) else "")
    group = task_digest([tenant, source["conversation_id"]])
    return {
        "turn_id": turn, "task_turn_id": source_turn, "trajectory_id": source["trajectory_id"], "source_group": group,
        "correction_trajectory_id": correction["trajectory_id"] if correction else None,
        "correction_query": (correction["query"] or "")[:2000] if correction and correction["owner_id"] == user else None,
        "draft_digest": task_digest([turn, source_turn, source["trajectory_id"], source["grant_epoch"], source["query"],
                                     [correction["trajectory_id"], correction["query"]] if correction else None,
                                     source["minio_files"], outline, source["observation"]["signals"]]),
        "query": (source["query"] or "")[:16000] if source["owner_id"] == user else None,
        "attachment_count": attachment_count, "attachment_names": labels,
        "tool_count": outline["tool_count"], "tools": outline["tools"],
        "signals": source["observation"]["signals"],
    }


def trace_case_draft(session, tenant, user, agent, version, turn, use_previous_task=False, preceding_turns=0):
    last = _single_draft(session, tenant, user, agent, version, turn, use_previous_task)
    if not preceding_turns:
        return last
    if not 1 <= preceding_turns <= 15:
        raise AppException(ErrorCode.COMMON_VALIDATION_ERROR, "Select up to 15 preceding user turns")
    segments = [last]
    for _ in range(preceding_turns):
        source = _authorized_source(session, tenant, agent, version, segments[-1]["task_turn_id"])
        previous = _preceding(session, tenant, source)
        segments.append(_single_draft(session, tenant, user, agent, version, previous))
    segments.reverse()
    if any("user_correction" in part["signals"] for part in segments):
        raise AppException(ErrorCode.COMMON_VALIDATION_ERROR, "Keep later corrections as evidence; choose the original task")
    counts = [part["attachment_count"] for part in segments]
    keys = ("task_turn_id", "trajectory_id", "query", "attachment_names", "attachment_count", "tool_count")
    return {**last, "query": segments[0]["query"], "preceding_turns": preceding_turns,
            "segments": [{k: part[k] for k in keys} for part in segments],
            "attachment_count": sum(counts) if None not in counts else None,
            "attachment_names": [name for part in segments for name in part["attachment_names"]],
            "tool_count": sum(part["tool_count"] for part in segments),
            "tools": [entry for part in segments for entry in part["tools"]][:32],
            "draft_digest": task_digest([part["draft_digest"] for part in segments])}


def verified_baseline(session, tenant, agent, version, case_id, digest, purpose, evaluator, language, judge, snapshot):
    return bool(session.scalar(text("""
        SELECT EXISTS (
          SELECT 1 FROM nexent.evolution_experiment_t e JOIN nexent.evolution_trial_t t USING (experiment_id)
           WHERE e.tenant_id=:tenant AND e.agent_id=:agent AND e.version_no=:version AND NOT e.cancelled
             AND e.plan->'request'->>'candidate_type'='baseline' AND t.case_id=:case AND t.variant='base'
             AND t.status=:status AND t.receipt_id IS NOT NULL AND t.result->>'case_digest'=:digest
             AND e.plan->'cases'->>CAST(:case AS text)=:digest
             AND t.result->>'snapshot_digest'=e.plan->'snapshots'->>'base'
             AND (CAST(:snapshot AS text) IS NULL OR t.result->>'snapshot_digest'=:snapshot)
             AND e.plan->'request'->>'language'=:language
             AND (e.plan->'request'->>'judge_model_id')::bigint IS NOT DISTINCT FROM CAST(:judge AS bigint)
             AND e.plan->'evaluator'=CAST(:evaluator AS jsonb))
    """), dict(tenant=tenant, agent=agent, version=version, case=case_id, digest=digest,
               language=language, judge=judge, snapshot=snapshot, status="fail" if purpose == "reproduce" else "pass",
               evaluator=json.dumps(evaluator, default=str))))


def verified_repair(session, tenant, agent, version, case_id, digest, scoring):
    """A failure becomes a fixed regression only after a complete, observed repair on that material."""
    return bool(session.scalar(text("""
        SELECT EXISTS (
          SELECT 1 FROM nexent.evolution_experiment_t e
          JOIN nexent.evolution_trial_t b ON b.experiment_id=e.experiment_id AND b.case_id=:case AND b.variant='base'
          JOIN nexent.evolution_trial_t t ON t.experiment_id=e.experiment_id AND t.case_id=b.case_id AND t.variant='result'
          WHERE e.tenant_id=:tenant AND e.agent_id=:agent AND e.version_no=:version AND NOT e.cancelled
            AND b.status='fail' AND t.status='pass' AND e.plan->'cases'->>CAST(:case AS text)=:digest
            AND e.plan->'evaluator'=CAST(:rubric AS jsonb) AND e.plan->'request'->>'language'=:language
            AND (e.plan->'request'->>'judge_model_id')::bigint IS NOT DISTINCT FROM CAST(:judge AS bigint)
            AND NOT EXISTS (
              SELECT 1 FROM jsonb_each_text(e.plan->'snapshots') arm
              WHERE NOT EXISTS (
                SELECT 1 FROM nexent.evolution_trial_t x WHERE x.experiment_id=e.experiment_id
                  AND x.case_id=b.case_id AND x.variant=arm.key AND x.status IN ('pass','fail')
                  AND x.receipt_id IS NOT NULL AND x.result->>'case_digest'=:digest
                  AND x.result->>'snapshot_digest'=arm.value)))
    """), dict(tenant=tenant, agent=agent, version=version, case=case_id, digest=digest,
               rubric=json.dumps(scoring["evaluator"], default=str), language=scoring["language"],
               judge=scoring["judge_model_id"])))
