# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Read tenant Skill and tool catalog records for verified Workbench mounts."""

from contextlib import nullcontext

from sqlalchemy import select

from infrastructure.agentos_identity import ServicePrincipal
from infrastructure.rdb.account_access import get_user_role_by_tenant, query_group_ids_by_user_in_tenant
from infrastructure.rdb.client import get_db_session
from infrastructure.rdb.conversation_state import tenant_membership_matches
from infrastructure.rdb.mcp_execution_records import ToolInfo, ToolInstance
from infrastructure.rdb.skill_execution_records import SkillInfo, SkillInstance, SkillToolRelation
from infrastructure.skill_execution import merge_skill_tool_parameters
from infrastructure.workbench_skill_execution import can_view_skill, resolve_skill_config


def read_workbench_skill_rows(
    agent_id: int, agent_version: int, actor: ServicePrincipal, mounts: dict[int, dict], ids: set[int],
) -> dict[int, dict]:
    """Recompute the root Skill configuration for the exact signed Workbench revision."""
    with get_db_session() as session:
        if not tenant_membership_matches(session, actor.user_id, actor.tenant_id):
            return {}
        published = {}
        for skill_id, values in session.execute(select(SkillInstance.skill_id, SkillInstance.config_values).where(
            SkillInstance.agent_id == agent_id, SkillInstance.version_no == agent_version,
            SkillInstance.tenant_id == actor.tenant_id, SkillInstance.enabled.is_(True), SkillInstance.delete_flag != "Y",
        )):
            if skill_id in published:
                return {}
            published[skill_id] = values or {}
        if (set(published) | mounts.keys()) != ids:
            return {}
        groups = set(query_group_ids_by_user_in_tenant(
            actor.user_id, actor.tenant_id, session_factory=lambda: nullcontext(session),
        ))
        role = get_user_role_by_tenant(actor.user_id, actor.tenant_id, session_factory=lambda: nullcontext(session))
        dependencies = {skill_id: [] for skill_id in ids}
        for skill_id, tool_id in session.execute(select(SkillToolRelation.skill_id, SkillToolRelation.tool_id).where(
            SkillToolRelation.skill_id.in_(ids), SkillToolRelation.delete_flag != "Y",
        )):
            dependencies[skill_id].append(tool_id)
        rows = {}
        for skill in session.scalars(select(SkillInfo).where(
            SkillInfo.skill_id.in_(ids), SkillInfo.tenant_id == actor.tenant_id, SkillInfo.delete_flag != "Y",
        )):
            if not can_view_skill(
                skill={"source": skill.source, "created_by": skill.created_by, "group_ids": skill.group_ids,
                       "ingroup_permission": skill.ingroup_permission},
                user_id=actor.user_id, user_role=role, user_group_ids=groups,
            ):
                continue
            rows[skill.skill_id] = {
                "skill_id": skill.skill_id, "name": skill.skill_name, "description": skill.skill_description or "",
                "config": resolve_skill_config(
                    skill.config_schemas or [], skill.config_values or {},
                    published.get(skill.skill_id, {}), mounts.get(skill.skill_id, {}),
                ),
                "tool_ids": sorted(dependencies[skill.skill_id]),
            }
        return rows


def read_workbench_derived_tools(
    agent_id: int, version_no: int, tenant_id: str, skills: list[dict],
) -> list[dict]:
    """Rebuild tool rows contributed by verified root skills without overriding Agent instances."""
    contributions = {}
    for skill in skills:
        for tool_id in skill["tool_ids"]:
            contributions.setdefault(tool_id, []).append(skill)
    if not contributions:
        return []

    tool, instance = ToolInfo, ToolInstance
    explicit = select(instance.tool_instance_id).where(
        instance.tool_id == tool.tool_id, instance.agent_id == agent_id, instance.version_no == version_no,
        instance.tenant_id == tenant_id, instance.enabled.is_(True), instance.delete_flag != "Y",
    ).exists()
    with get_db_session() as session:
        rows = session.execute(select(
            tool.tool_id, tool.name, tool.class_name, tool.source, tool.usage, tool.origin_name, tool.params,
            tool.description, tool.inputs, tool.output_type,
        ).where(
            tool.tool_id.in_(contributions), tool.author == tenant_id, tool.delete_flag != "Y",
            tool.is_available.is_(True), tool.source.in_(("local", "mcp", "langchain")), ~explicit,
        ).order_by(tool.tool_id)).mappings().all()

    tools = []
    for row in rows:
        tool_id = row["tool_id"]
        contributors = contributions[tool_id]
        params = row["params"] or []
        declared = {param["name"] for param in params}
        values = merge_skill_tool_parameters(tool_id, [
            (skill["name"], {name: value for name, value in skill["config"].items() if name in declared})
            for skill in contributors
        ])
        tools.append({
            **row, "instance_params": {}, "workbench_skill_ids": sorted({skill["skill_id"] for skill in contributors}),
            "params": [{**param, "default": values[param["name"]]} if param["name"] in values else param
                       for param in params],
        })
    return tools
