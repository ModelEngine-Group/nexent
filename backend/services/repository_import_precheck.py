"""Extract and validate repository import dependencies against the target tenant."""

from __future__ import annotations

import hashlib
from typing import Any, Dict, List, Optional, Set, Tuple

from consts.model import (
    RepositoryImportPrecheckResponse,
    RepositoryImportRequirementItem,
    ToolSourceEnum,
)
from database import skill_db
from database.knowledge_db import get_knowledge_record
from database.model_management_db import get_model_records
from database.remote_mcp_db import get_mcp_server_by_name_and_tenant
from database.tool_db import query_all_tools

_KB_TOOL_CLASS_NAMES = frozenset({
    "KnowledgeBaseSearchTool",
})

_REASON_MODEL_UNAVAILABLE = "model_unavailable"
_REASON_KB_NOT_FOUND = "kb_not_found"
_REASON_MCP_NOT_FOUND = "mcp_not_found"
_REASON_SKILL_PACKAGE_MISSING = "skill_package_missing"
_REASON_SKILL_INSTALL_REQUIRED = "skill_install_required"
_REASON_TOOL_UNAVAILABLE = "tool_unavailable"


def _tool_lookup_key(class_name: str, source: str) -> str:
    return f"{class_name}&{source}"


def _build_tenant_tool_map(tenant_id: str) -> Dict[str, Dict[str, Any]]:
    tools = query_all_tools(tenant_id=tenant_id)
    return {
        _tool_lookup_key(tool["class_name"], tool["source"]): tool
        for tool in tools
        if tool.get("class_name") and tool.get("source")
    }


def _match_target_model_names(
    model_names: List[str],
    tenant_id: str,
) -> List[int]:
    """Resolve every exact model display-name match in the target tenant."""
    matched_ids: List[int] = []
    seen_ids: Set[int] = set()
    for model_name in model_names:
        candidates = get_model_records(
            {"display_name": model_name, "model_type": "llm"},
            tenant_id,
        )
        if not candidates:
            continue
        model_id = candidates[0].get("model_id")
        if model_id is not None and model_id not in seen_ids:
            seen_ids.add(model_id)
            matched_ids.append(model_id)
    return matched_ids


def _check_kb_available(index_name: str) -> Tuple[bool, Optional[str]]:
    record = get_knowledge_record({"index_name": index_name})
    if not record:
        return False, _REASON_KB_NOT_FOUND
    return True, None


def _check_mcp_available(server_name: str, tenant_id: str) -> Tuple[bool, Optional[str]]:
    if not server_name or not str(server_name).strip():
        return False, _REASON_MCP_NOT_FOUND
    url = get_mcp_server_by_name_and_tenant(str(server_name).strip(), tenant_id)
    if not url:
        return False, _REASON_MCP_NOT_FOUND
    return True, None


def build_repository_skill_source(
    agent_repository_id: int,
    skill_zip_base64: str,
) -> str:
    """Build a short source marker for one installed repository Skill package."""
    package_hash = hashlib.sha256(skill_zip_base64.encode("utf-8")).hexdigest()[:8]
    return f"ar:{agent_repository_id}:{package_hash}"


def _check_tool_available(
    class_name: str,
    source: str,
    tenant_tools: Dict[str, Dict[str, Any]],
) -> Tuple[bool, Optional[str]]:
    tool = tenant_tools.get(_tool_lookup_key(class_name, source))
    if tool is None or not tool.get("is_available"):
        return False, _REASON_TOOL_UNAVAILABLE
    return True, None


def _agent_dict(agent: Any) -> Dict[str, Any]:
    if isinstance(agent, dict):
        return agent
    if hasattr(agent, "model_dump"):
        return agent.model_dump()
    return {}


def _tool_dict(tool: Any) -> Dict[str, Any]:
    if isinstance(tool, dict):
        return tool
    if hasattr(tool, "model_dump"):
        return tool.model_dump()
    return {}


