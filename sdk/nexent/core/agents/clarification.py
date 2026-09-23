"""Declarative clarification forms shared by the runtime and application boundary."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


Identifier = Annotated[str, Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")]

CLARIFICATION_SCHEMA_GUIDANCE = (
    "Each question has a unique id, type (text/single_choice/multiple_choice), a distinct title and required. "
    "Question and option IDs use 1-64 ASCII letters, digits, underscores or hyphens. "
    "Titles use 1-500 characters; option labels use 1-300 characters. "
    "Choice questions have 2-12 options with unique IDs. Put options [{id,label}] and allow_other "
    "directly on the question object, never inside a nested choices object. "
    "Use allow_other=True for free-text Other input; do not add an extra Other option. "
    "Text questions must omit options and allow_other or use options=[] and allow_other=False. "
    "Use Python True/False for booleans, and no additional fields. "
)

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
    + CLARIFICATION_SCHEMA_GUIDANCE
    + "Example: "
    "ask_user(questions=[{'id':'topic','type':'text','title':'What is the notice about?','required':True}]). "
    "Do not print the same questions in chat or use final_answer to solicit input. "
    "Emit one standalone call with literal question data inside <code>...</code>. "
    "This displays a clarification card and ends the current execution. It does not return an answer. "
    "Do not assign its result or place actions around it. The user submits the card as a new query "
    "in the same conversation. "
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


def clarification_policy(tool_name: str) -> str:
    """Describe the selected terminal form name without registering a Python tool."""
    return CLARIFICATION_POLICY.replace("ask_user", tool_name)


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
