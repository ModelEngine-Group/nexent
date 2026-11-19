# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Read back all supported ordinary configuration sections after real MCP saves."""

import json
import socket
from contextlib import contextmanager
from unittest.mock import AsyncMock, Mock
from urllib.parse import urlparse

import pytest
from sqlalchemy import inspect, select

from management.db.models import AgentInfo
from management.db.agent.models import AgentRelation
from management.db.tag.models import (
    ResourceTagAssignment, TagBucket, TagBucketResourceType, TagDefinition, TagValue,
)
from model_controls.runtime import runtime_fixture
from services import nl2agent_service

pytestmark = [pytest.mark.case_id("NL2A-CONFIG-D3-001"), pytest.mark.stage("D3")]
PATH = "/api/agent/nl2agent/run"


@contextmanager
def owned_runtime(monkeypatch):
    runtime = None
    try:
        with runtime_fixture(monkeypatch) as runtime:
            yield runtime
    finally:
        if runtime is not None:
            assert not inspect(runtime.storage["engine"]).has_schema(runtime.storage["schema"])
            assert not runtime.provider.thread.is_alive()
            for run in runtime.runs:
                assert run.thread_future.done()
                mcp = urlparse(run.mcp_host[0]["url"])
                with socket.socket() as client:
                    client.settimeout(1)
                    assert client.connect_ex((mcp.hostname, mcp.port)) != 0


def run(runtime, code):
    actions = iter([*(f"<code>print({statement})</code>" for statement in code),
                    "<final_answer>Fixture turn completed.</final_answer>"])
    runtime.provider.responder = lambda body: next(actions) if body.get("stream") else "Fixture"
    response = runtime.post(PATH, query="Update the requested ordinary configuration only.")
    assert response.status_code == 200, response.text
    events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
    assert events[-1]["type"] == "final_answer"
    assert next(actions, None) is None
    assert not any(event["type"] in {"error", "nl2a"} for event in events)
    states, receipts = [], []
    for event in events:
        if event["type"] == "nl2a_state":
            states.append(json.loads(event["content"]))
        if event["type"] == "execution_logs":
            try:
                receipt = json.loads(event["content"])
            except (TypeError, ValueError):
                continue
            if isinstance(receipt, dict) and receipt.get("status") in {"success", "error"}:
                receipts.append(receipt)
    return states, receipts


def patch(section, changes):
    return f"nl2a_save_agent_configuration(section={section!r}, changes={changes!r})"


