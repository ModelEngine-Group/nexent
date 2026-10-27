# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Construct SDK run objects without business lookups or deployment configuration."""

import threading

from nexent.core.agents.agent_model import AgentRunInfo
from nexent.core.utils.observer import MessageObserver


def build_run_info(*, language="zh", **prepared_values) -> AgentRunInfo:
    """Own local observer/cancellation primitives while preserving injected identities."""
    if "observer" not in prepared_values:
        prepared_values["observer"] = MessageObserver(lang=language)
    if "stop_event" not in prepared_values:
        prepared_values["stop_event"] = threading.Event()
    return AgentRunInfo(**prepared_values)
