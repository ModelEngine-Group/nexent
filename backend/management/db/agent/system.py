# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Transaction primitives for platform-owned Agent releases."""

from sqlalchemy import delete, func, insert, select, text, update

from contracts.constants.constants import ASSET_OWNER_TENANT_ID
from management.db.agent.models import AgentInfo, AgentRelation, AgentVersion
from management.db.skill.models import SkillInstance
from management.db.tool.models import ToolInstance


def lock_system_agent_release(session, system_key: str) -> None:
    """Serialize all releases of one system identity across server processes."""
    session.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:lock_key))"),
        {"lock_key": f"system-agent-release:{system_key}"},
    )


def load_system_agent(session, system_key: str, version_no: int = 0) -> dict | None:
    row = (
        session.execute(
            select(AgentInfo.__table__).where(
                AgentInfo.tenant_id == ASSET_OWNER_TENANT_ID,
                AgentInfo.agent_origin == "SYSTEM",
                AgentInfo.system_key == system_key,
                AgentInfo.version_no == version_no,
                AgentInfo.delete_flag == "N",
            )
        )
        .mappings()
        .one_or_none()
    )
    return dict(row) if row is not None else None


def write_system_agent_release(
    session,
    *,
    existing: dict,
    system_key: str,
    revision: str,
    fields: dict,
    version_no: int,
) -> dict:
    """Write a draft, immutable snapshot, version and pointer in the caller's transaction."""
    values = {
        **fields,
        "tenant_id": ASSET_OWNER_TENANT_ID,
        "agent_origin": "SYSTEM",
        "system_key": system_key,
        "system_revision": revision,
        "model_ids": [],
        "group_ids": "",
        "ingroup_permission": "PRIVATE",
        "is_new": False,
        "updated_by": "system",
        "delete_flag": "N",
    }
    agent_id = int(existing["agent_id"])
    session.execute(
        update(AgentInfo)
        .where(
            AgentInfo.agent_id == agent_id,
            AgentInfo.tenant_id == ASSET_OWNER_TENANT_ID,
            AgentInfo.version_no == 0,
            AgentInfo.delete_flag == "N",
        )
        .values(**values, current_version_no=version_no)
    )
    session.execute(
        insert(AgentInfo).values(
            **values,
            agent_id=agent_id,
            version_no=version_no,
            created_by="system",
        )
    )
    session.execute(
        insert(AgentVersion).values(
            tenant_id=ASSET_OWNER_TENANT_ID,
            agent_id=agent_id,
            version_no=version_no,
            version_name=revision,
            release_note=f"System release {revision}",
            source_type="NORMAL",
            status="RELEASED",
            created_by="system",
            updated_by="system",
            delete_flag="N",
        )
    )
    for model in (ToolInstance, SkillInstance, AgentRelation):
        agent_column = model.parent_agent_id if model is AgentRelation else model.agent_id
        for row in session.execute(select(model.__table__).where(
            agent_column == agent_id, model.tenant_id == ASSET_OWNER_TENANT_ID,
            model.version_no == 0, model.delete_flag == "N",
        )).mappings().all():
            session.execute(insert(model).values(**{**row, "version_no": version_no}))
    return {**values, "agent_id": agent_id, "version_no": version_no}


def replace_workbench_draft_bindings(session, agent_id, tools, skills):
    for model in (ToolInstance, SkillInstance):
        session.execute(delete(model).where(model.agent_id == agent_id, model.version_no == 0))
    for tool in tools:
        params = {item["name"]: item.get("default") for item in tool.get("params") or []}
        session.execute(insert(ToolInstance).values(
            agent_id=agent_id, tool_id=tool["tool_id"], tenant_id=ASSET_OWNER_TENANT_ID,
            version_no=0, params=params, enabled=True, user_id="system", created_by="system", updated_by="system",
        ))
    for skill in skills:
        session.execute(insert(SkillInstance).values(
            agent_id=agent_id, skill_id=skill["skill_id"], tenant_id=ASSET_OWNER_TENANT_ID,
            version_no=0, enabled=True, config_values={}, user_id="system", created_by="system", updated_by="system",
        ))


def latest_workbench_release(session, agent_id, revision):
    return session.execute(select(AgentInfo.__table__).where(
        AgentInfo.agent_id == agent_id, AgentInfo.version_no > 0,
        AgentInfo.system_revision == revision, AgentInfo.delete_flag == "N",
    ).order_by(AgentInfo.version_no.desc()).limit(1)).mappings().one_or_none()


def create_workbench_draft(session, fields):
    return session.execute(insert(AgentInfo).values(
        **fields, tenant_id=ASSET_OWNER_TENANT_ID, agent_origin="SYSTEM", system_key="workbench_main",
        version_no=0, created_by="system", updated_by="system", delete_flag="N", model_ids=[], is_new=False,
    ).returning(AgentInfo.agent_id)).scalar_one()


def next_workbench_version(session, agent_id):
    maximum = session.execute(select(func.max(AgentInfo.version_no)).where(AgentInfo.agent_id == agent_id)).scalar_one()
    return int(maximum or 0) + 1


def select_workbench_snapshot(session, version_no):
    draft = load_system_agent(session, "workbench_main")
    snapshot = load_system_agent(session, "workbench_main", version_no)
    if version_no < 1 or not draft or not snapshot or not snapshot.get("enabled"):
        raise ValueError("Workbench version is unavailable")
    metadata = session.execute(select(AgentVersion.status).where(
        AgentVersion.agent_id == draft["agent_id"], AgentVersion.version_no == version_no,
        AgentVersion.tenant_id == ASSET_OWNER_TENANT_ID, AgentVersion.delete_flag == "N",
    )).scalar_one_or_none()
    if metadata != "RELEASED":
        raise ValueError("Workbench version is not released")
    session.execute(update(AgentInfo).where(AgentInfo.agent_id == draft["agent_id"], AgentInfo.version_no == 0).values(
        current_version_no=version_no, updated_by="system",
    ))


def has_legacy_workbench_agents(session):
    """Reject fresh initialization against an upgrade that has not applied the SQL migration."""
    return session.execute(select(AgentInfo.agent_id).where(
        AgentInfo.agent_origin == "SYSTEM",
        AgentInfo.system_key == "workbench_main",
        AgentInfo.tenant_id.is_distinct_from(ASSET_OWNER_TENANT_ID),
    ).limit(1)).scalar_one_or_none() is not None
