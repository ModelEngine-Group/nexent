"""UT-SDK-TRACE-015: exported email never replaces internal account identity."""

import asyncio
from dataclasses import replace

import pytest

from nexent.monitor import (
    AgentRunMetadata,
    agent_monitoring_context,
    get_monitoring_context,
)


@pytest.mark.parametrize("email,expected", [("person@example.com", "person@example.com"), (None, "account-id")])
def test_ut_sdk_trace_015_agent_and_descendants_export_email(spans, email, expected):
    metadata = AgentRunMetadata(user_id="account-id", user_email=email, tenant_id="tenant")
    with spans.manager.start_agent_run(metadata):
        assert get_monitoring_context()["user_id"] == "account-id"
        with spans.manager.trace_llm_request("model.generate", "model"):
            pass
        with spans.manager.trace_tool_call("search", "agent", {"query": "test"}):
            pass
        child = replace(metadata, agent_id=2, agent_name="child")
        with agent_monitoring_context(child), spans.manager.trace_operation(
            "agent.subagent.child", **spans.manager.build_agent_run_attributes(child)
        ):
            assert get_monitoring_context()["user_id"] == "account-id"
    finished = spans.exporter.get_finished_spans()
    assert len(finished) == 4
    assert all(s.attributes["user.id"] == expected for s in finished)
    assert get_monitoring_context()["user_id"] is None


@pytest.mark.asyncio
async def test_ut_sdk_trace_015_concurrent_email_context_is_isolated(spans):
    async def run(index):
        metadata = AgentRunMetadata(user_id=f"uuid-{index}", user_email=f"user{index}@example.com")
        with spans.manager.start_agent_run(metadata):
            await asyncio.sleep(0)
            assert get_monitoring_context()["user_id"] == f"uuid-{index}"
    await asyncio.gather(run(1), run(2))
    assert {s.attributes["user.id"] for s in spans.exporter.get_finished_spans()} == {
        "user1@example.com", "user2@example.com",
    }
