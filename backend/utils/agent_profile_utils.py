"""Shared helpers for building agent profile context for LLM prompts.

Extracted from evaluator_service, agent_evaluation_service, and
evaluation_set_service to eliminate ~300 lines of duplicated code.
"""

import logging
from typing import Any, Dict, List, Optional, Tuple

from database.agent_db import query_sub_agent_relations, search_agent_info_by_agent_id
from database.tool_db import search_tools_for_sub_agent
from management.services.skill.service import SkillService


logger = logging.getLogger(__name__)

_MAX_TOOLS = 30
_MAX_SKILLS = 20
_MAX_SUB_AGENTS = 5
_DESC_TOOL_MAX = 200
_DESC_SKILL_MAX = 150
_DESC_SUB_AGENT_MAX = 150
_DESC_KB_MAX = 300
_DESC_AGENT_MAX = 2000
_DUTY_PROMPT_MAX = 3000


def _fetch_agent_tools(
    agent_id: int, tenant_id: str
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Load tools for an agent.

    Returns ``(tools, kb_index_names)`` where ``tools`` is the truncated
    tool list for the profile and ``kb_index_names`` is the list of
    knowledge-base index names referenced by search tools.
    """
    tools_list: List[Dict[str, Any]] = []
    kb_index_names: List[str] = []
    try:
        tools = search_tools_for_sub_agent(agent_id, tenant_id)
        if not tools:
            return tools_list, kb_index_names
        for t in tools[:_MAX_TOOLS]:
            name = t.get("name") or t.get("class_name", "")
            if not name:
                continue
            desc = t.get("description") or t.get("description_zh") or ""
            tools_list.append({
                "name": name,
                "description": desc[:_DESC_TOOL_MAX],
                "source": t.get("source", ""),
            })
            if name in ("search_knowledge", "knowledge_base_search"):
                kb_index_names.extend(_extract_kb_index_names(t))
    except Exception:
        logger.warning("Failed to load tools for agent %d", agent_id, exc_info=True)
    return tools_list, kb_index_names


def _extract_kb_index_names(tool: Dict[str, Any]) -> List[str]:
    """Extract knowledge-base index names from a search tool's params."""
    params = tool.get("params")
    if isinstance(params, list):
        candidates: List[Any] = params
    elif isinstance(params, dict):
        candidates = [params]
    else:
        return []

    names: List[str] = []
    for p in candidates:
        if not isinstance(p, dict):
            continue
        raw = p.get("index_names") or p.get("kb_names") or []
        if isinstance(raw, list):
            names.extend(raw)
    return names


def _fetch_knowledge_bases(
    kb_index_names: List[str], tenant_id: str
) -> List[Dict[str, Any]]:
    """Load knowledge-base info for the given index names."""
    if not kb_index_names:
        return []
    try:
        from database.client import get_db_session
        from database.db_models import KnowledgeRecord
        from database.knowledge_db import get_knowledge_name_map_by_index_names

        name_map = get_knowledge_name_map_by_index_names(kb_index_names, tenant_id)
        with get_db_session() as session:
            rows = session.query(
                KnowledgeRecord.index_name,
                KnowledgeRecord.knowledge_name,
                KnowledgeRecord.knowledge_describe,
            ).filter(
                KnowledgeRecord.index_name.in_(kb_index_names),
                KnowledgeRecord.tenant_id == tenant_id,
                KnowledgeRecord.delete_flag != "Y",
            ).all()
        return [
            {
                "name": kb_name or name_map.get(idx_name, idx_name),
                "description": (kb_desc or "")[:_DESC_KB_MAX],
            }
            for idx_name, kb_name, kb_desc in rows
        ]
    except Exception:
        logger.warning("Failed to load KB info", exc_info=True)
        return []


def _fetch_agent_skills(agent_id: int, tenant_id: str) -> List[Dict[str, Any]]:
    """Load enabled skills for an agent."""
    try:
        skill_service = SkillService()
        skills = skill_service.get_enabled_skills_for_agent(
            agent_id=agent_id, tenant_id=tenant_id,
        )
        if not skills:
            return []
        result: List[Dict[str, Any]] = []
        for s in skills[:_MAX_SKILLS]:
            name = s.get("name", "")
            if name:
                desc = (s.get("description") or "")[:_DESC_SKILL_MAX]
                result.append({"name": name, "description": desc})
        return result
    except Exception:
        logger.warning("Failed to load skills for agent %d", agent_id, exc_info=True)
        return []


def _fetch_sub_agents(agent_id: int, tenant_id: str) -> List[Dict[str, Any]]:
    """Load sub-agent info for an agent."""
    try:
        sub_relations = query_sub_agent_relations(
            main_agent_id=agent_id, tenant_id=tenant_id,
        )
        if not sub_relations:
            return []
        result: List[Dict[str, Any]] = []
        for rel in sub_relations[:_MAX_SUB_AGENTS]:
            sub_agent = search_agent_info_by_agent_id(
                agent_id=rel["selected_agent_id"], tenant_id=tenant_id,
            )
            if not sub_agent:
                continue
            name = sub_agent.get("display_name") or sub_agent.get("name", "")
            if name:
                desc = (sub_agent.get("description") or "")[:_DESC_SUB_AGENT_MAX]
                result.append({"name": name, "description": desc})
        return result
    except Exception:
        logger.warning("Failed to load sub-agents for agent %d", agent_id, exc_info=True)
        return []


def fetch_agent_profile(agent_id: int, tenant_id: str) -> Optional[Dict[str, Any]]:
    """Query agent info + tools + skills + sub-agents.

    Returns a structured dict (all string values are truncated for LLM context
    limits), or ``None`` when the agent is not found.
    """
    agent = search_agent_info_by_agent_id(agent_id=agent_id, tenant_id=tenant_id)
    if not agent:
        return None

    tools, kb_index_names = _fetch_agent_tools(agent_id, tenant_id)
    return {
        "name": agent.get("display_name") or agent.get("name") or "",
        "description": (agent.get("description") or "")[:_DESC_AGENT_MAX],
        "duty_prompt": (agent.get("duty_prompt") or "")[:_DUTY_PROMPT_MAX],
        "constraint_prompt": (agent.get("constraint_prompt") or "")[:_DESC_AGENT_MAX],
        "business_description": (agent.get("business_description") or "")[:_DESC_AGENT_MAX],
        "tools": tools,
        "skills": _fetch_agent_skills(agent_id, tenant_id),
        "sub_agents": _fetch_sub_agents(agent_id, tenant_id),
        "knowledge_bases": _fetch_knowledge_bases(kb_index_names, tenant_id),
    }


def _format_list_section(
    items: List[Dict[str, Any]], label: str
) -> str:
    """Format a list of ``{name, description}`` dicts as a labeled line.

    Returns ``""`` when ``items`` is empty.
    """
    if not items:
        return ""
    parts: List[str] = []
    for item in items:
        desc = item.get("description", "")
        if desc:
            parts.append(f"{item['name']} ({desc})")
        else:
            parts.append(item["name"])
    return f"{label}: {'; '.join(parts)}"


def _format_tool_section(tools: List[Dict[str, Any]]) -> str:
    """Format tools as a labeled line, including source tags."""
    if not tools:
        return ""
    parts: List[str] = []
    for t in tools:
        src = t.get("source", "")
        tag = f" [{src.upper()}]" if src and src != "local" else ""
        desc = t.get("description", "")
        if desc:
            parts.append(f"{t['name']}{tag}: {desc}")
        else:
            parts.append(f"{t['name']}{tag}")
    return f"Tools: {'; '.join(parts)}"


def format_agent_profile_context(profile: Optional[Dict[str, Any]]) -> str:
    """Render an agent profile as a human-readable Markdown string for LLM prompts.

    Returns an empty string when ``profile`` is ``None`` or empty.
    """
    if not profile:
        return ""

    lines: List[str] = [f"### Agent: {profile['name']}"]
    if profile["description"]:
        lines.append(f"Description: {profile['description']}")
    if profile["duty_prompt"]:
        lines.append(f"Duty: {profile['duty_prompt']}")
    if profile["constraint_prompt"]:
        lines.append(f"Constraints: {profile['constraint_prompt']}")
    if profile["business_description"]:
        lines.append(f"Business Context: {profile['business_description']}")

    tool_line = _format_tool_section(profile.get("tools", []))
    if tool_line:
        lines.append(tool_line)

    skill_line = _format_list_section(profile.get("skills", []), "Skills")
    if skill_line:
        lines.append(skill_line)

    sub_line = _format_list_section(profile.get("sub_agents", []), "Sub-agents")
    if sub_line:
        lines.append(sub_line)

    kb_line = _format_list_section(profile.get("knowledge_bases", []), "Knowledge Bases")
    if kb_line:
        lines.append(kb_line)

    return "## Agent Configuration\n" + "\n".join(lines)
