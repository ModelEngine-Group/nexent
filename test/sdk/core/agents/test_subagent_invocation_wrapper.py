"""Invocation factories preserve dispatch and balanced observer events."""

from contextlib import contextmanager
from unittest.mock import Mock

import pytest
from nexent.core.agents.subagent_wrapper import SubAgentDefinition, SubAgentToolWrapper


@pytest.mark.parametrize("entry", ["call", "forward"])
@pytest.mark.parametrize("failure", [None, "allocation", "execution"])
def test_factory_owns_each_call_and_balances_events(mocker, entry, failure):
    observer = Mock()
    agents, exits = [], []

    @contextmanager
    def allocate():
        if failure == "allocation":
            raise ValueError("allocation failed")
        agent = Mock(return_value="call-result")
        agent.forward.return_value = "forward-result"
        agents.append(agent)
        if failure == "execution":
            agent.side_effect = agent.forward.side_effect = ValueError("execution failed")
        try:
            yield agent
        finally:
            exits.append(agent)

    definition = SubAgentDefinition("worker", "Worker")
    wrapper = SubAgentToolWrapper(definition, observer, invocation_factory=allocate)
    invoke = wrapper if entry == "call" else wrapper.forward
    if failure:
        with pytest.raises(ValueError, match=f"{failure} failed"):
            invoke(task="first")
    else:
        assert invoke(task="first") == f"{entry}-result"
        assert invoke(task="second") == f"{entry}-result"
        assert agents[0] is not agents[1]
        for agent in agents:
            (agent if entry == "call" else agent.forward).assert_called_once()
    assert exits == agents
    starts = observer.add_subagent_start.call_args_list
    ends = observer.add_subagent_end.call_args_list
    assert len(starts) == len(ends)
    assert [call.kwargs["invocation_id"] for call in starts] == [call.kwargs["invocation_id"] for call in ends]
    assert len({call.kwargs["invocation_id"] for call in starts}) == len(starts)
    assert definition.state == {} and definition.managed_agents == {}