def _extract_skill_names(snapshot: Any) -> List[str]:
    names: List[str] = []
    seen: Set[str] = set()

    if snapshot.skills:
        for entry in snapshot.skills:
            skill_name = getattr(entry, "skill_name", None)
            if skill_name is None and isinstance(entry, dict):
                skill_name = entry.get("skill_name")
            if skill_name and skill_name not in seen:
                seen.add(skill_name)
                names.append(str(skill_name))

    for agent in snapshot.agent_info.values():
        agent_data = _agent_dict(agent)
        for skill_name in agent_data.get("skill_names") or []:
            if skill_name and skill_name not in seen:
                seen.add(str(skill_name))
                names.append(str(skill_name))

    return names


def _extract_bundled_skills(snapshot: Any) -> Dict[str, Dict[str, str]]:
    skills: Dict[str, Dict[str, str]] = {}
    for entry in snapshot.skills or []:
        skill_name = getattr(entry, "skill_name", None)
        if skill_name is None and isinstance(entry, dict):
            skill_name = entry.get("skill_name")
        if skill_name:
            source = getattr(entry, "source", None)
            zip_base64 = getattr(entry, "skill_zip_base64", None)
            if isinstance(entry, dict):
                source = source or entry.get("source")
                zip_base64 = zip_base64 or entry.get("skill_zip_base64")
            skills[str(skill_name)] = {
                "source": str(source or ""),
                "skill_zip_base64": str(zip_base64 or ""),
            }
    return skills


def _resolve_snapshot_skill_source(
    snapshot: Any,
    skill_name: str,
    bundled_source: str,
) -> str:
    if bundled_source:
        return bundled_source
    source_tenant_ids = {
        str(agent_data.get("tenant_id"))
        for agent in snapshot.agent_info.values()
        if (agent_data := _agent_dict(agent)).get("tenant_id")
    }
    for source_tenant_id in source_tenant_ids:
        source_skill = skill_db.get_skill_by_name(skill_name, source_tenant_id)
        if source_skill and source_skill.get("source"):
            return str(source_skill["source"])
    return ""


def _mcp_dict(mcp: Any) -> Dict[str, Any]:
    if isinstance(mcp, dict):
        return mcp
    if hasattr(mcp, "model_dump"):
        return mcp.model_dump()
    return {
        key: getattr(mcp, key)
        for key in ("mcp_server_name", "mcp_url")
        if hasattr(mcp, key)
    }


def _extract_mcp_servers(snapshot: Any) -> Dict[str, str]:
    servers: Dict[str, str] = {}
    for mcp in snapshot.mcp_info or []:
        mcp_data = _mcp_dict(mcp)
        server_name = mcp_data.get("mcp_server_name")
        if server_name:
            servers[str(server_name)] = str(mcp_data.get("mcp_url") or "")

    for agent in snapshot.agent_info.values():
        agent_data = _agent_dict(agent)
        for tool in agent_data.get("tools") or []:
            tool_data = _tool_dict(tool)
            if tool_data.get("source") == ToolSourceEnum.MCP.value:
                usage = tool_data.get("usage")
                if usage:
                    servers.setdefault(str(usage), "")

    return servers


def _resolve_repository_knowledge_base(
    configured_name: str,
    source_tenant_id: Optional[str],
) -> Tuple[Optional[str], Dict[str, Any]]:
    """Resolve a repository KB reference, preferring the publishing tenant for display names."""
    if source_tenant_id:
        record = get_knowledge_record({
            "index_name": configured_name,
            "tenant_id": source_tenant_id,
        })
        if record:
            return str(record.get("index_name") or configured_name), record

    record = get_knowledge_record({"index_name": configured_name})
    if record:
        return str(record.get("index_name") or configured_name), record

    if source_tenant_id:
        record = get_knowledge_record({
            "knowledge_name": configured_name,
            "tenant_id": source_tenant_id,
        })
        if record:
            return str(record.get("index_name") or configured_name), record

    return None, {}


