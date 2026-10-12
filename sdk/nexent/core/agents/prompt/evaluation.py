"""Render structured Agent profiles for independent evaluation requests."""

from collections.abc import Mapping, Sequence
from functools import lru_cache
import json
from typing import Any

from ...prompts import load_prompt, render_prompt_text
from .auxiliary import AuxiliaryPrompt, compose_auxiliary_prompt, render_auxiliary_field


def compose_evaluation_set_cases(
    language: str, *, context_blocks: list[str], count: int,
    sources: str, max_turns: int,
) -> AuxiliaryPrompt:
    """Join evidence and instructions for evaluation-set case generation."""
    values = {"count": count, "sources": sources, "max_turns": max_turns}
    return AuxiliaryPrompt(
        system=compose_evaluation_set_system(language, max_turns=max_turns),
        user="\n\n".join(
            part for part in (
                "\n\n".join(context_blocks),
                render_auxiliary_field(language, "evaluation_cases", "USER_PROMPT_INSTRUCTION", values),
            ) if part
        ),
    )


def compose_evaluation_set_system(language: str, *, max_turns: int) -> str:
    """Render the case-generation system policy when the user body is already built."""
    return render_auxiliary_field(
        language, "evaluation_cases", "SYSTEM_PROMPT", {"max_turns": max_turns}
    )


def compose_evaluation_case_context_blocks(
    language: str, *, agent_block: str, description: str,
    kb_block: str, file_name: str | None,
    file_content: str | None,
) -> list[str]:
    """Order the selected evidence sections for evaluation case generation."""
    blocks = []
    if agent_block:
        blocks.append(agent_block)
    blocks.append(render_evaluation_section(language, "scene", {"description": description}))
    if kb_block:
        blocks.append(kb_block)
    if file_content and file_name:
        blocks.append(render_evaluation_section(language, "file", {
            "name": file_name, "content": file_content[:3000],
        }))
    return blocks


def compose_evaluation_kb_context(
    language: str, *, kb_context: str, kb_names: str
) -> str:
    if kb_context:
        return render_evaluation_section(language, "knowledge_results", {"content": kb_context})
    if kb_names:
        return render_evaluation_section(language, "knowledge_empty", {"names": kb_names})
    return ""


def evaluation_case_sources(
    language: str, *, has_kb: bool, has_agent: bool, has_file: bool
) -> str:
    fields = ["source_scene"]
    if has_kb:
        fields.append("source_kb")
    if has_agent:
        fields.append("source_agent")
    if has_file:
        fields.append("source_file")
    separator = render_evaluation_section(language, "source_separator")
    return separator.join(render_evaluation_section(language, field) for field in fields)


def compose_evaluator_generation(
    language: str, description: str, agent_profile: str = ""
) -> AuxiliaryPrompt:
    """Select the evaluator request variant before rendering its dynamic values."""
    operation = "evaluation_evaluator"
    field = "USER_PROMPT_WITH_AGENT" if agent_profile else "USER_PROMPT_WITHOUT_AGENT"
    return AuxiliaryPrompt(
        system=compose_auxiliary_prompt(language, operation).system,
        user=render_auxiliary_field(
            language, operation, field,
            {"description": description, "agent_profile": agent_profile},
        ),
    )


def render_evaluation_section(
    language: str, section: str, values: Mapping[str, Any] | None = None
) -> str:
    """Render a fixed heading or line in an evaluation model request."""
    return render_prompt_text(_evaluation_sections(language)[section], values or {})


@lru_cache(maxsize=2)
def _evaluation_sections(language: str) -> dict[str, Any]:
    return load_prompt(language, "evaluation/sections")


def format_profile_list_section(
    items: Sequence[Mapping[str, Any]], label: str, language: str = "en"
) -> str:
    if not items:
        return ""
    parts = [
        render_evaluation_section(
            language,
            "profile_list_item_described" if item.get("description") else "profile_list_item",
            item,
        )
        for item in items
    ]
    return render_evaluation_section(
        language, "profile_list_line", {"label": label, "items": "; ".join(parts)}
    )


def format_profile_tool_section(
    tools: Sequence[Mapping[str, Any]], language: str = "en"
) -> str:
    if not tools:
        return ""
    parts = []
    for tool in tools:
        source = tool.get("source", "")
        tag = (
            render_evaluation_section(language, "profile_tool_tag", {"source": source.upper()})
            if source and source != "local" else ""
        )
        parts.append(render_evaluation_section(
            language,
            "profile_tool_item_described" if tool.get("description") else "profile_tool_item",
            {"name": tool["name"], "tag": tag, "description": tool.get("description", "")},
        ))
    label = render_evaluation_section(language, "profile_tools_label")
    return render_evaluation_section(
        language, "profile_list_line", {"label": label, "items": "; ".join(parts)}
    )


