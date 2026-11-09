# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Select runtime construction without sharing runtime-specific agent loops."""

from .core_agent import CoreAgent


def create_agent_runtime(runtime: str = "codeagent", **kwargs):
    """Keep the exact legacy constructor unless native execution is selected."""
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
