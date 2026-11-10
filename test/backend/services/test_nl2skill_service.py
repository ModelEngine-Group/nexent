# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Tests for the ephemeral NL2Skill runtime stream."""

import asyncio
import json
from types import SimpleNamespace

import pytest

from contracts.agent import NL2SkillRunRequest
from management.services.skill import creation as skill_service
from management.services.model import creator_snapshot
from management.services.skill.nl2skill import (
    _assemble_draft_content,
    _decorate_event,
    _extract_target_files,
    _normalize_draft_snapshot,
    _normalize_relative_path,
    project_creation_events,
)
from contracts.agentos import PreparedSkillCreatorRun
from infrastructure.agentos_identity import ServicePrincipal
from runtime.agentos import prepared_skill_creator as runtime
from runtime.agentos.prepared_skill_creator import NL2SKILL_NAME, create_nl2skill_agent_config


def test_create_nl2skill_agent_config_sets_ephemeral_runtime_options():
    config = create_nl2skill_agent_config("system", "model")
    assert config.name == NL2SKILL_NAME
    assert config.name == "__skill_creator__"
    assert config.display_name == "技能创建助手"
    assert config.model_name == "model"
    assert config.instructions is None
    assert config.context_items[0].content["text"] == "system"
    assert config.tools == []
    assert config.max_steps == 5
    assert config.output_protocol == "final_envelope"
    assert config.provide_run_summary is False
    assert config.enable_planning is False


def test_normalize_relative_path_rejects_absolute_parent_and_empty_segments():
    """UT-BE-NCR-009: reject unsafe or ambiguous generated file paths."""
    assert _normalize_relative_path("scripts/run.py") == "scripts/run.py"
    assert _normalize_relative_path("./scripts/run.py") == "scripts/run.py"
    assert _normalize_relative_path("/tmp/run.py") is None
    assert _normalize_relative_path("../run.py") is None
    assert _normalize_relative_path("scripts//run.py") is None
    assert _normalize_relative_path("C:/run.py") is None
    assert _normalize_relative_path("bad\\run.py") == "bad/run.py"


def test_assemble_draft_content_handles_invalid_files_and_skill_fallback():
    assert _assemble_draft_content({"content": "fallback", "files": "invalid"}) == "fallback"
    assert _assemble_draft_content({"content": "", "files": [{"path": "notes.txt", "content": ""}]}) == ""
    assert _assemble_draft_content({"content": "fallback", "files": [{"path": "notes.txt", "content": "note"}]}) == (
        "<skill>\nfallback\n</skill>\n\n<file path=\"notes.txt\">\nnote\n</file>"
    )


def test_decorate_event_adds_sequence_and_block_ids():
    assert _decorate_event({"type": "skill_body"}, 1) == {
        "type": "skill_body", "sequence": 1, "block_id": "skill:SKILL.md"
    }
    assert _decorate_event({"type": "file_content", "path": "a.py"}, 2)["block_id"] == "file:a.py"
    assert _decorate_event({"type": "summary"}, 3)["block_id"] == "summary"
    assert _decorate_event({"type": "others"}, 4)["sequence"] == 4


def test_normalize_draft_snapshot_assembles_all_files():
    result = _normalize_draft_snapshot(
        {
            "name": "demo",
            "description": "Demo skill",
            "tags": ["demo"],
            "files": [
                {"path": "SKILL.md", "content": "# Demo"},
                {"path": "scripts/run.py", "content": "print('ok')"},
            ],
        }
    )

    assert result is not None
    assert "<skill>\n# Demo\n</skill>" in result["content"]
    assert '<file path="scripts/run.py">' in result["content"]


def test_normalize_draft_snapshot_keeps_empty_initial_draft_empty():
    result = _normalize_draft_snapshot(
        {
            "name": "",
            "description": "",
            "tags": [],
            "files": [{"path": "SKILL.md", "content": ""}],
        }
    )

    assert result is not None
    assert result["content"] == ""


def test_extract_target_files_only_returns_existing_normalized_mentions():
    snapshot = {
        "files": [
            {"path": "SKILL.md", "content": "# Demo"},
            {"path": "references/guide.md", "content": "Guide"},
            {"path": "scripts/run.py", "content": "print('ok')"},
        ]
    }

    result = _extract_target_files(
        'Update <reference path="./references/guide.md" /> and '
        "<use_script path='scripts/run.py' />; ignore "
        '<reference path="../secret.md" /> and '
        '<use_script path="scripts/missing.py" />.',
        snapshot,
    )

    assert result == ["references/guide.md", "scripts/run.py"]


def test_extract_target_files_requires_a_draft_snapshot():
    assert _extract_target_files('<use_script path="scripts/run.py" />', None) == []


