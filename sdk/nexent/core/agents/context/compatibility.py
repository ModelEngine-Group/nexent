# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Explicit lazy support for the legacy ContextManager memory API."""


def memory_adapter(manager):
    from nexent.core.agents.cores.smolagents.context import SmolagentsMemoryAdapter

    return SmolagentsMemoryAdapter(manager)


def assemble_legacy_context(manager, *, model, memory, current_run_start_idx, run_context=None, **kwargs):
    from dataclasses import replace

    from nexent.core.agents.cores.smolagents.context import adapt_context_model, context_messages, context_tool_views
    from nexent.core.agents.cores.smolagents.context_contracts import native_context_messages

    tools = kwargs.get("tools")
    kwargs["tools"] = context_tool_views(tools)
    kwargs["request_system_messages"] = context_messages(kwargs.get("request_system_messages", ()))
    kwargs["request_tail_messages"] = context_messages(kwargs.get("request_tail_messages", ()))
    final = manager.assemble_context_items(
        model=adapt_context_model(model),
        current_items=memory_adapter(manager)._project_current_run(memory, current_run_start_idx),
        run_context=run_context or manager.prepare_items_context(""),
        **kwargs,
    )
    return replace(
        final, messages=native_context_messages(final.messages), tools=manager._canonical_tools(tools or ())
    )
