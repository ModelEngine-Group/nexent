"""Immutable run-local snapshot prepared by ContextManager."""
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any


if TYPE_CHECKING:
    from .selection import SelectionDecision

@dataclass(frozen=True)
class ManagedRunContext:
    item_messages: tuple[dict, ...] = ()
    stable_messages: tuple[dict, ...] = ()
    dynamic_messages: tuple[dict, ...] = ()
    selected_item_types: tuple[str, ...] = ()
    items: tuple[Any, ...] = ()
    selection_decision: "SelectionDecision | None" = None
