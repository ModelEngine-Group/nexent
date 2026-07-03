"""Registry mapping ContextItemType to ContextItemHandler instances."""

from typing import Dict

from .context_item import ContextItemType
from .item_handler import ContextItemHandler


class ItemHandlerRegistry:
    """Central registry for context item handlers.

    Ensures every ContextItemType has exactly one registered handler.
    """

    _handlers: Dict[ContextItemType, ContextItemHandler] = {}

    @classmethod
    def register(cls, handler: ContextItemHandler) -> None:
        """Register a handler for all its supported types."""
        for item_type in handler.supported_types():
            cls._handlers[item_type] = handler

    @classmethod
    def get(cls, item_type: ContextItemType) -> ContextItemHandler:
        """Retrieve the handler for a given item type.

        Raises:
            KeyError: If no handler is registered for the item type.
        """
        if item_type not in cls._handlers:
            raise KeyError(f"No handler registered for ContextItemType.{item_type.value}")
        return cls._handlers[item_type]

    @classmethod
    def all_types_covered(cls) -> bool:
        """Return True if every ContextItemType has a registered handler."""
        return all(item_type in cls._handlers for item_type in ContextItemType)

    @classmethod
    def reset(cls) -> None:
        """Clear all registered handlers. Useful for testing."""
        cls._handlers = {}
