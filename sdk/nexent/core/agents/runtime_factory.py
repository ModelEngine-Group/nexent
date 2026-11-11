# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Select runtime construction without sharing runtime-specific agent loops."""

from .core_agent import CoreAgent


def create_agent_runtime(runtime: str = "codeagent", **kwargs):
    """Keep the exact legacy constructor unless native execution is selected."""
    runtime = select_agent_runtime(runtime, kwargs.get("model"))
    if runtime == "codeagent":
        return CoreAgent(**kwargs)
    if runtime == "toolcalling":
        from .native_runtime import NativeToolCallingAgent

        return NativeToolCallingAgent(**kwargs)
    raise ValueError(f"Invalid NEXENT_AGENT_RUNTIME {runtime!r}; expected codeagent or toolcalling")


def is_runtime_agent(agent):
    """Recognize supported runtimes while keeping the stable import path isolated."""
    if isinstance(agent, CoreAgent):
        return True
    if getattr(type(agent), "nexent_runtime_name", None) == "toolcalling":
        from .native_runtime import NativeToolCallingAgent

        return isinstance(agent, NativeToolCallingAgent)
    return False


def select_agent_runtime(requested, model):
    """Treat absent capability evidence conservatively; never downgrade on errors."""
    if requested not in {"codeagent", "toolcalling"}:
        raise ValueError(f"Invalid NEXENT_AGENT_RUNTIME {requested!r}")
    profile = getattr(model, "profile", None)
    if requested == "toolcalling" and profile is not None and profile.capabilities.tools.status == "supported":
        return "toolcalling"
    return "codeagent"


def adapt_fallback_context_items(items, requested, effective, model):
    """Code actions do not require substituting prompted thoughts for native reasoning."""
    profile = getattr(model, "profile", None)
    if (
        requested != "toolcalling"
        or effective != "codeagent"
        or (profile is not None and profile.capabilities.reasoning.status == "supported")
    ):
        return items
    adapted = []
    for item in items:
        trusted = (
            item.id == "system:execution_flow"
            and getattr(item.type, "value", item.type) == "system"
            and item.metadata.get("authority") == "platform"
            and tuple(item.source) == ("agent_prompt:execution_flow",)
        )
        if trusted:
            text = (
                "Use <code>...</code> Python actions for authorized tools and wait for actual observations. "
                "No written thought or simulated reasoning is required. "
                "Return the completed user-facing answer inside <final_answer>...</final_answer>."
            )
            item = item.model_copy(update={"content": {**item.content, "text": text}})
        adapted.append(item)
    return adapted
