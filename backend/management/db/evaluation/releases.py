# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Atomic publication of verified business agent snapshots."""

from sqlalchemy import func, insert, select, text
from sqlalchemy.exc import IntegrityError

from contracts.agentos import ScopedSkillStepTrial
from contracts.errors.codes import ErrorCode
from contracts.errors.exceptions import AppException
from contracts.evolution_sources import task_digest
from contracts.releases import supports_release
from contracts.roles import has_any_role
from infrastructure.rdb.agent_execution import request_version_stop
from infrastructure.rdb.client import get_db_session
from infrastructure.rdb.skill_candidate_records import read_scoped_skill_candidate
from infrastructure.rdb.skill_execution_records import SkillInfo, effective_skill_description, release_skill
from infrastructure.skill_execution import skill_execution_revision
from management.db.agent.release_tools import publish_tool_selection
from infrastructure.rdb.released_skill_guides import publish_guides
from management.db.agent.session_versions import lock_release_scope
from management.db.evaluation.confirmation import _membership
from management.db.models import AgentInfo, AgentRelation, AgentVersion, SkillInstance, ToolInstance


def reject(message):
    raise AppException(ErrorCode.COMMON_VALIDATION_ERROR, message)


def set_publisher(tenant, agent, actor, grant):
    with get_db_session() as session:
        if not has_any_role(_membership(session, tenant, actor), {"ADMIN", "SU"}):
            raise AppException(ErrorCode.COMMON_FORBIDDEN)
        if grant.enabled and not _membership(session, tenant, grant.user_id):
            raise AppException(ErrorCode.COMMON_FORBIDDEN)
        session.execute(
            text("""
            INSERT INTO nexent.evolution_publisher_t (tenant_id,agent_id,user_id,enabled,updated_by)
            VALUES (:tenant,:agent,:user,:enabled,:actor)
            ON CONFLICT (tenant_id,agent_id,user_id) DO UPDATE SET enabled=excluded.enabled,updated_by=excluded.updated_by
        """),
            dict(tenant=tenant, agent=agent, user=grant.user_id, enabled=grant.enabled, actor=actor),
        )


def _require(session, tenant, agent, user):
    if not _membership(session, tenant, user) or not session.scalar(
        text("""
        SELECT enabled FROM nexent.evolution_publisher_t WHERE tenant_id=:t AND agent_id=:a AND user_id=:u FOR SHARE
    """),
        dict(t=tenant, a=agent, u=user),
    ):
        raise AppException(ErrorCode.COMMON_FORBIDDEN)


def _receipt(session, tenant, lock):
    row = (
        session.execute(
            text("""
        SELECT lock_id,agent_id,base_version,new_version,candidate_digest,rollback_at,disabled
          FROM nexent.evolution_release_t WHERE tenant_id=:t AND lock_id=:id
    """),
            dict(t=tenant, id=lock),
        )
        .mappings()
        .one_or_none()
    )
    return dict(row) if row else None


def _event(session, lock, action, actor, reason):
    session.execute(
        text("""INSERT INTO nexent.evolution_release_event_t
        (lock_id,action,actor,reason) VALUES (:lock,:action,:actor,:reason)
        ON CONFLICT (lock_id, action) DO NOTHING"""),
        dict(lock=lock, action=action, actor=actor, reason=reason),
    )


