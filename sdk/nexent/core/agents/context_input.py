"""Run-scoped input contract for context data authorized by the application."""

from dataclasses import dataclass
from typing import Any, Tuple

from .agent_model import AgentHistory


@dataclass(frozen=True)
class ContextInput:
    """Immutable context snapshot supplied by the application boundary.

    The SDK consumes this snapshot without loading business data or inferring
    user and tenant permissions. Components retain their current representation
    until the later ContextItem migration phase.
    """

    components: Tuple[Any, ...] = ()
    history: Tuple[AgentHistory, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.components, tuple) or not isinstance(self.history, tuple):
            raise TypeError("ContextInput collections must be immutable tuples")
