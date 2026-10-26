# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Regression tests for Skill observer routing, fragments and retries."""

import json
import threading
from types import SimpleNamespace

import pytest

from nexent.core.utils.observer import MessageObserver

from contracts.agent import NL2SkillRunRequest
import services.nl2skill_service as service


SKILL = "---\nname: demo\ndescription: Demo skill\ntags: [demo]\n---\n# Demo\n"
WIRE = (
    f"<skill>\n{SKILL}</skill>\n"
    '<file path="scripts/run.py">\nprint("ok")\n</file>\n'
    "<summary>\nReady.\n</summary>\n"
)


def answer(content, phase="delta", **metadata):
    return {"type": "final_answer", "content": content, "answer_phase": phase, **metadata}


def control(phase, attempt="a1"):
    return {"type": "model_attempt_control", "content": "", "phase": phase, "attempt_id": attempt}


@pytest.fixture
def collect(mocker):
    async def run(chunks, *, failure=None):
        stop = threading.Event()
        mocker.patch.object(service, "build_nl2skill_run_info", return_value=SimpleNamespace(stop_event=stop))

        async def agent_run(_run_info, *, thread_manager):
            assert thread_manager is not None
            for chunk in chunks:
                yield json.dumps(chunk)
            if failure:
                raise failure

        mocker.patch.object(service, "agent_run", agent_run)
        stream = await service.create_nl2skill_stream(NL2SkillRunRequest(query="Create"), "tenant", "en")
        result = [json.loads(item.removeprefix("data: ")) async for item in stream]
        assert stop.is_set()
        assert [item["sequence"] for item in result] == list(range(1, len(result) + 1))
        return result

    return run


def content(events, kind):
    return "".join(event.get("content", "") for event in events if event["type"] == kind)


@pytest.mark.asyncio
@pytest.mark.parametrize("size", [1, 2, 3, 7, 64, len(WIRE)])
@pytest.mark.parametrize("newline", ["\n", "\r\n"])
async def test_delta_reassembles_fragmented_tags_and_files(collect, size, newline):
    wire = WIRE.replace("\n", newline)
    events = await collect([answer(wire[pos:pos + size]) for pos in range(0, len(wire), size)])
    assert content(events, "skill_body") == SKILL.replace("\n", newline)
    assert content(events, "file_content") == 'print("ok")' + newline
    assert content(events, "summary").strip() == "Ready."
    assert events[-1]["type"] == "done"
    assert all(event.get("path") == "scripts/run.py" for event in events if event["type"] == "file_content")


@pytest.mark.asyncio
@pytest.mark.parametrize("completion", ["", WIRE])
async def test_complete_confirms_deltas_without_duplicate_files(collect, completion):
    events = await collect([
        control("begin"), answer("<sk", attempt_id="a1"),
        answer(WIRE[3:], attempt_id="a1"), control("commit"), answer(completion, "complete"),
    ])
    assert content(events, "skill_body") == SKILL
    assert content(events, "file_content") == 'print("ok")\n'
    assert content(events, "summary").strip() == "Ready."


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["complete", None])
async def test_complete_only_and_legacy_final_answer_remain_supported(collect, phase):
    chunk = answer(WIRE, phase)
    if phase is None:
        del chunk["answer_phase"]
    events = await collect([chunk])
    assert content(events, "skill_body") == SKILL
    assert content(events, "file_content") == 'print("ok")\n'


@pytest.mark.asyncio
async def test_semantic_events_retain_attempt_and_invocation_metadata(collect):
    metadata = {"attempt_id": "a1", "step_id": "s1", "invocation_id": "i1", "agent_id": 7}
    events = await collect([control("begin"), answer(WIRE, **metadata), control("commit")])
    semantic = [item for item in events if item["type"] in {"skill_body", "file_content", "summary"}]
    assert semantic
    assert all(all(item.get(key) == value for key, value in metadata.items()) for item in semantic)
    assert all(item["origin_type"] == "final_answer" for item in semantic)