def _context(session, tenant, actor, lock):
    row = (
        session.execute(
            text("""
        SELECT e.agent_id,e.version_no,e.experiment_id,e.plan,e.cancelled,c.submitted_by,c.recipe,c.digest,
               l.digest AS lock_digest,l.policy,l.suite_id,s.digest AS suite_digest,r.decision
          FROM nexent.evolution_confirmation_lock_t l JOIN nexent.evolution_experiment_t e USING (experiment_id)
          JOIN nexent.evolution_confirmation_candidate_t c USING (experiment_id)
          JOIN nexent.evolution_confirmation_suite_t s USING (suite_id)
          LEFT JOIN nexent.evolution_confirmation_result_t r ON r.lock_id=l.lock_id AND r.lock_digest=l.digest
         WHERE e.tenant_id=:t AND l.lock_id=:id FOR SHARE OF e,c,l
    """),
            dict(t=tenant, id=lock),
        )
        .mappings()
        .one_or_none()
    )
    if not row:
        raise AppException(ErrorCode.COMMON_RESOURCE_NOT_FOUND)
    _require(session, tenant, row["agent_id"], actor)
    locked = task_digest(
        [tenant, row["suite_id"], row["suite_digest"], row["experiment_id"], row["digest"], row["policy"]]
    )
    if (
        row["decision"] != "passed"
        or row["cancelled"]
        or locked != row["lock_digest"]
        or task_digest(row["recipe"]) != row["digest"]
        or row["recipe"]["plan_digest"] != task_digest(row["plan"])
    ):
        reject("An active, independently passed comparison is required")
    return dict(row)


_SNAPSHOT_TABLES = (AgentInfo, ToolInstance, AgentRelation, SkillInstance)


def _rows(session, tenant, agent, version):
    snapshots = {}
    for model in _SNAPSHOT_TABLES:
        table = model.__table__
        root = table.c.parent_agent_id if model is AgentRelation else table.c.agent_id
        query = select(table).where(
            table.c.tenant_id == tenant,
            root == agent,
            table.c.version_no == version,
            table.c.delete_flag == "N",
        )
        snapshots[model] = [
            dict(r)
            for r in session.execute(
                query.order_by(*table.primary_key.columns).with_for_update(read=True)
            ).mappings()
        ]
    if len(snapshots[AgentInfo]) != 1:
        reject("Released base snapshot is unavailable")
    return snapshots


def _stamp(snapshots):
    # SQL timestamp objects take the same ISO representation in both reads.
    import json

    return task_digest(json.dumps([snapshots[m] for m in _SNAPSHOT_TABLES], default=str, sort_keys=True))


def prepare(tenant, actor, lock):
    with get_db_session() as session:
        source = _context(session, tenant, actor, lock)
        existing = _receipt(session, tenant, lock)
        rows = _rows(session, tenant, source["agent_id"], source["version_no"]) if not existing else None
        return source, existing, _stamp(rows) if rows else None


def _draft(session, tenant, agent):
    lock_release_scope(session, tenant, agent, exclusive=True)
    draft = session.scalar(
        select(AgentInfo)
        .where(
            AgentInfo.tenant_id == tenant,
            AgentInfo.agent_id == agent,
            AgentInfo.version_no == 0,
            AgentInfo.delete_flag == "N",
        )
        .with_for_update()
    )
    if not draft or draft.agent_origin == "SYSTEM":
        reject("Business agent is unavailable")
    return draft


def _validate_skill_sources(session, tenant, records, pins):
    active = {row["skill_instance_id"]: row for row in records if row["enabled"]}
    if set(active) != {pin["row"]["instance_id"] for pin in pins}:
        reject("Enabled Skills changed while preparing the release")
    for pin in pins:
        expected = pin["row"]
        binding = active[expected["instance_id"]]
        skill = session.scalar(
            select(SkillInfo)
            .where(
                SkillInfo.tenant_id == tenant,
                SkillInfo.skill_id == pin["skill_id"],
                SkillInfo.delete_flag == "N",
            )
            .with_for_update(read=True)
        )
        if (
            not skill
            or binding["skill_id"] != skill.skill_id
            or expected["name"] != skill.skill_name
            or expected["description"] != effective_skill_description(binding.get("released_catalog_entry"), skill.skill_description)
            or expected["config"] != {**(skill.config_values or {}), **(binding["config_values"] or {})}
        ):
            reject("Authorized Skill metadata changed while preparing the release")


