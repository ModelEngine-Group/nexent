# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Verify Management projection using serialized Runtime observer events."""

import json

from management.services.agent.stream import AssistantMessageProjection, finalize_buffered_unit_fragments


def test_projection_retains_legacy_indices_and_only_committed_model_fragments():
    projection = AssistantMessageProjection(message_id=12, next_unit_index=7)

    def project(kind, content="", **fields):
        chunk, _ = projection.project(json.dumps({"type": kind, "content": content, **fields}))
        return json.loads(chunk)

    assert project("model_output_thinking", "discard", attempt_id="previous")["unit_index"] == 7
    project("model_attempt_control", phase="rollback", attempt_id="previous")
    assert project("search_content", json.dumps([{"title": "source", "url": "https://example.com"}]))["unit_index"] == 8
    assert projection.search_records[0]["unit_index"] == 8
    assert project("final_answer", "hello ", answer_phase="delta", attempt_id="current")["unit_index"] == 9
    assert project("final_answer", "world", answer_phase="delta", attempt_id="current")["unit_index"] == 9
    complete = project("final_answer", answer_phase="complete", attempt_id="current")
    assert "unit_index" not in complete
    project("history_summary", "display only")
    file_event = project("skill_artifact", {"artifacts": [{"absolute_path": "/run/report.txt"}]})
    assert file_event["type"] == "skill_artifact"
    project("automation_proposal", '{"proposal_id": 32}')

    finalize_buffered_unit_fragments(projection.units)
    assert [(item["unit_index"], item["type"], item["content"]) for item in projection.units] == [
        (8, "search_content_placeholder", '{"placeholder": true}'),
        (9, "final_answer", "hello world"),
        (10, "automation_proposal", '{"proposal_id": 32}'),
    ]
    assert projection.automation_proposals == [{"unit_index": 10, "proposal_id": 32}]


def test_unpersisted_stream_does_not_add_indices_or_buffer_units():
    projection = AssistantMessageProjection(message_id=None)
    chunk = '{"type":"final_answer","content":"answer"}'
    assert projection.project(chunk)[0] == chunk
    assert not projection.units
    assert projection.project("invalid JSON") == ("invalid JSON", {})
