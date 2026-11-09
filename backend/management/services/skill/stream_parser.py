# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Request-local routing of Skill observer output and attempt boundaries."""

from copy import deepcopy
import json
from typing import Any

from management.services.skill.classifier import ContentClassifier


PARSABLE_MODEL_TYPES = frozenset(
    {
        "model_output",
        "model_output_thinking",
        "model_output_code",
        "model_thinking_output",
    }
)


def _business_event(event: dict[str, Any]) -> dict[str, Any]:
    """Keep creator provenance without claiming to be a native runtime envelope."""
    if (type(event.get("schema_version")) is int and event["schema_version"] == 1
            and event.get("runtime_mode") == "native_agent"
            and isinstance(event.get("turn_id"), str) and event["turn_id"]):
        return {key: value for key, value in event.items() if key not in {"schema_version", "runtime_mode"}}
    return event


def project_skill_history_units(units: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Read old creator artifact wrappers without changing their saved contents."""
    projected = []
    for unit in units:
        item = unit
        if unit.get("unit_type") in {"skill_body", "file_content"}:
            try:
                event = json.loads(unit.get("unit_content", ""))
            except (ValueError, TypeError):
                event = None
            if (isinstance(event, dict) and event.get("type") == unit["unit_type"]
                    and isinstance(event.get("content"), str)):
                business = _business_event(event)
                if business is not event:
                    item = {**unit, "unit_content": json.dumps(business, ensure_ascii=False)}
        projected.append(item)
    return projected


class SkillStreamParser:
    """Classify deltas exactly once and restore parser state on model rollback."""

    def __init__(self) -> None:
        self.classifier = ContentClassifier()
        self.source: dict[str, Any] = {}
        self.has_answer_delta = False
        self.checkpoints: dict[str, tuple[ContentClassifier, dict[str, Any], bool]] = {}

    def _classify(self, chunk: dict[str, Any]) -> list[dict[str, Any]]:
        self.source = chunk
        return [
            {**chunk, **event}
            for event in self.classifier.classify(
                str(chunk.get("content") or ""),
                origin_type=chunk["type"],
            )
        ]

    def flush(self) -> list[dict[str, Any]]:
        """Flush with the producing chunk's metadata, before attempt commit."""
        return [_business_event({**self.source, **event}) for event in self.classifier.flush()]

    def process(self, chunk: dict[str, Any]) -> list[dict[str, Any]]:
        return [_business_event(event) for event in self._process(chunk)]

    def _process(self, chunk: dict[str, Any]) -> list[dict[str, Any]]:
        kind = chunk.get("type")
        # Provider reasoning can quote the entire output protocol. It is never
        # a generated file and must not advance the answer classifier state.
        if kind == "model_output_deep_thinking":
            return [chunk]
        if kind == "model_attempt_control":
            attempt_id = chunk.get("attempt_id")
            phase = chunk.get("phase")
            if phase == "begin" and attempt_id:
                self.checkpoints[attempt_id] = (
                    deepcopy(self.classifier),
                    self.source,
                    self.has_answer_delta,
                )
                self.classifier = ContentClassifier()
                self.source = {}
                self.has_answer_delta = False
            elif phase == "rollback" and attempt_id in self.checkpoints:
                self.classifier, self.source, self.has_answer_delta = self.checkpoints.pop(attempt_id)
            elif phase == "commit" and attempt_id in self.checkpoints:
                events = self.flush()
                del self.checkpoints[attempt_id]
                return [*events, chunk]
            return [chunk]

        if kind in PARSABLE_MODEL_TYPES:
            return self._classify(chunk)
        if kind != "final_answer":
            return [chunk]

        phase = chunk.get("answer_phase")
        if phase == "delta":
            self.has_answer_delta |= bool(chunk.get("content"))
            return self._classify(chunk)

        # Legacy final answers repeat raw tagged output; modern completion
        # confirms previously streamed answer deltas, even with a full body.
        if self.has_answer_delta or self.classifier.saw_control_tag:
            return self.flush()
        if phase == "complete":
            return [*self._classify(chunk), *self.flush()]
        if "<" in str(chunk.get("content") or "") or self.classifier.buffer:
            return self._classify(chunk)
        return [chunk]
