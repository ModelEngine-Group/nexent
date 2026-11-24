# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Closed output protocol for Nexent CodeAgent runtimes."""

from __future__ import annotations

import ast
import io
import re
import tokenize
import unicodedata
from dataclasses import dataclass
from enum import Enum
from typing import Any, Literal, NoReturn

from pydantic import ValidationError

from nexent.core.agents.contracts.adapter import ModelOutputProtocolExhaustedError as ModelOutputProtocolExhaustedError
from nexent.core.agents.contracts.clarification import ClarificationForm, parse_clarification_call
from nexent.core.agents.output.answer import EXECUTION_RECORD_TAGS, contains_provider_tool_markup
from nexent.core.agents.prompt.clarification import CLARIFICATION_SCHEMA_GUIDANCE


OutputProtocol = Literal["code_action", "final_envelope"]


class ProtocolErrorReason(str, Enum):
    """Stable classifications for invalid model output."""

    EMPTY_VISIBLE_CONTENT = "empty_visible_content"
    UNSUPPORTED_OR_TAG_ONLY_OUTPUT = "unsupported_or_tag_only_output"
    MALFORMED_ACTION = "malformed_action"
    PROVIDER_TOOL_MARKUP = "provider_tool_markup"
    RUNTIME_HISTORY_ECHO = "runtime_history_echo"
    MISSING_EXPLICIT_TERMINATION = "missing_explicit_termination"
    TRUNCATED_GENERATION = "truncated_generation"
    INVALID_FINAL_ENVELOPE = "invalid_final_envelope"
    INVALID_CLARIFICATION_FORM = "invalid_clarification_form"



@dataclass(frozen=True)
class ExecutableAction:
    """One validated Python action ready for the executor."""

    code: str
    legacy_format: bool = False
    final_answer: str | None = None


@dataclass(frozen=True)
class ExplicitFinalAnswer:
    """One validated final-answer envelope payload."""

    answer: str


@dataclass(frozen=True)
class NonterminalThought:
    """Complete visible text with no executable action or final signal."""


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


_FINAL_ENVELOPE_RE = re.compile(r"\A<FINAL_ANSWER>(?P<body>[\s\S]*)</FINAL_ANSWER>\Z", re.IGNORECASE)
_MODEL_CONTROL_TOKEN_RE = re.compile(r"<\|[^<>]{1,255}\|>")
_RUNTIME_HISTORY_ECHO_RE = re.compile(
    r"<\s*/?\s*(?:" + "|".join(sorted(EXECUTION_RECORD_TAGS)) + r")\b",
    re.IGNORECASE,
)
_RUNTIME_RECORD_RE = re.compile(_RUNTIME_HISTORY_ECHO_RE.pattern + r"|</?result>", re.IGNORECASE)
_CODE_MARKER_RE = re.compile(r"</?code>", re.IGNORECASE)
_PROTOCOL_MARKER_RE = re.compile(r"</?(?:code|final_answer)>|```<run>", re.IGNORECASE)
_MARKDOWN_RE = re.compile(
    r"(?m)^[ \t]{0,3}(?P<fence>`{3,}|~{3,})[^\n]*\n"
    r"[\s\S]*?(?:^[ \t]{0,3}(?P=fence)[ \t]*(?:\n|$)|\Z)"
    r"|(?P<ticks>`+)[\s\S]*?(?P=ticks)"
)
_PYTHON_FENCE_RE = re.compile(
    r"```python[^\S\r\n]*\r?\n(?P<body>[\s\S]*?)\r?\n[ \t]*```",
    re.IGNORECASE,
)
_CODE_OPEN = "<code>"
_CODE_CLOSE = "</code>"
_TRAILING_CODE_CLOSERS_RE = re.compile(r"(?:</code>\s*)+\Z", re.IGNORECASE)
_PYTHON_DATA_TOKEN_TYPES = {
    tokenize.STRING,
    tokenize.COMMENT,
    *([tokenize.FSTRING_MIDDLE] if hasattr(tokenize, "FSTRING_MIDDLE") else []),
}


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
    if protocol == "final_envelope":
        return (
            prefix + "Return exactly one complete <final_answer>...</final_answer> envelope. "
            "Put the required <skill>, <file>, and <summary> content inside it, with no content outside the envelope."
        )
    if reason in {ProtocolErrorReason.PROVIDER_TOOL_MARKUP, ProtocolErrorReason.RUNTIME_HISTORY_ECHO}:
        return (
            prefix + "Resume the unfinished task from the last successful execution result. "
            "Emit the next actual Python or tool action in a top-level <code>...</code> block. "
            "For a tool, call its registered Python function by name inside that block. "
            "Resolve missing prerequisites or failed steps before requesting their dependent tools. "
            "Do not echo runtime history or emit DSML or serialized tool tags. Do not repeat successful actions. "
            "Return a final answer only after the required actions have returned real results."
        )
    if reason == ProtocolErrorReason.INVALID_CLARIFICATION_FORM:
        return (
            prefix + "Return one standalone call to the configured clarification tool inside <code>...</code>, "
            "with 1-5 literal question objects. Do not use final_answer to solicit input. "
            + CLARIFICATION_SCHEMA_GUIDANCE
        )

    return (
        prefix + "Return optional reasoning followed by one or more complete <code>...</code> blocks. "
        "Only top-level protocol blocks execute; Markdown examples are data. Blocks execute together in order. "
        "To finish, put one complete <final_answer>...</final_answer> envelope at the end. "
        "When actions precede it, the runtime executes them and requests confirmation using the actual results."
    )


