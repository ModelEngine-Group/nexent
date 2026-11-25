# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Exercise cursor replay and stopping through separately routed Runtime instances."""

from contextlib import ExitStack
import json
import re

import httpx

from shared.runtime_scaling_admission import assert_conflict, new_conversations, wait_for
from shared.runtime_scaling_attachments import require_status, sign_in


RUN_PATH = "/api/agent/run"


def sse_frames(lines):
    fields = {}
    data = []
    for line in lines:
        if not line:
            if data:
                value = "\n".join(data)
                if value != "[DONE]":
                    yield fields.get("event", "message"), fields.get("id"), json.loads(value)
            fields, data = {}, []
            continue
        name, separator, value = line.partition(":")
        if not separator or name not in {"id", "event", "data"}:
            continue
        value = value.removeprefix(" ")
        if name == "data":
            data.append(value)
        else:
            fields[name] = value
    assert not data, "The response ended part-way through an SSE event"


def check_stream(response, conversation_id, *, resumed=False):
    require_status(response, 200, "Runtime SSE response")
    assert response.headers["content-type"].startswith("text/event-stream"), "Expected SSE, not a fallback body"
    assert "conversation_id" not in response.headers or int(response.headers["conversation_id"]) == conversation_id
    if resumed:
        assert response.headers.get("X-AgentOS-Run-ID") or response.headers["X-Stream-Status"] == "resumed"
    return sse_frames(response.iter_lines())


def read_prefix(client, auth, payload, tag, *, path=RUN_PATH):
    prefix = f"stream-prefix:{tag}:界🌊"
    with client.stream("POST", path, headers=auth, json=payload) as response:
        seen = []
        for _, cursor, frame in check_stream(response, payload["conversation_id"]):
            seen.append(frame.get("type"))
            assert frame.get("type") != "error", "The producer failed before the controlled prefix"
            if frame.get("content") == prefix:
                match = re.fullmatch(r"([0-9a-f]{32}):[1-9][0-9]*", cursor or "")
                assert match, "The prefix did not bind an execution cursor"
                return cursor, match[1]
    raise AssertionError(f"The initial subscription ended without the controlled prefix: {seen}")


def conversation_history(client, auth, conversation_id):
    response = client.get(f"/api/conversation/{conversation_id}", headers=auth)
    require_status(response, 200, "Owner's persisted conversation")
    record, = response.json()["data"]
    assert int(record["conversation_id"]) == conversation_id
    return record


def check_replayed_tail(frames, tag, generation):
    assert frames[-1][0] == "agentos_terminal" and frames[-1][2]["status"] == "completed"
    assert not any(frame.get("type") == "error" or frame.get("replay_unavailable") for _, _, frame in frames)
    replay = [(cursor, frame) for _, cursor, frame in frames if cursor is not None]
    assert replay and all(cursor.startswith(generation + ":") for cursor, _ in replay)
    assert len({cursor for cursor, _ in replay}) == len(replay)
    assert not any(f"stream-prefix:{tag}" in str(frame.get("content")) for _, frame in replay)
    tail = "".join(frame["content"] for _, frame in replay if frame.get("type") == "final_answer")
    assert tail == f"stream-tail:{tag}:结束🌊"
    return replay


def assert_persisted_answer(client, auth, conversation_id, message_id, tag):
    persisted = conversation_history(client, auth, conversation_id)
    assistant, = [message for message in persisted["message"] if message["message_id"] == message_id]
    assert assistant["status"] == "completed"
    assert [unit["content"] for unit in assistant["message"] if unit["type"] == "final_answer"] == [
        f"stream-tail:{tag}:结束🌊",
    ]