def _extract_knowledge_bases(
    snapshot: Any,
) -> List[Tuple[str, str, Optional[str], Optional[str]]]:
    """Return repository KB dependencies with globally resolved index names."""
    items: Dict[str, Tuple[str, str, Optional[str], Optional[str]]] = {}
    for agent_key, agent in snapshot.agent_info.items():
        agent_data = _agent_dict(agent)
        source_tenant_id = agent_data.get("tenant_id")
        for tool in agent_data.get("tools") or []:
            tool_data = _tool_dict(tool)
            if tool_data.get("class_name") not in _KB_TOOL_CLASS_NAMES:
                continue
            params = tool_data.get("params") or {}
            for configured_name in params.get("index_names") or []:
                if not configured_name:
                    continue
                configured_name = str(configured_name)
                resolved_index_name, record = _resolve_repository_knowledge_base(
                    configured_name,
                    str(source_tenant_id) if source_tenant_id else None,
                )
                key = f"knowledge_base:{agent_key}:{configured_name}"
                items[key] = (
                    key,
                    str(record.get("knowledge_name") or configured_name),
                    record.get("knowledge_describe"),
                    resolved_index_name,
                )
    return list(items.values())


def sanitize_repository_knowledge_base_references(snapshot: Any) -> List[str]:
    """Remove unresolved KB selections and normalize retained values to index names."""
    removed: List[str] = []
    for agent in snapshot.agent_info.values():
        agent_data = _agent_dict(agent)
        source_tenant_id = agent_data.get("tenant_id")
        tools = agent.get("tools", []) if isinstance(agent, dict) else getattr(agent, "tools", [])
        for tool in tools or []:
            tool_data = tool if isinstance(tool, dict) else tool.model_dump()
            if tool_data.get("class_name") not in _KB_TOOL_CLASS_NAMES:
                continue
            params = tool.get("params", {}) if isinstance(tool, dict) else tool.params
            configured_names = list(params.get("index_names") or [])
            retained: List[str] = []
            for configured_name in configured_names:
                resolved_index_name, _ = _resolve_repository_knowledge_base(
                    str(configured_name),
                    str(source_tenant_id) if source_tenant_id else None,
                )
                if resolved_index_name:
                    if resolved_index_name not in retained:
                        retained.append(resolved_index_name)
                else:
                    removed.append(str(configured_name))
            params["index_names"] = retained
    return list(dict.fromkeys(removed))


def _extract_models(snapshot: Any) -> List[Dict[str, Any]]:
    """Return each Agent's ordered, de-duplicated model_names selection."""
    models: List[Dict[str, Any]] = []
    for agent_key, agent in snapshot.agent_info.items():
        agent_data = _agent_dict(agent)
        agent_id = int(agent_data.get("agent_id") or agent_key)
        model_names = list(dict.fromkeys(
            str(name).strip()
            for name in agent_data.get("model_names") or []
            if str(name).strip()
        ))
        if model_names:
            models.append({
                "key": f"model:{agent_id}",
                "agent_id": agent_id,
                "model_names": model_names,
            })
    return models


def _extract_tools(
    snapshot: Any,
) -> List[Tuple[str, str, str, str]]:
    """Return (key, name, class_name, source) for import-required tools."""
    tools: Dict[str, Tuple[str, str, str]] = {}
    for agent in snapshot.agent_info.values():
        agent_data = _agent_dict(agent)
        for tool in agent_data.get("tools") or []:
            tool_data = _tool_dict(tool)
            class_name = tool_data.get("class_name")
            source = tool_data.get("source")
            if not class_name or not source:
                continue
            key = f"tool:{_tool_lookup_key(class_name, source)}"
            display = (
                tool_data.get("name")
                or tool_data.get("origin_name")
                or class_name
            )
            tools.setdefault(key, (str(display), str(class_name), str(source)))
    return [
        (key, name, class_name, source)
        for key, (name, class_name, source) in tools.items()
    ]


