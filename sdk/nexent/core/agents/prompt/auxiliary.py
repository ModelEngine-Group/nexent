"""Compose standalone model requests from SDK-owned prompt resources."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from ...prompts import load_prompt, render_prompt_text


@dataclass(frozen=True)
class AuxiliaryPrompt:
    system: str
    user: str = ""


# The operation selects both the resource and its message fields. Callers supply
# only runtime values and do not need to know the YAML layout.
_OPERATIONS: dict[str, tuple[str, str, str | None]] = {
    "chat_title": ("agent/generate_chat_title", "SYSTEM_PROMPT", "USER_PROMPT"),
    "greeting": ("meta/generate_greeting", "GREETING_SYSTEM_PROMPT", "USER_PROMPT"),
    "guardrail_regex": ("safety/guardrail_regex", "GUARDRAIL_SYSTEM_PROMPT", "GUARDRAIL_USER_PROMPT"),
    "automation_intent": ("automation/agent", "INTENT_ANALYSIS_SYSTEM_PROMPT", "INTENT_ANALYSIS_USER_PROMPT"),
    "automation_task_content": ("automation/agent", "TASK_CONTENT_SYSTEM_PROMPT", "TASK_CONTENT_USER_PROMPT"),
    "evaluation_error": ("evaluation/error_explain", "SYSTEM_PROMPT", "USER_PROMPT"),
    "evaluation_cases": ("evaluation/generate_cases", "SYSTEM_PROMPT", "AGENT_QUERY_USER_PROMPT"),
    "evaluation_judge": ("evaluation/judge", "SYSTEM_PROMPT", None),
    "evaluation_report": ("evaluation/analyze_report", "SYSTEM_PROMPT", None),
    "evaluation_kb_plan": ("evaluation/plan_kb_queries", "SYSTEM_PROMPT", "USER_PROMPT"),
    "evaluation_evaluator": ("evaluation/generate_evaluator", "SYSTEM_PROMPT", None),
    "document_summary": ("document/summary", "system_prompt", "user_prompt"),
    "document_cluster_summary": ("document/cluster_summary_reduce", "system_prompt", "user_prompt"),
    "memory_extraction": ("memory/fa_extraction", "system", "user"),
    "memory_dreaming": ("memory/dreaming_user", "system", "user"),
}


def compose_auxiliary_prompt(
    language: str,
    operation: str,
    values: Mapping[str, Any] | None = None,
    *,
    override: Mapping[str, Any] | None = None,
) -> AuxiliaryPrompt:
    """Load one task template and render its model-facing messages strictly.

    An override is a selected user template in the same field schema. Missing
    override fields inherit the SDK default; an empty override field stays empty.
    """
    path, system_key, user_key = _OPERATIONS[operation]
    template = load_prompt(language, path)
    if override:
        template.update(override)
    parameters = values or {}
    # Most system resources deliberately contain literal {{name}} examples for
    # the model to reproduce. Only the case-generation system field is dynamic.
    system = (
        render_prompt_text(template[system_key], parameters)
        if operation == "evaluation_cases" else template[system_key]
    )
    user = render_prompt_text(template[user_key], parameters) if user_key else ""
    return AuxiliaryPrompt(system=system, user=user)


def render_auxiliary_field(
    language: str, operation: str, field: str, values: Mapping[str, Any] | None = None
) -> str:
    """Render a supplemental field of an already registered operation."""
    path = _OPERATIONS[operation][0]
    return render_prompt_text(load_prompt(language, path)[field], values or {})
