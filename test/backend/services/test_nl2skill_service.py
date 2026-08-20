"""Tests for the ephemeral NL2Skill runtime stream."""

import asyncio
import json
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from consts.model import NL2SkillRunRequest
import services.nl2skill_service as nl2skill_service
from services.nl2skill_service import (
    _assemble_draft_content,
    _convert_history,
    _decorate_event,
    _extract_target_files,
    _normalize_draft_snapshot,
    _normalize_relative_path,
    _resolve_model_for_nl2skill,
    build_nl2skill_run_info,
    create_nl2skill_stream,
)
from agents.nl2skill_agent import NL2SKILL_NAME, create_nl2skill_agent_config


def test_create_nl2skill_agent_config_sets_ephemeral_runtime_options():
    config = create_nl2skill_agent_config("system", "model")
    assert config.name == NL2SKILL_NAME
    assert config.model_name == "model"
    assert config.instructions == "system"
    assert config.tools == []
    assert config.max_steps == 5
    assert config.provide_run_summary is False
    assert config.enable_planning is False


def test_normalize_relative_path_rejects_absolute_parent_and_empty_segments():
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
        "<SKILL>\nfallback\n</SKILL>\n\n<FILE path=\"notes.txt\">\nnote\n</FILE>"
    )


def test_convert_history_filters_non_chat_roles():
    history = _convert_history([
        SimpleNamespace(role="user", content="question"),
        SimpleNamespace(role="tool", content="ignored"),
        SimpleNamespace(role="assistant", content="answer"),
    ])
    assert [(item.role, item.content) for item in history] == [("user", "question"), ("assistant", "answer")]
    assert _convert_history(None) == []


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
    assert "<SKILL>\n# Demo\n</SKILL>" in result["content"]
    assert '<FILE path="scripts/run.py">' in result["content"]


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


@pytest.mark.parametrize(
    ("model_id", "configured", "model_list", "expected"),
    [
        (7, None, [], ("chosen", "chosen", {"display_name": "chosen"})),
        (None, {"model_name": "fallback"}, [SimpleNamespace(cite_name="main_model", model_name="primary")], ("main_model", "primary", {"model_name": "fallback"})),
        (None, {"model_name": "fallback", "model_repo": "fallback"}, [], ("main_model", "fallback/fallback", {"model_name": "fallback", "model_repo": "fallback"})),
        (None, None, [SimpleNamespace(cite_name="secondary", model_name="backup")], ("secondary", "backup", {})),
    ],
)
def test_resolve_model_for_nl2skill_selects_requested_configured_or_fallback(
    mocker, model_id, configured, model_list, expected
):
    mocker.patch.object(nl2skill_service, "get_model_by_model_id", return_value={"display_name": "chosen"})
    mocker.patch.object(nl2skill_service.tenant_config_manager, "get_model_config", return_value=configured)

    assert _resolve_model_for_nl2skill("tenant", model_id, model_list) == expected


def test_resolve_model_for_nl2skill_rejects_missing_requested_or_any_model(mocker):
    mocker.patch.object(nl2skill_service, "get_model_by_model_id", return_value=None)
    with pytest.raises(ValueError, match="Requested model_id"):
        _resolve_model_for_nl2skill("tenant", 9, [])

    mocker.patch.object(nl2skill_service.tenant_config_manager, "get_model_config", return_value=None)
    with pytest.raises(ValueError, match="No LLM model"):
        _resolve_model_for_nl2skill("tenant", None, [])


