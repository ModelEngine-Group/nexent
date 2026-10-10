"""Exercise the NexentAgent MCP dispatch path with configured arguments."""

from threading import Event
from types import SimpleNamespace
from unittest.mock import MagicMock

from test.sdk.core.agents.test_nexent_agent import MessageObserver, NexentAgent, ToolConfig


def test_mcp_dispatch_applies_parameters_without_mutating_template():
    agent = NexentAgent(observer=MagicMock(spec=MessageObserver), model_config_list=[], stop_event=Event())
    template = SimpleNamespace(
        name="add", inputs={"left": {}, "right": {}},
        forward=lambda left, right: left + right,
    )
    agent.mcp_tool_collection = SimpleNamespace(tools=[template])
    config = ToolConfig(
        class_name="add", name="add", description="Addition", inputs='{}',
        output_type="integer", params={"left": 40, "right": 2}, source="mcp", metadata={},
    )
    first = agent.create_tool(config)
    assert first.forward(left=1, right=2) == 42
    config.params = {"left": 10}
    second = agent.create_tool(config)
    assert second.forward(left=1, right=2) == 12
    assert first.forward(left=1, right=2) == 42
    assert template.forward(left=1, right=2) == 3
