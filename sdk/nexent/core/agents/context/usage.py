# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Request-local usage calibration; summary calls never update this baseline."""

import logging
from dataclasses import dataclass


def record_capacity_rejection(*, local_tokens, estimated_tokens, limit, baseline, model_key):
    """Record numeric provenance without logging any input or model credentials."""
    calibrated = (baseline.model_key == model_key and baseline.actual_input_tokens is not None
                  and baseline.request_estimate is not None)
    source = baseline.source if calibrated or baseline.source != "provider_calibrated" else "estimated"
    logging.getLogger("agent_context.runtime").warning(
        "event=context_input_rejected local_input=%s calibrated_input=%s combined_window=%s "
        "usage_source=%s provider_input=%s previous_request_estimate=%s",
        local_tokens, estimated_tokens, limit, source,
        baseline.actual_input_tokens if calibrated else None,
        baseline.request_estimate if calibrated else None,
    )


@dataclass
class ContextUsageBaseline:
    """Anchor estimates to one accepted request, never cumulative billing usage."""

    model_key: object = None
    request_estimate: int | None = None
    actual_input_tokens: int | None = None
    pending_model_key: object = None
    pending_estimate: int | None = None
    source: str = "estimated"

    def capture(self, estimate: int, model_key: object) -> None:
        self.pending_estimate = estimate
        self.pending_model_key = model_key

    def accept(self, input_tokens: int | None) -> bool:
        if self.pending_estimate is None:
            return False
        self.model_key = self.pending_model_key
        self.request_estimate = self.pending_estimate
        self.actual_input_tokens = input_tokens if type(input_tokens) is int and input_tokens >= 0 else None
        self.source = "provider_calibrated" if self.actual_input_tokens is not None else "estimated"
        self.pending_estimate = None
        return True

    def estimate(self, local_tokens: int, model_key: object) -> int:
        if self.actual_input_tokens is None or self.model_key != model_key or self.request_estimate is None:
            return local_tokens
        return max(0, self.actual_input_tokens + local_tokens - self.request_estimate)

    def invalidate(self) -> None:
        self.actual_input_tokens = None
        self.request_estimate = None
        self.source = "estimated_after_maintenance"