@pytest.mark.parametrize(("model_id", "configured", "expected"), [
    (7, None, 7), (None, 8, 8), (None, None, 9),
])
def test_snapshot_model_selection(mocker, model_id, configured, expected):
    def record(model_id):
        return {"model_id": model_id, "display_name": str(model_id), "update_time": "v1", "model_type": "llm"}

    mocker.patch.object(creator_snapshot, "preflight_turn_controls")
    mocker.patch.object(creator_snapshot, "get_model_by_model_id", return_value=record(7))
    mocker.patch.object(creator_snapshot.tenant_config_manager, "get_model_config",
                        return_value=record(configured) if configured else None)
    mocker.patch.object(creator_snapshot, "get_model_records", return_value=[record(9)])
    mocker.patch.object(creator_snapshot, "_resolve_input_budget", return_value=(8192, {}, None))
    mocker.patch.object(creator_snapshot, "_resolve_context_budget", return_value=None)
    request = NL2SkillRunRequest(query="Create", model_id=model_id, history=[
        {"role": "user", "content": "old"}, {"role": "system", "content": "ignored"},
    ])
    snapshot = skill_service.prepare_nl2skill_snapshot(request, "owner", "tenant", "unknown")
    assert snapshot.model.model_id == expected and snapshot.language == "zh"
    assert [(item.role, item.content) for item in snapshot.input.history] == [("user", "old")]


def test_snapshot_requires_a_model(mocker):
    mocker.patch.object(creator_snapshot.tenant_config_manager, "get_model_config", return_value={})
    mocker.patch.object(creator_snapshot, "get_model_records", return_value=[])
    with pytest.raises(ValueError, match="No LLM model"):
        skill_service.prepare_nl2skill_snapshot(NL2SkillRunRequest(query="Create"), "owner", "tenant", "en")


def test_runtime_renders_authorized_attachment_in_prompt(mocker):
    from nexent.core.agents.agent_model import ModelConfig
    from runtime.agentos import prepared_attachments

    mocker.patch.object(runtime, "_materialize_model", return_value=ModelConfig(
        cite_name="model", model_name="provider-model", api_key="test", url="https://provider.invalid",
    ))
    authorized = mocker.patch.object(prepared_attachments, "validate_attachment_references")
    payload = PreparedSkillCreatorRun.model_validate({
        "mode": "nl2skill", "run_id": "c" * 32, "language": "en",
        "input": {"query": "Create a parser", "attachment_refs": [{"name": "sample.csv", "url": "s3://bucket/sample.csv"}]},
        "model": {"model_id": 5, "alias": "model", "revision": "v1"},
        "input_budget": 8192, "context_window_tokens": 16000,
    })
    info = runtime.prepare_skill_creator_run(payload, ServicePrincipal("owner", "tenant"))
    authorized.assert_called_once_with(["s3://bucket/sample.csv"], "owner", "tenant")
    assert "sample.csv" in info.query and "s3://bucket/sample.csv" in info.query
    assert info.enable_planning is False and info.sandbox_config is None
    assert info.agent_config.context_manager_config.context_window_tokens == 16000


@pytest.mark.asyncio
async def test_stream_preserves_raw_types_and_emits_semantic_events():
    """UT-BE-NCR-016: preserve Skill event semantics."""
    async def fake_agent_run():
        chunks = [
            {"type": "model_thinking_output", "content": "Preparing.\n<final_"},
            {"type": "model_output_thinking", "content": "answer>\n<sk"},
            {
                "type": "model_output_thinking",
                "content": "ill>\n---\nname: demo\ndescription: Demo\ntags: [demo]\n---\n# Demo\n</skill>\n",
            },
            {"type": "model_output_code", "content": '<file path="scripts/run.py">\nprint("ok")\n</file>\n'},
            {"type": "model_output_thinking", "content": "<summary>\nReady.\n</summary>\n</final_answer>"},
            {"type": "final_answer", "content": "duplicate"},
        ]
        for chunk in chunks:
            yield json.dumps(chunk)

    stream = project_creation_events(fake_agent_run(), [])
    payloads = []
    async for item in stream:
        payloads.append(json.loads(item.removeprefix("data: ").strip()))

    assert payloads[0]["type"] == "model_thinking_output"
    assert any(item["type"] == "skill_body" for item in payloads)
    assert any(
        item["type"] == "file_content" and item["path"] == "scripts/run.py"
        for item in payloads
    )
    assert any(item["type"] == "summary" for item in payloads)
    assert not any("</final_answer>" in item.get("content", "") for item in payloads)
    assert not any(item.get("content") == "duplicate" for item in payloads)
    assert payloads[-1]["type"] == "done"


