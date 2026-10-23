"""Strict structural and Jinja validation for Agent prompt templates."""

from collections.abc import Mapping
from typing import Any

from jinja2 import Environment, StrictUndefined, meta

from .schema import (
    FIELD_VARIABLES,
    FINAL_ANSWER_FIELDS,
    REQUIRED_SYSTEM_SECTIONS,
    SUPPORTED_LANGUAGES,
    SUPPORTED_ROLES,
)


_PARSER = Environment(undefined=StrictUndefined, autoescape=False)


def validate_agent_prompt_template(
    *, role: str, language: str, template: Mapping[str, Any],
) -> None:
    """Validate one complete role/language prompt template without disclosure."""
    if role not in SUPPORTED_ROLES:
        raise ValueError("unsupported Agent prompt role")
    if language not in SUPPORTED_LANGUAGES:
        raise ValueError("unsupported Agent prompt language")
    module = f"{role}_agent"
    if not isinstance(template, Mapping):
        raise ValueError("Agent prompt template is invalid")
    if set(template) != {"system_sections", module, "final_answer"}:
        raise ValueError("Agent prompt template has unsupported root fields")

    sections = template.get("system_sections")
    if not isinstance(sections, Mapping) or set(sections) != REQUIRED_SYSTEM_SECTIONS:
        raise ValueError("Agent prompt system_sections are incomplete")
    expected_stage_fields = (
        {"task", "report", "orchestration"}
        if role == "manager"
        else {"task", "report"}
    )
    stage = template.get(module)
    if not isinstance(stage, Mapping) or set(stage) != expected_stage_fields:
        raise ValueError(f"Agent prompt {module} is incomplete")
    final_answer = template.get("final_answer")
    if not isinstance(final_answer, Mapping) or set(final_answer) != FINAL_ANSWER_FIELDS:
        raise ValueError("Agent prompt final_answer is incomplete")
    for group in ("system_sections", module, "final_answer"):
        for field, value in template[group].items():
            location = f"{group}.{field}"
            if not isinstance(value, str):
                raise ValueError(f"Agent prompt {location} is not text")
            try:
                variables = meta.find_undeclared_variables(_PARSER.parse(value))
            except Exception as error:
                raise ValueError(
                    f"Agent prompt {location} has invalid syntax"
                ) from error
            if variables - FIELD_VARIABLES[group].get(field, frozenset()):
                raise ValueError(
                    f"Agent prompt {location} has unsupported variables"
                )
