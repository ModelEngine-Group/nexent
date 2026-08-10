"""Shared helpers for building agent profile context for LLM prompts.

Extracted from evaluator_service, agent_evaluation_service, and
evaluation_set_service to eliminate ~300 lines of duplicated code.
"""

import logging
from typing import Any, Dict, List, Optional

from database.agent_db import query_sub_agent_relations, search_agent_info_by_agent_id
from database.tool_db import search_tools_for_sub_agent
from services.skill_service import SkillService


logger = logging.getLogger(__name__)


def fetch_agent_profile(agent_id: int, tenant_id: str) -> Optional[Dict[str, Any]]:
    """Query agent info + tools + skills + sub-agents.

    Returns a structured dict (all string values are truncated for LLM context
    limits), or ``None`` when the agent is not found.
    """
    agent = search_agent_info_by_agent_id(agent_id=agent_id, tenant_id=tenant_id)
    if not agent:
        return None

    profile: Dict[str, Any] = {
        "name": agent.get("display_name") or agent.get("name") or "",
        "description": (agent.get("description") or "")[:2000],
        "duty_prompt": (agent.get("duty_prompt") or "")[:3000],
        "constraint_prompt": (agent.get("constraint_prompt") or "")[:2000],
        "business_description": (agent.get("business_description") or "")[:2000],
        "tools": [],
        "skills": [],
        "sub_agents": [],
        "knowledge_bases": [],
    }

    # ── Tools ──────────────────────────────────────────────────────
    kb_index_names: List[str] = []
    try:
        tools = search_tools_for_sub_agent(agent_id, tenant_id)
        if tools:
            for t in tools[:30]:
                name = t.get("name") or t.get("class_name", "")
                desc = t.get("description") or t.get("description_zh") or ""
                source = t.get("source", "")
                if name:
                    profile["tools"].append({
                        "name": name, "description": desc[:200], "source": source,
                    })
                # Extract knowledge base names from search_knowledge / knowledge_base_search tool params.
                # params may be a dict or a list of dicts (tool configs differ across sources).
                if name in ("search_knowledge", "knowledge_base_search"):
                    params = t.get("params")
                    candidates: List[Any] = []
                    if isinstance(params, list):
                        candidates = params
                    elif isinstance(params, dict):
                        candidates = [params]
                    for p in candidates:
                        if not isinstance(p, dict):
                            continue
                        names = p.get("index_names") or p.get("kb_names") or []
                        if isinstance(names, list):
                            kb_index_names.extend(names)
    except Exception:
        logger.warning("Failed to load tools for agent %d", agent_id, exc_info=True)

    # ── Knowledge Bases ────────────────────────────────────────────
    if kb_index_names:
        try:
            from database.knowledge_db import get_knowledge_name_map_by_index_names
            name_map = get_knowledge_name_map_by_index_names(kb_index_names, tenant_id)
            # Also fetch descriptions
            from database.client import get_db_session
            from database.db_models import KnowledgeRecord
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
            for row in rows:
                idx_name, kb_name, kb_desc = row
                profile["knowledge_bases"].append({
                    "name": kb_name or name_map.get(idx_name, idx_name),
                    "description": (kb_desc or "")[:300],
                })
        except Exception:
            logger.warning("Failed to load KB info for agent %d", agent_id, exc_info=True)

    # ── Skills ─────────────────────────────────────────────────────
    try:
        skill_service = SkillService()
        skills = skill_service.get_enabled_skills_for_agent(
            agent_id=agent_id, tenant_id=tenant_id,
        )
        if skills:
            for s in skills[:20]:
                name = s.get("name", "")
                desc = (s.get("description") or "")[:150]
                if name:
                    profile["skills"].append({"name": name, "description": desc})
    except Exception:
        logger.warning("Failed to load skills for agent %d", agent_id, exc_info=True)

    # ── Sub-agents ─────────────────────────────────────────────────
    try:
        sub_relations = query_sub_agent_relations(
            main_agent_id=agent_id, tenant_id=tenant_id,
        )
        if sub_relations:
            for rel in sub_relations[:5]:
                sub_agent = search_agent_info_by_agent_id(
                    agent_id=rel["selected_agent_id"], tenant_id=tenant_id,
                )
                if sub_agent:
                    name = sub_agent.get("display_name") or sub_agent.get("name", "")
                    desc = (sub_agent.get("description") or "")[:150]
                    if name:
                        profile["sub_agents"].append({"name": name, "description": desc})
    except Exception:
        logger.warning("Failed to load sub-agents for agent %d", agent_id, exc_info=True)

    return profile


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

    if profile["tools"]:
        tool_lines = []
        for t in profile["tools"]:
            src_tag = f" [{t['source'].upper()}]" if t.get("source") and t["source"] != "local" else ""
            if t["description"]:
                tool_lines.append(f"{t['name']}{src_tag}: {t['description']}")
            else:
                tool_lines.append(f"{t['name']}{src_tag}")
        lines.append(f"Tools: {'; '.join(tool_lines)}")

    if profile["skills"]:
        skill_lines = []
        for s in profile["skills"]:
            if s["description"]:
                skill_lines.append(f"{s['name']} ({s['description']})")
            else:
                skill_lines.append(s["name"])
        lines.append(f"Skills: {'; '.join(skill_lines)}")

    if profile["sub_agents"]:
        sub_lines = []
        for sa in profile["sub_agents"]:
            if sa["description"]:
                sub_lines.append(f"{sa['name']} ({sa['description']})")
            else:
                sub_lines.append(sa["name"])
        lines.append(f"Sub-agents: {'; '.join(sub_lines)}")

    if profile["knowledge_bases"]:
        kb_lines = []
        for kb in profile["knowledge_bases"]:
            if kb["description"]:
                kb_lines.append(f"{kb['name']}: {kb['description']}")
            else:
                kb_lines.append(kb["name"])
        lines.append(f"Knowledge Bases: {'; '.join(kb_lines)}")

    return "## Agent Configuration\n" + "\n".join(lines)