def _raise_protocol_error(
    reason: ProtocolErrorReason,
    protocol: OutputProtocol,
    logger: Any,
) -> NoReturn:
    raise ModelOutputProtocolError(reason, protocol, logger)


def _parse_executable_action(
    code: str,
    *,
    protocol: OutputProtocol,
    logger: Any,
    legacy_format: bool = False,
) -> ExecutableAction:
    code = code.strip()
    if not has_meaningful_visible_content(code):
        _raise_protocol_error(ProtocolErrorReason.MALFORMED_ACTION, protocol, logger)
    try:
        ast.parse(code)
    except (SyntaxError, ValueError, TypeError):
        _raise_protocol_error(ProtocolErrorReason.MALFORMED_ACTION, protocol, logger)
    return ExecutableAction(code=code, legacy_format=legacy_format)


def _line_offsets(value: str) -> list[int]:
    offsets = [0]
    for match in re.finditer("\n", value):
        offsets.append(match.end())
    return offsets


def _absolute_offset(offsets: list[int], position: tuple[int, int]) -> int:
    line, column = position
    return offsets[line - 1] + column


def _python_literal_and_comment_spans(value: str) -> list[tuple[int, int]]:
    """Return source spans whose protocol-like text is Python data, not markup."""

    offsets = _line_offsets(value)
    spans: list[tuple[int, int]] = []
    try:
        tokens = tokenize.generate_tokens(io.StringIO(value).readline)
        for token in tokens:
            if token.type not in _PYTHON_DATA_TOKEN_TYPES:
                continue
            spans.append(
                (
                    _absolute_offset(offsets, token.start),
                    _absolute_offset(offsets, token.end),
                )
            )
    except (tokenize.TokenError, IndentationError, SyntaxError):
        # Lexically incomplete Python cannot form a complete executable Action.
        return spans
    return spans


def _position_in_spans(position: int, spans: list[tuple[int, int]]) -> bool:
    return any(start <= position < end for start, end in spans)


def _outer_code_markers(action_region: str) -> list[re.Match[str]]:
    """Find code protocol markers while ignoring markers in strings/comments."""

    matches = list(_CODE_MARKER_RE.finditer(action_region))
    sanitized = list(action_region)
    for match in matches:
        sanitized[match.start() : match.end()] = " " * (match.end() - match.start())
    spans = _python_literal_and_comment_spans("".join(sanitized))
    return [match for match in matches if not _position_in_spans(match.start(), spans)]


def _markdown_spans(text: str) -> list[tuple[int, int]]:
    """Identify quoted examples before interpreting protocol markers."""
    return [(match.start(), match.end()) for match in _MARKDOWN_RE.finditer(text)
            if not match.group(0).lower().startswith("```<run>")]