def _pin(session, tenant, agent, version, pin, variant):
    digest, files = pin[variant]
    row = pin["row"]
    if "result_description" in pin:
        if variant == "result":
            row = {**row, "description": pin["result_description"]}
        session.execute(
            SkillInstance.__table__.update().where(
                SkillInstance.tenant_id == tenant, SkillInstance.agent_id == agent,
                SkillInstance.version_no == version, SkillInstance.skill_instance_id == row["instance_id"],
            ).values(released_catalog_entry={"description": row["description"]})
        )
    if variant == "result" and pin.get("result_image"):
        row = {**row, "script_image": pin["result_image"]}
    values = dict(
        sandbox_image=row.get("script_image"),
        tenant_id=tenant,
        agent_id=agent,
        version_no=version,
        instance_id=pin["row"]["instance_id"],
        skill_id=pin["skill_id"],
        digest=digest,
        revision=skill_execution_revision(tenant, agent, version, row, files),
    )
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    session.execute(pg_insert(release_skill).values(**values).on_conflict_do_nothing())
    original = (
        session.execute(
            select(release_skill).where(
                *[
                    release_skill.c[k] == values[k]
                    for k in ("tenant_id", "agent_id", "version_no", "instance_id")
                ]
            )
        )
        .mappings()
        .one()
    )
    if dict(original) != values:
        reject("The stable version already has a different Skill package")


def _confirmed_new_guide(session, tenant, agent, base, ctx, expected):
    recipe = ctx["recipe"]
    if recipe["candidate_type"] != "skill_new":
        return None
    from permissions.rbac import has_permission

    row = (
        session.execute(
            text("""
        SELECT candidate_id, name, digest, created_by FROM nexent.evolution_new_skill_candidate_t
        WHERE tenant_id=:tenant AND agent_id=:agent AND version_no=:base AND candidate_id=:cid FOR SHARE
    """),
            dict(tenant=tenant, agent=agent, base=base, cid=recipe["candidate_id"]),
        )
        .mappings()
        .one_or_none()
    )
    if not row or expected != {key: row[key] for key in ("candidate_id", "name", "digest")}:
        reject("The confirmed new Skill is no longer available")
    if not has_permission(_membership(session, tenant, row["created_by"]), "skill:create"):
        raise AppException(ErrorCode.COMMON_FORBIDDEN)
    if session.scalar(
        select(SkillInfo.skill_id)
        .where(
            SkillInfo.tenant_id == tenant, SkillInfo.skill_name == row["name"], SkillInfo.delete_flag == "N"
        )
        .limit(1)
    ):
        reject("The new Skill name is already used by a tenant Skill")
    return {key: row[key] for key in ("candidate_id", "name", "digest")}


