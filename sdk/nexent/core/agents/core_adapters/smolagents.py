"""Compatibility adapter for the existing smolagents execution path."""

from .base import AgentCoreAdapter


class SmolagentsAdapter(AgentCoreAdapter):
    core_name = "smolagents"

    def __init__(self, run_info, *, executor=None):
        super().__init__(run_info)
        self.executor = executor

    @classmethod
    def capabilities(cls):
        return frozenset({"tools", "mcp", "skills", "workers", "a2a", "planning", "verification"})

    def validate(self):
        """Children validate through their selected adapter at invocation time."""

    def run(self):
        if self.executor is not None:
            return self.executor(self.run_info)
        from ..run_agent import _run_smolagents

        return _run_smolagents(self.run_info)
