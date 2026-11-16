# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Neutral at-least-once work delivery contracts; job results belong to records."""

from dataclasses import dataclass
from typing import Protocol

from .models import CapabilitySet, OperationContext, StorageScope, TaskEnvelope


@dataclass(frozen=True)
class Delivery:
    receipt: str
    task: TaskEnvelope


@dataclass(frozen=True)
class DeliveryState:
    phase: str
    cancel_requested: bool


class WorkQueue(Protocol):
    @property
    def scope(self) -> StorageScope: ...

    @property
    def capabilities(self) -> CapabilitySet: ...

    def enqueue(self, task: TaskEnvelope, *, context: OperationContext) -> None: ...

    def consume(self, *, max_wait: float, context: OperationContext) -> Delivery | None: ...

    def ack(self, receipt: str, *, context: OperationContext) -> None: ...

    def retry(self, receipt: str, *, context: OperationContext) -> None: ...

    def cancel_request(self, task_id: str, *, context: OperationContext) -> None: ...

    def inspect_delivery(self, task_id: str, *, context: OperationContext) -> DeliveryState: ...

    def close(self) -> None: ...
