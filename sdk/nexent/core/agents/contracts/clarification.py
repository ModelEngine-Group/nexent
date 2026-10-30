# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Declarative clarification DTOs and deterministic pure validation."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


Identifier = Annotated[str, Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")]


class ClarificationOption(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)
    id: Identifier
    label: str = Field(min_length=1, max_length=300)


class ClarificationQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)
    id: Identifier
    type: Literal["text", "single_choice", "multiple_choice"]
    title: str = Field(min_length=1, max_length=500)
    required: bool = True
    options: list[ClarificationOption] = Field(default_factory=list, max_length=12)
    allow_other: bool = False
    placeholder: str = Field(default="", max_length=300)

    @model_validator(mode="before")
    @classmethod
    def normalize_nested_choices(cls, value):
        """Accept the common declarative choice wrapper without accepting executable fields."""
        if not isinstance(value, dict) or "choices" not in value:
            return value
        choices = value["choices"]
        if isinstance(choices, list):
            choices = {"options": choices}
        if not isinstance(choices, dict) or set(choices) - {"options", "allow_other"}:
            return value
        if any(key in value and value[key] != item for key, item in choices.items()):
            raise ValueError("Conflicting choice definitions")
        return {**{key: item for key, item in value.items() if key != "choices"}, **choices}

    @model_validator(mode="after")
    def validate_options(self):
        if self.type == "text" and (self.options or self.allow_other):
            raise ValueError("Text questions cannot contain choices or an other-answer field")
        if self.type != "text" and len(self.options) < 2:
            raise ValueError("Choice questions require at least two options")
        if len({option.id for option in self.options}) != len(self.options):
            raise ValueError("Option IDs must be unique within a question")
        return self


class ClarificationForm(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    questions: list[ClarificationQuestion] = Field(min_length=1, max_length=5)

    @model_validator(mode="after")
    def validate_questions(self):
        if len({question.id for question in self.questions}) != len(self.questions):
            raise ValueError("Question IDs must be unique")
        if len({question.title for question in self.questions}) != len(self.questions):
            raise ValueError("Ask distinct questions about the key missing intent")
        return self


def render_question_text(form: ClarificationForm) -> str:
    """Render a deterministic, complete fallback for model history and text clients."""
    lines = []
    for index, question in enumerate(form.questions, 1):
        lines.append(f"{index}. {question.title}")
        for option in question.options:
            lines.append(f"   - {option.label}")
        if question.allow_other:
            lines.append("   - 其他 / Other")
        if question.placeholder:
            lines.append(f"   {question.placeholder}")
    return "\n".join(lines)


def choose_clarification_tool_name(occupied: set[str]) -> str:
    candidate = "ask_user"
    suffix = 0
    while candidate in occupied:
        candidate = "nexent_ask_user" + (f"_{suffix}" if suffix else "")
        suffix += 1
    return candidate
