"""Compose agent-generation prompts from selected resources and user templates."""

from collections.abc import Mapping, Sequence
import logging
from typing import Any

from jinja2 import Template

from ...prompts import load_prompt, render_prompt_text
from .auxiliary import AuxiliaryPrompt

logger = logging.getLogger(__name__)


def default_section_title(language: str, section_type: str) -> str:
    selected_language = language if language in {"zh", "en"} else "zh"
    return load_prompt(selected_language, "meta/resource_descriptions")["section_titles"].get(
        section_type, section_type
    )


def optimization_scope_instruction(language: str) -> str:
    selected_language = "zh" if language == "zh" else "en"
    return load_prompt(selected_language, "meta/resource_descriptions")["optimization_global_scope"]


def append_optimization_scope_instruction(feedback: str, language: str) -> str:
    return "\n\n".join(
        part for part in ((feedback or "").strip(), optimization_scope_instruction(language)) if part
    ).strip()


def load_generation_template(language: str) -> dict[str, Any]:
    """Return the raw editable template schema for persistence and overrides."""
    return load_prompt(language, "meta/generate_prompt")


def compose_nl2agent_system(language: str, values: Mapping[str, Any]) -> str:
    return render_prompt_text(load_prompt(language, "meta/nl2agent")["system_prompt"], values)


def compose_nl2skill(
    language: str, *, existing_skill: Mapping[str, Any] | None,
    user_request: str, target_files: Sequence[str],
) -> dict[str, str]:
    template = load_prompt(language, "meta/nl2skill")
    context = {
        "existing_skill": existing_skill,
        "has_existing_skill_content": bool(
            str(existing_skill.get("content") or "").strip()
        ) if isinstance(existing_skill, Mapping) else False,
        "user_request": user_request,
        "target_files": target_files,
    }
    result = {}
    for key in ("system_prompt", "user_prompt"):
        source = template.get(key, "")
        try:
            result[key] = render_prompt_text(source, context) if source else ""
        except Exception as exc:
            logger.warning("Failed to render %s template: %s, using raw content", key, exc)
            result[key] = source
    return result


def compose_name_regeneration(
    language: str, template: Mapping[str, Any], *, field_key: str,
    task_description: str, original_value: str, existing_values: str,
) -> AuxiliaryPrompt:
    """Render a selected tenant template, retaining its lenient legacy fallback."""
    prefix = {"name": "agent_name_regenerate", "display_name": "agent_display_name_regenerate"}[field_key]
    defaults = load_prompt(language, "meta/name_regeneration")
    context = {
        "task_description": task_description,
        "original_value": original_value,
        "existing_values": existing_values,
    }

    system = render_name_template(
        template.get(f"{prefix}_system_prompt", ""), original_value=original_value
    )
    user = render_name_template(template.get(f"{prefix}_user_prompt", ""), **context)
    return AuxiliaryPrompt(
        system=system or defaults[f"{field_key}_system"],
        user=user or defaults[f"{field_key}_user"].format(**context),
    )


def render_name_template(template_str: str | None, **context: Any) -> str:
    """Preserve the editable naming template's lenient render fallback."""
    if not template_str:
        return ""
    try:
        return Template(template_str).render(**context).strip()
    except Exception as exc:
        logger.warning("Failed to render prompt template: %s", exc)
        return template_str


def _resource_context(
    language: str,
    tools: Sequence[Mapping[str, Any]],
    worker_agents: Sequence[Mapping[str, Any]],
    *,
    has_local_knowledge_tool: bool,
    has_aidp_knowledge_tool: bool,
    optimization: bool,
) -> dict[str, Any]:
    descriptions = load_prompt(language, "meta/resource_descriptions")
    tool_description = "\n".join(
        render_prompt_text(descriptions["tool"], tool).rstrip("\n") for tool in tools
    )
    worker_description = "\n".join(
        render_prompt_text(descriptions["worker_agent"], agent) for agent in worker_agents
    )
    if has_local_knowledge_tool or has_aidp_knowledge_tool:
        key = "optimization_knowledge_scope" if optimization else "generation_knowledge_scope"
        tool_description = "\n\n".join(
            part for part in (tool_description, descriptions[key]) if part
        )
    return {
        "tool_description": tool_description,
        "assistant_description": worker_description,
        "knowledge_base_names": "",
        "aidp_kb_names": "",
        "has_local_knowledge_tool": has_local_knowledge_tool,
        "has_aidp_knowledge_tool": has_aidp_knowledge_tool,
    }


def compose_agent_generation_user(
    language: str,
    template: Mapping[str, Any],
    *,
    task_description: str,
    tools: Sequence[Mapping[str, Any]],
    worker_agents: Sequence[Mapping[str, Any]],
    has_local_knowledge_tool: bool,
    has_aidp_knowledge_tool: bool,
    has_selected_resources: bool,
) -> str:
    context = _resource_context(
        language, tools, worker_agents,
        has_local_knowledge_tool=has_local_knowledge_tool,
        has_aidp_knowledge_tool=has_aidp_knowledge_tool,
        optimization=False,
    )
    context.update(task_description=task_description, has_selected_resources=has_selected_resources)
    return render_prompt_text(template["user_prompt"], context)


def compose_agent_optimization(
    language: str,
    *,
    section_type: str,
    section_title: str,
    task_description: str,
    current_content: str,
    feedback: str,
    tools: Sequence[Mapping[str, Any]],
    worker_agents: Sequence[Mapping[str, Any]],
    has_local_knowledge_tool: bool,
    has_aidp_knowledge_tool: bool,
    template_override: Mapping[str, Any] | None = None,
) -> AuxiliaryPrompt:
    context = _resource_context(
        language, tools, worker_agents,
        has_local_knowledge_tool=has_local_knowledge_tool,
        has_aidp_knowledge_tool=has_aidp_knowledge_tool,
        optimization=True,
    )
    context.update(
        section_type=section_type, section_title=section_title,
        task_description=task_description, current_content=current_content,
        feedback=feedback,
    )
    template = load_prompt(language, "meta/optimize_prompt")
    if template_override:
        template.update(template_override)
    return AuxiliaryPrompt(
        system=template["OPTIMIZE_SYSTEM_PROMPT"],
        user=render_prompt_text(template["OPTIMIZE_USER_PROMPT"], context),
    )
