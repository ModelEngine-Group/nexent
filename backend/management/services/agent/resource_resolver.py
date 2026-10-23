# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Database-backed Agent resource descriptions, without SDK object construction."""

import copy
import logging
from typing import Any, Dict, List, Optional

from contracts.errors.exceptions import ValidationError
from management.db.skill import repository as skill_db
from management.db.tool.repository import query_tools_by_ids, search_tools_for_sub_agent

logger = logging.getLogger("create_agent_info")


def _get_skills_for_template(
    agent_id: int,
    tenant_id: str,
    version_no: int = 0,
    runtime_skill_snapshot: Optional[List[Dict[str, Any]]] = None,
) -> List[dict]:
    """Get skills list for prompt template injection.

    Args:
        agent_id: Agent ID
        tenant_id: Tenant ID
        version_no: Version number

    Returns:
        List of skill dicts with name and description
    """
    try:
        if runtime_skill_snapshot is None:
            from management.services.skill.service import SkillService

            skill_service = SkillService()
            enabled_skills = skill_service.get_enabled_skills_for_agent(
                agent_id=agent_id,
                tenant_id=tenant_id,
                version_no=version_no,
            )
        else:
            enabled_skills = runtime_skill_snapshot
        return [
            {"name": s.get("name", ""), "description": s.get("description", "")}
            for s in enabled_skills
        ]
    except Exception as e:
        logger.error(
            f"Failed to get skills for agent {agent_id} (tenant={tenant_id}, version={version_no}): {e}",
            exc_info=True,
        )
        return []


def _resolve_runtime_tool_records(
    agent_id: int,
    tenant_id: str,
    version_no: int = 0,
    runtime_skill_snapshot: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """Merge explicitly enabled tools with tools required by enabled skills."""
    explicit_tools = search_tools_for_sub_agent(
        agent_id,
        tenant_id,
        version_no=version_no,
    )
    explicit_tool_ids = {
        tool.get("tool_id")
        for tool in explicit_tools
        if tool.get("tool_id") is not None
    }

    dependency_values: Dict[int, Dict[str, Any]] = {}
    dependency_sources: Dict[int, Dict[str, str]] = {}
    enabled_skill_instances = (
        skill_db.search_skills_for_agent(
            agent_id=agent_id,
            tenant_id=tenant_id,
            version_no=version_no,
        )
        if runtime_skill_snapshot is None
        else runtime_skill_snapshot
    )
    for skill_instance in enabled_skill_instances:
        skill = (
            skill_db.get_skill_by_id(skill_instance.get("skill_id"), tenant_id)
            if runtime_skill_snapshot is None
            else skill_instance
        )
        if not skill:
            continue
        effective_config = dict(skill.get("config_values") or {})
        if runtime_skill_snapshot is None:
            effective_config.update(skill_instance.get("config_values") or {})
        skill_name = skill.get("name") or str(skill.get("skill_id"))
        for tool_id in skill.get("tool_ids") or []:
            if tool_id in explicit_tool_ids:
                continue
            values = dependency_values.setdefault(tool_id, {})
            sources = dependency_sources.setdefault(tool_id, {})
            runtime_definition = next(
                (
                    item
                    for item in skill.get("tool_definitions") or []
                    if item.get("tool_id") == tool_id
                ),
                {},
            )
            runtime_parameter_names = {
                param.get("name") for param in runtime_definition.get("params") or []
            }
            for name, value in effective_config.items():
                if (
                    runtime_skill_snapshot is not None
                    and name not in runtime_parameter_names
                ):
                    continue
                if name in values and values[name] != value:
                    raise ValidationError(
                        f"Skills '{sources[name]}' and '{skill_name}' configure "
                        f"tool ID {tool_id} parameter '{name}' with different values."
                    )
                values[name] = value
                sources[name] = skill_name

    implicit_tool_ids = set(dependency_values) - explicit_tool_ids
    if not implicit_tool_ids:
        return explicit_tools

    implicit_definitions = (
        query_tools_by_ids(list(implicit_tool_ids))
        if runtime_skill_snapshot is None
        else [
            definition
            for skill in runtime_skill_snapshot
            for definition in skill.get("tool_definitions") or []
        ]
    )
    definitions_by_id = {tool.get("tool_id"): tool for tool in implicit_definitions}
    missing_tool_ids = implicit_tool_ids - set(definitions_by_id)
    if missing_tool_ids:
        raise ValidationError(
            f"Enabled skills require missing tools: {sorted(missing_tool_ids)}"
        )

    implicit_tools = []
    for tool_id in sorted(implicit_tool_ids):
        tool = copy.deepcopy(definitions_by_id[tool_id])
        if tool.get("is_available") is False:
            raise ValidationError(
                f"Enabled skills require unavailable tool '{tool.get('name') or tool_id}'."
            )
        configured_values = dependency_values[tool_id]
        for param in tool.get("params") or []:
            param_name = param.get("name")
            if param_name in configured_values:
                param["default"] = configured_values[param_name]
        implicit_tools.append(tool)

    return explicit_tools + implicit_tools
