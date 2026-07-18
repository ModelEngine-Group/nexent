"""Run-scoped aggregation for one evidence record per agent loop."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, replace
from threading import Lock

from ...context_runtime.contracts import ContextEvidence


logger = logging.getLogger("context_evidence")


class ContextEvidenceCollector:
    """Collect internal model-call snapshots and emit one final loop record."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._calls: list[ContextEvidence] = []
        self._finalized: ContextEvidence | None = None

    def reset(self) -> None:
        with self._lock:
            self._calls.clear()
            self._finalized = None

    def record_call(self, evidence: ContextEvidence) -> None:
        with self._lock:
            if self._finalized is not None:
                raise RuntimeError("context evidence loop is already finalized")
            self._calls.append(evidence)

    def finalize(self, *, status: str) -> ContextEvidence:
        with self._lock:
            if self._finalized is not None:
                return self._finalized
            if not self._calls:
                self._finalized = ContextEvidence(loop_status=status)
            else:
                latest = self._calls[-1]
                compression_records = tuple(
                    record
                    for call in self._calls
                    for record in call.compression_records
                )
                self._finalized = replace(
                    latest,
                    compression_records=compression_records,
                    model_call_count=len(self._calls),
                    loop_status=status,
                )
            payload = asdict(self._finalized)
        logger.info(
            "Agent loop context evidence: %s",
            json.dumps(payload, ensure_ascii=False, default=str, sort_keys=True),
        )
        return self._finalized

    @property
    def finalized(self) -> ContextEvidence | None:
        return self._finalized
