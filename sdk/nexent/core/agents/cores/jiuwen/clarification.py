# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Adapt the shared terminal form to Jiuwen's two execution protocols."""

import asyncio
import json

from nexent.core.agents.contracts.clarification import (
    ClarificationForm,
    choose_clarification_tool_name,
    parse_clarification_call,
)
from nexent.core.agents.cores.jiuwen.protocol import EXECUTION_TOOL, NATIVE_EXECUTION_TOOL, JiuwenProtocolError
from nexent.core.agents.prompt.clarification import clarification_policy, native_clarification_policy


class ClarificationRequested(asyncio.CancelledError):
    """Unwind the native loop without cancelling the run's resource scope."""

    def __init__(self, form: ClarificationForm):
        super().__init__("NEXENT_CLARIFICATION_REQUESTED")
        self.form = form


class JiuwenClarification:
    def __init__(self, occupied: set[str]):
        self.name = choose_clarification_tool_name(occupied)
        self.schema = ClarificationForm.model_json_schema()

    def instructions(self, language="en", *, text_protocol=False):
        render = clarification_policy if text_protocol else native_clarification_policy
        return render(self.name, language)

    def form_for(self, calls, *, text_protocol):
        """Validate the complete action before any sibling call can be dispatched."""
        form = None
        try:
            for call in calls:
                arguments = json.loads(call.arguments)
                if call.name == self.name:
                    if text_protocol:
                        raise ValueError("Native clarification in text mode")
                    form = ClarificationForm.model_validate(arguments)
                elif call.name in {EXECUTION_TOOL, NATIVE_EXECUTION_TOOL}:
                    candidate = parse_clarification_call(arguments["code"], self.name)
                    if candidate is not None:
                        if not text_protocol or call.name != EXECUTION_TOOL:
                            raise ValueError("Clarification cannot execute in the sandbox")
                        form = candidate
            if form is not None and len(calls) != 1:
                raise ValueError("Clarification must be the sole action")
            return form
        except (ValueError, TypeError, KeyError, SyntaxError, RecursionError, MemoryError):
            raise JiuwenProtocolError("JIUWEN_INVALID_CLARIFICATION") from None
