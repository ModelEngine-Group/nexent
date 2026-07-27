"""Run-scoped input contract for context data authorized by the application."""

from copy import deepcopy
from dataclasses import dataclass
from typing import Tuple

from .context.models import ContextItemInput


@dataclass(frozen=True)
class ContextInput:
    """Immutable context snapshot supplied by the application boundary.

    The SDK consumes this snapshot without loading business data or inferring
    user and tenant permissions. Every item is fully materialized and
    authorized by the application before crossing this boundary.
    """

    items: Tuple[ContextItemInput, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.items, tuple):
            raise TypeError("ContextInput collections must be immutable tuples")
        frozen_items = tuple(
            ContextItemInput.model_validate(deepcopy(item.model_dump()))
            for item in self.items
        )
        object.__setattr__(self, "items", frozen_items)
