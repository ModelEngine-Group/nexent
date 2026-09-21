"""Closed output protocol for Nexent CodeAgent runtimes."""

from __future__ import annotations

import ast
import re
import unicodedata
from dataclasses import dataclass
from enum import Enum
from typing import Any, Literal


OutputProtocol = Literal["code_action", "final_answer_envelope"]


class ProtocolErrorReason(str, Enum):
    """Stable classifications for invalid model output."""

    EMPTY_VISIBLE_CONTENT = "empty_visible_content"
    UNSUPPORTED_OR_TAG_ONLY_OUTPUT = "unsupported_or_tag_only_output"
    MALFORMED_ACTION = "malformed_action"
    MISSING_EXPLICIT_TERMINATION = "missing_explicit_termination"
    TRUNCATED_GENERATION = "truncated_generation"
    INVALID_FINAL_ENVELOPE = "invalid_final_envelope"


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
    ) -> None:
        self.reason = reason
        self.protocol = protocol
        self.repair_instruction = protocol_repair_instruction(protocol, reason)
        super().__init__(self.repair_instruction)
        self.message = self.repair_instruction


class RuntimeFinalAnswer(Exception):
    """A trusted runtime-controlled terminal answer."""

    def __init__(self, answer: Any, source: str) -> None:
        super().__init__(source)
        self.answer = answer
        self.source = source


_CODE_RE = re.compile(r"\A<code>(?P<body>[\s\S]*)</code>\Z")
_RUN_RE = re.compile(r"\A```<RUN>(?P<body>[\s\S]*?)```\Z")
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
