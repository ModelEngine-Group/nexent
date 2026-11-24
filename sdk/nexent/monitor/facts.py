# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Process-local entry point for sanitized monitoring facts."""

import logging
from collections.abc import Callable

from .private_logging import private_evaluation_active


logger = logging.getLogger(__name__)
_sink: Callable[[dict], None] | None = None


def set_fact_sink(sink: Callable[[dict], None] | None) -> None:
    """Bind the backend-owned producer during process startup."""
    global _sink
    _sink = sink


def get_fact_sink() -> Callable[[dict], None] | None:
    """Capture the current sink for a multi-event operation."""
    return None if private_evaluation_active.get() else _sink


def emit_fact(event: dict) -> None:
    """Offer an operation fact without interrupting its business execution."""
    sink = get_fact_sink()
    if sink is not None:
        try:
            sink(event)
        except Exception as error:
            logger.warning("Monitoring fact rejected error=%s", type(error).__name__)
