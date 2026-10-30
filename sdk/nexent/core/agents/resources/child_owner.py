# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.


from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from threading import Event
from typing import TYPE_CHECKING, Any, Callable, Dict, Optional

from nexent.core.agents.contracts.config import AgentConfig


logger = logging.getLogger(__name__)


if TYPE_CHECKING:
    from nexent.core.agents.resources.subagents import SubAgentToolWrapper

class SubagentResources:
    """Track child scopes while dispatch is supplied by the composition owner."""

    def _wrap_subagent(
        self,
        inner_agent: Any,
        sub_agent_config: Any,
        agent_id: Any = None,
        *,
        invocation_factory: Optional[Callable] = None,
    ) -> "SubAgentToolWrapper":
        """Wrap a sub-agent ``Tool`` so the observer sees nesting boundaries.

        Both internal ``AgentConfig``-derived managed agents and external
        ``ExternalA2AAgentConfig``-derived wrappers funnel through here, so
        every nested invocation emits ``subagent_start``/``subagent_end``
        regardless of which kind of sub-agent was added to ``managed_agents``.
        """

        from nexent.core.agents.resources.subagents import SubAgentToolWrapper

        resolved_id = (
            agent_id
            if agent_id is not None
            else getattr(sub_agent_config, "agent_id", None)
            or getattr(sub_agent_config, "_sub_agent_id", None)
        )
        agent_name = (
            getattr(sub_agent_config, "display_name", None)
            or getattr(sub_agent_config, "name", None)
            or getattr(inner_agent, "name", None)
            or "subagent"
        )
        return SubAgentToolWrapper(
            inner_agent=inner_agent,
            observer=self.observer,
            agent_id=resolved_id,
            agent_name=str(agent_name),
            runtime_identity={
                key: getattr(sub_agent_config, key, None)
                for key in ("runtime_ref", "version_no", "display_name", "origin")
            },
            invocation_name=(
                getattr(sub_agent_config, "invocation_name", None)
                or getattr(inner_agent, "name", None)
                or str(agent_name)
            ),
            invocation_factory=invocation_factory,
        )


    def _create_subagent_definition(self, config: AgentConfig, tree_context: Dict[str, Any]):
        """Register a definition; each call builds and owns a separate runtime."""
        from nexent.core.agents.resources.subagents import SubAgentDefinition

        definition = SubAgentDefinition(config.invocation_name or config.name, config.description)
        return self._wrap_subagent(
            definition,
            config,
            invocation_factory=lambda: self._subagent_invocation(config, definition, tree_context),
        )


    @contextmanager
    def _subagent_invocation(self, config: AgentConfig, definition: Any, tree_context: Dict[str, Any]):
        """Keep allocation, state, cancellation and cleanup local to one call."""
        from nexent.core.concurrency.cancellation import RunCancellationScope, RunTerminated

        scope = RunCancellationScope(parent_stop_event=self.stop_event)
        done = Event()
        with self._subagent_invocations_lock:
            if self._subagent_invocations_closed or self.stop_event.is_set():
                raise RunTerminated("Subagent owner has stopped accepting invocations")
            self._subagent_invocations[done] = scope
        parent_token = None
        drained = False
        allocated = False

        def mark_drained():
            nonlocal drained
            drained = True
        try:
            if self.cancellation_scope is not None:
                parent_token = self.cancellation_scope.register_closer(scope.cancel)
            if scope.cancelled or self.stop_event.is_set():
                raise RunTerminated("Subagent invocation cancelled before allocation")
            if getattr(self, "_child_invocation_factory", None) is not None:
                try:
                    yield self._child_invocation_factory(config, scope)
                finally:
                    mark_drained()
                return
            allocated = True
            with self._legacy_subagent_invocation(config, definition, tree_context, scope, mark_drained) as agent:
                yield agent
        finally:
            try:
                if not allocated:
                    drained = True
            finally:
                if drained:
                    if parent_token is not None:
                        self.cancellation_scope.unregister_closer(parent_token)
                    with self._subagent_invocations_lock:
                        self._subagent_invocations.pop(done, None)
                    done.set()


    def _close_subagent_invocations(self, timeout: float = 5.0) -> None:
        """Cancel and drain owned calls before shared workspace teardown."""
        with self._subagent_invocations_lock:
            self._subagent_invocations_closed = True
            pending = tuple(self._subagent_invocations.items())
        for _, scope in pending:
            scope.cancel()
        deadline = time.monotonic() + timeout
        for done, _ in pending:
            if not done.wait(max(0.0, deadline - time.monotonic())):
                logger.error("Subagent invocation exceeded close grace; retaining owner resources")
                raise RuntimeError("Subagent invocation did not terminate before owner cleanup")

    @contextmanager
    def _legacy_subagent_invocation(self, config, definition, tree_context, scope, mark_drained):
        mark_drained()
        raise RuntimeError("Child execution requires an injected invocation factory")
        yield
