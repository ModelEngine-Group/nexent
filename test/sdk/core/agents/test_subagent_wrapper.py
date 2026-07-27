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
    observer.add_subagent_start.assert_called_once_with(
        agent_id="agent-1", agent_name="Research agent", task="Review the report"
    )
    observer.add_subagent_end.assert_called_once_with(agent_id="agent-1", agent_name="Research agent")
