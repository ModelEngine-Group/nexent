"""Unit tests for sub-agent wrapper delegation and observer boundaries."""

from __future__ import annotations

from unittest.mock import Mock

import pytest

from nexent.core.agents.subagent_wrapper import SubAgentToolWrapper, _default_task_extractor


class InnerAgent:
    """Callable inner agent that accepts mutable tool contract attributes."""

    def __init__(self, result: object = "result") -> None:
        self.name = "researcher"
        self.result = result
        self.calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def __call__(self, *args: object, **kwargs: object) -> object:
        self.calls.append((args, kwargs))
        return self.result


class RejectingInnerAgent:
    """Inner agent that rejects unknown attributes."""

    name = "restricted"

    def __setattr__(self, item: str, value: object) -> None:
        if item == "name":
            object.__setattr__(self, item, value)
            return
        raise AttributeError(item)


@pytest.fixture
def observer() -> Mock:
    return Mock()


def test_setattr_keeps_wrapper_owned_state_on_wrapper(observer: Mock) -> None:
    inner = InnerAgent()
    wrapper = SubAgentToolWrapper(inner, observer)

    replacement_observer = Mock()
    wrapper._observer = replacement_observer

    assert wrapper._observer is replacement_observer
    assert not hasattr(inner, "_observer")


def test_setattr_forwards_tool_contract_attribute_to_inner_agent(observer: Mock) -> None:
    inner = InnerAgent()
    wrapper = SubAgentToolWrapper(inner, observer)

    wrapper.description = "Search for useful information"

    assert inner.description == "Search for useful information"
    assert "description" not in wrapper.__dict__


def test_setattr_falls_back_to_wrapper_when_inner_rejects_attribute(observer: Mock) -> None:
    wrapper = SubAgentToolWrapper(RejectingInnerAgent(), observer)

    wrapper.description = "Fallback description"

    assert wrapper.description == "Fallback description"


@pytest.mark.parametrize(
    ("args", "kwargs", "expected_task"),
    [
        (("positional task",), {}, "positional task"),
        (("fallback task",), {"task": None}, "fallback task"),
        (("ignored positional",), {"task": "keyword task"}, "keyword task"),
        ((None, {"task": "dictionary task"}), {}, "dictionary task"),
        ((None, 42), {}, "42"),
        ((None, {"other": "value"}), {}, None),
        ((None, object()), {}, None),
    ],
)
def test_default_task_extractor_handles_supported_inputs(
    args: tuple[object, ...], kwargs: dict[str, object], expected_task: str | None
) -> None:
    assert _default_task_extractor(args, kwargs) == expected_task


def test_call_reports_extracted_task_and_balances_observer_events(observer: Mock) -> None:
    inner = InnerAgent(result="completed")
    wrapper = SubAgentToolWrapper(inner, observer, agent_id="agent-1", agent_name="Research agent")

    assert wrapper(task="Review the report") == "completed"

    assert inner.calls == [((), {"task": "Review the report"})]
    start_kwargs = observer.add_subagent_start.call_args.kwargs
    end_kwargs = observer.add_subagent_end.call_args.kwargs
    # A stable invocation_id must be generated per call and reused for the
    # matching end so downstream consumers can group every nested chunk.
    assert "invocation_id" in start_kwargs
    assert start_kwargs["invocation_id"] == end_kwargs["invocation_id"]
    assert start_kwargs == {
        "agent_id": "agent-1",
        "agent_name": "Research agent",
        "task": "Review the report",
        "invocation_id": start_kwargs["invocation_id"],
    }
    assert end_kwargs == {
        "agent_id": "agent-1",
        "agent_name": "Research agent",
        "invocation_id": start_kwargs["invocation_id"],
    }


def test_call_generates_distinct_invocation_ids_per_call(observer: Mock) -> None:
    """Each invocation must get a fresh invocation_id so parallel siblings don't collide."""
    inner = InnerAgent(result="ok")
    wrapper = SubAgentToolWrapper(inner, observer, agent_id="agent-1", agent_name="Research")

    wrapper(task="first")
    wrapper(task="second")

    assert observer.add_subagent_start.call_count == 2
    first_invocation = observer.add_subagent_start.call_args_list[0].kwargs["invocation_id"]
    second_invocation = observer.add_subagent_start.call_args_list[1].kwargs["invocation_id"]
    assert first_invocation != second_invocation
    assert observer.add_subagent_end.call_args_list[0].kwargs["invocation_id"] == first_invocation
    assert observer.add_subagent_end.call_args_list[1].kwargs["invocation_id"] == second_invocation


def test_call_still_balances_observer_events_when_inner_raises(observer: Mock) -> None:
    """A failing inner agent must still emit subagent_end so the stack stays balanced."""
    inner = Mock(side_effect=RuntimeError("boom"))
    wrapper = SubAgentToolWrapper(inner, observer, agent_id="agent-1", agent_name="Research")

    with pytest.raises(RuntimeError):
        wrapper(task="x")

    start_kwargs = observer.add_subagent_start.call_args.kwargs
    end_kwargs = observer.add_subagent_end.call_args.kwargs
    assert start_kwargs["invocation_id"] == end_kwargs["invocation_id"]
