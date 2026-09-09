"""SDK Workbench identity acceptance tests."""

from unittest.mock import Mock

from nexent.core.agents.agent_model import AgentConfig
from nexent.core.agents.subagent_wrapper import SubAgentToolWrapper


def test_ut_sdk_wb_001_agent_config_carries_formal_runtime_identity():
    """UT-SDK-WB-001: identity survives AgentConfig validation and copying."""
    config = AgentConfig(
        agent_id=12,
        version_no=4,
        invocation_name="agent_12_v4",
        runtime_ref="agent:12:v4",
        display_name="Invoice agent",
        origin="PERSISTED",
        name="Invoice agent",
        description="Extract invoices",
        tools=[],
        model_name="main_model",
    )
    copied = config.model_copy(deep=True)
    restored = AgentConfig.model_validate(config.model_dump())
    assert restored.runtime_ref == "agent:12:v4"
    assert restored.display_name == "Invoice agent"
    assert restored.origin == "PERSISTED"
    assert (copied.agent_id, copied.version_no, copied.invocation_name) == (
        12,
        4,
        "agent_12_v4",
    )


def test_ut_sdk_wb_002_subagent_events_include_formal_invocation_name():
    """UT-SDK-WB-002: wrappers emit formal identity while preserving display name."""
    inner = Mock(return_value="ok")
    observer = Mock()
    wrapper = SubAgentToolWrapper(
        inner,
        observer,
        agent_id=12,
        agent_name="Invoice agent",
        invocation_name="agent_12_v4",
        runtime_identity={
            "runtime_ref": "agent:12:v4", "version_no": 4,
            "display_name": "Invoice agent", "origin": "PERSISTED",
        },
    )
    assert wrapper(task="read") == "ok"
    assert observer.add_subagent_start.call_args.kwargs["invocation_name"] == "agent_12_v4"
    assert observer.add_subagent_end.call_args.kwargs["invocation_name"] == "agent_12_v4"
    for call in (observer.add_subagent_start.call_args, observer.add_subagent_end.call_args):
        assert call.kwargs["runtime_ref"] == "agent:12:v4"
        assert call.kwargs["version_no"] == 4
        assert call.kwargs["display_name"] == "Invoice agent"
        assert call.kwargs["origin"] == "PERSISTED"
    assert observer.add_subagent_start.call_args.kwargs["invocation_id"] == observer.add_subagent_end.call_args.kwargs["invocation_id"]


def test_ut_sdk_wb_003_invocation_name_is_not_the_display_name():
    """UT-SDK-WB-003: renaming UI copy does not change callable identity."""
    first = AgentConfig(
        agent_id=12, version_no=4, invocation_name="agent_12_v4",
        name="旧名称", description="", tools=[], model_name="main_model",
    )
    renamed = first.model_copy(update={"name": "新名称"})
    assert renamed.invocation_name == first.invocation_name
    assert renamed.name != first.name