def publish(
    tenant, actor, lock, reason, expected, digest, stamp, pins, prompt, baseline, removed, expected_guide=None, mapping=None, tool_build=None
):
    try:
        with get_db_session() as session:
            ctx = _context(session, tenant, actor, lock)
            agent, base = ctx["agent_id"], ctx["version_no"]
            draft = _draft(session, tenant, agent)
            existing = _receipt(session, tenant, lock)
            if existing:
                return existing
            if draft.current_version_no != base or expected != base or ctx["digest"] != digest:
                reject("The default version or verified candidate changed")
            if session.scalar(
                text("""SELECT paused FROM nexent.evolution_release_scope_t
                    WHERE tenant_id=:t AND agent_id=:a"""),
                dict(t=tenant, a=agent),
            ):
                reject("Restore a verified default before publishing another version")
            rows = _rows(session, tenant, agent, base)
            if _stamp(rows) != stamp:
                reject("The published source changed while preparing the release")
            _validate_skill_sources(session, tenant, rows[SkillInstance], pins)
            version = (
                max(
                    session.scalar(
                        select(func.max(model.version_no)).where(
                            model.tenant_id == tenant, model.agent_id == agent
                        )
                    )
                    or 0
                    for model in (AgentInfo, AgentVersion)
                )
                + 1
            )
            if mapping:
                bindings = [r for r in rows[ToolInstance] if r["tool_instance_id"] == mapping["instance_id"] and r["enabled"]]
                if len(bindings) != 1 or (bindings[0]["released_argument_formats"] or {}) != mapping["previous"]:
                    reject("The source MCP tool mapping changed during publication")
            if tool_build:
                bindings = [r for r in rows[ToolInstance] if r["tool_instance_id"] == tool_build["instance_id"] and r["enabled"]]
                if len(bindings) != 1 or bindings[0]["released_mcp_implementation"] not in (None, tool_build["base"]):
                    reject("The source MCP implementation changed during publication")
                session.execute(
                    ToolInstance.__table__.update().where(
                        ToolInstance.tenant_id == tenant, ToolInstance.agent_id == agent,
                        ToolInstance.version_no == base, ToolInstance.tool_instance_id == tool_build["instance_id"],
                    ).values(released_mcp_implementation=tool_build["base"])
                )
            for model, records in rows.items():
                for row in records:
                    data = {k: v for k, v in row.items() if k not in {"create_time", "update_time"}}
                    data.update(version_no=version, updated_by=actor)
                    if model is ToolInstance and tool_build and row["tool_instance_id"] == tool_build["instance_id"]:
                        data["released_mcp_implementation"] = tool_build["result"]
                    if model is ToolInstance and mapping and row["tool_instance_id"] == mapping["instance_id"]:
                        data["released_argument_formats"] = mapping["proposed"]
                    if model is AgentInfo:
                        data["current_version_no"] = None
                        if prompt is not None:
                            data["prompt"] = prompt
                    session.execute(insert(model.__table__).values(**data))
            for pin in pins:
                _pin(session, tenant, agent, base, pin, "base")
                _pin(session, tenant, agent, version, pin, "result")
            added_guide = _confirmed_new_guide(session, tenant, agent, base, ctx, expected_guide)
            revisions = []
            if isinstance(expected_guide, list):
                recipe = ctx["recipe"]
                steps = {part["candidate_id"] for part in (recipe.get("components") or [recipe])
                         if part["candidate_type"] == "skill_step"}
                for trial in expected_guide:
                    if trial["candidate_id"] not in steps:
                        reject("The scoped Skill was not part of the confirmed comparison")
                    row = read_scoped_skill_candidate(tenant, agent, base, trial["candidate_id"], session=session)
                    if not row or ScopedSkillStepTrial.from_binding(row, "result").model_dump() != trial:
                        reject("The scoped Skill has changed since confirmation")
                    revisions.append((trial["source"], trial["result_digest"]))
            publish_guides(session, tenant, agent, base, version, added_guide, revised=revisions)
            publish_tool_selection(session, tenant, agent, base, version, removed)
            session.add(
                AgentVersion(
                    tenant_id=tenant,
                    agent_id=agent,
                    version_no=version,
                    version_name=f"Evolution V{version}",
                    release_note=reason,
                    source_type="EVOLUTION",
                    source_version_no=base,
                    status="RELEASED",
                    created_by=actor,
                    updated_by=actor,
                    delete_flag="N",
                )
            )
            session.execute(
                text("""INSERT INTO nexent.evolution_release_scope_t(tenant_id,agent_id,initial_version)
                VALUES (:t,:a,:base) ON CONFLICT DO NOTHING"""),
                dict(t=tenant, a=agent, base=base),
            )
            session.execute(
                text("""INSERT INTO nexent.evolution_release_t
                (lock_id,tenant_id,agent_id,base_version,new_version,candidate_digest,published_by,reason,baseline_digest)
                VALUES (:id,:t,:a,:base,:new,:digest,:actor,:reason,:baseline)"""),
                dict(
                    id=lock,
                    t=tenant,
                    a=agent,
                    base=base,
                    new=version,
                    digest=digest,
                    actor=actor,
                    reason=reason,
                    baseline=baseline,
                ),
            )
            _event(session, lock, "publish", actor, reason)
            draft.current_version_no = version
            return _receipt(session, tenant, lock)
    except IntegrityError as exc:
        raise AppException(
            ErrorCode.COMMON_VALIDATION_ERROR, "Concurrent release changed the version. Refresh the agent."
        ) from exc


