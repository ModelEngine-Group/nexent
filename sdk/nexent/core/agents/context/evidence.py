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
                    raw_token_estimate=max(call.raw_token_estimate for call in self._calls),
                    history_compression_triggered=any(
                        call.history_compression_triggered for call in self._calls
                    ),
                    new_summary_coverage=next((
                        call.new_summary_coverage for call in reversed(self._calls)
                        if call.new_summary_coverage is not None
                    ), None),
                    summary_persist_status=next((
                        call.summary_persist_status for call in reversed(self._calls)
                        if call.summary_persist_status != "not_attempted"
                    ), "not_attempted"),
                    current_action_compact_count=max(
                        call.current_action_compact_count for call in self._calls
                    ),
                    representation_cache_hits=sum(
                        call.representation_cache_hits for call in self._calls
                    ),
                    representation_cache_misses=sum(
                        call.representation_cache_misses for call in self._calls
                    ),
                    compact_exhausted=any(call.compact_exhausted for call in self._calls),
                    over_hard_budget=any(call.over_hard_budget for call in self._calls),
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
