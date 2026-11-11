# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Project ordered native protocol messages without rewriting call records."""

from copy import deepcopy

from .context.models import ContextItemInput


def native_context_items(messages, records, loaded_messages):
    items = []
    for order, message in enumerate(messages):
        content = {"messages": [deepcopy(message)]}
        if message.get("role") == "tool" and order in records:
            content.update(execution_key=records[order], execution_fields={"OUTPUT": message.get("content", "")},
                           loaded_result=order in loaded_messages)
        items.append(ContextItemInput(id=f"native:{order}", type="current_action", content=content,
                                      metadata={"run_order": order, "layout_order": order}))
    return items
