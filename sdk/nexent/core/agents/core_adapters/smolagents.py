"""Compatibility adapter for the existing smolagents execution path."""

from .base import AgentCoreAdapter, UnsupportedAgentCoreConfig


class SmolagentsAdapter(AgentCoreAdapter):
    core_name = "smolagents"

    def __init__(self, run_info, *, executor=None):
        super().__init__(run_info)
        self.executor = executor

    @classmethod
    def capabilities(cls):
        return frozenset({"tools", "mcp", "skills", "workers", "a2a", "planning", "verification"})

    def validate(self):
        def validate_tree(config):
            for child in getattr(config, "worker_agents", ()):
                if getattr(child, "agent_core", "smolagents") != self.core_name:
                    raise UnsupportedAgentCoreConfig("Mixed-core worker agents are not supported")
                validate_tree(child)

        validate_tree(self.run_info.agent_config)

    def run(self):
        if self.executor is not None:
            return self.executor(self.run_info)
        from ..run_agent import _run_smolagents

        _run_smolagents(self.run_info)
