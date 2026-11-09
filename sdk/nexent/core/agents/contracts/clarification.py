# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Declarative clarification DTOs and deterministic pure validation."""

import ast
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
    creation_request: str | None = Field(default=None, min_length=1, max_length=8000)

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
        if self.id == "workbench_creation_mode":
            choices = {option.id for option in self.options}
            if (self.type != "single_choice" or not self.required or self.allow_other
                    or not self.creation_request or "continue_chat" not in choices
                    or not choices <= {"agent_create", "skill_create", "continue_chat"}
                    or not choices.intersection({"agent_create", "skill_create"})):
                raise ValueError("Invalid Workbench creation confirmation")
        elif self.creation_request is not None:
            raise ValueError("Creation context requires a Workbench creation confirmation")
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
        if len(self.questions) != 1 and any(q.id == "workbench_creation_mode" for q in self.questions):
            raise ValueError("Ask the creation-mode confirmation separately")
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


def _terminal_clarification_call(tree: ast.Module, tool_name: str) -> ast.Call:
    """Unwrap only a terminal call or its inert assignment/print presentation."""
    if not 1 <= len(tree.body) <= 2:
        raise ValueError("Expected one terminal clarification")
    statement = tree.body[0]
    if isinstance(statement, ast.Expr) and len(tree.body) == 1:
        call = statement.value
    elif (isinstance(statement, ast.Assign) and len(statement.targets) == 1
            and isinstance(statement.targets[0], ast.Name)
            and statement.targets[0].id not in {tool_name, "print"}):
        call = statement.value
        if len(tree.body) == 2:
            output = tree.body[1]
            if not (isinstance(output, ast.Expr) and isinstance(output.value, ast.Call)
                    and isinstance(output.value.func, ast.Name) and output.value.func.id == "print"
                    and len(output.value.args) == 1 and not output.value.keywords
                    and isinstance(output.value.args[0], ast.Name)
                    and output.value.args[0].id == statement.targets[0].id):
                raise ValueError("Only printing the clarification result is allowed")
    else:
        raise ValueError("Expected a simple clarification call or assignment")
    if (not isinstance(call, ast.Call) or not isinstance(call.func, ast.Name)
            or call.func.id != tool_name or call.args or len(call.keywords) != 1
            or call.keywords[0].arg != "questions"):
        raise ValueError("Expected only the questions keyword")
    return call


def parse_clarification_call(code: str, tool_name: str) -> ClarificationForm | None:
    """Recognize an exclusive literal terminal call without executing Python."""
    tree = ast.parse(code)
    references = any(
        (isinstance(node, ast.Name) and node.id == tool_name)
        or (isinstance(node, ast.Attribute) and node.attr == tool_name)
        or (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name == tool_name)
        or (isinstance(node, ast.arg) and node.arg == tool_name)
        or (isinstance(node, ast.alias) and tool_name in (node.name, node.asname))
        for node in ast.walk(tree)
    )
    if not references:
        return None
    if len(code) > 131072:
        raise ValueError("Clarification action exceeds its size limit")
    call = _terminal_clarification_call(tree, tool_name)
    literal = call.keywords[0].value
    nodes = list(ast.walk(literal))
    if len(nodes) > 4096 or any(
        not isinstance(node, (ast.List, ast.Dict, ast.Constant, ast.Load)) for node in nodes
    ):
        raise ValueError("Questions must be literal data")
    for node in nodes:
        if isinstance(node, ast.Dict):
            keys = [ast.literal_eval(key) for key in node.keys]
            if len(set(keys)) != len(keys):
                raise ValueError("Duplicate fields are not allowed")
    return ClarificationForm.model_validate({"questions": ast.literal_eval(literal)})
