# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Strict recognition of the existing, explicitly executable text protocol."""

import ast
import re
from dataclasses import dataclass


EXECUTION_TOOL = "nexent_execute_block"
NATIVE_EXECUTION_TOOL = "nexent_execute_python"
PROTOCOL_INSTRUCTION = (
    "This outlet uses the controlled text execution protocol, not native function calls. "
    "Only complete <code>...</code> blocks request Python execution with the listed authorized tools. "
    "For each action step emit one complete, non-nested <code>...</code> block with only Python inside. "
    "Never put code tags inside a code block, repeat opening tags, or wrap executable tags in Markdown fences. "
    "Ordinary prose and fenced Python examples are not executable. "
    "After execution, use the returned observation to continue or answer. "
    "Do not combine an executable block with a final_answer envelope. "
    "When finished, answer in ordinary text without code tags or a final_answer envelope."
)


class JiuwenProtocolError(ValueError):
    """Expose a stable code, never the rejected model content or arguments."""


@dataclass(frozen=True)
class TextExecution:
    code: str


def parse_execution_blocks(content: str) -> TextExecution | None:
    """Accept complete code/run blocks; reject ambiguous or partial control syntax."""
    has_code = "<code>" in content or "</code>" in content
    has_run = "```<run>" in content
    if not has_code and not has_run:
        return None
    if has_code and has_run or "<final_answer>" in content or "</final_answer>" in content:
        raise JiuwenProtocolError("JIUWEN_AMBIGUOUS_EXECUTION_BLOCK")
    pattern = r"<code>(.*?)</code>" if has_code else r"```<run>\s*(.*?)```"
    matches = list(re.finditer(pattern, content, re.DOTALL))
    if not matches:
        raise JiuwenProtocolError("JIUWEN_INCOMPLETE_EXECUTION_BLOCK")
    # Examples stay non-executable even when they contain malformed nested tags.
    for match in matches:
        if content[:match.start()].count("```") % 2:
            raise JiuwenProtocolError("JIUWEN_AMBIGUOUS_EXECUTION_BLOCK")
    if any(any(marker in match.group(1) for marker in ("<code>", "</code>", "```<run>")) for match in matches):
        raise JiuwenProtocolError("JIUWEN_NESTED_EXECUTION_BLOCK")
    remainder = re.sub(pattern, "", content, flags=re.DOTALL)
    if any(marker in remainder for marker in ("<code>", "</code>", "```<run>")):
        raise JiuwenProtocolError("JIUWEN_INCOMPLETE_EXECUTION_BLOCK")
    code = "\n\n".join(match.group(1).strip() for match in matches)
    if not code:
        raise JiuwenProtocolError("JIUWEN_EMPTY_EXECUTION_BLOCK")
    try:
        ast.parse(code, mode="exec")
    except (SyntaxError, ValueError, RecursionError):
        raise JiuwenProtocolError("JIUWEN_INVALID_EXECUTION_BLOCK") from None
    return TextExecution(code)
