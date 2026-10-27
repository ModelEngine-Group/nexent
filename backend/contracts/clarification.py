# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Validated, versioned responses to ordinary clarification forms."""

from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

AnswerText = Annotated[str, Field(max_length=8000)]
Identifier = Annotated[str, Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")]


def normalize_form(value: dict[str, Any]) -> dict[str, Any]:
    """Apply the runtime form contract without accepting execution fields."""
    from nexent.core.agents.clarification import ClarificationForm

    raw = dict(value)
    if type(raw.pop("schema_version", None)) is not int or value["schema_version"] != 1:
        raise ValueError("Unsupported clarification schema version")
    return {"schema_version": 1, **ClarificationForm.model_validate(raw).model_dump()}


class ClarificationAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    questionId: Identifier
    value: AnswerText | Annotated[list[Identifier], Field(max_length=12)]
    otherText: AnswerText | None = None


class ClarificationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Annotated[int, Field(strict=True, ge=1, le=1)] = 1
    form: dict[str, Any]
    unit_index: int | None = Field(default=None, ge=0)
    answers: list[ClarificationAnswer] = Field(min_length=1, max_length=5)

    @model_validator(mode="after")
    def validate_answers(self):
        self.form = normalize_form(self.form)
        by_id = {answer.questionId: answer for answer in self.answers}
        if len(by_id) != len(self.answers) or set(by_id) != {q["id"] for q in self.form["questions"]}:
            raise ValueError("Answers must match the clarification questions exactly")
        for question in self.form["questions"]:
            answer = by_id[question["id"]]
            options = {option["id"] for option in question["options"]}
            value, other = answer.value, (answer.otherText or "").strip()
            if question["type"] == "multiple_choice":
                valid = isinstance(value, list) and len(set(value)) == len(value) and set(value) <= options
            else:
                valid = isinstance(value, str) and (question["type"] == "text" or not value or value in options)
            if not valid or (other and not question["allow_other"]):
                raise ValueError("Invalid clarification answer")
            has_value = bool(value if isinstance(value, list) else value.strip())
            if question["required"] and not has_value and not other:
                raise ValueError("Missing required clarification answer")
        return self