@pytest.mark.asyncio
async def test_build_nl2skill_run_info_uses_template_and_request_history(mocker):
    model_config = {"cite_name": "main_model", "model_name": "primary"}
    mocker.patch.object(nl2skill_service, "get_skill_creation_simple_prompt_template", return_value={
        "system_prompt": "system", "user_prompt": "rendered query"
    })
    mocker.patch.object(nl2skill_service, "create_model_config_list", new_callable=AsyncMock, return_value=[model_config])
    mocker.patch.object(nl2skill_service, "_resolve_model_for_nl2skill", return_value=("main_model", "primary", {}))
    agent_config = MagicMock()
    mocker.patch.object(nl2skill_service, "create_nl2skill_agent_config", return_value=agent_config)
    mocker.patch.object(nl2skill_service, "AgentRunInfo", side_effect=lambda **kwargs: SimpleNamespace(**kwargs))

    result = await build_nl2skill_run_info(
        NL2SkillRunRequest(query="Update <use_script path=\"scripts/run.py\" />", history=[{"role": "user", "content": "old"}]),
        tenant_id="tenant",
        language="en",
    )

    assert result.query == "rendered query"
    assert result.agent_config is agent_config
    assert [(item.role, item.content) for item in result.history] == [("user", "old")]
    assert result.enable_planning is False


@pytest.mark.asyncio
async def test_build_nl2skill_run_info_requires_at_least_one_model(mocker):
    mocker.patch.object(nl2skill_service, "get_skill_creation_simple_prompt_template", return_value={})
    mocker.patch.object(nl2skill_service, "create_model_config_list", new_callable=AsyncMock, return_value=[])

    with pytest.raises(ValueError, match="No LLM model"):
        await build_nl2skill_run_info(NL2SkillRunRequest(query="Create"), "tenant", "zh")


@pytest.mark.asyncio
async def test_stream_preserves_raw_types_and_emits_semantic_events(mocker):
    stop_event = threading.Event()
    run_info = SimpleNamespace(stop_event=stop_event)
    mocker.patch.object(
        nl2skill_service,
        "build_nl2skill_run_info",
        return_value=run_info,
    )

    async def fake_agent_run(_run_info):
        chunks = [
            {"type": "model_thinking_output", "content": "Preparing.\n<SK"},
            {
                "type": "model_output_thinking",
                "content": "ILL>\n---\nname: demo\ndescription: Demo\ntags: [demo]\n---\n# Demo\n</SKILL>\n",
            },
            {"type": "model_output_code", "content": '<FILE path="scripts/run.py">\nprint("ok")\n</FILE>\n'},
            {"type": "model_output_thinking", "content": "<SUMMARY>\nReady.\n</SUMMARY>\n"},
            {"type": "final_answer", "content": "duplicate"},
        ]
        for chunk in chunks:
            yield json.dumps(chunk)

    mocker.patch.object(nl2skill_service, "agent_run", fake_agent_run)
    stream = await create_nl2skill_stream(
        NL2SkillRunRequest(query="Create a demo skill"),
        tenant_id="tenant",
        language="en",
    )
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
    assert not any(item.get("content") == "duplicate" for item in payloads)
    assert payloads[-1]["type"] == "done"
    assert stop_event.is_set()


@pytest.mark.asyncio
async def test_stream_parses_skill_start_after_reasoning_without_newline(mocker):
    stop_event = threading.Event()
    run_info = SimpleNamespace(stop_event=stop_event)
    mocker.patch.object(
        nl2skill_service,
        "build_nl2skill_run_info",
        return_value=run_info,
    )

    async def fake_agent_run(_run_info):
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
                "content": "SKILL>\n# Demo\n</SKILL>\n",
            }
        )

    mocker.patch.object(nl2skill_service, "agent_run", fake_agent_run)
    stream = await create_nl2skill_stream(
        NL2SkillRunRequest(query="Create a demo skill"),
        tenant_id="tenant",
        language="en",
    )
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
    assert stop_event.is_set()


