# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Real preflight, SDK cancellation and retry; provider alone controls failure/delay."""

import asyncio
import json
import time
from concurrent.futures import ThreadPoolExecutor, CancelledError, wait

import pytest
from sqlalchemy import select, update, func

from management.db.models import ModelRecord, ConversationRecord, ConversationMessage
from model_controls.runtime import runtime_fixture

pytestmark = [pytest.mark.case_id("CHAT-MODEL-CONTROLS-D3-002"), pytest.mark.stage("D3")]
PATHS = [("/api/agent/run", False), ("/api/agent/run", True),
         ("/api/agent/nl2agent/run", False), ("/api/agent/nl2agent/run", True),
         ("/api/skills/nl2skill/run", False), ("/api/skills/nl2skill/run", True)]


@pytest.fixture
def runtime(monkeypatch):
    with runtime_fixture(monkeypatch) as fixture:
        yield fixture


def counts(runtime):
    with runtime.storage["sessions"]() as session:
        return tuple(session.scalar(select(func.count()).select_from(table)) for table in (ConversationRecord, ConversationMessage))


def test_unavailable_and_stream_failure_never_fall_back(runtime):
    before, histories = runtime.draft(), counts(runtime)
    with runtime.storage["sessions"]() as session:
        session.execute(update(ModelRecord).where(ModelRecord.model_id == runtime.models["selected-B"]).values(connect_status="unavailable", delete_flag="Y"))
    for path, workbench in PATHS:
        response = runtime.post(path, workbench=workbench, generation={"deep_thinking": True, "thinking_effort": "xhigh"}, version_no=0)
        assert response.status_code == 404 and "model_not_available" in response.text
    assert not runtime.provider.wire and not runtime.runs
    assert runtime.draft() == before and counts(runtime) == histories
    with runtime.storage["sessions"]() as session:
        session.execute(update(ModelRecord).where(ModelRecord.model_id == runtime.models["selected-B"]).values(delete_flag="N"))
    # An old failed check is historical evidence, not a live availability gate.
    stale = runtime.post("/api/agent/run", version_no=0)
    assert stale.status_code == 200, stale.text
    assert runtime.provider.wire[-1]["model"] == "fixture-selected-B"
    before = runtime.draft()
    runtime.provider.failure = True
    for path, workbench in PATHS:
        response = runtime.post(path, workbench=workbench, generation={"deep_thinking": True, "thinking_effort": "xhigh"}, version_no=0)
        assert response.status_code == 200, response.text
        events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
        assert any(e.get("type") == "error" for e in events), response.text
        root = next(m for m in runtime.runs[-1].model_config_list if m.cite_name == runtime.runs[-1].agent_config.model_name)
        assert root.model_name == "fixture-selected-B"
        assert runtime.draft() == before
    runtime.provider.failure = False
    recovered = runtime.post("/api/skills/nl2skill/run", label="default-A", generation={"deep_thinking": False})
    assert recovered.status_code == 200 and '"type": "done"' in recovered.text
    assert runtime.provider.wire[-1]["model"] == "fixture-default-A"


