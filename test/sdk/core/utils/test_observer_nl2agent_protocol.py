# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""NL2Agent policy and Workbench naming events survive the SDK boundary."""

import json

import pytest

from nexent.core.utils.observer import MessageObserver, ProcessType


@pytest.mark.parametrize("fields", [
    ["enable_protocol_repair_retry"],
    ["name", "display_name"],
    ["description", "enable_protocol_repair_retry"],
])
def test_policy_and_workbench_naming_saves_emit_each_time(fields):
    observer = MessageObserver(lang="en", enable_nl2a_wrapper=True)
    state = {"event": "agent_draft_fields_saved", "agent_id": 42, "updated_fields": fields}
    content = '{"status":"success"}\n<nl2a_state>' + json.dumps(state) + '</nl2a_state>'
    for _ in range(2):
        observer.add_message("nl2agent", ProcessType.EXECUTION_LOGS, content)
    events = [json.loads(item) for item in observer.get_cached_message()]
    states = [json.loads(item["content"]) for item in events if item["type"] == ProcessType.NL2A_STATE.value]
    assert states == [state, state]
    assert not any("agent_generation_completed" in item["content"] for item in events)
    assert all("<nl2a_state>" not in item["content"] for item in events)


@pytest.mark.parametrize("fields", [
    ["enable_protocol_repair_retry", "unknown"],
    ["enable_protocol_repair_retry", "enable_protocol_repair_retry"],
    ["display_name", "display_name"],
])
def test_new_policy_fields_do_not_weaken_invalid_batch_rejection(fields):
    state = {"event": "agent_draft_fields_saved", "agent_id": 42, "updated_fields": fields}
    event, visible = MessageObserver._extract_nl2a_state('<nl2a_state>' + json.dumps(state) + '</nl2a_state>\nVisible')
    assert event is None
    assert visible == "Visible"
