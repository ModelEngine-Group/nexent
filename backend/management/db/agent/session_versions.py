# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Select a business chat version before compilation and confirm it at admission."""

from sqlalchemy import text

from contracts.errors.exceptions import ForbiddenError
from infrastructure.rdb.client import get_db_session


class ReleaseVersionConflict(ValueError):
    """The selected version changed before the prepared turn was admitted."""


def lock_release_scope(session, tenant, agent, *, exclusive):
    # A first publication has no scope row yet. Publishing and staging still share a lock.
    function = "pg_advisory_xact_lock" if exclusive else "pg_advisory_xact_lock_shared"
    session.execute(
        text(f"SELECT {function}(hashtextextended(:key,0))"),
        {"key": f"nexent.evolution.release/{tenant}/{agent}"},
    )


def _select(session, params, requested):
    scope = (
        session.execute(
            text("""
        SELECT s.initial_version, s.paused, a.current_version_no,b.created_by AS owner,b.version_no AS bound_version
          FROM nexent.evolution_release_scope_t s
          LEFT JOIN nexent.evolution_session_version_t b ON (b.tenant_id,b.agent_id)=(s.tenant_id,s.agent_id)
               AND b.conversation_id=:cid
          LEFT JOIN nexent.ag_tenant_agent_t a ON a.tenant_id=s.tenant_id AND a.agent_id=s.agent_id
               AND a.version_no=0 AND a.delete_flag='N'
         WHERE s.tenant_id=:tenant AND s.agent_id=:agent
    """),
            params,
        )
        .mappings()
        .one_or_none()
    )
    if scope is None:
        return None, False
    if scope["bound_version"] is not None:
        if scope["owner"] != params["owner"]:
            raise ForbiddenError("Conversation version is outside the current identity")
        return _enabled_version(session,params,scope["bound_version"]), False
    # Existing chats can predate this feature. Only read root identifiers from a trusted run.
    history = (
        session.execute(
            text("""
        SELECT CASE WHEN e.resource_versions ? 'model_revision' THEN e.resource_versions->'agent_version_no'
               END AS receipt_version, t.agent_version_no AS trace_version
          FROM nexent.agent_execution_t e
          LEFT JOIN nexent.trajectory_execution_t t ON t.agentos_run_id=e.run_id
           AND t.conversation_id=e.conversation_id AND t.created_by=e.created_by AND t.delete_flag='N'
           AND t.agent_id=:agent
         WHERE e.tenant_id=:tenant AND e.conversation_id=:cid AND e.created_by=:owner
           AND e.delete_flag='N' AND (
             (e.resource_versions->'agent_id'=to_jsonb(CAST(:agent AS integer))
               AND (e.resource_versions ? 'model_revision' OR t.agent_id IS NOT NULL)) OR
             (NOT (e.resource_versions ? 'agent_id') AND t.agent_id IS NOT NULL))
         ORDER BY e.create_time DESC NULLS LAST,t.turn_no DESC NULLS LAST,e.run_id DESC LIMIT 1
    """),
            params,
        )
        .mappings()
        .one_or_none()
    )
    if history:
        recorded = (
            history["receipt_version"] if history["receipt_version"] is not None else history["trace_version"]
        )
        if type(recorded) is int and recorded > 0:
            return _enabled_version(session,params,recorded), True
    legacy = session.scalar(
        text("""
        SELECT EXISTS (SELECT 1 FROM nexent.conversation_message_t m
          JOIN nexent.conversation_record_t c ON c.conversation_id=m.conversation_id AND c.created_by=m.created_by
            AND c.agent_id=:agent AND c.delete_flag='N'
          JOIN nexent.evolution_release_scope_t s ON s.tenant_id=:tenant AND s.agent_id=:agent
         WHERE m.conversation_id=:cid AND m.created_by=:owner AND m.delete_flag='N'
           AND m.create_time < s.enabled_at)
    """),
        params,
    )
    if legacy:
        # An old page can explicitly select an old version. Do not silently migrate a chat
        # whose last running version could not be reconstructed.
        return _enabled_version(session,params,requested or scope["initial_version"]), False
    current = scope["current_version_no"]
    if scope["paused"] or not current or current <= 0:
        raise ReleaseVersionConflict("No active published version for this business agent")
    return _enabled_version(session,params,current), True