def contains_runtime_record_echo(text: str) -> bool:
    """Recognize reserved execution markup outside quoted examples and Python literals."""
    records = list(_RUNTIME_HISTORY_ECHO_RE.finditer(text))
    if not records:
        return False
    spans = _markdown_spans(text)
    markers = _outer_code_markers(text)
    for opening, closing in zip(markers, markers[1:]):
        if opening.group().lower() != _CODE_OPEN or closing.group().lower() != _CODE_CLOSE:
            continue
        start = opening.end()
        spans.extend(
            (start + left, start + right)
            for left, right in _python_literal_and_comment_spans(text[start:closing.start()])
        )
    return any(not _position_in_spans(record.start(), spans) for record in records)


def has_unquoted_match(text: str, pattern: re.Pattern[str]) -> bool:
    """Find a protocol marker outside Markdown code examples."""
    examples = _markdown_spans(text)
    return any(not _position_in_spans(match.start(), examples) for match in pattern.finditer(text))


def restore_stopped_code_closer(output: Any, finish_reason: str | None) -> Any:
    """Restore a delimiter removed by a stop-capable text provider."""
    if finish_reason != "stop" or not isinstance(output, str):
        return output
    examples = _markdown_spans(output)
    first_marker = next(
        (marker for marker in _PROTOCOL_MARKER_RE.finditer(output)
         if marker.group().lower() != _CODE_CLOSE and not _position_in_spans(marker.start(), examples)),
        None,
    )
    if first_marker is None or first_marker.group().lower() != _CODE_OPEN:
        return output
    markers = _outer_code_markers(output[first_marker.start():])
    if len(markers) != 1:
        return output
    separator = "" if output.endswith("\n") else "\n"
    return output + separator + _CODE_CLOSE


def is_stray_code_closer_only(output: Any) -> bool:
    return _TRAILING_CODE_CLOSERS_RE.fullmatch(strip_protocol_padding(output)) is not None


def is_raw_final_answer_candidate(output: Any) -> bool:
    """Keep reserved protocol records out of the exhaustion-only fallback."""
    text = strip_protocol_padding(output)
    return (
        has_meaningful_visible_content(text)
        and not _PROTOCOL_MARKER_RE.search(text)
        and not _MODEL_CONTROL_TOKEN_RE.search(text)
        and not contains_provider_tool_markup(text)
        and not _RUNTIME_RECORD_RE.search(text)
        and not re.search(r"</?(?:think|tool_call|code_exec_result|summaried_result|output_ref)\b", text, re.I)
    )


def _classify_code_action(
    text: str,
    *,
    protocol: OutputProtocol,
    logger: Any,
) -> ExecutableAction | ExplicitFinalAnswer | NonterminalThought:
    bodies: list[str] = []
    position = 0
    legacy = False
    final_answer = None
    while True:
        remaining = text[position:]
        examples = _markdown_spans(remaining)
        marker = next((candidate for candidate in _PROTOCOL_MARKER_RE.finditer(remaining)
                       if not _position_in_spans(candidate.start(), examples)), None)
        prefix_end = marker.start() if marker else len(remaining)
        if any(not _position_in_spans(token.start(), examples)
               for token in _MODEL_CONTROL_TOKEN_RE.finditer(remaining[:prefix_end])):
            _raise_protocol_error(ProtocolErrorReason.MALFORMED_ACTION, protocol, logger)
        if any(not _position_in_spans(token.start(), examples)
               for token in _RUNTIME_RECORD_RE.finditer(remaining[:prefix_end])):
            _raise_protocol_error(ProtocolErrorReason.UNSUPPORTED_OR_TAG_ONLY_OUTPUT, protocol, logger)
        if marker is None:
            break
        start = position + marker.start()
        end = position + marker.end()
        tag = marker.group().lower()
        if tag == _CODE_CLOSE:
            position = end
            continue
        if tag == "<final_answer>":
            envelope = _TRAILING_CODE_CLOSERS_RE.sub("", text[start:]).rstrip()
            final = _classify_final_envelope(envelope, protocol=protocol, logger=logger)
            final_answer = final.answer
            break
        if tag == "```<run>":
            close = text.find("```", end)
            if close < 0:
                _raise_protocol_error(ProtocolErrorReason.MALFORMED_ACTION, protocol, logger)
            bodies.append(strip_protocol_padding(text[end:close]))
            position = close + 3
            legacy = True
            continue
        if tag != _CODE_OPEN:
            _raise_protocol_error(ProtocolErrorReason.MALFORMED_ACTION, protocol, logger)
        region = text[start:]
        markers = _outer_code_markers(region)
        if len(markers) < 2 or markers[1].group().lower() != _CODE_CLOSE:
            _raise_protocol_error(ProtocolErrorReason.MALFORMED_ACTION, protocol, logger)
        body = strip_protocol_padding(region[markers[0].end():markers[1].start()])
        fence = _PYTHON_FENCE_RE.fullmatch(body)
        if fence:
            body = strip_protocol_padding(fence.group("body"))
        if not has_meaningful_visible_content(body):
            _raise_protocol_error(ProtocolErrorReason.MALFORMED_ACTION, protocol, logger)
        bodies.append(body)
        position = start + markers[1].end()
    if bodies:
        action = _parse_executable_action("\n\n".join(bodies), protocol=protocol, logger=logger,
                                          legacy_format=legacy)
        return ExecutableAction(action.code, action.legacy_format, final_answer)
    if final_answer is not None:
        return ExplicitFinalAnswer(final_answer)
    if re.search(r"</?(?:think|tool_call|display:python)\b", text, re.I):
        _raise_protocol_error(ProtocolErrorReason.UNSUPPORTED_OR_TAG_ONLY_OUTPUT, protocol, logger)
    return NonterminalThought()