@pytest.mark.parametrize("path,workbench", PATHS)
def test_cancel_retry_rejects_delayed_old_provider_output(runtime, path, workbench):
    before = runtime.draft()
    runtime.provider.delay = True
    runtime.provider.release.clear()
    original_responder = runtime.provider.responder
    def respond(body):
        if body["model"] == "fixture-selected-B":
            return '<code>result = nl2a_save_agent_draft_fields(agent_id=' + str(runtime.agent_id) + ', fields={"description": "Late B must not overwrite"})\nprint(result)</code>'
        return original_responder(body)
    runtime.provider.responder = respond
    with ThreadPoolExecutor(max_workers=1) as worker:
        old = worker.submit(runtime.post, path, generation={"deep_thinking": True, "thinking_effort": "xhigh"}, workbench=workbench, version_no=0)
        deadline = time.monotonic() + 20
        while (not runtime.provider.wire or not runtime.runs) and time.monotonic() < deadline:
            time.sleep(0.02)
        assert runtime.provider.wire and runtime.runs
        old_run = runtime.runs[-1]
        # The actual runtime consumes this same cooperative cancellation scope.
        if old_run.cancellation_scope is not None:
            old_run.cancellation_scope.cancel()
        else:
            old_run.stop_event.set()
        if path == "/api/agent/run":
            with runtime.storage["sessions"]() as session:
                stop_id = session.scalar(select(ConversationRecord.conversation_id).order_by(ConversationRecord.conversation_id.desc()).limit(1))
            stopped = runtime.client.get(f"/api/agent/stop/{stop_id}", headers={"Authorization": "Bearer fixture-creator"})
            assert stopped.status_code == 200
        else:
            # Ephemeral stream disconnect cancels this real managed execution.
            old_run.thread_manager.cancel(old_run.thread_execution_id, reason="Case-owned client cancellation",
                                          wait_timeout=0, mark_stuck_on_timeout=False)
        # Wait for the terminal stream/persistence boundary, as the client does
        # before regenerating the same saved user turn. The provider stays delayed.
        deadline = time.monotonic() + 8
        while not old.done() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert old.done(), "Canceled stream did not reach its persistence boundary"
        runtime.provider.delay = False
        if path == "/api/agent/run":
            # Native Agent admission retains its slot until the physical worker
            # drains. Preserve that guard; defer consuming its old SSE until C.
            runtime.provider.release.set()
            finished, _ = wait([old_run.thread_future], timeout=10)
            assert finished
            from management.services.agent.lifecycle import agent_run_manager
            deadline = time.monotonic() + 2
            while agent_run_manager.get_agent_run_info(stop_id, runtime.storage["owner"]) and time.monotonic() < deadline:
                time.sleep(0.02)
            assert agent_run_manager.get_agent_run_info(stop_id, runtime.storage["owner"]) is None
        retry = {}
        conversation_id = None
        if workbench or path == "/api/agent/run":
            with runtime.storage["sessions"]() as session:
                conversation = session.scalars(select(ConversationRecord).order_by(ConversationRecord.conversation_id.desc()).limit(1)).one()
                conversation_id = conversation.conversation_id
                if workbench and path == "/api/agent/run":
                    retry["expected_workbench_config_version"] = conversation.workbench_config_version
                user_message = session.scalars(select(ConversationMessage).where(ConversationMessage.conversation_id == conversation_id,
                                                                               ConversationMessage.message_role == "user")).one()
                retry["conversation_id"] = conversation_id
                if "nl2" in path:
                    retry.update(retry_user_message_id=user_message.message_id, retry_message_index=user_message.message_index)
        new = runtime.post(path, label="default-A", generation={"deep_thinking": True, "thinking_effort": "minimal"}, workbench=workbench, version_no=0, **retry)
        assert new.status_code == 200, new.text
        assert any(row["model"] == "fixture-default-A" and row.get("reasoning_effort") == "minimal" for row in runtime.provider.wire), new.text
        runtime.provider.release.set()
        finished, _ = wait([old_run.thread_future], timeout=10)
        assert finished, "Old provider worker did not finish after its delayed response"
        try:
            canceled_text = old.result(timeout=25).text
        except (CancelledError, asyncio.CancelledError):
            canceled_text = ""
        assert old_run.stop_event.is_set()
        assert "Late B must not overwrite" not in canceled_text
        assert runtime.draft()["description"] != "Late B must not overwrite"
        assert runtime.draft()["model_ids"] == before["model_ids"]
        assert runtime.draft()["model_params_override"] == before["model_params_override"]
        root = next(m for m in runtime.runs[-1].model_config_list if m.cite_name == runtime.runs[-1].agent_config.model_name)
        assert root.model_name == "fixture-default-A" and root.resolved_profile.parameter_values.get("reasoning_effort") == "minimal"
        if conversation_id is not None:
            with runtime.storage["sessions"]() as session:
                user_rows = session.scalars(select(ConversationMessage).where(
                    ConversationMessage.conversation_id == conversation_id, ConversationMessage.message_role == "user")).all()
                # Native regeneration keeps immutable branch rows at one logical
                # position; creator retries reuse the existing saved user row.
                assert len(user_rows) == (2 if path == "/api/agent/run" else 1)
                assert {row.message_index for row in user_rows} == {0}


@pytest.mark.parametrize("strict", [False, True])
@pytest.mark.parametrize("recover", [False, True])
def test_empty_stop_recovery_never_restarts_as_protocol_repair(runtime, strict, recover):
    from management.db.agent.models import AgentInfo
    with runtime.storage["sessions"]() as session:
        session.execute(update(AgentInfo).where(AgentInfo.agent_id == runtime.agent_id).values(
            enable_protocol_repair_retry=strict))
    def respond(body):
        requests = [wire for wire in runtime.provider.wire if wire.get("stream")]
        return "<final_answer>Recovered</final_answer>" if recover and len(requests) >= 2 else ""
    runtime.provider.responder = respond
    before, models = runtime.draft(), runtime.model_records()
    response = runtime.post("/api/agent/run", generation={"deep_thinking": False}, version_no=0)
    assert response.status_code == 200, response.text
    requests = [wire for wire in runtime.provider.wire if wire.get("stream")]
    assert len(requests) == 2, response.text
    assert requests[0] == requests[1]
    events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
    assert any(event.get("type") == "error" for event in events) is (not recover), response.text
    if recover:
        assert "Recovered" in response.text
    assert runtime.draft() == before and runtime.model_records() == models
