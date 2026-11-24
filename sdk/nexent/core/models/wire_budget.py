# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""A request-scoped callback for charging physical provider calls."""

from collections.abc import Callable
from contextvars import ContextVar
from typing import Any, Protocol


class ModelWireBudgetExceeded(RuntimeError):
    """The selected background job may not make another provider request."""


SettleUsage = Callable[[int, int], None]
class AdmitModelCall(Protocol):
    def __call__(self, wire: dict[str, Any], model_id: int | None = None) -> SettleUsage | None: ...

model_wire_budget: ContextVar[AdmitModelCall | None] = ContextVar("model_wire_budget", default=None)
