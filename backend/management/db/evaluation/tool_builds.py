# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import json

from sqlalchemy import text

from infrastructure.rdb.client import get_db_session


def store_build(tenant, user, fid, digest, manifest):
    args = dict(t=tenant, u=user, fid=fid, digest=digest, manifest=json.dumps(manifest, ensure_ascii=False))
    with get_db_session() as db:
        bid = db.scalar(
            text("""
            INSERT INTO nexent.evolution_tool_build_t(tenant_id,created_by,feedback_id,digest,manifest)
            VALUES (:t,:u,:fid,:digest,CAST(:manifest AS jsonb))
            ON CONFLICT DO NOTHING RETURNING build_id"""),
            args,
        )
        if bid is None:
            bid = db.execute(
                text("""SELECT build_id FROM nexent.evolution_tool_build_t
                WHERE tenant_id=:t AND created_by=:u AND feedback_id=:fid AND digest=:digest"""),
                args,
            ).scalar_one()
    return bid


def build_record(tenant, bid):
    with get_db_session() as db:
        row = (
            db.execute(
                text("""SELECT build_id,feedback_id,digest,manifest,created_by
            FROM nexent.evolution_tool_build_t WHERE tenant_id=:t AND build_id=:b"""),
                {"t": tenant, "b": bid},
            )
            .mappings()
            .one_or_none()
        )
        return dict(row) if row else None


def build_ids(tenant, fid):
    with get_db_session() as db:
        return list(
            db.scalars(
                text("""SELECT build_id FROM nexent.evolution_tool_build_t
            WHERE tenant_id=:t AND feedback_id=:fid ORDER BY build_id DESC"""),
                {"t": tenant, "fid": fid},
            )
        )


def store_guard(tenant, bid, user, req, agent, version, data):
    with get_db_session() as db:
        db.execute(
            text("""INSERT INTO nexent.evolution_tool_build_guard_t
            (build_id,experiment_id,case_id,tool_name,agent_id,version_no,approved_by,data)
            SELECT build_id,:eid,:cid,:name,:agent,:version,:actor,CAST(:data AS jsonb)
            FROM nexent.evolution_tool_build_t WHERE build_id=:b AND tenant_id=:t ON CONFLICT DO NOTHING"""),
            dict(
                t=tenant,
                b=bid,
                eid=req.experiment_id,
                cid=req.case_id,
                name=req.tool_name,
                agent=agent,
                version=version,
                actor=user,
                data=json.dumps(data, ensure_ascii=False),
            ),
        )


def guard_records(tenant, bid):
    with get_db_session() as db:
        return [
            dict(r)
            for r in db.execute(
                text("""SELECT g.* FROM nexent.evolution_tool_build_guard_t g
            JOIN nexent.evolution_tool_build_t b USING(build_id) WHERE b.tenant_id=:t AND b.build_id=:b
            ORDER BY agent_id,version_no,tool_name,experiment_id,case_id,approved_by"""),
                dict(t=tenant, b=bid),
            ).mappings()
        ]


def save_run(tenant, bid, digest, report):
    with get_db_session() as db:
        return db.execute(
            text("""INSERT INTO nexent.evolution_tool_build_run_t(build_id,plan_digest,report)
            SELECT build_id,:digest,CAST(:report AS jsonb) FROM nexent.evolution_tool_build_t
            WHERE tenant_id=:t AND build_id=:b RETURNING run_id"""),
            dict(t=tenant, b=bid, digest=digest, report=json.dumps(report)),
        ).scalar_one()


def latest_run(tenant, bid, digest):
    with get_db_session() as db:
        return db.scalar(
            text("""SELECT report FROM nexent.evolution_tool_build_run_t r
            JOIN nexent.evolution_tool_build_t b USING(build_id)
            WHERE b.tenant_id=:t AND b.build_id=:b AND plan_digest=:digest ORDER BY run_id DESC LIMIT 1"""),
            dict(t=tenant, b=bid, digest=digest),
        )


def published_callers(tenant, server_id):
    """Inventory current business roots, including their selected child versions and bound Skills."""
    with get_db_session() as db:
        rows = db.execute(
            text("""
            WITH RECURSIVE agents AS (
                SELECT agent_id,version_no,current_version_no FROM nexent.ag_tenant_agent_t
                WHERE tenant_id=:t AND delete_flag='N'
            ), reachable(root,root_version,agent,version) AS (
                SELECT a.agent_id,a.current_version_no,a.agent_id,a.current_version_no
                FROM agents a JOIN agents v ON v.agent_id=a.agent_id AND v.version_no=a.current_version_no
                WHERE a.version_no=0 AND a.current_version_no>0
                UNION
                SELECT n.root,n.root_version,r.selected_agent_id,child.version_no FROM reachable n
                JOIN nexent.ag_agent_relation_t r ON r.tenant_id=:t AND r.parent_agent_id=n.agent
                    AND r.version_no=n.version AND r.delete_flag='N'
                JOIN agents draft ON draft.agent_id=r.selected_agent_id AND draft.version_no=0
                JOIN agents child ON child.agent_id=r.selected_agent_id AND child.version_no>0
                    AND child.version_no=COALESCE(NULLIF(r.selected_agent_version_no,0),draft.current_version_no)
            ), tools AS (
                SELECT i.tool_id,i.name FROM nexent.ag_tool_info_t i
                JOIN nexent.mcp_record_t m ON m.mcp_name=i.usage AND m.tenant_id=:t AND m.mcp_id=:sid
                WHERE i.source='mcp' AND i.author=:t AND i.delete_flag='N' AND i.is_available IS NOT FALSE
                    AND m.delete_flag='N' AND m.enabled IS NOT FALSE
            ), exposed(agent,version,name) AS (
                SELECT i.agent_id,i.version_no,t.name FROM nexent.ag_tool_instance_t i
                JOIN tools t ON t.tool_id=i.tool_id WHERE i.tenant_id=:t AND i.enabled AND i.delete_flag='N'
                UNION
                SELECT i.agent_id,i.version_no,t.name FROM nexent.ag_skill_instance_t i
                JOIN nexent.ag_skill_info_t s ON s.skill_id=i.skill_id AND s.tenant_id=:t AND s.delete_flag='N'
                JOIN nexent.ag_skill_tools_rel_t r ON r.skill_id=s.skill_id
                JOIN tools t ON t.tool_id=r.tool_id WHERE i.tenant_id=:t AND i.enabled AND i.delete_flag='N'
            )
            SELECT DISTINCT root AS agent_id,root_version AS version_no,n.agent AS owner_agent,n.version AS owner_version,e.name
            FROM reachable n JOIN exposed e ON e.agent=n.agent AND e.version=n.version
            ORDER BY agent_id,version_no,owner_agent,owner_version,e.name"""),
            dict(t=tenant, sid=server_id),
        ).mappings()
        return [dict(r) for r in rows]


def source_approval(tenant, fid):
    with get_db_session() as db:
        return (
            db.execute(
                text("""SELECT experiment_id,created_by FROM nexent.evolution_feedback_handoff_t
            WHERE tenant_id=:t AND feedback_id=:f"""),
                {"t": tenant, "f": fid},
            )
            .mappings()
            .one()
        )