@pytest.mark.asyncio
async def test_stream_emits_targets_and_filters_non_target_file_updates(mocker):
    stop_event = threading.Event()
    run_info = SimpleNamespace(stop_event=stop_event)
    mocker.patch.object(nl2skill_service, "build_nl2skill_run_info", return_value=run_info)

    async def fake_agent_run(_run_info):
        yield json.dumps(
            {
                "type": "model_output_code",
                "content": (
                    "<SKILL>\n# Changed unexpectedly\n</SKILL>\n"
                    '<FILE path="scripts/other.py">\nother\n</FILE>\n'
                    '<FILE path="scripts/run.py">\nupdated\n</FILE>\n'
                    "<SUMMARY>\nDone.\n</SUMMARY>\n"
                ),
            }
        )

    mocker.patch.object(nl2skill_service, "agent_run", fake_agent_run)
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
    stream = await create_nl2skill_stream(request, tenant_id="tenant", language="en")
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
async def test_stream_skips_malformed_chunks_and_emits_error_on_agent_failure(mocker):
    stop_event = threading.Event()
    mocker.patch.object(
        nl2skill_service,
        "build_nl2skill_run_info",
        return_value=SimpleNamespace(stop_event=stop_event),
    )

    async def failing_agent_run(_run_info):
        yield "not json"
        yield ["not a mapping"]
        raise RuntimeError("provider failed")

    mocker.patch.object(nl2skill_service, "agent_run", failing_agent_run)
    stream = await create_nl2skill_stream(NL2SkillRunRequest(query="Create"), "tenant", "en")
    payloads = [json.loads(item.removeprefix("data: ").strip()) async for item in stream]

    assert payloads == [
        {"type": "error", "content": "NL2Skill execution failed.", "sequence": 1}
    ]
    assert stop_event.is_set()


@pytest.mark.asyncio
async def test_stream_classifies_final_answer_control_content_and_skips_later_tail(mocker):
    stop_event = threading.Event()
    mocker.patch.object(
        nl2skill_service,
        "build_nl2skill_run_info",
        return_value=SimpleNamespace(stop_event=stop_event),
    )

    async def fake_agent_run(_run_info):
        yield json.dumps({"type": "final_answer", "content": "<SKILL>\n# Demo"})
        yield json.dumps({"type": "final_answer", "content": "tail"})

    mocker.patch.object(nl2skill_service, "agent_run", fake_agent_run)
    stream = await create_nl2skill_stream(NL2SkillRunRequest(query="Create"), "tenant", "en")
    payloads = [json.loads(item.removeprefix("data: ").strip()) async for item in stream]

    assert any(item["type"] == "skill_body" and "# Demo" in item["content"] for item in payloads)
    assert not any(item.get("content") == "tail" for item in payloads)
    assert payloads[-1]["type"] == "done"
    assert stop_event.is_set()


@pytest.mark.asyncio
async def test_stream_preserves_final_answer_without_control_content(mocker):
    stop_event = threading.Event()
    mocker.patch.object(
        nl2skill_service,
        "build_nl2skill_run_info",
        return_value=SimpleNamespace(stop_event=stop_event),
    )

    async def fake_agent_run(_run_info):
        yield json.dumps({"type": "final_answer", "content": "Done."})

    mocker.patch.object(nl2skill_service, "agent_run", fake_agent_run)
    stream = await create_nl2skill_stream(NL2SkillRunRequest(query="Create"), "tenant", "en")
    payloads = [json.loads(item.removeprefix("data: ").strip()) async for item in stream]

    assert payloads == [
        {"type": "final_answer", "content": "Done.", "sequence": 1},
        {"type": "done", "content": "", "sequence": 2},
    ]
    assert stop_event.is_set()


@pytest.mark.asyncio
async def test_stream_propagates_cancellation_and_stops_run_info(mocker):
    stop_event = threading.Event()
    mocker.patch.object(
        nl2skill_service,
        "build_nl2skill_run_info",
        return_value=SimpleNamespace(stop_event=stop_event),
    )

    async def cancelled_agent_run(_run_info):
        raise asyncio.CancelledError()
        yield None

    mocker.patch.object(nl2skill_service, "agent_run", cancelled_agent_run)
    stream = await create_nl2skill_stream(NL2SkillRunRequest(query="Create"), "tenant", "en")

    with pytest.raises(asyncio.CancelledError):
        await anext(stream)
    assert stop_event.is_set()