@pytest.mark.asyncio
async def test_stream_parses_skill_start_after_reasoning_without_newline():
    async def fake_agent_run():
        yield json.dumps(
            {
                "type": "model_output_deep_thinking",
                "content": "Reasoning finished.",
            }
        )
        yield json.dumps(
            {
                "type": "model_output_thinking",
                "content": "<",
            }
        )
        yield json.dumps(
            {
                "type": "model_output_thinking",
                "content": "skill>\n# Demo\n</skill>\n",
            }
        )

    stream = project_creation_events(fake_agent_run(), [])
    payloads = [
        json.loads(item.removeprefix("data: ").strip())
        async for item in stream
    ]

    assert "".join(
        item["content"] for item in payloads if item["type"] == "skill_body"
    ) == "# Demo\n"
    assert not any(
        item["type"] == "model_output_thinking"
        and "SKILL" in item["content"]
        for item in payloads
    )
    assert payloads[-1]["type"] == "done"


@pytest.mark.asyncio
async def test_stream_emits_targets_and_filters_non_target_file_updates():
    async def fake_agent_run():
        yield json.dumps(
            {
                "type": "model_output_code",
                "content": (
                    "<skill>\n# Changed unexpectedly\n</skill>\n"
                    '<file path="scripts/other.py">\nother\n</file>\n'
                    '<file path="scripts/run.py">\nupdated\n</file>\n'
                    "<summary>\nDone.\n</summary>\n"
                ),
            }
        )

    request = NL2SkillRunRequest(
        query='Improve <use_script path="scripts/run.py" />',
        draft_snapshot={
            "files": [
                {"path": "SKILL.md", "content": "# Demo"},
                {"path": "scripts/run.py", "content": "old"},
                {"path": "scripts/other.py", "content": "keep"},
            ]
        },
    )
    stream = project_creation_events(fake_agent_run(), _extract_target_files(request.query, request.draft_snapshot))
    payloads = [json.loads(item.removeprefix("data: ").strip()) async for item in stream]

    assert payloads[0]["type"] == "target_files"
    assert payloads[0]["paths"] == ["scripts/run.py"]
    assert any(
        item["type"] == "file_content"
        and item["path"] == "scripts/run.py"
        and "updated" in item["content"]
        for item in payloads
    )
    assert not any(item["type"] == "skill_body" for item in payloads)
    assert not any(item.get("path") == "scripts/other.py" for item in payloads)


@pytest.mark.asyncio
async def test_stream_skips_malformed_chunks_and_emits_error_on_agent_failure():
    """UT-BE-NCR-018: runtime failure produces one safe terminal error."""
    async def failing_agent_run():
        yield "not json"
        yield ["not a mapping"]
        raise RuntimeError("provider failed")

    stream = project_creation_events(failing_agent_run(), [])
    payloads = [json.loads(item.removeprefix("data: ").strip()) async for item in stream]

    assert payloads == [
        {"type": "error", "content": "NL2Skill execution failed.", "sequence": 1}
    ]


@pytest.mark.asyncio
async def test_stream_classifies_final_answer_deltas_including_later_tail():
    async def fake_agent_run():
        yield json.dumps({"type": "final_answer", "content": "<skill>\n# Demo", "answer_phase": "delta"})
        yield json.dumps({"type": "final_answer", "content": "tail\n</skill>", "answer_phase": "delta"})

    stream = project_creation_events(fake_agent_run(), [])
    payloads = [json.loads(item.removeprefix("data: ").strip()) async for item in stream]

    assert any(item["type"] == "skill_body" and "# Demo" in item["content"] for item in payloads)
    assert "".join(item["content"] for item in payloads if item["type"] == "skill_body") == "# Demotail\n"
    assert payloads[-1]["type"] == "done"


@pytest.mark.asyncio
async def test_stream_preserves_final_answer_without_control_content():
    async def fake_agent_run():
        yield json.dumps({"type": "final_answer", "content": "Done."})

    stream = project_creation_events(fake_agent_run(), [])
    payloads = [json.loads(item.removeprefix("data: ").strip()) async for item in stream]

    assert payloads == [
        {"type": "final_answer", "content": "Done.", "sequence": 1},
        {"type": "done", "content": "", "sequence": 2},
    ]


@pytest.mark.asyncio
async def test_stream_propagates_cancellation_without_success_terminal():
    """UT-BE-NCR-019: cancellation stops without duplicate terminal output."""
    async def cancelled_agent_run():
        raise asyncio.CancelledError()
        yield None

    stream = project_creation_events(cancelled_agent_run(), [])
    with pytest.raises(asyncio.CancelledError):
        await anext(stream)
