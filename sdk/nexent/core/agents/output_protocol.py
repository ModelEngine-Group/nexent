"""Closed output protocol for Nexent CodeAgent runtimes."""

from __future__ import annotations

import ast
import re
import unicodedata
from dataclasses import dataclass
from enum import Enum
from typing import Any, Literal

from pydantic import ValidationError

from .clarification import CLARIFICATION_SCHEMA_GUIDANCE, ClarificationForm


OutputProtocol = Literal["code_action", "final_answer_envelope"]


class ProtocolErrorReason(str, Enum):
    """Stable classifications for invalid model output."""

    EMPTY_VISIBLE_CONTENT = "empty_visible_content"
    UNSUPPORTED_OR_TAG_ONLY_OUTPUT = "unsupported_or_tag_only_output"
    MALFORMED_ACTION = "malformed_action"
    MISSING_EXPLICIT_TERMINATION = "missing_explicit_termination"
    TRUNCATED_GENERATION = "truncated_generation"
    INVALID_FINAL_ENVELOPE = "invalid_final_envelope"
    INVALID_CLARIFICATION_FORM = "invalid_clarification_form"


@dataclass(frozen=True)
class ExecutableAction:
    """One validated Python action ready for the executor."""

    code: str
    legacy_format: bool = False


@dataclass(frozen=True)
class ExplicitFinalAnswer:
    """One validated NL2Skill final-answer envelope payload."""

    answer: str


class ModelOutputProtocolError(Exception):
    """A recoverable model-output protocol violation."""

    def __init__(
        self,
        reason: ProtocolErrorReason,
        protocol: OutputProtocol,
        logger: Any = None,
        *,
        repair_hint: str | None = None,
    ) -> None:
        self.reason = reason
        self.protocol = protocol
        self.repair_instruction = protocol_repair_instruction(protocol, reason)
        if repair_hint:
            self.repair_instruction += " " + repair_hint
        super().__init__(self.repair_instruction)
        self.message = self.repair_instruction


class RuntimeFinalAnswer(Exception):
    """A trusted runtime-controlled terminal answer."""

    def __init__(self, answer: Any, source: str) -> None:
        super().__init__(source)
        self.answer = answer
        self.source = source


class ModelOutputProtocolExhaustedError(Exception):
    """Terminal failure after the runtime exhausts protocol repair attempts."""


_CODE_RE = re.compile(r"\A<code>(?P<body>[\s\S]*)</code>\Z")
_RUN_RE = re.compile(r"\A```<RUN>(?P<body>[\s\S]*?)```\Z")
_ACTION_PREAMBLE_RE = re.compile(
    r"\A(?P<preamble>(?:(?:Think|Thought|思考)[ \t]*[:：][\s\S]*?\n)?"
    r"[ \t]*(?:Code|代码)[ \t]*[:：])\s*(?P<action><code>[\s\S]*|```<RUN>[\s\S]*)\Z",
    re.IGNORECASE,
)
_FINAL_ENVELOPE_RE = re.compile(r"\A<FINAL_ANSWER>(?P<body>[\s\S]*)</FINAL_ANSWER>\Z")
_TAG_RE = re.compile(r"</?[A-Za-z][^<>]{0,255}>")


def _is_protocol_padding(character: str) -> bool:
    return character.isspace() or unicodedata.category(character) == "Cf"


def strip_protocol_padding(value: Any) -> str:
    """Strip only protocol-ignorable edge whitespace and format characters."""

    text = "" if value is None else str(value)
    start = 0
    end = len(text)
    while start < end and _is_protocol_padding(text[start]):
        start += 1
    while end > start and _is_protocol_padding(text[end - 1]):
        end -= 1
    return text[start:end]


def has_meaningful_visible_content(value: Any) -> bool:
    """Return whether content contains a non-whitespace, non-format character."""

    if value is None:
        return False
    return any(not _is_protocol_padding(character) for character in str(value))


def unicode_category_summary(value: Any) -> str:
    """Return a content-free Unicode category count for diagnostics."""

    counts: dict[str, int] = {}
    for character in str(value or ""):
        category = unicodedata.category(character)
        counts[category] = counts.get(category, 0) + 1
    return ",".join(f"{key}:{counts[key]}" for key in sorted(counts)) or "empty"


def protocol_repair_instruction(
    protocol: OutputProtocol,
    reason: ProtocolErrorReason,
) -> str:
    """Build safe feedback that teaches only the configured runtime protocol."""

    prefix = f"The previous response violated the Agent output protocol ({reason.value}). "
    if protocol == "final_answer_envelope":
        return (
            prefix + "Return exactly one complete <FINAL_ANSWER>...</FINAL_ANSWER> envelope. "
            "Put the required <SKILL>, <FILE>, and <SUMMARY> content inside it, with no content outside the envelope."
        )
    if reason == ProtocolErrorReason.INVALID_CLARIFICATION_FORM:
        return (
            prefix + "Return one standalone call to the configured clarification tool inside <code>...</code>, "
            "with 1-5 literal question objects. Do not use final_answer to solicit input. "
            + CLARIFICATION_SCHEMA_GUIDANCE
        )
    return (
        prefix + "Return exactly one executable Python action inside <code>...</code>. "
        "To finish, call final_answer(...) inside that code block; never return a bare-text final answer."
    )


