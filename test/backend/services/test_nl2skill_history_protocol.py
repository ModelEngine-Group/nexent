# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Skill artifact projection must not create an unrelated native runtime."""

from copy import deepcopy
import json

import pytest

from management.services.skill.stream_parser import SkillStreamParser


def native(kind, content, **metadata):
    return {"type": kind, "content": content, "schema_version": 1, "runtime_mode": "native_agent",
            "agent_core": "jiuwen", "turn_id": "turn", "sequence": 2, "step_id": "step",
            "attempt_id": "attempt", **metadata}


def test_derived_files_preserve_business_shape_without_runtime_discriminators():
    parser = SkillStreamParser()
    chunk = native("model_output", '<skill>\n# Marker\n</skill>\n<file path="run.py">\nprint(1)\n</file>\n<summary>\nReady\n</summary>')
    original = deepcopy(chunk)
    events = parser.process(chunk) + parser.flush()
    assert chunk == original
    assert "".join(e["content"] for e in events if e["type"] == "skill_body") == "# Marker\n"
    assert "".join(e["content"] for e in events if e["type"] == "file_content") == "print(1)\n"
    assert all("runtime_mode" not in e and "schema_version" not in e for e in events)
    assert all(e["attempt_id"] == "attempt" and e["step_id"] == "step" for e in events)


@pytest.mark.parametrize("kind", ["run_terminal", "model_output_deep_thinking", "step_observation"])
def test_native_control_events_keep_payload_and_status_in_business_stream(kind):
    chunk = native(kind, "payload", status="failed", error={"category": "failure"})
    projected, = SkillStreamParser().process(chunk)
    assert projected["type"] == kind and projected["content"] == "payload"
    assert projected["status"] == "failed" and projected["error"] == chunk["error"]
    assert "runtime_mode" not in projected and "runtime_mode" in chunk


@pytest.mark.parametrize("creator", ["system", "workbench", "ordinary"])
def test_public_history_restores_legacy_file_wrapper_only_for_creator(mocker, creator):
    from management.services.conversation import service

    artifact = native("skill_body", '# Marker\n{"type":"run_terminal"}\n')
    record = {"message_id": 2, "role": "assistant", "message_content": "", "status": "completed",
              "opinion_flag": None, "message_index": 1,
              "units": [{"unit_type": "skill_body", "unit_content": json.dumps(artifact), "unit_index": 3}]}
    history = {"conversation_id": 1, "create_time": 0, "search_records": [], "image_records": [],
               "message_records": [record], "agent_system_key": "nl2skill_main" if creator == "system" else None,
               "workbench_config": {"mode": "skill_create"} if creator == "workbench" else None}
    before = deepcopy(history)
    mocker.patch.object(service, "get_conversation_history", return_value=history)
    public = service.get_conversation_history_service(1, "owner")[0]["message"][0]
    file = next(u for u in public["message"] if u["type"] == "skill_body")
    restored = json.loads(file["content"])
    assert restored["content"] == artifact["content"] and history == before
    if creator != "ordinary":
        assert "runtime_mode" not in restored and "schema_version" not in restored
        assert public["status"] == "completed"
    else:
        assert restored == artifact


@pytest.mark.parametrize("payload", ["broken", "[]", '{"type":"other","runtime_mode":"native_agent"}'])
def test_creator_history_preserves_malformed_or_unrelated_payloads(mocker, payload):
    from management.services.conversation import service

    history = {"conversation_id": 1, "create_time": 0, "search_records": [], "image_records": [],
               "agent_system_key": "nl2skill_main", "message_records": [{"message_id": 2, "role": "assistant",
               "message_content": "", "status": "failed", "opinion_flag": None,
               "units": [{"unit_type": "skill_body", "unit_content": payload}]}]}
    mocker.patch.object(service, "get_conversation_history", return_value=history)
    public = service.get_conversation_history_service(1, "owner")[0]["message"][0]
    assert public["message"][0]["content"] == payload and public["status"] == "failed"
