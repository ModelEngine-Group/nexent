"""Core-independent execution and lifecycle contract."""

from abc import ABC, abstractmethod
from typing import Any


class UnsupportedAgentCoreConfig(ValueError):
    """A selected core cannot honor a requested execution policy."""


class AgentCoreAdapter(ABC):
    """Own one run; receive resolved resources without reading environment variables."""

    core_name: str

    def __init__(self, run_info: Any):
        self.run_info = run_info

    @classmethod
    @abstractmethod
    def capabilities(cls) -> frozenset[str]:
        """Return supported execution capabilities."""

    @abstractmethod
    def validate(self) -> None:
        """Reject unsupported settings before acquiring execution resources."""

    def prepare(self) -> None:
        """Bind resolved resources for this run."""

    @abstractmethod
    def run(self) -> Any:
        """Emit the existing observer protocol and return the terminal value to a delegator."""

    def close(self) -> None:
        """Release only resources owned by this adapter; must be idempotent."""
