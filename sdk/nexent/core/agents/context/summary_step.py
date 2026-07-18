"""Context summary steps and managed run state."""

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Tuple

from smolagents.memory import TaskStep
from smolagents.models import ChatMessage, MessageRole


if TYPE_CHECKING:
    from .selection import SelectionDecision


@dataclass
class SummaryTaskStep(TaskStep):
    """TaskStep subclass that contains a compressed summary of earlier steps."""
    is_summary: bool = True
    prefix: str = "Summary of earlier steps in this task:"

    def to_messages(self, summary_mode: bool = False) -> list:
        content = [{"type": "text", "text": f"{self.prefix}:\n{self.task}"}]
        return [ChatMessage(role=MessageRole.USER, content=content)]


@dataclass(frozen=True)
class ManagedRunContext:
    """Run-local fine-grained item partition owned by ManagedContextRuntime."""

    item_messages: Tuple[dict, ...] = ()
    stable_messages: Tuple[dict, ...] = ()
    dynamic_messages: Tuple[dict, ...] = ()
    selected_item_types: Tuple[str, ...] = ()
    items: Tuple[Any, ...] = ()
    selection_decision: "SelectionDecision | None" = None
