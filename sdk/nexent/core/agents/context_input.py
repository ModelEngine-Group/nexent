# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

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


def build_authorized_context_input(
    agent_run_info,
    historical_context=None,
) -> ContextInput:
    """Freeze configured context and authorized history into one item snapshot."""
    if historical_context is None:
        fallback_turns = []
        pending_user = None
        for index, entry in enumerate(agent_run_info.history or ()):
            if entry.role == "user":
                pending_user = (index, entry)
            elif entry.role == "assistant" and pending_user is not None:
                user_index, user_entry = pending_user
                fallback_turns.append(
                    {
                        "user_message": user_entry.content,
                        "assistant_final_answer": entry.content,
                        "attachments": [],
                        "user_message_id": -(user_index + 1),
                        "assistant_message_id": -(index + 1),
                    }
                )
                pending_user = None
        historical_context = {"conversation_turns": fallback_turns}

    history_items = []
    summary = historical_context.get("history_summary")
    if summary:
        history_items.append(
            ContextItemInput(
                id=f"history_summary:{summary['unit_id']}",
                type="history_summary",
                content=summary,
                source=("conversation_history",),
            )
        )
    for order, turn in enumerate(historical_context.get("conversation_turns", ())):
        history_items.append(
            ContextItemInput(
                id=(
                    f"conversation_turn:{turn['user_message_id']}:"
                    f"{turn['assistant_message_id']}"
                ),
                type="conversation_turn",
                content=turn,
                source=("conversation_history",),
                metadata={"layout_order": order},
            )
        )
    return ContextInput(
        items=(
            tuple(agent_run_info.agent_config.context_items or ())
            + tuple(history_items)
        ),
    )