def _classify_final_envelope(
    text: str,
    *,
    protocol: OutputProtocol,
    logger: Any,
) -> ExplicitFinalAnswer:
    envelope_match = _FINAL_ENVELOPE_RE.fullmatch(text)
    if envelope_match and text.lower().count("<final_answer>") == 1 and text.lower().count("</final_answer>") == 1:
        answer = envelope_match.group("body")
        if contains_runtime_record_echo(answer):
            _raise_protocol_error(ProtocolErrorReason.UNSUPPORTED_OR_TAG_ONLY_OUTPUT, protocol, logger)
        if has_meaningful_visible_content(answer):
            return ExplicitFinalAnswer(answer=answer)
    _raise_protocol_error(
        ProtocolErrorReason.INVALID_FINAL_ENVELOPE,
        protocol,
        logger,
    )


def classify_model_output(
    output: Any,
    *,
    protocol: OutputProtocol,
    finish_reason: str | None = None,
    logger: Any = None,
) -> ExecutableAction | ExplicitFinalAnswer | NonterminalThought:
    """Classify one complete model response using a closed runtime protocol."""

    if protocol not in ("code_action", "final_envelope"):
        raise ValueError(f"Unsupported output protocol: {protocol}")
    if finish_reason == "length":
        _raise_protocol_error(ProtocolErrorReason.TRUNCATED_GENERATION, protocol, logger)

    text = strip_protocol_padding(output)
    if contains_provider_tool_markup(text):
        _raise_protocol_error(ProtocolErrorReason.PROVIDER_TOOL_MARKUP, protocol, logger)
    if not has_meaningful_visible_content(text):
        _raise_protocol_error(ProtocolErrorReason.EMPTY_VISIBLE_CONTENT, protocol, logger)

    if protocol == "final_envelope":
        return _classify_final_envelope(text, protocol=protocol, logger=logger)
    return _classify_code_action(text, protocol=protocol, logger=logger)


def extract_clarification_form(code: str, tool_name: str) -> ClarificationForm | None:
    """Recognize a terminal form before any part of the Python action can execute."""
    try:
        return parse_clarification_call(code, tool_name)
    except ValidationError as exc:
        # Report schema locations and error types without echoing rejected values.
        fields = {"questions", "id", "type", "title", "required", "options", "label", "allow_other", "placeholder", "creation_request"}
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
            repair_hint=f"Use <code>{tool_name}(questions=[...])</code>. Invalid fields: " + "; ".join(issues) + ".",
        ) from exc
    except (ValueError, TypeError, SyntaxError, RecursionError, MemoryError) as exc:
        raise ModelOutputProtocolError(
            ProtocolErrorReason.MALFORMED_ACTION,
            "code_action",
            repair_hint=(
                f"The clarification was not executed. Return <code>{tool_name}(questions=[...])</code> "
                "as a terminal action with literal question data only. Do not mix it with business tools, "
                "imports, dynamic expressions, or other statements. Assignment is optional; only a single "
                "print of that same result is accepted after it. " + CLARIFICATION_SCHEMA_GUIDANCE
            ),
        ) from exc
