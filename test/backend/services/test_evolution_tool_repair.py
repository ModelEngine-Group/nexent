# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from mcp.types import CallToolResult, TextContent
from pydantic import ValidationError

from contracts.agentos import ReplayToolObservation
from contracts.errors.exceptions import AppException
from contracts.evolution import ToolUseRule
from management.services.evaluation.tool_repairs import verified_example
from management.services.evaluation.tool_use import judge_tool_use
from nexent.core.agents.resources.replay_mcp import call_session_tool, capture_reply
from nexent.core.agents.resources.replay_tools import argument_digest


def test_remote_checks_are_opt_in_and_exclude_identity_fields():
    assert "expected_mcp_reply" not in ToolUseRule(name="lookup").model_dump()
    check = {"kind": "structured", "value": {"day": "Friday"}}
    assert ToolUseRule(name="lookup", expected_mcp_reply=check).expected_mcp_reply.value == check["value"]
    for invalid in [
        {"expected_mcp_reply": {**check, "value": "wrong type"}},
        {"min_calls": 0},
        {"arguments": {"tenant_id": "t"}},
        {"expected_mcp_reply": {"kind": "text", "value": "a" * 70000}},
        {"expected_script_files": {}},
    ]:
        with pytest.raises(ValidationError):
            ToolUseRule(**{"name": "lookup", "expected_mcp_reply": check, **invalid})


def test_remote_check_requires_a_bound_root_mcp_tool_and_replay(monkeypatch):
    from contracts.constants import environment
    from runtime.agentos.prepared_evaluation import prepare_evaluation_run

    for replay, tool, fields in [
        (False, "mcp", {"receipt": []}),
        (True, "local", {"receipt": []}),
        (True, "mcp", {}),
    ]:
        monkeypatch.setattr(environment, "EVOLUTION_REPLAY_RUNTIME", replay)
        payload = SimpleNamespace(
            omit_root_skill_candidate_id=None,
            observe_root_skill_choices=False,
            new_skill_trial=None,
            scoped_skill_trials=[],
            watch_skill_process=None,
            watch_tool_arguments=fields,
            watch_mcp_replies={"receipt": {"kind": "structured"}},
            replay_trial_id="a" * 32,
            tool_set_check=None,
            resource=SimpleNamespace(
                tools=[SimpleNamespace(tool_id=tool, version="1", parameters={"tool_name": "receipt"})]
            ),
        )
        with pytest.raises(HTTPException) as error:
            prepare_evaluation_run(payload, None)
        assert error.value.status_code == 422


def test_protocol_error_unselected_input_and_absent_evidence_cannot_be_tool_repairs():
    name, args = "receipt", {"day": "Friday"}
    rule = {
        "name": name,
        "min_calls": 1,
        "max_calls": 1,
        "arguments": args,
        "expected_mcp_reply": {"kind": "structured", "value": {"label": "private"}},
    }
    physical = {**args, "tenant_id": "private-identity"}
    response = CallToolResult(
        content=[TextContent(type="text", text="unused")], structuredContent={"label": "private"}
    )
    session = SimpleNamespace(call_tool=AsyncMock(return_value=response))

    def capture(values, *, repeat=False):
        call = {
            "name": name,
            "arguments": {"day": argument_digest("Friday")},
            "start": 1,
            "end": 2,
            "outcome": "returned",
        }
        with capture_reply(call, ["day"], {"kind": "structured"}):
            assert asyncio.run(call_session_tool(session, name, values)) is response
            if repeat:
                asyncio.run(call_session_tool(session, name, values))
        obs = ReplayToolObservation(registered=[name], calls=[call], complete=True)
        assert "private" not in obs.model_dump_json()
        return judge_tool_use({"rules": [rule]}, obs)

    assert capture(physical)["status"] == "pass"
    assert {i["reason"] for i in capture({**physical, "unapproved": "x"})["issues"]} == {"wrong_mcp_inputs"}
    assert capture(physical, repeat=True)["reason"] == "unverified_mcp_reply"
    response.structuredContent = None
    assert capture(physical)["reason"] == "unverified_mcp_reply"
    response.structuredContent = {"label": "private"}
    response.isError = True
    assert {i["reason"] for i in capture(physical)["issues"]} == {"mcp_remote_error"}
    rule["expected_mcp_reply"]["error"] = True
    assert capture(physical)["status"] == "pass"
    rule["expected_mcp_reply"]["error"] = False
    with pytest.raises(AppException):
        verified_example(
            {"digest": "case", "task": {"tool_use": {"rules": [rule]}}},
            {
                "receipt_id": "r",
                "status": "fail",
                "result": {"case_digest": "case", "snapshot_digest": "baseline", "tool_use": capture(physical)},
            },
            "fail",
            "baseline",
            name,
        )


