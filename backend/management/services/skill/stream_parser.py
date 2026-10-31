# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Request-local routing of Skill observer output and attempt boundaries."""

from copy import deepcopy
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
        return [{**self.source, **event} for event in self.classifier.flush()]

    def process(self, chunk: dict[str, Any]) -> list[dict[str, Any]]:
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