def _raise_protocol_error(
    reason: ProtocolErrorReason,
    protocol: OutputProtocol,
    logger: Any,
) -> None:
    raise ModelOutputProtocolError(reason, protocol, logger)


def classify_model_output(
    output: Any,
    *,
    protocol: OutputProtocol,
    finish_reason: str | None = None,
    logger: Any = None,
) -> ExecutableAction | ExplicitFinalAnswer:
    """Classify one complete model response using a closed runtime protocol."""

    if protocol not in ("code_action", "final_answer_envelope"):
        raise ValueError(f"Unsupported output protocol: {protocol}")
    if finish_reason == "length":
        _raise_protocol_error(ProtocolErrorReason.TRUNCATED_GENERATION, protocol, logger)

    text = strip_protocol_padding(output)
    if not has_meaningful_visible_content(text):
        _raise_protocol_error(ProtocolErrorReason.EMPTY_VISIBLE_CONTENT, protocol, logger)

    if protocol == "code_action":
        # The platform prompt explicitly requests Think:/Code: (or 思考：/代码：).
        # Only strip that labeled preamble; the complete remaining action still
        # has to match one envelope and pass Python syntax validation.
        preamble_match = _ACTION_PREAMBLE_RE.fullmatch(text)
        if preamble_match:
            preamble = preamble_match.group("preamble")
            if any(marker in preamble for marker in ("<code>", "</code>", "```")):
                _raise_protocol_error(ProtocolErrorReason.MALFORMED_ACTION, protocol, logger)
            text = preamble_match.group("action")
        code_match = _CODE_RE.fullmatch(text)
        if code_match:
            code = code_match.group("body").strip()
            if not has_meaningful_visible_content(code):
                _raise_protocol_error(ProtocolErrorReason.MALFORMED_ACTION, protocol, logger)
            try:
                ast.parse(code)
            except (SyntaxError, ValueError, TypeError):
                _raise_protocol_error(ProtocolErrorReason.MALFORMED_ACTION, protocol, logger)
            return ExecutableAction(code=code)

        run_match = _RUN_RE.fullmatch(text)
        if run_match and text.count("```<RUN>") == 1:
            code = run_match.group("body").strip()
            if not has_meaningful_visible_content(code):
                _raise_protocol_error(ProtocolErrorReason.MALFORMED_ACTION, protocol, logger)
            try:
                ast.parse(code)
            except (SyntaxError, ValueError, TypeError):
                _raise_protocol_error(ProtocolErrorReason.MALFORMED_ACTION, protocol, logger)
            return ExecutableAction(code=code, legacy_format=True)

        if any(marker in text for marker in ("<code>", "</code>", "```<RUN>")):
            _raise_protocol_error(ProtocolErrorReason.MALFORMED_ACTION, protocol, logger)
        if _TAG_RE.search(text):
            _raise_protocol_error(
                ProtocolErrorReason.UNSUPPORTED_OR_TAG_ONLY_OUTPUT,
                protocol,
                logger,
            )
        _raise_protocol_error(
            ProtocolErrorReason.MISSING_EXPLICIT_TERMINATION,
            protocol,
            logger,
        )

    envelope_match = _FINAL_ENVELOPE_RE.fullmatch(text)
    if envelope_match and text.count("<FINAL_ANSWER>") == 1 and text.count("</FINAL_ANSWER>") == 1:
        answer = envelope_match.group("body")
        if not has_meaningful_visible_content(answer):
            _raise_protocol_error(
                ProtocolErrorReason.INVALID_FINAL_ENVELOPE,
                protocol,
                logger,
            )
        return ExplicitFinalAnswer(answer=answer)

    _raise_protocol_error(
        ProtocolErrorReason.INVALID_FINAL_ENVELOPE,
        protocol,
        logger,
    )


def extract_clarification_form(code: str, tool_name: str) -> ClarificationForm | None:
    """Recognize a terminal form before any part of the Python action can execute."""
    try:
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
        if len(code) > 131072 or len(tree.body) != 1 or not isinstance(tree.body[0], ast.Expr):
            raise ValueError("Expected a standalone clarification call")
        call = tree.body[0].value
        if (not isinstance(call, ast.Call) or not isinstance(call.func, ast.Name)
                or call.func.id != tool_name or call.args or len(call.keywords) != 1
                or call.keywords[0].arg != "questions"):
            raise ValueError("Expected only the questions keyword")
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
    except ValidationError as exc:
        # Report schema locations and error types without echoing rejected values.
        fields = {"questions", "id", "type", "title", "required", "options", "label", "allow_other", "placeholder"}
        issues = []
        for error in exc.errors(include_url=False, include_input=False)[:5]:
            location = ".".join(
                str(part) if isinstance(part, int) or part in fields else "<field>"
                for part in error["loc"]
            ) or "questions"
            issues.append(f"{location}: {error['type']}")
        raise ModelOutputProtocolError(
            ProtocolErrorReason.INVALID_CLARIFICATION_FORM,
            "code_action",
            repair_hint="Invalid fields: " + "; ".join(issues) + ".",
        ) from exc
    except (ValueError, TypeError, SyntaxError, RecursionError, MemoryError) as exc:
        raise ModelOutputProtocolError(ProtocolErrorReason.MALFORMED_ACTION, "code_action") from exc
