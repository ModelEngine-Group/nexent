from threading import Event

from nexent.core.agents.agent_model import (
    AgentConfig,
    AgentRunInfo,
    MCPBinding,
    ModelConfig,
)
from nexent.core.utils.observer import MessageObserver


def test_mcp_binding_headers_are_request_scoped_and_not_serialized():
    binding = MCPBinding(
        server_id="server-1",
        server_name="private-server",
        url="https://mcp.example/mcp",
        transport="streamable-http",
        headers={"Authorization": "Bearer secret"},
        required=True,
        tool_names=["search"],
        required_tool_names=["search"],
    )
    agent = AgentConfig(
        id=1,
        name="agent",
        description="agent",
        tools=[],
        model_name="model",
        runtime_framework="openjiuwen",
        mcp_bindings=[binding],
    )
    run_info = AgentRunInfo(
        query="hello",
        model_config_list=[
            ModelConfig(cite_name="model", model_name="model", url="https://llm.example")
        ],
        observer=MessageObserver(),
        agent_config=agent,
        stop_event=Event(),
        runtime_framework="openjiuwen",
        mcp_bindings=[binding],
    )

    serialized = run_info.model_dump()

    assert serialized["mcp_bindings"][0]["server_name"] == "private-server"
    assert "headers" not in serialized["mcp_bindings"][0]
    assert "headers" not in serialized["agent_config"]["mcp_bindings"][0]
    assert binding.headers == {"Authorization": "Bearer secret"}
