# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Real stream/record collaboration before the existing batch persistence boundary."""
import json
import pytest
from nexent.core.agents.context.execution_history import ExecutionHistory
from management.services.agent.stream import bind_execution_result_unit, finalize_execution_result_units


def test_ac015_ac016_binding_and_final_snapshot_preserve_original_and_summary():
    history = ExecutionHistory()
    key = history.register("agent", {"STDOUT": "original <body>"})
    unit = bind_execution_result_unit(history, key, 81, 7, {"invocation_id": "child"})
    original = json.loads(unit["unit_content"])["content"]
    assert history.get(key).reference == "message:81/unit-index:7"
    assert unit["invocation_id"] == "child"
    history.get(key).summary = "concise facts"
    finalize_execution_result_units(history, [unit])
    payload = json.loads(unit["unit_content"])
    assert payload == {"content": original, "summary": "concise facts"}
    assert "_execution_key" not in unit
    assert "source_digest" not in payload and "recipe_version" not in payload
    assert json.loads(history.read("agent", "message:81/unit-index:7"))["text"] == original


def test_ac006_unknown_record_does_not_create_a_false_unit():
    history = ExecutionHistory()
    with pytest.raises(ValueError, match="Unknown"):
        bind_execution_result_unit(history, "missing", 81, 7, {})


def test_ac016_legacy_units_unchanged():
    units = [{"type": "tool", "unit_content": "legacy", "content": "legacy"}]
    finalize_execution_result_units(ExecutionHistory(), units)
    assert units == [{"type": "tool", "unit_content": "legacy", "content": "legacy"}]
