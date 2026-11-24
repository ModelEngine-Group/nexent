# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import asyncio
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from contracts.agentos import ReplayToolObservation
from contracts.evolution import ToolUseExpectation
from management.services.evaluation.tool_use import judge_tool_use
from nexent.core.agents.resources.replay_tools import ReplayToolRecorder, bind_replay_tool


def test_actual_forward_calls_preserve_values_and_distinguish_null_from_absent():
    config = object()
    recorder = ReplayToolRecorder(config, {"read": ["key"]})
    tool = SimpleNamespace(forward=lambda *args, **kwargs: "unchanged", inputs={"key":{}})
    observer = SimpleNamespace(replay_tool_recorder=recorder)
    bind_replay_tool(observer, object(), tool, "read")
    assert tool.forward("other agent") == "unchanged" and recorder.receipt()["calls"] == []
    bind_replay_tool(observer, config, tool, "read")
    assert tool.forward(None) == tool.forward(private="never store this") == "unchanged"
    receipt = ReplayToolObservation.model_validate(recorder.receipt())
    assert "private" not in receipt.model_dump_json() and "never store this" not in receipt.model_dump_json()
    expectation = ToolUseExpectation(rules=[{"name":"read","min_calls":2,"max_calls":2,"arguments":{"key":None}}])
    grade = judge_tool_use(expectation.model_dump(), receipt)
    assert grade["issues"] == [{"tool":"read","reason":"wrong_arguments","call":2,"fields":["key"]}]


def test_zero_calls_requires_a_registered_tool_and_complete_receipt():
    rule = ToolUseExpectation(rules=[{"name":"write","min_calls":0,"max_calls":0}]).model_dump()
    observation = {"registered":["write"], "complete":True, "calls":[]}
    assert judge_tool_use(rule, ReplayToolObservation(**observation))["status"] == "pass"
    for updates in ({"registered":[]}, {"complete":False}):
        assert judge_tool_use(rule, ReplayToolObservation(**{**observation, **updates}))["status"] == "missing_evidence"
    assert judge_tool_use(rule, None)["status"] == "missing_evidence"


def test_versioned_exclusions_still_require_a_consistent_receipt():
    absent = {"excluded"}
    zero = ToolUseExpectation(rules=[{"name": "excluded", "min_calls": 0, "max_calls": 0},
                                     {"name": "retained", "min_calls": 0, "max_calls": 0}]).model_dump()
    receipt = ReplayToolObservation(registered=["retained"], complete=True, calls=[])
    assert judge_tool_use(zero, receipt, absent=absent)["status"] == "pass"
    for observation in (None, receipt.model_copy(update={"complete": False}),
                        receipt.model_copy(update={"registered": []}),
                        receipt.model_copy(update={"registered": ["retained", "excluded"]})):
        assert judge_tool_use(zero, observation, absent=absent)["status"] == "missing_evidence"
    required = ToolUseExpectation(rules=[{"name": "excluded", "min_calls": 1, "max_calls": 1}]).model_dump()
    grade = judge_tool_use(required, ReplayToolObservation(registered=[], complete=True, calls=[]), absent=absent)
    assert grade["issues"] == [{"tool": "excluded", "reason": "too_few", "count": 0}]


def test_raised_forward_remains_an_error_and_extra_calls_fail():
    recorder = ReplayToolRecorder(object(), {"apply":[]})
    def fail():
        raise RuntimeError("not written")
    tool = SimpleNamespace(forward=fail)
    recorder.bind(tool, "apply")
    with pytest.raises(RuntimeError, match="not written"):
        tool.forward()
    rule = ToolUseExpectation(rules=[{"name":"apply","min_calls":0,"max_calls":0}]).model_dump()
    result = judge_tool_use(rule, ReplayToolObservation(**recorder.receipt()))
    assert [issue["reason"] for issue in result["issues"]] == ["too_many","raised"]


def test_required_order_uses_completion_and_detects_overlapping_calls():
    recorder = ReplayToolRecorder(object(), {"read":[], "save":[]})
    started, release = asyncio.Event(), asyncio.Event()
    async def read():
        started.set()
        await release.wait()
    reader, writer = SimpleNamespace(forward=read), SimpleNamespace(forward=lambda: 1)
    recorder.bind(reader, "read")
    recorder.bind(writer, "save")
    async def overlap():
        first = asyncio.create_task(reader.forward())
        await started.wait()
        assert not recorder.receipt()["complete"]
        assert writer.forward() == 1
        release.set()
        await first
    asyncio.run(overlap())
    rule = ToolUseExpectation(rules=[{"name":"read"},{"name":"save"}],order=["read","save"]).model_dump()
    result = judge_tool_use(rule, ReplayToolObservation(**recorder.receipt()))
    assert result["sequence"] == ["read","save"] and result["issues"] == [{"reason":"wrong_order"}]


@pytest.mark.parametrize("rules,order", [
    ([{"name":"read","min_calls":2,"max_calls":1}], None),
    ([{"name":"x"},{"name":"x"}], None),
    ([{"name":"x"}], ["x","y"]),
    ([{"name":"x","max_calls":1}], ["x","x"]),
])
def test_invalid_business_rule_is_rejected_at_case_creation(rules, order):
    with pytest.raises(ValidationError):
        ToolUseExpectation(rules=rules, order=order)