def build_repository_import_precheck(
    *,
    agent_repository_id: int,
    display_name: str,
    snapshot: Any,
    tenant_id: str,
) -> RepositoryImportPrecheckResponse:
    """Build import precheck response for a repository listing snapshot."""
    tenant_tools = _build_tenant_tool_map(tenant_id)
    existing_skills_by_name = {
        str(skill["name"]): skill
        for skill in skill_db.list_skills(tenant_id)
        if skill.get("name")
    }
    bundled_skills = _extract_bundled_skills(snapshot)

    items: List[RepositoryImportRequirementItem] = []

    for model in _extract_models(snapshot):
        model_names = model["model_names"]
        matched_model_ids = _match_target_model_names(model_names, tenant_id)
        available = bool(matched_model_ids)
        items.append(RepositoryImportRequirementItem(
            type="model",
            key=model["key"],
            name=", ".join(model_names),
            agent_id=model["agent_id"],
            source_model_names=model_names,
            matched_model_ids=matched_model_ids,
            requires_replacement=not available,
            available=available,
            reason_code=None if available else _REASON_MODEL_UNAVAILABLE,
        ))

    for key, kb_name, description, index_name in _extract_knowledge_bases(snapshot):
        available, reason = (
            _check_kb_available(index_name)
            if index_name
            else (False, _REASON_KB_NOT_FOUND)
        )
        items.append(RepositoryImportRequirementItem(
            type="knowledge_base",
            key=key,
            name=kb_name,
            description=description,
            index_name=index_name,
            will_auto_deselect=not available,
            available=available,
            reason_code=reason,
        ))

    for server_name, mcp_url in sorted(_extract_mcp_servers(snapshot).items()):
        available, reason = _check_mcp_available(server_name, tenant_id)
        items.append(RepositoryImportRequirementItem(
            type="mcp",
            key=f"mcp:{server_name}",
            name=server_name,
            mcp_url=mcp_url,
            available=available,
            reason_code=reason,
        ))

    for skill_name in _extract_skill_names(snapshot):
        bundled_skill = bundled_skills.get(skill_name, {})
        local_skill = existing_skills_by_name.get(skill_name)
        skill_source = _resolve_snapshot_skill_source(
            snapshot,
            skill_name,
            bundled_skill.get("source", ""),
        )
        source_is_official = skill_source.lower() == "official"
        has_local_official_skill = bool(
            local_skill
            and str(local_skill.get("source") or "").lower() == "official"
        )
        is_official_skill = source_is_official and has_local_official_skill
        has_install_package = bool(bundled_skill.get("skill_zip_base64"))

        if is_official_skill:
            available = True
            reason = None
        elif has_install_package:
            installed_source = build_repository_skill_source(
                agent_repository_id,
                bundled_skill["skill_zip_base64"],
            )
            available = bool(
                local_skill and local_skill.get("source") == installed_source
            )
            reason = None if available else _REASON_SKILL_INSTALL_REQUIRED
        else:
            available = False
            reason = _REASON_SKILL_PACKAGE_MISSING

        items.append(RepositoryImportRequirementItem(
            type="skill",
            key=f"skill:{skill_name}",
            name=skill_name,
            has_local_skill=local_skill is not None,
            has_install_package=has_install_package,
            is_official_skill=is_official_skill,
            available=available,
            reason_code=reason,
        ))

    for key, tool_name, class_name, source in _extract_tools(snapshot):
        available, reason = _check_tool_available(
            class_name,
            source,
            tenant_tools,
        )
        items.append(RepositoryImportRequirementItem(
            type="tool",
            key=key,
            name=tool_name,
            available=available,
            reason_code=reason,
        ))

    total_count = len(items)
    available_count = sum(1 for item in items if item.available)
    if total_count == 0:
        percent = 100
    else:
        percent = round(available_count / total_count * 100)

    return RepositoryImportPrecheckResponse(
        agent_repository_id=agent_repository_id,
        display_name=display_name,
        total_count=total_count,
        available_count=available_count,
        percent=percent,
        has_abnormal=available_count < total_count,
        items=items,
    )