def rollback_target(tenant, actor, lock):
    with get_db_session() as session:
        row = (
            session.execute(
                text("""SELECT r.*,c.recipe->>'language' AS language FROM nexent.evolution_release_t r
            JOIN nexent.evolution_confirmation_lock_t l USING (lock_id)
            JOIN nexent.evolution_confirmation_candidate_t c USING (experiment_id)
            WHERE r.tenant_id=:t AND r.lock_id=:id"""),
                dict(t=tenant, id=lock),
            )
            .mappings()
            .one_or_none()
        )
        if not row:
            raise AppException(ErrorCode.COMMON_RESOURCE_NOT_FOUND)
        _require(session, tenant, row["agent_id"], actor)
        return dict(row)


def release_view(tenant, actor, lock):
    with get_db_session() as session:
        row = (
            session.execute(
                text("""
            SELECT e.agent_id,e.version_no AS base_version,e.experiment_id,c.digest AS candidate_digest,
                   c.recipe->'components' AS components,
                   e.plan->'tool_mapping' AS tool_mapping,
                   e.plan->'tool_build' AS tool_build,
                   CASE WHEN e.plan ? 'script_build' THEN jsonb_build_object(
                       'name',e.plan->'script_build'->>'name','path',e.plan->'script_build'->>'path',
                       'function',e.plan->'script_build'->>'function','image',e.plan->'script_build'->>'image')
                   END AS script_build,
                   c.recipe->>'candidate_type' AS candidate_type,(c.recipe->>'candidate_id')::bigint AS resource_candidate_id,
                   a.current_version_no AS current_version,
                   r.summary,COALESCE(s.paused,false) AS paused,
                   ARRAY(SELECT jsonb_array_elements_text(CAST(tools.source_text AS jsonb)->'selectable')
                         EXCEPT SELECT jsonb_array_elements_text(CAST(tools.result_text AS jsonb)->'retained')
                         ORDER BY 1) AS excluded_tools
              FROM nexent.evolution_confirmation_lock_t l
              JOIN nexent.evolution_experiment_t e USING(experiment_id)
              JOIN nexent.evolution_confirmation_candidate_t c USING(experiment_id)
              JOIN nexent.ag_tenant_agent_t a ON a.tenant_id=e.tenant_id AND a.agent_id=e.agent_id AND a.version_no=0
              LEFT JOIN nexent.evolution_candidate_t tools
                ON tools.resource_field='agent.tools'
               AND tools.tenant_id=e.tenant_id AND tools.agent_id=e.agent_id AND tools.base_version_no=e.version_no
               AND tools.candidate_id=CASE c.recipe->>'candidate_type'
                   WHEN 'tool_set' THEN CAST(c.recipe->>'candidate_id' AS bigint)
                   WHEN 'combination' THEN (
                       SELECT CAST(part->>'candidate_id' AS bigint)
                       FROM jsonb_array_elements(c.recipe->'components') part
                       WHERE part->>'candidate_type'='tool_set'
                   ) END
              LEFT JOIN nexent.evolution_confirmation_result_t r ON r.lock_id=l.lock_id AND r.lock_digest=l.digest
              LEFT JOIN nexent.evolution_release_scope_t s ON s.tenant_id=e.tenant_id AND s.agent_id=e.agent_id
             WHERE e.tenant_id=:t AND l.lock_id=:id AND (NOT e.cancelled OR EXISTS (
                 SELECT 1 FROM nexent.evolution_release_t ledger WHERE ledger.lock_id=l.lock_id))
        """),
                dict(t=tenant, id=lock),
            )
            .mappings()
            .one_or_none()
        )
        if not row:
            raise AppException(ErrorCode.COMMON_RESOURCE_NOT_FOUND)
        _require(session, tenant, row["agent_id"], actor)
        data = dict(row)
        cid = data.pop("resource_candidate_id")
        receipt = _receipt(session, tenant, lock)
        if data["candidate_type"] == "skill_discovery":
            description = session.execute(text("""
                SELECT skill_name AS name, feedback->'edit'->>'old' AS previous, feedback->'edit'->>'new' AS proposed
                FROM nexent.evolution_skill_candidate_t
                WHERE tenant_id=:tenant AND candidate_id=:cid AND feedback->>'method'='S1'
            """), {"tenant": tenant, "cid": cid}).mappings().one_or_none()
            data["skill_description"] = dict(description) if description else None
        if data["candidate_type"] == "skill_new":
            if receipt:
                from infrastructure.rdb.released_skill_guides import guides_for_version
                choices = guides_for_version(session,tenant,row["agent_id"],receipt["new_version"])
                data["added_guide"] = next((g for g in choices if g["candidate_id"] == cid), None)
            else:
                name = session.execute(text("""
                    SELECT candidate_id, name, digest FROM nexent.evolution_new_skill_candidate_t
                    WHERE tenant_id=:t AND agent_id=:a AND version_no=:v AND candidate_id=:c
                """), dict(t=tenant,a=row["agent_id"],v=row["base_version"],c=cid)).mappings().one_or_none()
                data["added_guide"] = dict(name) if name else None
        return {**data, "release": receipt, "supported_type": supports_release(data["candidate_type"], data["components"])}


