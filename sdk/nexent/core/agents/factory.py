# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Registry and lazy construction of execution-core adapters."""

import re
from threading import RLock

from nexent.core.agents.contracts.adapter import AgentCoreAdapter, UnsupportedAgentCoreConfig


class AgentCoreFactory:
    _adapters: dict[str, type[AgentCoreAdapter]] = {}
    _lock = RLock()

    @classmethod
    def register(cls, name: str, adapter: type[AgentCoreAdapter]) -> None:
        """Register an extension without replacing built-in or existing adapters."""
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,29}", name):
            raise ValueError("Invalid agent core name")
        if not isinstance(adapter, type) or not issubclass(adapter, AgentCoreAdapter):
            raise TypeError("Adapter must inherit AgentCoreAdapter")
        if adapter.core_name != name:
            raise ValueError("Adapter core_name must match its registry name")
        with cls._lock:
            if name in {"smolagents", "jiuwen"} or name in cls._adapters:
                raise ValueError(f"Agent core already registered: {name}")
            cls._adapters[name] = adapter

    @classmethod
    def create(cls, run_info, *, smolagents_executor=None) -> AgentCoreAdapter:
        name = getattr(run_info.agent_config, "agent_core", "smolagents")
        if name == "smolagents":
            from nexent.core.agents.cores.smolagents.adapter import SmolagentsAdapter

            return SmolagentsAdapter(run_info, executor=smolagents_executor)
        elif name == "jiuwen":
            from nexent.core.agents.cores.jiuwen.adapter import JiuwenAdapter

            adapter = JiuwenAdapter
        else:
            with cls._lock:
                adapter = cls._adapters.get(name)
            if adapter is None:
                raise UnsupportedAgentCoreConfig(f"Unknown agent core: {name}")
        return adapter(run_info)
