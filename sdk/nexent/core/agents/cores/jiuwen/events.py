# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Translate Jiuwen facts to public observations and one explicit run result."""

import json
import threading
import time
import uuid

from nexent.core.agents.contracts.output import RunResult, StepObservation
from nexent.core.agents.output.answer import AnswerBoundaryError, PublicTextFilter, normalize_public_answer
from nexent.core.model_service.contracts import ModelError
from nexent.core.utils.observer import ProcessType


class JiuwenEventAdapter:
    def __init__(self, observer, agent_name, turn_id=None, *, capacity_provider=None):
        self.observer, self.agent_name = observer, agent_name
        self.turn_id = turn_id or uuid.uuid4().hex
        self.final_answer = None
        self.result = None
        self.last_error = None
        self.blocks = []
        self.calls = []
        self.sequence = 0
        self.step_number = 0
        self._lock = threading.RLock()
        self.capacity_provider = capacity_provider

    def _capacity(self):
        return self.capacity_provider() if self.capacity_provider is not None else None

    def output(self, kind, content="", **metadata):
        with self._lock:
            if self.result is not None:
                raise RuntimeError("Runtime output after terminal result")
            self.sequence += 1
            self.observer.add_message(self.agent_name, kind, content, runtime_envelope={
                "schema_version": 1, "runtime_mode": "native_agent", "agent_core": "jiuwen",
                "turn_id": self.turn_id, "sequence": self.sequence, **metadata,
            })

    def begin_step(self, request):
        if self.final_answer is not None:
            raise RuntimeError("Model step after Runner terminal")
        self.step_number += 1
        self.output(ProcessType.STEP_COUNT, str(self.step_number), step_number=self.step_number)
        self.blocks.append({"id": uuid.uuid4().hex, "text": "", "reasoning": "", "started": time.monotonic(),
                            "filters": {"text": PublicTextFilter(), "reasoning": PublicTextFilter()},
                            "received": set()})

    def _model_text(self, block, key, text, kind):
        block["received"].add(key)
        visible = block["filters"][key].push(text)
        block[key] += visible
        if visible:
            self.output(kind, visible, block_id=block["id"], phase="partial")

    def model_event(self, event):
        if event.type == "error":
            self.record_error(event.error)
            return
        block = self.blocks[-1]
        if event.type in {"text_delta", "reasoning_delta"}:
            reasoning = event.type == "reasoning_delta"
            self._model_text(block, "reasoning" if reasoning else "text", event.delta,
                             ProcessType.MODEL_OUTPUT_DEEP_THINKING if reasoning else ProcessType.MODEL_OUTPUT)
        elif event.type == "message_completed":
            message = event.message
            for key, parts, kind in (("reasoning", message.reasoning_parts, ProcessType.MODEL_OUTPUT_DEEP_THINKING),
                                     ("text", message.content_parts, ProcessType.MODEL_OUTPUT)):
                text = "".join(part.get("text", "") for part in parts if part.get("type") == "text")
                if key not in block["received"] and text:
                    self._model_text(block, key, text, kind)
            block["observed"] = True
            self.calls.extend(message.tool_calls)
            observation = StepObservation(turn_id=self.turn_id, block_id=block["id"],
                step_number=self.step_number, duration=max(0, time.monotonic() - block["started"]),
                usage=message.usage, finish_reason=message.finish_reason, context_capacity=self._capacity())
            self.output(ProcessType.STEP_OBSERVATION, observation.model_dump_json(),
                        block_id=block["id"], phase="intermediate",
                        **observation.model_dump(exclude={"turn_id", "block_id"}))

    def record_error(self, error):
        self.last_error = error
        if self.blocks and not self.blocks[-1].get("observed"):
            block = self.blocks[-1]
            block["observed"] = True
            observation = StepObservation(turn_id=self.turn_id, block_id=block["id"],
                step_number=self.step_number, duration=max(0, time.monotonic() - block["started"]), step_error=error,
                context_capacity=self._capacity())
            self.output(ProcessType.STEP_OBSERVATION, observation.model_dump_json(), block_id=block["id"],
                        phase="partial", **observation.model_dump(exclude={"turn_id", "block_id"}))

    def recovery(self, details):
        """Keep the rejected observation, but do not poison a later successful result."""
        self.output(ProcessType.OTHER, json.dumps({"type": "logical_recovery", **details}),
                    phase="intermediate")
        self.last_error = None

    def tool_call(self, name, arguments, call_id):
        provider_id = None
        with self._lock:
            for index, call in enumerate(self.calls):
                if call.name == name and call.parsed_arguments == arguments:
                    provider_id = self.calls.pop(index).provider_call_id
                    break
            self.output(ProcessType.TOOL, "", local_call_id=call_id, provider_call_id=provider_id,
                        tool_call_id=call_id, tool_name=name, tool_arguments=arguments,
                        raw_arguments=json.dumps(arguments, ensure_ascii=False))
        return provider_id

    def tool_result(self, call_id, provider_id, result, is_error=False):
        self.output(ProcessType.TOOL_RESULT, str(result), local_call_id=call_id,
                    tool_call_id=call_id, provider_call_id=provider_id, result=str(result), is_error=is_error)

    def emit(self, chunk):
        kind, payload = getattr(chunk, "type", None), getattr(chunk, "payload", None)
        if isinstance(chunk, dict):
            kind, payload = chunk.get("type", kind), chunk.get("payload", payload)
        if kind == "answer":
            if self.final_answer is not None:
                self.last_error = self.error("JIUWEN_DUPLICATE_TERMINAL")
                raise RuntimeError("Jiuwen emitted multiple terminal answers")
            if not isinstance(payload, dict) or payload.get("result_type") == "error":
                raise RuntimeError("Jiuwen agent execution failed")
            output = payload.get("output")
            if not isinstance(output, str) or not output.strip():
                raise RuntimeError("Jiuwen returned no final answer")
            try:
                self.final_answer = normalize_public_answer(output)
            except AnswerBoundaryError:
                self.last_error = self.error("JIUWEN_FINAL_OUTPUT_INVALID")
                raise
        elif kind == "context.usage" and isinstance(payload, dict):
            self.observer.add_message(self.agent_name, ProcessType.TOKEN_COUNT, json.dumps(payload))
        # ModelService owns ordered content/reasoning; native llm_output would duplicate it.

    def error(self, category):
        return ModelError(category=category, scope="protocol", retryable=False, safe_message=category,
                          request_id=self.turn_id)

    def finish(self, status="completed", error=None):
        if self.result is not None:
            return self.result
        error = error or self.last_error
        if status == "completed" and self.final_answer is None and error is None:
            error = self.error("JIUWEN_TERMINAL_MISSING")
        if error is not None and status == "completed":
            status = "failed"
        if status == "failed" and error is None:
            error = self.error("JIUWEN_EXECUTION_FAILED")
        final_ids = []
        if status == "completed":
            matching = next((b for b in reversed(self.blocks) if b["text"].strip() == self.final_answer), None)
            if matching is None:
                matching = {"id": uuid.uuid4().hex, "text": self.final_answer}
                self.blocks.append(matching)
                self.output(ProcessType.MODEL_OUTPUT, self.final_answer, block_id=matching["id"], phase="partial")
            final_ids = [matching["id"]]
        result = RunResult(turn_id=self.turn_id, status=status,
            end_reason="runner_answer" if status == "completed" else "cancelled" if status == "stopped"
            else (error.category if error else "JIUWEN_EXECUTION_FAILED"),
            final_content=self.final_answer if status == "completed" else "", final_block_ids=final_ids,
            error=error if status != "completed" else None)
        if status == "completed":
            self.observer.add_message(self.agent_name, ProcessType.FINAL_ANSWER, self.final_answer)
        self.output(ProcessType.RUN_TERMINAL, result.model_dump_json(), **result.model_dump(exclude={"turn_id"}))
        self.result = result
        return result