def _enabled_version(session,params,version):
    if session.scalar(text("""SELECT disabled FROM nexent.evolution_release_t
        WHERE tenant_id=:tenant AND agent_id=:agent AND new_version=:v"""),{**params,"v":version}):
        raise ReleaseVersionConflict("This business agent version has been stopped")
    if session.scalar(text("""SELECT EXISTS (
        SELECT 1 FROM nexent.evolution_release_skill_t p
        LEFT JOIN nexent.ag_skill_instance_t i ON i.tenant_id=p.tenant_id AND i.agent_id=p.agent_id
          AND i.version_no=p.version_no AND i.skill_instance_id=p.instance_id AND i.skill_id=p.skill_id
          AND i.delete_flag='N' AND i.enabled
        LEFT JOIN nexent.ag_skill_info_t s ON s.tenant_id=p.tenant_id AND s.skill_id=p.skill_id AND s.delete_flag='N'
        WHERE p.tenant_id=:tenant AND p.agent_id=:agent AND p.version_no=:v
          AND (i.skill_instance_id IS NULL OR s.skill_id IS NULL))"""),{**params,"v":version}):
        raise ReleaseVersionConflict("A published Skill is no longer authorized for this agent version")
    return version


def select_chat_version(tenant, agent, cid, owner, requested):
    with get_db_session() as session:
        selected, _ = _select(session, dict(tenant=tenant, agent=agent, cid=cid, owner=owner), requested)
        return selected


def confirm_chat_version(session, tenant, agent, cid, owner, requested, compiled):
    params = dict(tenant=tenant, agent=agent, cid=cid, owner=owner)
    lock_release_scope(session, tenant, agent, exclusive=False)
    selected, persist = _select(session, params, requested)
    if selected is None:
        return False
    if compiled != selected:
        raise ReleaseVersionConflict("Business agent version changed. Retry the turn.")
    if persist:
        inserted = session.scalar(
            text("""
            INSERT INTO nexent.evolution_session_version_t
                (tenant_id,agent_id,conversation_id,version_no,created_by)
            VALUES (:tenant,:agent,:cid,:version,:owner) ON CONFLICT DO NOTHING RETURNING version_no
        """),
            {**params, "version": compiled},
        )
        if inserted is not None:
            return True
        actual = session.scalar(
            text("""
            SELECT version_no FROM nexent.evolution_session_version_t
             WHERE tenant_id=:tenant AND agent_id=:agent AND conversation_id=:cid AND created_by=:owner
        """),
            params,
        )
        if actual != compiled:
            raise ReleaseVersionConflict("Another first turn selected a different version")
    return False


def discard_unstarted_binding(session, tenant, owner, cid, run, agent, version):
    # The caller holds the conversation/admission locks and only removes the binding
    # its own rejected staging transaction created. A Runtime receipt proves execution started.
    session.execute(
        text("""
        DELETE FROM nexent.evolution_session_version_t
         WHERE tenant_id=:tenant AND created_by=:owner AND conversation_id=:cid
           AND agent_id=:agent AND version_no=:version
           AND NOT EXISTS (SELECT 1 FROM nexent.agent_execution_t e WHERE e.run_id=:run
             AND e.tenant_id=:tenant AND e.created_by=:owner AND e.conversation_id=:cid
             AND e.resource_versions->'agent_id'=to_jsonb(CAST(:agent AS integer))
             AND e.resource_versions->'agent_version_no'=to_jsonb(CAST(:version AS integer)))
    """),
        dict(tenant=tenant, owner=owner, cid=cid, run=run, agent=agent, version=version),
    )
