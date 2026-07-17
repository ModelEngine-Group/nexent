import re
from typing import Any, Dict, Iterable, List, Optional

from .agent_identity_adapter import resolve_agent_display_names
from .models import CapabilityBinding, CapabilityResolution, CapabilityType


SEARCH_HINTS = ("联网", "网络", "搜索", "新闻", "网页", "竞品", "公开")
KNOWLEDGE_HINTS = ("知识库", "文档", "资料", "项目", "销售线索")


def _safe_text(*parts: Any) -> str:
    return " ".join(str(part or "") for part in parts).lower()


def _tool_binding(tool: Any) -> CapabilityBinding:
    class_name = getattr(tool, "class_name", "") or ""
    name = getattr(tool, "name", None) or class_name
    metadata = getattr(tool, "metadata", None) or {}
    if class_name == "KnowledgeBaseSearchTool":
        index_names = (getattr(tool, "params", None) or {}).get("index_names", [])
        display_map = metadata.get("index_name_to_display_map", {})
        display = ", ".join(display_map.get(index, index) for index in index_names) if index_names else name
        return CapabilityBinding(
            type=CapabilityType.KNOWLEDGE_BASE,
            name=",".join(index_names) if index_names else name,
            display_name=display,
            binding_ref=f"tool:KnowledgeBaseSearchTool:index:{','.join(index_names)}",
            reason="Agent has a configured knowledge-base search tool.",
        )
    return CapabilityBinding(
        type=CapabilityType.TOOL,
        name=name,
        display_name=name,
        binding_ref=f"tool:{name}",
        reason=getattr(tool, "description", None) or "Agent has this tool configured.",
    )


def _skill_binding(skill: Dict[str, Any]) -> CapabilityBinding:
    name = skill.get("name") or ""
    return CapabilityBinding(
        type=CapabilityType.SKILL,
        name=name,
        display_name=name,
        binding_ref=f"skill:{name}",
        reason=skill.get("description") or "Agent has this skill enabled.",
    )


def _agent_binding(agent: Any, capability_type: CapabilityType) -> CapabilityBinding:
    name = getattr(agent, "name", None) or getattr(agent, "agent_id", "")
    return CapabilityBinding(
        type=capability_type,
        name=str(name),
        display_name=str(name),
        binding_ref=f"{capability_type.value.lower()}:{name}",
        reason=getattr(agent, "description", None) or "Agent is available as a callable capability.",
    )


def _flatten_bindings(bindings: Iterable[CapabilityBinding]) -> Dict[str, CapabilityBinding]:
    return {binding.binding_ref: binding for binding in bindings}


async def resolve_agent_capabilities(
    agent_id: int,
    tenant_id: str,
    user_id: str,
    instruction: str,
    version_no: int = 0,
) -> CapabilityResolution:
    """Resolve capabilities from the same assembly path used by normal agent runs."""
    from agents.create_agent_info import create_agent_config
    from services.skill_service import SkillService

    agent_config = await create_agent_config(
        agent_id=agent_id,
        tenant_id=tenant_id,
        user_id=user_id,
        last_user_query=instruction,
        version_no=version_no,
        allow_memory_search=False,
    )

    tool_bindings = [_tool_binding(tool) for tool in getattr(agent_config, "tools", []) or []]
    skill_bindings = []
    try:
        enabled_skills = SkillService().get_enabled_skills_for_agent(
            agent_id=agent_id,
            tenant_id=tenant_id,
            version_no=version_no,
        )
        skill_bindings.extend(_skill_binding(skill) for skill in enabled_skills)
    except Exception:
        enabled_skills = []

    # Skills may also be carried in context components for context-manager agents.
    for component in getattr(agent_config, "context_components", []) or []:
        if getattr(component, "component_type", None) == "skills":
            for skill in getattr(component, "skills", []) or []:
                skill_bindings.append(_skill_binding(skill))

    managed_bindings = [
        _agent_binding(agent, CapabilityType.MANAGED_AGENT)
        for agent in getattr(agent_config, "managed_agents", []) or []
    ]
    a2a_bindings = [
        _agent_binding(agent, CapabilityType.EXTERNAL_A2A_AGENT)
        for agent in getattr(agent_config, "external_a2a_agents", []) or []
    ]

    all_bindings = tool_bindings + skill_bindings + managed_bindings + a2a_bindings
    lower_instruction = instruction.lower()
    missing: List[Dict[str, Any]] = []

    has_search_tool = any(
        binding.type == CapabilityType.TOOL
        and re.search(r"search|linkup|exa|web|联网|搜索", binding.name.lower())
        for binding in all_bindings
    )
    if any(hint in instruction for hint in SEARCH_HINTS) and not has_search_tool:
        missing.append({
            "type": CapabilityType.TOOL.value,
            "name": "web_search",
            "suggestion": (
                "请先为该 Agent 启用联网搜索工具，"
                "或删除任务中的联网/新闻/网页检索要求。"
            ),
        })

    has_knowledge = any(binding.type == CapabilityType.KNOWLEDGE_BASE for binding in all_bindings)
    if any(hint in instruction for hint in KNOWLEDGE_HINTS) and not has_knowledge:
        missing.append({
            "type": CapabilityType.KNOWLEDGE_BASE.value,
            "name": "knowledge_base",
            "suggestion": "请先为该 Agent 选择知识库，或修改任务为仅基于当前会话执行。",
        })

    matched = []
    for binding in all_bindings:
        text = _safe_text(binding.name, binding.display_name, binding.reason)
        instruction_tokens = re.findall(r"[\w\u4e00-\u9fff]+", lower_instruction)
        if not lower_instruction or any(token in text for token in instruction_tokens):
            matched.append(binding)

    if not matched:
        matched = all_bindings[:10]

    agent_display_name = resolve_agent_display_names(
        [(agent_id, version_no)],
        tenant_id,
    ).get((agent_id, version_no))

    return CapabilityResolution(
        matched_capabilities=matched[:20],
        missing_capabilities=missing,
        agent_snapshot={
            "agent_id": agent_id,
            "version_no": version_no,
            "name": getattr(agent_config, "name", ""),
            "display_name": agent_display_name or getattr(agent_config, "name", ""),
            "description": getattr(agent_config, "description", ""),
            "tools_count": len(tool_bindings),
            "skills_count": len(skill_bindings),
            "managed_agents_count": len(managed_bindings),
            "external_a2a_agents_count": len(a2a_bindings),
        },
        executable=len(missing) == 0,
    )


async def validate_bindings_available(
    agent_id: int,
    tenant_id: str,
    user_id: str,
    instruction: str,
    bindings: List[Dict[str, Any]],
    version_no: int = 0,
) -> Dict[str, Any]:
    resolution = await resolve_agent_capabilities(agent_id, tenant_id, user_id, instruction, version_no)
    available = _flatten_bindings(resolution.matched_capabilities)
    unavailable = []
    for binding in bindings or []:
        ref = binding.get("binding_ref")
        if ref and ref not in available:
            unavailable.append(binding)
    return {
        "available": not unavailable and resolution.executable,
        "unavailable_bindings": unavailable,
        "resolution": resolution.model_dump(mode="json"),
    }
