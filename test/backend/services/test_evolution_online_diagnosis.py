# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import json
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from management.services.evaluation import online_diagnosis as diagnosis


@pytest.mark.parametrize("evidence", [[], ["other-turn"], ["answer", "answer"], {"answer": "actual output"}])
def test_reject_missing_unknown_or_repeated_model_evidence(evidence):
    result = json.dumps({"finding": "tool_arguments", "evidence": evidence, "missing": []})
    with pytest.raises(ValueError):
        diagnosis.model_finding(result, {"answer": {"ref": "message:1"}}, clipped=False)


def test_model_cannot_clear_incomplete_evidence():
    result = '{"finding":"no_issue","evidence":[],"missing":[]}'
    assert diagnosis.model_finding(result, {}, clipped=True) == {
        "status": "needs_evidence", "reason": "incomplete_trace",
    }


@pytest.mark.parametrize("reason", ["trajectory_expired", "trajectory_mismatch"])
def test_unavailable_trajectory_short_circuits_message_and_model_analysis(mocker, reason):
    queue = diagnosis.queue
    mocker.patch.object(queue, "get_db_session", return_value=nullcontext(Mock()))
    facts = {"coverage": "missing", "signals": ["user_correction", "negative_feedback"], "unavailable": reason}
    mocker.patch.object(queue, "_authorized_claim", return_value=({"observation": facts}, {}))
    message_pair = mocker.patch.object(queue, "_message_pair")

    job = {"tenant_id": "t", "owner_id": "u", "previous_attempt": None, "diagnosis_claim_count": 1}
    evidence = queue.read_evidence(job)
    assert diagnosis.rule_finding(evidence) == {"status": "needs_evidence", "reason": reason}
    message_pair.assert_not_called()


@pytest.mark.parametrize("grant_seconds,claim_seconds", [(120, 10), (5, 20)])
def test_diagnosis_dispatch_is_bounded_by_grant_and_worker_lease(mocker, grant_seconds, claim_seconds):
    queue = diagnosis.queue
    now = datetime.now(timezone.utc)
    grant_deadline = now + timedelta(seconds=grant_seconds)
    claim_deadline = now + timedelta(seconds=claim_seconds)
    session = Mock()
    session.scalar.return_value = 27
    mocker.patch.object(queue, "get_db_session", return_value=nullcontext(session))
    mocker.patch.object(queue, "lock_model_charges")
    mocker.patch.object(queue, "_authorized_claim", return_value=(
        {"valid_until": grant_deadline}, {"diagnosis_attempt_id": None, "diagnosis_lease_until": claim_deadline},
    ))
    allowance = SimpleNamespace(model_id=11, revision=lambda: "fixture")
    assert queue.authorize_model({"turn_id": 4, "tenant_id": "t"}, None, allowance, "test-v1") == 27
    assert session.scalar.call_args.args[1]["until"] == min(grant_deadline, claim_deadline)


@pytest.mark.asyncio
@pytest.mark.parametrize("source", ["rule", "model", "missing_original"])
async def test_only_ambiguous_authorized_turns_use_the_diagnosis_model(mocker, source):
    async def direct(_name, function, *args):
        return function(*args)

    data = {"facts": {"coverage": "complete", "signals": ["negative_feedback"]}, "source_turn_id": 3,
            "request": "Expected business output", "answer": "Actual output", "clipped": False,
            "request_ref": "message:8", "answer_ref": "message:9", "nodes": [],
            "correction": "A required value is missing", "correction_ref": "message:10"}
    if source == "rule":
        data = {"facts": {"signals": ["tool_error"], "node_refs": ["otel:proof"]}}
    elif source == "missing_original":
        data = {"facts": {"signals": ["user_correction"]}, "missing": "missing_authorized_original"}
    mocker.patch.object(diagnosis, "_io", direct)
    mocker.patch.object(diagnosis.queue, "read_evidence", return_value=data)
    model = mocker.patch.object(diagnosis, "diagnosis_budget", return_value=SimpleNamespace(model_id=11))
    mocker.patch.object(diagnosis.queue, "authorize_model", return_value=27)
    model_call = mocker.patch.object(diagnosis, "invoke_chat_prompt", new_callable=AsyncMock,
                                     return_value='{"finding":"requirements_missed","evidence":["correction"],"missing":[]}')
    finish = mocker.patch.object(diagnosis.queue, "finish", Mock(return_value=True))
    job = {"tenant_id": "t", "owner_id": "u", "turn_id": 4}
    assert await diagnosis.diagnose_one(job)
    output = finish.call_args.args[1]
    if source == "model":
        model.assert_called_once_with("t")
        assert model_call.await_args.kwargs["diagnosis_attempt"] == 27
        assert model_call.await_args.kwargs["evolution_output_limit"] == 2048
        prompt = json.loads(model_call.await_args.kwargs["user_prompt"])
        assert prompt["allowed_evidence_keys"] == list(prompt["evidence"]) == ["request", "answer", "correction"]
        assert all("ref" not in item for item in prompt["evidence"].values())
        assert output["direction"] == "prompt" and output["evidence"] == ["message:10"]
        assert "required value" not in json.dumps(output)
    else:
        model_call.assert_not_awaited()
        model.assert_not_called()
        assert output["reason"] == ("tool_failure" if source == "rule" else "missing_authorized_original")
