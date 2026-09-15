"""Declarative clarification forms shared by the runtime and application boundary."""

import json
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


Identifier = Annotated[str, Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")]
AnswerText = Annotated[str, Field(max_length=8000)]

CLARIFICATION_POLICY = (
    "Human clarification is optional, not a required first step. Answer clear requests directly. "
    "First use the user's message, conversation history, attachments and available tools. "
    "An uploaded report with a request to analyze it is sufficient intent: read and analyze it first. "
    "Do not ask about optional preferences, information already supplied, or facts tools can retrieve. "
    "Only call ask_user when a missing key fact prevents a correct or safe next action, or when materially "
    "different interpretations cannot reasonably be resolved from context. "
    "If clarification is necessary, call ask_user(questions=[...]) once with one concise structured card. "
    "Normally ask up to 3 key questions; use 4-5 only for independent essential blockers. "
    "If only 1-2 facts are missing, ask only those; never pad the form. Five questions is the maximum. "
    "Use short titles in the user's language, one fact per question, and useful choices where possible. "
    "Each question has id, type (text/single_choice/multiple_choice), title and required; "
    "For choice questions, put options [{id,label}] and allow_other directly on the question object, "
    "never inside a nested choices object. Example: "
    "ask_user(questions=[{'id':'topic','type':'text','title':'What is the notice about?','required':True}]). "
    "Do not print the same questions in chat or use final_answer to solicit input. "
    "Wait for the returned answer, then continue the same task. Only one clarification card is allowed per run. "
    "After the user replies, use their answers without repeating or rephrasing the questions. "
    "For any remaining unknowns, proceed with explicit reasonable assumptions or explain what cannot safely "
    "be concluded; never fabricate critical facts or request passwords/credentials."
)


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


class ClarificationAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)
    question_id: Identifier
    value: AnswerText | list[Identifier]
    other_text: AnswerText | None = None


def format_clarification_answers(payload: dict, answers: list[ClarificationAnswer]) -> str:
    """Validate submitted values against frozen questions and return labeled JSON."""
    form = ClarificationForm.model_validate({"questions": payload["questions"]})
    by_id = {answer.question_id: answer for answer in answers}
    if len(by_id) != len(answers):
        raise ValueError("Duplicate question answers are not allowed")
    if set(by_id) - {question.id for question in form.questions}:
        raise ValueError("Answer contains an unknown question ID")
    result = []
    for question in form.questions:
        answer = by_id.get(question.id)
        if answer is None:
            if question.required:
                raise ValueError(f"Answer is required: {question.title}")
            continue
        other = answer.other_text or ""
        if other and not question.allow_other:
            raise ValueError(f"Other answers are not allowed: {question.title}")
        value = answer.value
        options = {option.id: option.label for option in question.options}
        if question.type == "multiple_choice":
            if not isinstance(value, list) or len(value) != len(set(value)):
                raise ValueError(f"Choose distinct options: {question.title}")
            if any(item not in options for item in value):
                raise ValueError(f"Unknown option: {question.title}")
            resolved = [options[item] for item in value]
        else:
            if not isinstance(value, str):
                raise ValueError(f"Expected one answer: {question.title}")
            if question.type == "single_choice" and value and value not in options:
                raise ValueError(f"Unknown option: {question.title}")
            resolved = options.get(value, value)
        if question.required and not value and not other:
            raise ValueError(f"Answer is required: {question.title}")
        result.append(
            {
                "question_id": question.id,
                "question": question.title,
                "value": value,
                "answer": resolved,
                "other_text": other or None,
            }
        )
    return json.dumps({"answers": result}, ensure_ascii=False, separators=(",", ":"))