def restore(tenant, actor, lock, request, ready):
    with get_db_session() as session:
        record = _receipt(session, tenant, lock)
        if not record:
            raise AppException(ErrorCode.COMMON_RESOURCE_NOT_FOUND)
        agent = record["agent_id"]
        _require(session, tenant, agent, actor)
        draft = _draft(session, tenant, agent)
        record = _receipt(session, tenant, lock)
        if request.expected_version != record["new_version"]:
            reject("Release version changed")
        params = dict(
            t=tenant, a=agent, id=lock, user=actor, reason=request.reason, base=record["base_version"]
        )
        is_default = draft.current_version_no == record["new_version"]
        if not request.emergency and not record["rollback_at"] and not is_default:
            reject("Another release is already active")
        if request.emergency and not record["disabled"]:
            session.execute(
                text("""UPDATE nexent.evolution_release_t SET disabled=true,stop_reason=:reason,
                stopped_by=:user,stopped_at=now() WHERE lock_id=:id"""),
                params,
            )
            _event(session, lock, "stop", actor, request.reason)
        if request.emergency:
            request_version_stop(session, tenant, agent, record["new_version"], actor)
        if not record["rollback_at"] and is_default:
            stopped_base = session.scalar(
                text("""SELECT disabled FROM nexent.evolution_release_t
                WHERE tenant_id=:t AND agent_id=:a AND new_version=:base"""),
                params,
            )
            paused = not ready or bool(stopped_base)
            session.execute(
                text("""UPDATE nexent.evolution_release_scope_t SET paused=:paused
                WHERE tenant_id=:t AND agent_id=:a"""),
                {**params, "paused": paused},
            )
            if paused:
                _event(session, lock, "pause", actor, request.reason)
                return {**_receipt(session, tenant, lock), "new_sessions_paused": True}
            _event(session, lock, "rollback", actor, request.reason)
            draft.current_version_no = record["base_version"]
            session.execute(
                text("""UPDATE nexent.evolution_release_t SET rollback_at=now(),rollback_reason=:reason,
                rollback_by=:user WHERE lock_id=:id"""),
                params,
            )
        paused = session.scalar(
            text("""SELECT paused FROM nexent.evolution_release_scope_t
            WHERE tenant_id=:t AND agent_id=:a"""),
            params,
        )
        return {**_receipt(session, tenant, lock), "new_sessions_paused": bool(paused)}
