"""Render authorized knowledge data into localized prompt sections."""

from collections.abc import Mapping, Sequence
from typing import Any

from ...prompts import load_prompt


def render_knowledge_scope_resources(language: str, scope: Mapping[str, Any]) -> str:
    """Format a Backend-authorized scope snapshot without resolving permissions."""
    labels = load_prompt(language, "agent/knowledge_scope")["resources"]
    local_capable = bool(scope["local_capable"])
    aidp_capable = bool(scope["aidp_capable"])
    local_names = list(scope["local_display_names"])
    aidp_names = list(scope["aidp_display_names"])
    lines = [labels["heading"], "", labels["untrusted_notice"], ""]
    if local_capable and local_names:
        lines.append(labels["local_heading"])
        lines.extend(f"{index}. {name}" for index, name in enumerate(local_names, 1))
    if aidp_capable and aidp_names:
        if local_capable and local_names:
            lines.append("")
        lines.append(labels["aidp_heading"])
        lines.extend(f"{index}. {name}" for index, name in enumerate(aidp_names, 1))
    has_capability = local_capable or aidp_capable
    all_disabled = has_capability and (
        (not local_capable or bool(scope["local_disabled"]))
        and (not aidp_capable or bool(scope["aidp_disabled"]))
    )
    if not has_capability:
        lines.append(labels["no_capability"])
    elif all_disabled:
        lines.append(labels["disabled"])
    elif not ((local_capable and local_names) or (aidp_capable and aidp_names)):
        lines.append(labels["empty"])
    return "\n".join(lines)


def render_knowledge_base_summaries(summaries: Sequence[Mapping[str, Any]]) -> str:
    """Format selected display names and summaries without exposing index routing."""
    return "".join(
        f"**{record['display_name']}**: {record['summary']}\n\n"
        for record in summaries
    )
