# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Adapt the shared terminal form to Jiuwen's two execution protocols."""

import asyncio
import json
import re

from pydantic import ValidationError

from nexent.core.agents.contracts.clarification import (
    ClarificationForm,
    choose_clarification_tool_name,
    parse_clarification_call,
)
from nexent.core.agents.cores.jiuwen.protocol import EXECUTION_TOOL, NATIVE_EXECUTION_TOOL, JiuwenProtocolError
from nexent.core.agents.prompt.clarification import clarification_policy, native_clarification_policy


WORKBENCH_CONFIRMATION_REQUIRED = "JIUWEN_WORKBENCH_CONFIRMATION_REQUIRED"
_WORKBENCH_QUESTION = "workbench_creation_mode"
_FORM_START = re.compile(r'\{\s*"questions"\s*:\s*\[')


class ClarificationRequested(asyncio.CancelledError):
    """Unwind the native loop without cancelling the run's resource scope."""

    def __init__(self, form: ClarificationForm):
        super().__init__("NEXENT_CLARIFICATION_REQUESTED")
        self.form = form


class InvalidClarification(JiuwenProtocolError):
    def __init__(self, reason, issues=()):
        super().__init__("JIUWEN_INVALID_CLARIFICATION")
        self.reason = reason
        self.issues = issues


_FORM_FIELDS = frozenset(
    {"questions", "id", "type", "title", "required", "options", "allow_other", "placeholder", "creation_request", "label"}
)
_FORM_REASONS = {
    "clarification_too_few_choices": "clarification_too_few_choices",
    "clarification_duplicate_option_id": "clarification_duplicate_ids",
    "clarification_duplicate_question_id": "clarification_duplicate_ids",
}


class JiuwenClarification:
    def __init__(self, occupied: set[str], *, workbench: bool = False):
        self.name = choose_clarification_tool_name(occupied)
        self.schema = ClarificationForm.model_json_schema()
        self.workbench = workbench

    def instructions(self, language="en", *, text_protocol=False):
        render = clarification_policy if text_protocol else native_clarification_policy
        instructions = render(self.name, language)
        if self.workbench and not text_protocol:
            if language == "zh":
                return instructions + f"\n进入创建模式时，只发出原生 {self.name} 工具调用。确认表单是工具参数，正文留空。"
            return instructions + f"\nFor creation-mode confirmation, call {self.name} natively and leave the reply text empty."
        return instructions

    def has_workbench_form_text(self, content):
        """Detect a bare trailing confirmation form for regeneration, never for execution."""
        if not self.workbench or f'"{_WORKBENCH_QUESTION}"' not in content:
            return False
        for match in _FORM_START.finditer(content):
            try:
                form = json.loads(content[match.start():])
            except (ValueError, RecursionError):
                continue
            questions = form.get("questions")
            if set(form) == {"questions"} and isinstance(questions, list) and any(
                isinstance(question, dict) and question.get("id") == _WORKBENCH_QUESTION
                for question in questions
            ):
                return True
        return False

    def workbench_repair_instruction(self):
        return (
            f"Call {self.name} as the only native tool action for Workbench creation confirmation. "
            f"Use one single_choice question with id {_WORKBENCH_QUESTION}, include the complete "
            "creation_request from the conversation, and offer the relevant creation mode and continue_chat. "
            "Leave the assistant reply text empty."
        )

    def form_for(self, calls, *, text_protocol):
        """Validate the complete action before any sibling call can be dispatched."""
        form = None
        try:
            for call in calls:
                arguments = json.loads(call.arguments)
                if call.name == self.name:
                    if text_protocol:
                        raise InvalidClarification("clarification_mode_mismatch")
                    form = ClarificationForm.model_validate(arguments)
                elif call.name in {EXECUTION_TOOL, NATIVE_EXECUTION_TOOL}:
                    candidate = parse_clarification_call(arguments["code"], self.name)
                    if candidate is not None:
                        if not text_protocol or call.name != EXECUTION_TOOL:
                            raise InvalidClarification("clarification_mode_mismatch")
                        form = candidate
            if form is not None and len(calls) != 1:
                raise InvalidClarification("clarification_mixed_actions")
            return form
        except InvalidClarification:
            raise
        except ValidationError as error:
            # Locations for forbidden extra keys can contain arbitrary model text.
            issues = tuple(
                (issue["type"], tuple(part if isinstance(part, int) or part in _FORM_FIELDS else "<extra>"
                                      for part in issue["loc"]))
                for issue in error.errors(include_input=False, include_context=False, include_url=False)[:5]
            )
            reason = "clarification_form_invalid"
            if issues:
                kind, path = issues[0]
                if path == ("questions",) and kind in {"missing", "too_short", "too_long"}:
                    reason = "clarification_question_count"
                else:
                    reason = _FORM_REASONS.get(kind, reason)
            raise InvalidClarification(reason, issues) from None
        except (ValueError, TypeError, KeyError, SyntaxError, RecursionError, MemoryError):
            raise InvalidClarification("clarification_call_invalid") from None
