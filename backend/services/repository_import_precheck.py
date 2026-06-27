"""Extract and validate repository import dependencies against the target tenant."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Set, Tuple

from consts.model import (
    ModelConnectStatusEnum,
    RepositoryImportPrecheckResponse,
    RepositoryImportRequirementItem,
    ToolSourceEnum,
)
from database import skill_db
from database.knowledge_db import (
    get_knowledge_name_map_by_index_names,
    get_knowledge_record,
)
from database.model_management_db import (
    get_model_by_model_id,
    get_model_id_by_display_name,
)
from database.remote_mcp_db import get_mcp_server_by_name_and_tenant
from database.tool_db import query_all_tools

_KB_TOOL_CLASS_NAMES = frozenset({
    "KnowledgeBaseSearchTool",
    "DataMateSearchTool",
})

_REASON_MODEL_UNAVAILABLE = "model_unavailable"
_REASON_KB_NOT_FOUND = "kb_not_found"
_REASON_MCP_NOT_FOUND = "mcp_not_found"
_REASON_SKILL_DUPLICATE = "skill_duplicate"
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


def _check_model_available(display_name: Optional[str], tenant_id: str) -> Tuple[bool, Optional[str]]:
    if not display_name or not str(display_name).strip():
        return True, None

    name = str(display_name).strip()
    model_id = get_model_id_by_display_name(name, tenant_id)
    if not model_id:
        return False, _REASON_MODEL_UNAVAILABLE

    model_info = get_model_by_model_id(model_id, tenant_id)
    if not model_info:
        return False, _REASON_MODEL_UNAVAILABLE

    connect_status = ModelConnectStatusEnum.get_value(
        model_info.get("connect_status")
    )
    if connect_status != ModelConnectStatusEnum.AVAILABLE.value:
        return False, _REASON_MODEL_UNAVAILABLE

    return True, None


def _check_kb_available(index_name: str, tenant_id: str) -> Tuple[bool, Optional[str]]:
    record = get_knowledge_record({
        "index_name": index_name,
        "tenant_id": tenant_id,
    })
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


def _check_skill_available(
    skill_name: str,
    existing_skill_names: Set[str],
) -> Tuple[bool, Optional[str]]:
    if skill_name in existing_skill_names:
        return False, _REASON_SKILL_DUPLICATE
    return True, None


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


def _extract_mcp_server_names(snapshot: Any) -> Set[str]:
    names: Set[str] = set()
    for mcp in snapshot.mcp_info or []:
        mcp_data = _mcp_dict(mcp)
        server_name = mcp_data.get("mcp_server_name")
        if server_name:
            names.add(str(server_name))

    for agent in snapshot.agent_info.values():
        agent_data = _agent_dict(agent)
        for tool in agent_data.get("tools") or []:
            tool_data = _tool_dict(tool)
            if tool_data.get("source") == ToolSourceEnum.MCP.value:
                usage = tool_data.get("usage")
                if usage:
                    names.add(str(usage))

    return names


def _extract_knowledge_bases(
    snapshot: Any,
) -> List[Tuple[str, str, Optional[str]]]:
    """Return (key, display_name, description) tuples for knowledge bases."""
    index_names: Set[str] = set()
    for agent in snapshot.agent_info.values():
        agent_data = _agent_dict(agent)
        for tool in agent_data.get("tools") or []:
            tool_data = _tool_dict(tool)
            if tool_data.get("class_name") not in _KB_TOOL_CLASS_NAMES:
                continue
            params = tool_data.get("params") or {}
            for index_name in params.get("index_names") or []:
                if index_name:
                    index_names.add(str(index_name))

    if not index_names:
        return []

    name_map = get_knowledge_name_map_by_index_names(list(index_names))
    items: List[Tuple[str, str, Optional[str]]] = []
    for index_name in sorted(index_names):
        display_name = name_map.get(index_name) or index_name
        items.append((
            f"knowledge_base:{index_name}",
            display_name,
            None,
        ))
    return items


def _extract_models(snapshot: Any) -> List[Tuple[str, str]]:
    """Return (key, display_name) tuples for models."""
    models: Dict[str, str] = {}
    for agent in snapshot.agent_info.values():
        agent_data = _agent_dict(agent)
        for field in ("model_name", "business_logic_model_name"):
            name = agent_data.get(field)
            if name and str(name).strip():
                label = str(name).strip()
                models.setdefault(f"model:{label}", label)
    return list(models.items())


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
    existing_skill_names = {
        skill.get("name")
        for skill in skill_db.list_skills(tenant_id)
        if skill.get("name")
    }

    items: List[RepositoryImportRequirementItem] = []

    for key, model_name in _extract_models(snapshot):
        available, reason = _check_model_available(model_name, tenant_id)
        items.append(RepositoryImportRequirementItem(
            type="model",
            key=key,
            name=model_name,
            available=available,
            reason_code=reason,
        ))

    for key, kb_name, description in _extract_knowledge_bases(snapshot):
        index_name = key.split(":", 1)[1]
        available, reason = _check_kb_available(index_name, tenant_id)
        record = get_knowledge_record({
            "index_name": index_name,
            "tenant_id": tenant_id,
        })
        kb_description = record.get("knowledge_describe") if record else description
        items.append(RepositoryImportRequirementItem(
            type="knowledge_base",
            key=key,
            name=kb_name,
            description=kb_description,
            available=available,
            reason_code=reason,
        ))

    for server_name in sorted(_extract_mcp_server_names(snapshot)):
        available, reason = _check_mcp_available(server_name, tenant_id)
        items.append(RepositoryImportRequirementItem(
            type="mcp",
            key=f"mcp:{server_name}",
            name=server_name,
            available=available,
            reason_code=reason,
        ))

    for skill_name in _extract_skill_names(snapshot):
        available, reason = _check_skill_available(
            skill_name,
            existing_skill_names,
        )
        items.append(RepositoryImportRequirementItem(
            type="skill",
            key=f"skill:{skill_name}",
            name=skill_name,
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