def test_update_configuration_sections_and_reject_forbidden_patch(monkeypatch):
    catalogs = AsyncMock(side_effect=AssertionError("ordinary configuration must not load resources"))
    monkeypatch.setattr(nl2agent_service, "_load_installed_resource_catalog", catalogs)
    monkeypatch.setattr(nl2agent_service, "_load_internal_uninstalled_resource_catalog", catalogs)

    with owned_runtime(monkeypatch) as runtime:
        tenant = runtime.storage["tenant"]
        owner = runtime.storage["owner"]
        audit = {"tenant_id": tenant, "created_by": owner, "updated_by": owner}
        with runtime.storage["sessions"]() as session:
            for agent in session.scalars(select(AgentInfo).where(AgentInfo.system_key == "nl2agent_main")):
                agent.max_steps = 10
            target = session.scalars(select(AgentInfo).where(AgentInfo.agent_id == runtime.agent_id)).one()
            target.verification_config = {"enabled": False, "max_final_rounds": 3}
            original_prompt = target.prompt
            original_params = target.model_params_override
            extra = AgentInfo(name="additional_helper", display_name="Additional helper", version_no=0,
                              enabled=True, **audit)
            session.add(extra)
            session.add(TagBucket(bucket_id=1, bucket_key="default_resource", bucket_name="Resource tags", **audit))
            session.flush()
            extra_id = extra.agent_id
            session.add(TagBucketResourceType(bucket_resource_type_id=1, bucket_id=1, resource_type="agent", **audit))
            session.add(TagDefinition(definition_id=1, bucket_id=1, definition_key="fixture",
                                      definition_name="Fixture", selection_mode="multi_select", **audit))
            session.flush()
            session.add_all([
                TagValue(value_id=i, definition_id=1, display_value=f"Tag {i}", normalized_value=f"tag {i}", **audit)
                for i in (11, 12)
            ])
            session.flush()
            session.add(ResourceTagAssignment(resource_type="agent", resource_id=str(runtime.agent_id),
                                              definition_id=1, value_id=11, **audit))

        model_id = runtime.models["selected-B"]
        states, receipts = run(runtime, [
            "nl2a_read_agent_configuration(section='model')",
            patch("model", {"model_ids": [model_id]}),
            patch("collaborators", {"add": [{"agent_id": extra_id, "version_no": 0}]}),
            patch("permissions", {"ingroup_permission": "READ_ONLY", "is_main_agent": False}),
            patch("tags", {"add": [12]}),
            patch("guardrails", {"enabled": True, "upsert_rules": [
                {"name": "redact", "pattern": "fixture-private", "severity": "mask"},
                {"name": "block_pii", "pattern": "password", "severity": "block"},
                {"name": "allow", "pattern": "fixture-public", "severity": "pass"},
            ]}),
            patch("advanced", {"max_steps": 14, "provide_run_summary": True, "allow_chat_metadata": True,
                               "enable_protocol_repair_retry": True, "self_verification_enabled": True}),
        ])
        assert len(receipts) == 7 and all(receipt["status"] == "success" for receipt in receipts), receipts
        assert model_id in {row["model_id"] for row in receipts[0]["configuration"]["options"]}
        assert "api_key" not in json.dumps(receipts[0]) and "base_url" not in json.dumps(receipts[0])
        assert len(states) == 6
        for event, receipt in zip(states, receipts[1:]):
            assert event == {"event": "agent_draft_fields_saved", "agent_id": runtime.agent_id,
                             "updated_fields": receipt["updated_fields"]}

        rejected, errors = run(runtime, [patch("advanced", {"max_steps": 30, "prompt": "Injected"})])
        assert rejected == [] and errors[0]["code"] == "invalid_configuration"
        with runtime.storage["sessions"]() as session:
            agent = session.scalars(select(AgentInfo).where(AgentInfo.agent_id == runtime.agent_id)).one()
            assert agent.version_no == 0 and agent.model_ids == [model_id]
            assert agent.prompt == original_prompt and agent.model_params_override == original_params
            assert agent.ingroup_permission == "READ_ONLY" and agent.is_main_agent is False
            assert agent.max_steps == 14 and agent.provide_run_summary and agent.allow_chat_metadata
            assert agent.enable_protocol_repair_retry
            assert agent.verification_config["enabled"] and agent.verification_config["max_final_rounds"] == 3
            assert agent.verification_config["guardrail_config"]["rules"][0]["name"] == "redact"
            assert {rule["name"]: rule["severity"] for rule in
                    agent.verification_config["guardrail_config"]["rules"]} == {
                "redact": "mask", "block_pii": "block", "allow": "pass",
            }
            assert {item.selected_agent_id for item in session.scalars(
                select(AgentRelation).where(AgentRelation.parent_agent_id == runtime.agent_id)
            )} >= {extra_id}
            assert {item.value_id for item in session.scalars(
                select(ResourceTagAssignment).where(ResourceTagAssignment.resource_id == str(runtime.agent_id))
            )} == {11, 12}
        catalogs.assert_not_awaited()

        from services import nl2agent_configuration

        with runtime.storage["sessions"]() as session:
            previous_relations = {item.selected_agent_id for item in session.scalars(
                select(AgentRelation).where(AgentRelation.parent_agent_id == runtime.agent_id,
                                            AgentRelation.tenant_id == tenant, AgentRelation.version_no == 0,
                                            AgentRelation.delete_flag != "Y")
            )}
        candidates = Mock(side_effect=AssertionError("Removal must not load candidate agents"))
        with monkeypatch.context() as removal:
            removal.setattr(nl2agent_configuration, "_visible_collaborators", candidates)
            removed_states, removed_receipts = run(runtime, [patch("collaborators", {"remove": [extra_id]})])
        candidates.assert_not_called()
        assert len(removed_receipts) == 1 and removed_receipts[0]["status"] == "success"
        assert removed_states == [{"event": "agent_draft_fields_saved", "agent_id": runtime.agent_id,
                                   "updated_fields": ["related_agents"]}]
        with runtime.storage["sessions"]() as session:
            assert {item.selected_agent_id for item in session.scalars(
                select(AgentRelation).where(AgentRelation.parent_agent_id == runtime.agent_id,
                                            AgentRelation.tenant_id == tenant, AgentRelation.version_no == 0,
                                            AgentRelation.delete_flag != "Y")
            )} == previous_relations - {extra_id}
            removed = session.scalars(select(AgentRelation).where(
                AgentRelation.parent_agent_id == runtime.agent_id, AgentRelation.selected_agent_id == extra_id,
                AgentRelation.tenant_id == tenant, AgentRelation.version_no == 0,
            )).one()
            assert removed.delete_flag == "Y"
        catalogs.assert_not_awaited()
