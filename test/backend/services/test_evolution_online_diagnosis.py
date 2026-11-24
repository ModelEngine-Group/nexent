# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from management.services.evaluation import online_diagnosis as diagnosis


@pytest.mark.parametrize("evidence", [[], ["other-turn"], ["answer", "answer"]])
def test_reject_missing_unknown_or_repeated_model_evidence(evidence):
    result = json.dumps({"finding": "tool_arguments", "evidence": evidence, "missing": []})
    with pytest.raises(ValueError):
        diagnosis.model_finding(result, {"answer": {"ref": "message:1"}}, clipped=False)


def test_model_cannot_clear_incomplete_evidence():
    result = '{"finding":"no_issue","evidence":[],"missing":[]}'
    assert diagnosis.model_finding(result, {}, clipped=True) == {
        "status": "needs_evidence", "reason": "incomplete_trace",
    }


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
        assert output["direction"] == "prompt" and output["evidence"] == ["message:10"]
        assert "required value" not in json.dumps(output)
    else:
        model_call.assert_not_awaited()
        model.assert_not_called()
        assert output["reason"] == ("tool_failure" if source == "rule" else "missing_authorized_original")
