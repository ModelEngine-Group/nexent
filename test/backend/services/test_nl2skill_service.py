"""Tests for the ephemeral NL2Skill runtime stream."""

import json
import threading
from types import SimpleNamespace

import pytest

from consts.model import NL2SkillRunRequest
import services.nl2skill_service as nl2skill_service
from services.nl2skill_service import (
    _extract_target_files,
    _normalize_draft_snapshot,
    create_nl2skill_stream,
)


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