@pytest.mark.parametrize("initial", [None, {"receipt": "unexpected"}])
def test_missing_or_dirty_initial_state_stops_before_remote_action(initial):
    read = AsyncMock(return_value=SimpleNamespace(contents=[SimpleNamespace(text=json.dumps(initial))]))
    session = SimpleNamespace(read_resource=read, call_tool=AsyncMock())
    trace = {}
    with capture_reply(trace, [], {"kind": "text", "initial_digest": argument_digest({"receipt": ""})}):
        with pytest.raises(ValueError, match="initial state"):
            asyncio.run(call_session_tool(session, "receipt", {}))
    session.call_tool.assert_not_awaited()
    assert trace["mcp_fixture_unready"]


def test_remote_fault_after_correct_inputs_is_not_an_agent_invocation_edit():
    from management.services.evaluation.feedback_handoff import invocation_issues

    grade = {
        "mcp_evidence": [{"tool": "lookup", "call": 1, "error": True, "input_matches": True}],
        "issues": [
            {"tool": "lookup", "reason": reason, "call": 1}
            for reason in ("wrong_mcp_reply", "wrong_mcp_state", "mcp_remote_error", "raised")
        ],
    }
    assert invocation_issues(grade, "lookup", []) == []
    missing = {"tool": "lookup", "reason": "wrong_mcp_inputs", "call": 2}
    grade["issues"].append(missing)
    assert invocation_issues(grade, "lookup", []) == [missing]


@pytest.mark.parametrize("status,code", [("pass", 0), ("fail", 1), ("missing_evidence", 2)])
def test_maintainer_command_propagates_regression_status(monkeypatch, capsys, status, code):
    import sys
    from management.cli import tool_repair_check

    run = AsyncMock(return_value={"case": "failure", "status": status})
    monkeypatch.setattr(tool_repair_check, "run_case", run)
    monkeypatch.setattr(
        sys, "argv", ["check", "cases.json", "--case", "failure", "--fixture-url", "http://127.0.0.1:9090/mcp"]
    )
    assert tool_repair_check.main() == code
    assert json.loads(capsys.readouterr().out)["status"] == status
    run.assert_awaited_once()


def test_exported_contract_cannot_select_a_server_or_omit_independent_state():
    from contracts.tool_repair import ToolReproductionSuite

    rule = {
        "name": "post_receipt",
        "min_calls": 1,
        "max_calls": 1,
        "arguments": {"reference": "A"},
        "expected_mcp_reply": {
            "kind": "text",
            "value": "ok",
            "fixture": {"initial": {}, "final": {"receipt": "A"}},
        },
    }
    suite = {"format": "nexent-mcp-repair-v1", "failure": rule, "protection": rule}
    assert ToolReproductionSuite.model_validate(suite).failure.name == "post_receipt"
    for invalid in [
        {"url": "http://unused"},
        {"protection": {**rule, "name": "another"}},
        {"failure": {**rule, "expected_mcp_reply": {"kind": "text", "value": "ok"}}},
    ]:
        with pytest.raises(ValidationError):
            ToolReproductionSuite.model_validate({**suite, **invalid})
