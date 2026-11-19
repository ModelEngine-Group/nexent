# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Lifecycle interface for process-owned thread managers."""

from abc import ABC, abstractmethod
from collections.abc import Callable

from .models import DrainResult, ManagedExecution, ManagedTaskSpec, ThreadManagerSnapshot


class ThreadManagerBase(ABC):
    """Start, observe, and drain a service's managed executor."""

    @abstractmethod
    def start(self) -> None:
        """Start accepting work."""

    @abstractmethod
    def submit(self, lane: str, spec: ManagedTaskSpec, fn: Callable, *args, **kwargs) -> ManagedExecution:
        """Submit work to a named execution lane."""

    @abstractmethod
    async def run(self, lane: str, spec: ManagedTaskSpec, fn: Callable, *args, **kwargs):
        """Run work and await its result."""

    @abstractmethod
    def snapshot(self) -> ThreadManagerSnapshot:
        """Report current capacity and execution state."""

    @abstractmethod
    async def shutdown(self, timeout: float) -> DrainResult:
        """Drain work within the process shutdown budget."""
