"""Wrappers for sub-agents invoked by a managed parent.

The parent agent owns a single ``MessageObserver``. When the parent's ReAct
loop dispatches to a managed sub-agent (or to an external A2A wrapper), we
want the frontend to render that nested execution inside a dedicated container
so users can tell the main agent's thinking from the sub-agent's thinking.

This module provides :class:`SubAgentToolWrapper`, an opaque passthrough that
emits ``subagent_start`` / ``subagent_end`` observer signals around every
invocation while still behaving like a smolagents ``Tool`` from the parent's
perspective.
"""

from __future__ import annotations

import uuid
from typing import Any, Callable, Iterable

from ..utils.observer import MessageObserver


class SubAgentToolWrapper:
    """Wrap an inner sub-agent ``Tool``/callable so the shared observer
    records a nesting boundary on every invocation.

    The wrapper is designed to satisfy smolagents' managed-agent contract:

    * Exposes ``name``, ``description``, ``inputs`` and ``output_type``
      attributes (forwarded from the inner agent when present).
    * Is callable: ``wrapper(task=...)`` runs the inner agent, optionally
      surfacing the task string into the ``subagent_start`` chunk.
    * Forwards every attribute read AND write to the inner agent via
      ``__getattr__`` / ``__setattr__`` so smolagents can mutate the wrapped
      agent's Tool contract fields without hitting read-only properties.

    The wrapper is intentionally minimal — it does not duplicate any of
    smolagents' Tool machinery. The inner agent remains the source of truth
    for execution; the wrapper only annotates the stream.
    """

    # Managed-agent orchestration must stay in the trusted Runtime process.
    # Remote code executors expose this wrapper through the authenticated host
    # tool bridge, while the inner agent uses its own sandbox executor.
    _nexent_execute_on_host = True

    # Attributes that live on the wrapper itself rather than being forwarded
    # to the inner agent. Anything else is dispatched via ``__getattr__`` /
    # ``__setattr__`` so the wrapper stays transparent.
    _WRAPPER_OWN_ATTRS = frozenset({
        "_inner",
        "_observer",
        "_agent_id",
        "_agent_name",
        "_task_extractor",
    })

    def __init__(
        self,
        inner_agent: Any,
        observer: MessageObserver,
        agent_id: Any = None,
        agent_name: str | None = None,
        task_extractor: Callable[[Iterable[Any], dict], str | None] | None = None,
    ):
        # Set attributes through ``object.__setattr__`` so the new
        # ``__setattr__`` below (which forwards everything to the inner
        # agent) does not interfere with our own construction.
        object.__setattr__(self, "_inner", inner_agent)
        object.__setattr__(self, "_observer", observer)
        object.__setattr__(self, "_agent_id", agent_id)
        object.__setattr__(
            self,
            "_agent_name",
            agent_name
            if agent_name is not None
            else getattr(inner_agent, "name", None) or "subagent",
        )
        # Optional callable that extracts the task string from the parent's
        # call args. Default: read the first positional arg or the ``task``
        # kwarg, whichever is present.
        object.__setattr__(
            self,
            "_task_extractor",
            task_extractor or _default_task_extractor,
        )

    # --- attribute dispatch -------------------------------------------------

    def __getattr__(self, item: str) -> Any:
        # ``__getattr__`` is only invoked when normal lookup fails, so any
        # attribute set on the wrapper (including smolagents-mutated fields)
        # is served from the wrapper's own ``__dict__`` first.
        return getattr(self._inner, item)

    def __setattr__(self, item: str, value: Any) -> None:
        # Wrapper-owned state stays on the wrapper. Anything else — most
        # importantly smolagents' Tool contract fields (``name``,
        # ``description``, ``inputs``, ``output_type``) — is forwarded to the
        # inner agent so its prompt rendering sees consistent values.
        if item in self._WRAPPER_OWN_ATTRS:
            object.__setattr__(self, item, value)
            return
        try:
            setattr(self._inner, item, value)
        except AttributeError:
            # Inner agent does not accept this attribute (e.g. some tools
            # raise on unknown attrs); fall back to storing it on the wrapper
            # so subsequent reads still work.
            object.__setattr__(self, item, value)

    # --- invocation --------------------------------------------------------

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        """Invoke the inner agent and wrap the call with observer signals.

        The wrapper does not swallow exceptions; if the inner agent raises,
        we still emit ``subagent_end`` so the frontend nesting state stays
        balanced. Callers can still rely on the exception propagating up to
        smolagents for normal retry / fail semantics.

        A unique ``invocation_id`` (UUID4) is generated for each call and
        propagated to both ``subagent_start`` and ``subagent_end`` so the
        observer — and downstream consumers — can group every chunk produced
        during this invocation, even when sibling sub-agents execute in
        parallel.
        """
        task_text = self._task_extractor(args, kwargs)
        invocation_id = uuid.uuid4().hex
        self._observer.add_subagent_start(
            agent_id=self._agent_id,
            agent_name=self._agent_name,
            task=task_text,
            invocation_id=invocation_id,
        )
        try:
            return self._inner(*args, **kwargs)
        finally:
            self._observer.add_subagent_end(
                agent_id=self._agent_id,
                agent_name=self._agent_name,
                invocation_id=invocation_id,
            )

    # Some smolagents versions dispatch via ``forward`` rather than
    # ``__call__``. Forward through to the inner agent's ``forward`` if it
    # exists, but still wrap with the observer signals.
    def forward(self, *args: Any, **kwargs: Any) -> Any:  # pragma: no cover
        task_text = self._task_extractor(args, kwargs)
        invocation_id = uuid.uuid4().hex
        self._observer.add_subagent_start(
            agent_id=self._agent_id,
            agent_name=self._agent_name,
            task=task_text,
            invocation_id=invocation_id,
        )
        try:
            inner_forward = getattr(self._inner, "forward", None)
            if callable(inner_forward):
                return inner_forward(*args, **kwargs)
            return self._inner(*args, **kwargs)
        finally:
            self._observer.add_subagent_end(
                agent_id=self._agent_id,
                agent_name=self._agent_name,
                invocation_id=invocation_id,
            )


def _default_task_extractor(args: Iterable[Any], kwargs: dict) -> str | None:
    """Best-effort extraction of the task string passed to a sub-agent.

    Sub-agents in Nexent typically expose ``task`` as their primary input,
    but the parent may also call positionally. We accept either form.
    """
    if "task" in kwargs and kwargs["task"] is not None:
        return str(kwargs["task"])
    for arg in args:
        if arg is None:
            continue
        if isinstance(arg, (str, int, float, bool)):
            return str(arg)
        if isinstance(arg, dict):
            task_value = arg.get("task")
            if task_value is not None:
                return str(task_value)
    return None
