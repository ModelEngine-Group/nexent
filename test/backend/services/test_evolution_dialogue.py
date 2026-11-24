# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from pydantic import ValidationError

from contracts.agentos import EvaluationAgentResult, ReplayReceipt, ReplayToolObservation, RunInput
from contracts.errors.exceptions import AppException
from contracts.evolution import ReplayCaseRequest, ToolUseExpectation
from management.services.evaluation.replay_cases import _approve_trace
from management.services.evaluation.replay_dialogue import run_turns
from management.services.evaluation.tool_use import judge_dialogue_tools


@pytest.mark.parametrize("failure", ["receipt_id", "outcome", "missing_final", "private_bucket", "followup_revoked", None])
@pytest.mark.asyncio
async def test_followup_receives_only_this_arms_completed_answer(failure):
    spec = Mock(new_skill_trial=None, scoped_skill_trials=[], confirmation_bucket="private" if failure == "private_bucket" else None,
                resource=SimpleNamespace(skill_refs=[]), observe_root_skill_choices=False, tool_set_check=None)
    spec.model_copy.side_effect = lambda update: SimpleNamespace(**update)
    job = {"receipt_id": "3" * 32, "trial_id": 44}
    inputs = [RunInput(query="outline", attachment_refs=[{"name":"minutes", "url":"s3://bucket/first"}]),
              RunInput(query="publish")]
    load_input = AsyncMock(side_effect=inputs)
    payloads = []
    permitted = []

    async def authorize_turn(turn_index):
        assert load_input.await_count == turn_index + 1
        if turn_index == 1 and failure == "followup_revoked":
            raise ValueError("permission revoked")
        permitted.append(turn_index)

    async def respond(payload, user, tenant):
        assert permitted[-1] == len(payloads)
        payloads.append(payload)
        first = len(payloads) == 1
        receipt = ReplayReceipt(trial_id="0" * 32 if first and failure == "receipt_id" else payload.replay_trial_id,
                                outcome="aborted" if first and failure == "outcome" else "completed")
        return EvaluationAgentResult(answer="this arm" if first else "done", replay_receipt=receipt,
            events=[] if first and failure == "missing_final" else [{"type":"final_answer"}])

    task = {"followups":[{"query":"publish", "attachment_names":[]}], "expected":"private scoring key"}
    client = SimpleNamespace(run_prepared_evaluation=respond)
    if failure == "followup_revoked":
        with pytest.raises(ValueError, match="permission revoked"):
            await run_turns(client, spec, task, load_input, job, "editor", "tenant", before_dispatch=authorize_turn)
        assert len(payloads) == 1 and permitted == [0]
        return
    observed, records, error = await run_turns(client, spec, task, load_input, job, "editor", "tenant",
                                               before_dispatch=authorize_turn)
    assert not payloads[0].input.history and "private scoring key" not in payloads[0].input.model_dump_json()
    if failure:
        assert error and not observed and len(records) == load_input.await_count == 1
        assert records[0]["outcome"] == error["error"]
        assert records[0]["answer"] is None
        return
    assert not error and len(observed) == len(records) == 2
    assert payloads[0].replay_trial_id != payloads[1].replay_trial_id == job["receipt_id"]
    history = payloads[1].input.history
    assert [(item.role, item.content) for item in history] == [("user", "outline"), ("assistant", "this arm")]
    assert history[0].attachment_refs == inputs[0].attachment_refs and not history[1].attachment_refs
    assert records[0]["attachments"] == ["minutes"] and records[1]["attachments"] == []


@pytest.mark.parametrize("followups", [
    [{"query":"  "}], [{"query":"x", "answer":"recorded answer"}],
    [{"query":"x", "attachment_names":["missing"]}], [{"query":"x"}] * 16,
    [{"query":"x", "attachment_names":["minutes"]}] * 2,
])
def test_reject_impossible_or_prefilled_dialogue(followups):
    with pytest.raises(ValidationError):
        ReplayCaseRequest(agent_id=1, version_no=1, family="minutes", query="start", expected="done",
                          attachments=[{"name":"minutes", "object_name":"attachments/me/source"}], followups=followups)


def test_tool_receipts_are_checked_across_turns_in_execution_order():
    def turn(tool):
        return ReplayToolObservation(registered=["read", "write"], complete=True, calls=[
            {"name":tool, "outcome":"returned", "start":1, "end":2, "arguments":{}}])
    rule = ToolUseExpectation(rules=[{"name":"read", "max_calls":1}, {"name":"write"}], order=["read","write"]).model_dump()
    assert judge_dialogue_tools(rule, [turn("read"), turn("write")])["status"] == "pass"
    assert judge_dialogue_tools(rule, [turn("write"), turn("read")])["status"] == "fail"
    assert judge_dialogue_tools(rule, [None, turn("write")])["status"] == "missing_evidence"


def test_trace_confirmation_requires_input_coverage_in_its_original_turn():
    digest = "d" * 64
    segments = [{"task_turn_id": i, "trajectory_id": str(i), "attachment_count": count}
                for i, count in enumerate([0, 1], 1)]
    draft = {"draft_digest": digest, "segments": segments, "attachment_count":1, "tool_count":0,
             "trajectory_id":"2", "task_turn_id":2, "source_group":"chat", "correction_trajectory_id":None}
    body = dict(agent_id=1, version_no=1, family="minutes", query="list", expected="source",
                attachments=[{"name":"notes", "object_name":"attachments/me/notes"}],
                trace={"turn_id":2, "preceding_turns":1, "inputs_reviewed":True, "purpose":"protect", "draft_digest":digest})
    with pytest.raises(AppException, match="each selected source turn"):
        _approve_trace(ReplayCaseRequest(**body), draft)
    with pytest.raises(AppException, match="attachments for each turn"):
        _approve_trace(ReplayCaseRequest(**body, followups=[{"query":"append sources"}]), draft)
    request = ReplayCaseRequest(**body, followups=[{"query":"append sources", "attachment_names":["notes"]}])
    assert _approve_trace(request, draft)["turn_sources"] == [
        {"turn_id":1, "trajectory_id":"1"}, {"turn_id":2, "trajectory_id":"2"}]