@pytest.mark.asyncio
@pytest.mark.parametrize("failed", ["<ski", "<skill>\nFAILED<fi", '<file path="bad.py">\nBAD</fi'])
async def test_rollback_discards_failed_partial_tags_before_retry(collect, failed):
    events = await collect([
        control("begin"), answer(failed, attempt_id="a1"), control("rollback"),
        control("begin", "a2"), answer(WIRE, attempt_id="a2"),
        control("commit", "a2"), answer("", "complete"),
    ])
    rollback = next(i for i, item in enumerate(events) if item.get("phase") == "rollback")
    accepted = events[rollback + 1:]
    assert content(accepted, "skill_body") == SKILL
    assert content(accepted, "file_content") == 'print("ok")\n'
    assert "FAILED" not in content(accepted, "skill_body")
    assert not any(item.get("path") == "bad.py" for item in accepted)
    assert not any(item.get("content") in {"<ski", "<fi", "</fi"} for item in events)


@pytest.mark.asyncio
async def test_commit_flushes_literal_tail_before_checkpoint_is_discarded(collect):
    events = await collect([
        control("begin"), answer("<skill>\n# Demo\n<literal", attempt_id="a1"), control("commit"),
        answer("", "complete"),
    ])
    commit = next(i for i, item in enumerate(events) if item.get("phase") == "commit")
    assert content(events[:commit], "skill_body") == "# Demo\n<literal"
    assert all(item.get("attempt_id") == "a1" for item in events[:commit] if item["type"] == "skill_body")
    assert not any(item["type"] == "skill_body" for item in events[commit:])


@pytest.mark.asyncio
async def test_failure_does_not_flush_unaccepted_buffer_or_emit_done(collect):
    events = await collect([control("begin"), answer("<ski", attempt_id="a1")], failure=RuntimeError("secret"))
    assert events[-1]["type"] == "error"
    assert not any(item["type"] in {"skill_body", "done"} for item in events)
    assert "secret" not in str(events)


@pytest.mark.asyncio
async def test_real_observer_envelope_deltas_and_retry_reach_skill_files(collect):
    observer = MessageObserver(lang="en")
    observer.begin_model_attempt("a1", 1)
    observer.add_model_new_token("<final_answer><skill>\nFAILED<fi")
    observer.rollback_model_attempt("a1", 1)
    observer.begin_model_attempt("a2", 2)
    for char in f"<final_answer>{WIRE}</final_answer>":
        observer.add_model_new_token(char)
    observer.commit_model_attempt("a2", 2)
    observer.complete_final_answer("__skill_creator__", WIRE)
    chunks = [json.loads(raw) for raw in observer.get_cached_message()]
    assert any(item.get("answer_phase") == "delta" for item in chunks)
    assert any(item.get("answer_phase") == "complete" and not item["content"] for item in chunks)
    events = await collect(chunks)
    rollback = next(i for i, item in enumerate(events) if item.get("phase") == "rollback")
    assert content(events[rollback + 1:], "skill_body") == SKILL
    assert content(events[rollback + 1:], "file_content") == 'print("ok")\n'


@pytest.mark.asyncio
@pytest.mark.parametrize("size", [1, 64, len(WIRE)])
async def test_explicit_reasoning_tag_examples_never_write_skill_files(collect, size):
    reasoning = f"Example only:\n<final_answer>\n{WIRE}</final_answer>\nUse this structure."
    events = await collect([
        control("begin"),
        *[
            {"type": "model_output_deep_thinking", "content": reasoning[pos:pos + size], "attempt_id": "a1"}
            for pos in range(0, len(reasoning), size)
        ],
        answer("<ski", attempt_id="a1"), answer(WIRE[4:], attempt_id="a1"),
        control("commit"), answer("", "complete"),
    ])
    assert content(events, "model_output_deep_thinking") == reasoning
    assert content(events, "skill_body") == SKILL
    assert content(events, "file_content") == 'print("ok")\n'
    assert content(events, "summary").strip() == "Ready."
    assert all(item["origin_type"] == "final_answer" for item in events if item["type"] in {
        "skill_body", "file_content", "summary",
    })