def format_agent_profile_context(
    profile: Mapping[str, Any] | None, language: str = "en"
) -> str:
    if not profile:
        return ""
    lines = [render_evaluation_section(language, "profile_agent", {"value": profile["name"]})]
    for source, field in (
        ("description", "profile_description"),
        ("duty_prompt", "profile_duty"),
        ("constraint_prompt", "profile_constraints"),
        ("business_description", "profile_business"),
    ):
        if profile[source]:
            lines.append(render_evaluation_section(language, field, {"value": profile[source]}))
    tool_line = format_profile_tool_section(profile.get("tools", []), language)
    if tool_line:
        lines.append(tool_line)
    for source, label_field in (
        ("skills", "profile_skills_label"),
        ("sub_agents", "profile_workers_label"),
        ("knowledge_bases", "profile_knowledge_label"),
    ):
        label = render_evaluation_section(language, label_field)
        line = format_profile_list_section(profile.get(source, []), label, language)
        if line:
            lines.append(line)
    return render_evaluation_section(language, "profile_title") + "\n" + "\n".join(lines)


def compose_evaluator_run_prompt(
    template: str, *, query: str, expected: str, actual: str,
    runtime_context: str | None = None,
    conversation_history: list[Mapping[str, Any]] | None = None,
) -> str:
    """Apply the editable evaluator template's literal placeholder contract."""
    lines = []
    if conversation_history:
        lines.append(render_evaluation_section("en", "history_header"))
        for message in conversation_history:
            role = message.get("role")
            if role in {"user", "assistant"}:
                field = "history_user" if role == "user" else "history_agent"
                lines.append(render_evaluation_section("en", field, {
                    "content": message.get("content", ""),
                }))
    prompt = "\n".join(lines) + "\n\n" + template if lines else template
    for name, value in (("query", query), ("expected", expected), ("actual", actual)):
        prompt = prompt.replace("{{" + name + "}}", str(value))
    if runtime_context is not None and "{{runtime_stats}}" in prompt:
        prompt = prompt.replace("{{runtime_stats}}", runtime_context)
    return prompt


def render_analysis_stats(
    total: int, passed: int, thresholds: Mapping[str, Any]
) -> str:
    stats = render_evaluation_section("en", "analysis_stats", {
        "total": total, "passed": passed, "failed": total - passed,
    })
    if thresholds:
        stats += "\n" + render_evaluation_section("en", "analysis_thresholds", {
            "thresholds": json.dumps(thresholds, ensure_ascii=False),
        })
    return stats


def render_analysis_failures(
    failure_examples: list[Mapping[str, Any]], max_examples: int
) -> str:
    if not failure_examples:
        return "\n" + render_evaluation_section("en", "analysis_no_fail")
    parts = []
    for index, example in enumerate(failure_examples[:max_examples], 1):
        query = (example["query"] or "(empty)").replace("\n", " ")[:1000]
        parts.append(render_evaluation_section("en", "analysis_case", {
            "index": index, "query": query,
        }))
        parts.append(render_evaluation_section("en", "analysis_score", {
            "score": json.dumps(example["score"], ensure_ascii=False),
        }))
        if example["reason"]:
            parts.append(render_evaluation_section("en", "analysis_reason", {
                "reason": example["reason"],
            }))
        if example["answer"]:
            parts.append(render_evaluation_section("en", "analysis_answer", {
                "answer": example["answer"],
            }))
    return "\n" + "\n".join(parts) + "\n"


def compose_analysis_report(
    language: str, *, total: int, passed: int,
    thresholds: Mapping[str, Any], failure_examples: list[Mapping[str, Any]],
    max_examples: int,
) -> AuxiliaryPrompt:
    stats = render_analysis_stats(total, passed, thresholds)
    failures = render_analysis_failures(failure_examples, max_examples)
    user = render_evaluation_section("en", "analysis_user", {
        "stats": stats, "max_failures": max_examples, "failures": failures,
    })
    return AuxiliaryPrompt(
        system=compose_auxiliary_prompt(language, "evaluation_report").system,
        user=user,
    )
