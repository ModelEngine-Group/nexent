"""Deterministic formatting for structured context item groups.

These pure functions are owned by the SDK because final model-message
rendering is an SDK responsibility. Callers provide authorized data only.
"""

import json
from typing import Any, Dict, List

from nexent.core.prompts import load_prompt, render_prompt_text


def _localize_schema_descriptions(value: Any, language: str) -> Any:
    """Select localized prose while preserving fixed schema/protocol fields."""
    was_json = isinstance(value, str)
    if was_json:
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError):
            return value
    else:
        parsed = value

    def localize(item: Any) -> Any:
        if isinstance(item, list):
            return [localize(entry) for entry in item]
        if not isinstance(item, dict):
            return item
        localized = {
            key: localize(entry)
            for key, entry in item.items()
            if key != "description_zh"
        }
        if language == "zh" and item.get("description_zh"):
            localized["description"] = item["description_zh"]
        return localized

    result = localize(parsed)
    return json.dumps(result, ensure_ascii=False) if was_json else result




def _format_skills_inventory(
    skills: List[Dict[str, str]],
    language: str = "zh",
) -> str:
    """Format authorized skill data; usage policy comes from the role YAML."""
    if not skills:
        return ""
    labels = load_prompt(language, "agent/context_sections")["skills"]
    lines = [labels["heading"], labels["intro"], "", "<available_skills>"]
    for skill in skills:
        lines.extend([
            "  <skill>",
            f"    <name>{skill.get('name', '')}</name>",
            f"    <description>{skill.get('description', '')}</description>",
            "  </skill>",
        ])
    lines.append("</available_skills>")
    return "\n".join(lines)

def _format_tools_description(
    tools: Dict[str, Any],
    language: str = "zh",
    is_manager: bool = True,
) -> str:
    """Format authorized tool data with SDK-owned usage guidance."""
    labels = load_prompt(language, "agent/context_sections")["tools"]
    lines = [labels["heading"]]
    if not tools:
        return "\n".join([*lines, labels["unavailable"]])

    lines.append(labels["intro"])
    for name, tool in tools.items():
        if hasattr(tool, "description"):
            desc = (getattr(tool, "description_zh", None) or tool.description) if language == "zh" else tool.description
            inputs = tool.inputs
            output_type = tool.output_type
            source = getattr(tool, "source", "local")
        else:
            desc = (tool.get("description_zh") or tool.get("description", "")) if language == "zh" else tool.get("description", "")
            inputs = tool.get("inputs", "")
            output_type = tool.get("output_type", "")
            source = tool.get("source", "local")
        inputs = _localize_schema_descriptions(inputs, language)
        source_marker = " [MCP]" if source == "mcp" else ""
        lines.append(f"- {name}{source_marker}: {desc}")
        if source == "mcp":
            lines.append("   " + render_prompt_text(labels["mcp_call_guidance"], {"name": name}))
        lines.extend([
            f"   {labels['input_label']}: {inputs}",
            f"   {labels['output_label']}: {output_type}",
        ])
    guide = "file_url_guide_manager" if is_manager else "file_url_guide_worker"
    lines.extend(["", labels[guide]])
    return "\n".join(lines)

def _format_worker_agents_description(
    worker_agents: Dict[str, Any],
    language: str = "zh",
) -> str:
    """Format authorized worker agents with SDK-owned calling guidance."""
    if not worker_agents:
        return ""
    labels = load_prompt(language, "agent/context_sections")["worker_agents"]
    lines = [labels["heading"], labels["intro"]]
    for name, agent in worker_agents.items():
        desc = agent.description if hasattr(agent, "description") else agent.get("description", "")
        lines.append(f" - {name}: {desc}")
    lines.extend(["", labels["guidance"]])
    return "\n".join(lines)

def _format_external_agents_description(
    external_a2a_agents: Dict[str, Any],
    language: str = "zh",
) -> str:
    """Format authorized external agents with SDK-owned calling guidance."""
    if not external_a2a_agents:
        return ""
    labels = load_prompt(language, "agent/context_sections")["external_agents"]
    lines = [labels["heading"]]
    lines.append(labels["intro"])
    for agent in external_a2a_agents.values():
        name = agent.name if hasattr(agent, "name") else agent.get("name", "")
        desc = agent.description if hasattr(agent, "description") else agent.get("description", "")
        lines.append(f" - {name}: {desc}")
    lines.extend(["", labels["guidance"]])
    return "\n".join(lines)