def exercise_stream_control(url_a, url_b, stable_url, identities, agent, token, *, control, stream_probe, wait_seconds):
    with ExitStack() as stack:
        runtime_a, runtime_b, stable = [stack.enter_context(httpx.Client(base_url=url, timeout=wait_seconds,
                                                                         trust_env=False))
                                        for url in (url_a, url_b, stable_url)]
        owner = sign_in(stable, identities["owner"])
        foreign = sign_in(stable, identities["foreign"])
        identifier, = new_conversations(stable, owner, 1)

        def payload(tag):
            return {**agent, "conversation_id": identifier, "query": f"runtime-stream:{token}:{tag}",
                    "history": [], "stream_cursor": True}

        def resume_params(cursor):
            return {"resume": "true", "run_id": cursor.partition(":")[0], "after_event_id": cursor}

        cursor, generation = read_prefix(runtime_a, owner, payload("resume"), "resume")
        active = conversation_history(runtime_b, owner, identifier)
        assert active["streaming_message"]["status"] == "streaming"
        message_id = active["streaming_message"]["message_id"]
        resume_request = payload("resume")
        with runtime_b.stream("POST", RUN_PATH, headers=owner, params=resume_params(cursor),
                              json=resume_request) as response:
            subscription = check_stream(response, identifier, resumed=True)
            assert control("probe")["calls_by_tag"] == {"resume": 1}
            assert control("release/resume")["released"] is True
            wait_for(lambda: stream_probe("settled", identifier, generation)["terminal_committed"], wait_seconds,
                     "Producer did not commit the terminal reservation and replay checkpoint before consumption")
            replay = check_replayed_tail(list(subscription), "resume", generation)

        with stable.stream("POST", RUN_PATH, headers=owner, params=resume_params(cursor), json=resume_request) as response:
            repeated = check_replayed_tail(list(check_stream(response, identifier, resumed=True)), "resume", generation)
        assert repeated == replay, "Repeating a cursor through the stable Gateway returned different content"
        assert_persisted_answer(stable, owner, identifier, message_id, "resume")
        expiry = stream_probe("expire", identifier, generation)
        expired = runtime_b.post(RUN_PATH, headers=owner, params=resume_params(cursor), json=resume_request)
        require_status(expired, 404, "Expired journal is no longer replayable")
        assert expired.json() == {"detail": {"code": "AGENTOS_RUN_NOT_FOUND"}}
        assert_persisted_answer(runtime_b, owner, identifier, message_id, "resume")
        assert control("probe")["calls_by_tag"] == {"resume": 1}

        stopped_cursor, stopped_generation = read_prefix(runtime_a, owner, payload("stop"), "stop")
        assert stopped_generation != generation
        stopped_id = conversation_history(runtime_b, owner, identifier)["streaming_message"]["message_id"]
        history_path = f"/api/conversation/{identifier}"
        require_status(runtime_b.get(history_path), 401, "Anonymous conversation lookup")
        hidden = runtime_b.get(history_path, headers=foreign)
        require_status(hidden, 200, "Foreign conversation lookup has no visible history")
        assert hidden.json()["data"] == []
        stop_path = f"/api/agent/stop/{stopped_generation}"
        for headers, status in ((foreign, 404), ({}, 401)):
            denied = runtime_b.post(RUN_PATH, headers=headers, params=resume_params(stopped_cursor), json=payload("stop"))
            require_status(denied, status, "Unowned SSE replay")
            assert "stream-prefix:stop" not in denied.text and denied.headers.get("X-Stream-Status") is None
        require_status(runtime_b.get(stop_path), 401, "Anonymous stop")
        denied = runtime_b.get(stop_path, headers=foreign)
        require_status(denied, 404, "Unowned stop reveals no run")
        assert denied.json() == {"detail": {"code": "AGENTOS_RUN_NOT_FOUND"}}
        assert conversation_history(runtime_b, owner, identifier)["streaming_message"]["message_id"] == stopped_id
        stop = runtime_b.get(stop_path, headers=owner)
        require_status(stop, 200, "Stop the execution owned by Runtime A")
        assert stop.json()["status"] == "success" and not stop.json().get("already_stopped")

        def is_stopped():
            history = conversation_history(runtime_b, owner, identifier)
            return any(message["message_id"] == stopped_id and message["status"] == "stopped"
                       for message in history["message"])

        try:
            wait_for(is_stopped, min(wait_seconds, 30), "Runtime A did not persist the remotely requested stop")
        finally:
            control("release/stop")

        next_cursor, next_generation = read_prefix(runtime_a, owner, payload("next"), "next")
        assert next_generation not in {generation, stopped_generation}
        late = stream_probe("late", identifier, next_generation, stopped_generation)
        assert_conflict(runtime_b.post(RUN_PATH, headers=owner, json=payload("overlap")))
        stale_replay = runtime_b.post(RUN_PATH, headers=owner, params=resume_params(stopped_cursor), json=payload("stop"))
        old_frames = list(check_stream(stale_replay, identifier, resumed=True))
        assert old_frames[-1][0] == "agentos_terminal" and old_frames[-1][2]["status"] == "stopped"
        assert all(cursor is None or cursor.startswith(stopped_generation + ":") for _, cursor, _ in old_frames)
        stale_stop = runtime_b.get(stop_path, headers=owner)
        require_status(stale_stop, 200, "Ignore stop for the earlier execution")
        assert stale_stop.json()["already_stopped"] is True
        with runtime_b.stream("POST", RUN_PATH, headers=owner, params=resume_params(next_cursor),
                              json=payload("next")) as response:
            subscription = check_stream(response, identifier, resumed=True)
            assert control("release/next")["released"] is True
            next_replay = check_replayed_tail(list(subscription), "next", next_generation)
        assert not any("stream-tail:stop" in str(frame.get("content")) for _, frame in next_replay)
        model = control("probe")
        assert model["calls_by_tag"] == {"resume": 1, "stop": 1, "next": 1} and model["unexpected_calls"] == 0
        final = conversation_history(stable, owner, identifier)
        assert [message["message"] for message in final["message"] if message["role"] == "user"] == [
            payload(tag)["query"] for tag in ("resume", "stop", "next")
        ]
        return {"conversation_id": identifier, "generations": [generation, stopped_generation, next_generation],
                "replayed_events": len(replay), "next_generation_events": len(next_replay),
                "terminal_before_tail_consumption": True, "replay_expiry": expiry, "late_write_injection": late,
                "model_calls": model["calls_by_tag"]}
