"""D3 real Agent SSE, tool, planning, nesting, metadata and attachment scenarios."""

from __future__ import annotations
from shared.resource_ids import absent_numeric_id

import asyncio
import json
import os
from pathlib import Path
import re
import time
import pytest

from d3.assets import asset_path, temporary_conversation, get_test_asset
from shared.cases import case_params
from shared.http import MODEL_TIMEOUT, assert_status, client
from shared.sse import assert_terminal_event, read_sse
from shared.runtime_fault import owned_failure_model, fault_control
from shared.auth import sign_in


RUNTIME_CASES = ['AGT-013', 'AGT-014', 'AGT-015', 'AGT-016', 'AGT-017', 'AGT-018', 'AGT-019', 'AGT-020', 'AGT-021', 'AGT-022', 'AGT-023', 'AGT-024', 'AGT-025', 'AGT-026', 'AGT-027', 'AGT-029', 'AGT-030', 'AGT-031', 'AGT-032', 'AGT-033', 'AGT-034', 'AGT-035', 'AGT-036', 'AGT-037', 'AGT-038', 'AGT-039']


def _agent_asset(key: str) -> int:
    value = get_test_asset("agents", key)
    return int(value)


def _event_text(events: list[dict]) -> str:
    return json.dumps(events, ensure_ascii=False).lower()


async def _run(identity, agent_id: int, query: str, *, conversation_id: int | None = None,
               resume: bool = False, expected: int | tuple[int, ...] = 200,
               **overrides) -> list[dict]:
    payload = {
        "query": query,
        "agent_id": agent_id,
        "conversation_id": conversation_id,
        "history": [],
        "is_debug": True,
        **overrides,
    }
    async with client("runtime", token=identity.access_token, timeout=MODEL_TIMEOUT) as api:
        async with api.stream("POST", "/agent/run", params={"resume": resume}, json=payload) as response:
            assert_status(response, expected)
            if expected != 200:
                return []
            events = await read_sse(response, limit=2000)
    return events


async def _disconnect_persisted_run(identity, agent_id: int, conversation_id: int) -> int:
    """Start a persisted run and close the client after observable SSE data.

    Resume is a reconnection contract for an in-flight persisted conversation;
    a completed debug run has neither persisted message units nor a live stream
    to resume.
    """
    payload = {
        "query": "Return the exact marker RESUME-42 after completing the request.",
        "agent_id": agent_id,
        "conversation_id": conversation_id,
        "history": [],
        "is_debug": False,
    }
    observed = 0
    async with client("runtime", token=identity.access_token, timeout=MODEL_TIMEOUT) as api:
        async with api.stream("POST", "/agent/run", params={"resume": False}, json=payload) as response:
            assert_status(response, 200)
            async for raw in response.aiter_lines():
                line = raw.rstrip("\r")
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                observed += 1
                if observed >= 2:
                    break
    assert observed, "initial persisted run produced no SSE data before disconnect"
    return observed


async def _basic_stream(identity, mode: str) -> None:
    if mode == "core":
        events = await _run(identity, _agent_asset("basic_id"), "Reply with the exact marker D3_BASIC_OK.")
        assert_terminal_event(events)
        assert "d3_basic_ok" in _event_text(events)
    elif mode == "boundary":
        events = await _run(identity, absent_numeric_id(__name__), "test")
        text = _event_text(events)
        assert "error" in text or "failed" in text or "not_found" in text or "not found" in text
    else:
        owner = await sign_in('tenant_a_admin')
        assert owner.tenant_id == identity.tenant_id, 'Fault model owner and runtime user must share the declared tenant'
        async with owned_failure_model(owner, 'AGT-015') as (model_id, nonce):
            events = await _run(
                identity, _agent_asset("basic_id"), "Provider failure probe",
                model_id=model_id,
            )
            receipt = await fault_control(nonce)
            assert receipt['calls'] >= 1, 'Runtime did not reach the selected failure provider'
            payloads = [event.get('data') for event in events if isinstance(event.get('data'), dict)]
            assert payloads and payloads[-1].get('type') == 'error', 'Provider failure has no explicit root error terminal'
            assert_terminal_event(events, allow_error=True)


async def _resume(identity, valid: bool) -> None:
    async with temporary_conversation(identity, "D3 resume") as conversation_id:
        if valid:
            agent_id = _agent_asset("basic_id")
            await _disconnect_persisted_run(identity, agent_id, conversation_id)
            payload = {
                "query": "",
                "agent_id": agent_id,
                "conversation_id": conversation_id,
                "history": [],
                "is_debug": False,
            }
            async with client("runtime", token=identity.access_token, timeout=MODEL_TIMEOUT) as api:
                async with api.stream(
                    "POST", "/agent/run", params={"resume": True}, json=payload,
                ) as response:
                    assert_status(response, 200)
                    content_type = response.headers.get("content-type", "").lower()
                    if "text/event-stream" in content_type:
                        resumed = await read_sse(response, limit=2000)
                        assert_terminal_event(resumed)
                        text = _event_text(resumed)
                        assert "resumed" in text
                        assert "resume-42" in text
                    else:
                        body = json.loads((await response.aread()).decode("utf-8"))
                        assert str(body.get("status", "")).lower() in {"completed", "stopped"}, body
                        # A very fast provider may finish between disconnect and
                        # reconnect.  In that race, verify the persisted result.
                        history = await api.get(f"/conversation/{conversation_id}")
                        assert_status(history, 200)
                        assert "resume-42" in json.dumps(history.json(), ensure_ascii=False).lower()
        else:
            await _run(
                identity,
                _agent_asset("basic_id"),
                "invalid resume",
                conversation_id=absent_numeric_id(__name__),
                resume=True,
                expected=(403, 404),
                is_debug=False,
            )


async def _stop_stream_then_stop(
    identity, *, payload: dict, stop_target: str | None,
    before_stop=None,
) -> tuple[list[dict], dict, dict]:
    """Consume a live /agent/run stream, stop the run mid-flight, drain.

    Returns the observed events, the first stop response body, and the run
    response headers. The stream must terminate after stop; a hung run raises
    a contract failure.
    """
    events: list[dict] = []
    first_stop: dict | None = None
    async with client("runtime", token=identity.access_token, timeout=MODEL_TIMEOUT) as api:
        async with api.stream("POST", "/agent/run", params={"resume": False}, json=payload) as response:
            assert_status(response, 200)
            headers = dict(response.headers)
            if stop_target is None:
                run_header = headers.get("run_id")
                assert run_header and str(run_header).startswith("debug-"), (
                    f"debug runs must expose a transient run_id header, got {run_header!r}"
                )
                assert "conversation_id" not in headers, (
                    "debug runs must not bind a conversation"
                )
                stop_target = str(run_header)
            try:
                async with asyncio.timeout(240):
                    async for raw in response.aiter_lines():
                        line = raw.rstrip("\r")
                        if not line.startswith("data:"):
                            continue
                        data = line[5:].strip()
                        if data == "[DONE]":
                            break
                        try:
                            parsed = json.loads(data)
                        except json.JSONDecodeError:
                            parsed = {"type": "raw", "content": data}
                        events.append(parsed if isinstance(parsed, dict) else {"type": "raw", "content": parsed})
                        if first_stop is None and len(events) >= 3:
                            if before_stop is not None:
                                await before_stop(stop_target)
                            async with client("runtime", token=identity.access_token) as stopper:
                                stop_response = await stopper.get(f"/agent/stop/{stop_target}")
                            assert_status(stop_response, 200)
                            first_stop = stop_response.json()
            except BaseException as exc:
                # Closing a persisted SSE subscriber need not stop its producer.
                # On observation/transport failure, cancel only this owned target.
                try:
                    async with client("runtime", token=identity.access_token) as stopper:
                        cleanup = await stopper.get(f"/agent/stop/{stop_target}")
                    assert_status(cleanup, 200)
                except Exception as cleanup_error:
                    exc.add_note(f"Owned stop cleanup failed: {type(cleanup_error).__name__}")
                if isinstance(exc, TimeoutError):
                    raise AssertionError(
                        "agent run stream did not converge within 240s after /agent/stop"
                    ) from exc
                raise
    assert first_stop is not None, "run produced fewer than three events; cannot stop it mid-flight"
    return events, first_stop, headers


async def _stop(identity, valid: bool) -> None:
    if not valid:
        async with client("runtime", token=identity.access_token) as api:
            missing = await api.get(f"/agent/stop/{absent_numeric_id(__name__)}")
        assert_status(missing, 200)
        body = missing.json()
        assert body.get("status") == "success"
        assert body.get("already_stopped") is True
        assert "no running" in str(body.get("message", "")).lower()
        return

    agent_id = _agent_asset("parallel_id")
    slow_query = "Run the two configured delayed children concurrently and aggregate both markers."

    # 1. Normal runs stop by conversation_id and release the run slot.
    async with temporary_conversation(identity, "D3 stop live") as conversation_id:
        events, first_stop, _headers = await _stop_stream_then_stop(
            identity,
            payload={
                "query": slow_query, "agent_id": agent_id, "conversation_id": conversation_id,
                "history": [], "is_debug": False,
            },
            stop_target=str(conversation_id),
        )
        assert events, "stopped run emitted no SSE events"
        assert first_stop.get("status") == "success"
        assert "successfully stopped" in str(first_stop.get("message", "")), (
            f"stop of an active run must report success, got {first_stop}"
        )
        assert first_stop.get("already_stopped") is not True
        async with client("runtime", token=identity.access_token) as api:
            second = await api.get(f"/agent/stop/{conversation_id}")
        assert_status(second, 200)
        assert second.json().get("status") == "success"
        assert second.json().get("already_stopped") is True, (
            f"repeat stop must be idempotent, got {second.json()}"
        )

    # 2. Debug runs stop by the transient run_id header and persist nothing.
    async with client("runtime", token=identity.access_token) as api:
        before = await api.get("/conversation/list", params={
            "today_start_ms": 0, "week_start_ms": 0, "offset": 0, "limit": 100,
        })
    assert_status(before, 200)
    before_total = int((before.json().get("data") or {}).get("total") or 0)

    debug_payload = {
        "query": slow_query, "agent_id": agent_id, "conversation_id": None,
        "history": [], "is_debug": True,
    }
    events, first_stop, headers = await _stop_stream_then_stop(
        identity, payload=debug_payload, stop_target=None,
    )
    debug_run_id = str(headers["run_id"])
    assert events and first_stop.get("status") == "success"
    async with client("runtime", token=identity.access_token) as api:
        repeated = await api.get(f"/agent/stop/{debug_run_id}")
        after = await api.get("/conversation/list", params={
            "today_start_ms": 0, "week_start_ms": 0, "offset": 0, "limit": 100,
        })
    assert_status(repeated, 200)
    assert repeated.json().get("already_stopped") is True
    assert_status(after, 200)
    after_total = int((after.json().get("data") or {}).get("total") or 0)
    assert after_total == before_total, (
        f"debug run must not persist conversation records ({before_total} -> {after_total})"
    )


PROTOCOL_TAG_PATTERN = re.compile(r"Calling tools:|Observation:")
STEP_MARKER_PATTERN = re.compile(r"\*\*(?:Step|step|\u6b65\u9aa4)\s*(\d+)\*\*")


def _payload_chunks(events: list[dict], types: tuple[str, ...]) -> list[dict]:
    return [
        item for item in events
        if isinstance(item.get("data"), dict) and str(item["data"].get("type", "")) in types
    ]


async def _tool_loop(identity, mode: str) -> None:
    agent_id = _agent_asset("tool_id")
    queries = {
        "core": "Use the deterministic test tool to add 19 and 23, then answer only the result.",
        "boundary": "Call the deterministic test tool with malformed argument unknown_field=true.",
        "failure": "Call the deterministic test tool in forced-timeout mode and report the failure safely.",
    }
    events = await _run(identity, agent_id, queries[mode])
    text = _event_text(events)
    assert_terminal_event(events)
    if mode != "core":
        assert any(word in text for word in ("error", "failed", "timeout", "invalid"))
        return

    assert "42" in text and ("observation" in text or "tool" in text)

    # Assertion 6 (neutral action projection): ReAct protocol tags must never
    # resurface in model-facing step content or the final answer.
    model_side = _payload_chunks(events, ("model_output_thinking", "model_output_deep_thinking", "model_output_code", "final_answer"))
    assert model_side, "core run produced no model output events"
    for chunk in model_side:
        assert not PROTOCOL_TAG_PATTERN.search(json.dumps(chunk["data"], ensure_ascii=False)), (
            "ReAct protocol tag leaked into model-visible step content (neutral action projection broken)"
        )

    # Assertion 6 (observer contract): every tool event carries arguments
    # mapped onto declared input names, never raw positional argN keys.
    tool_events = _payload_chunks(events, ("tool",))
    assert tool_events, "core ReAct run recorded no tool observer event"
    for chunk in tool_events:
        data = chunk["data"]
        assert str(data.get("tool_name") or ""), "tool event must name the invoked tool"
        arguments = data.get("tool_arguments")
        assert isinstance(arguments, dict) and arguments, (
            f"tool observer event must carry mapped arguments: {data}"
        )
        for key in arguments:
            assert isinstance(key, str) and key and not re.fullmatch(r"arg\d+", key), (
                f"positional tool arguments were not projected to declared names: {arguments}"
            )

    # Assertion 6 (transparent empty-response retry): visible step numbers
    # advance by exactly one; retries inside the model adapter leave no gap
    # and no duplicate step.
    steps: list[int] = []
    for chunk in _payload_chunks(events, ("step_count",)):
        content = str((chunk["data"] or {}).get("content", ""))
        match = STEP_MARKER_PATTERN.search(content)
        if match:
            steps.append(int(match.group(1)))
    assert steps, "run produced no step_count events to audit"
    assert steps == list(range(steps[0], steps[0] + len(steps))), (
        f"visible step numbers must be contiguous: {steps}"
    )
    assert len(steps) == len(set(steps)), f"visible steps repeated (phantom retry step): {steps}"


async def _planning(identity, mode: str) -> None:
    agent_id = _agent_asset("plan_id")
    queries = {
        "core": "Create a two-step plan: calculate 6*7 and then state the result.",
        "boundary": "Create a plan with an intentionally impossible middle step, skip it safely, and finish.",
        "failure": "Start a plan whose deterministic tool times out and expose the failed step.",
    }
    events = await _run(identity, agent_id, queries[mode], enable_plan=True)
    text = _event_text(events)
    assert_terminal_event(events)
    assert "plan" in text or "step" in text
    if mode != "core":
        assert any(word in text for word in ("skip", "fail", "error", "timeout"))


async def _nested(identity, mode: str) -> None:
    agent_id = _agent_asset("nested_id")
    queries = {
        "core": "Ask both configured child agents for their markers and combine them in order.",
        "boundary": "Ask the empty-result child and the normal child, preserving their order.",
        "failure": "Ask the failing child, then return a bounded error without inventing its result.",
    }
    events = await _run(identity, agent_id, queries[mode])
    assert_terminal_event(events, allow_error=mode == "failure")
    text = _event_text(events)
    assert "agent" in text
    if mode == "failure":
        assert "error" in text or "failed" in text


async def _parallel(identity, mode: str) -> None:
    agent_id = _agent_asset("parallel_id")
    query = {
        "core": "Run the two configured delayed children concurrently and aggregate both markers.",
        "boundary": "Run one successful and one failing child concurrently and retain the successful result.",
        "failure": "Run the timeout child and cancellation child concurrently and finish with a bounded failure.",
    }[mode]
    started = time.monotonic()
    events = await _run(identity, agent_id, query)
    elapsed = time.monotonic() - started
    assert_terminal_event(events)
    text = _event_text(events)
    assert elapsed < 300
    if mode != "core":
        assert "fail" in text or "timeout" in text or "cancel" in text or "error" in text


async def _metadata(identity, mode: str) -> None:
    marker = "D3-META-314159"
    metadata = {"project": marker, "nested": {"scope": "runtime"}}
    if mode == "core":
        events = await _run(
            identity, _agent_asset("metadata_id"), "Return the runtime metadata project marker.",
            metadata=metadata,
        )
        assert marker.lower() in _event_text(events)
    elif mode == "boundary":
        await _run(
            identity, _agent_asset("metadata_id"), "Do not confuse audit fields with runtime metadata.",
            metadata=metadata, context_policy={"unknown": True}, expected=422,
        )
    else:
        oversized = {"value": "x" * 2000000}
        await _run(identity, _agent_asset("metadata_id"), "oversized metadata", metadata=oversized, expected=413)


async def _tool_params(identity, valid: bool) -> None:
    agent_id = _agent_asset("tool_id")
    if valid:
        service_name = str(get_test_asset("mcp", "service_name"))
        async with client("config", token=identity.access_token) as api:
            agent = await api.post('/agent/search_info', json={'agent_id': agent_id, 'version_no': 0})
            assert_status(agent, 200)
            agent_row = agent.json().get('data') or agent.json()
            agent_name = str(agent_row['name'])
            listed = await api.get("/tool/list")
            assert_status(listed, 200)
            tools = [tool for tool in listed.json()
                     if tool.get("usage") == service_name
                     and tool.get("origin_name") == "deterministic_add"]
            assert len(tools) == 1, "expected the exact owned deterministic tool"
            tool = tools[0]
            configured = await api.post("/tool/update", json={
                "tool_id": int(tool.get("tool_id") or tool["id"]),
                "agent_id": agent_id, "version_no": 0, "enabled": True,
                "params": {"left": 1, "right": 2},
            })
            assert_status(configured, 200)
        wire = Path(os.environ["NEXENT_TEST_MCP_WIRE_LOG"])
        offset = wire.stat().st_size if wire.exists() else 0
        params = {"agents": {agent_name: {"tools": {tool["name"]: {"left": 40, "right": 2}}}}}
        events = await _run(identity, agent_id, "Call the configured addition tool with left=1 and right=2, then return its result.", tool_params=params)
        assert_terminal_event(events)
        with wire.open("rb") as handle:
            handle.seek(offset)
            calls = [json.loads(line) for line in handle if line.strip()]
        additions = [call for call in calls if call.get("tool") == "deterministic_add"]
        assert additions, "the owned MCP tool was not invoked"
        assert all(call["arguments"] == {"left": 40, "right": 2} and call["result"] == 42
                   for call in additions), "request overrides did not reach the actual tool invocation"
        assert "42" in _event_text(events)
    else:
        params = {"agents": {"d3_tool_agent": {"tools": {"deterministic_test_tool": {"unknown_param": 1}}}}}
        events = await _run(identity, agent_id, "Reply UNKNOWN_MAPPING_IGNORED.", tool_params=params)
        assert_terminal_event(events)
        assert "unknown_mapping_ignored" in _event_text(events)


async def _upload_attachment(identity) -> tuple[dict, str]:
    source = asset_path("files", "small_text")
    async with client("runtime", token=identity.access_token) as api:
        response = await api.post(
            "/file/storage", files={"files": (source.name, source.read_bytes(), "text/plain")},
            data={"folder": "attachments"},
        )
    assert_status(response, 200)
    record = response.json()["results"][0]
    assert record.get("success") is True, f"attachment upload failed: {record}"
    object_name = record.get("object_name") or record.get("key")
    assert object_name, f"attachment upload omitted object name: {record}"
    return record, object_name


async def _attachments(identity, mode: str) -> None:
    if mode == "boundary":
        events = await _run(
            identity, _agent_asset("basic_id"), "Read missing attachment.",
            minio_files=[{"object_name": "attachments/missing.txt", "filename": "missing.txt"}],
        )
        assert "error" in _event_text(events) or "missing" in _event_text(events)
        return
    record, object_name = await _upload_attachment(identity)
    try:
        files = [record, record] if mode == "core" else [record, {**record, "object_name": "missing"}]
        events = await _run(
            identity, _agent_asset("attachment_id"),
            "Read the attachments and return their D3 marker without inventing missing content.",
            minio_files=files,
        )
        if mode == "core":
            assert_terminal_event(events)
            assert "d3" in _event_text(events)
        else:
            assert "missing" in _event_text(events) or "error" in _event_text(events), events
    finally:
        if object_name:
            async with client("config", token=identity.access_token) as api:
                cleanup = await api.delete(f"/file/storage/{object_name}")
            assert_status(cleanup, 200)


@pytest.mark.asyncio
async def execute_agent_runtime_scenario(case: dict, tenant_a_user) -> None:
    case_id = case["id"]
    handlers = {
        "AGT-013": lambda: _basic_stream(tenant_a_user, "core"),
        "AGT-014": lambda: _basic_stream(tenant_a_user, "boundary"),
        "AGT-015": lambda: _basic_stream(tenant_a_user, "failure"),
        "AGT-016": lambda: _resume(tenant_a_user, True),
        "AGT-017": lambda: _resume(tenant_a_user, False),
        "AGT-018": lambda: _stop(tenant_a_user, True),
        "AGT-019": lambda: _stop(tenant_a_user, False),
        "AGT-020": lambda: _tool_loop(tenant_a_user, "core"),
        "AGT-021": lambda: _tool_loop(tenant_a_user, "boundary"),
        "AGT-022": lambda: _tool_loop(tenant_a_user, "failure"),
        "AGT-023": lambda: _planning(tenant_a_user, "core"),
        "AGT-024": lambda: _planning(tenant_a_user, "boundary"),
        "AGT-025": lambda: _planning(tenant_a_user, "failure"),
        "AGT-026": lambda: _nested(tenant_a_user, "core"),
        "AGT-027": lambda: _nested(tenant_a_user, "boundary"),
        "AGT-029": lambda: _parallel(tenant_a_user, "core"),
        "AGT-030": lambda: _parallel(tenant_a_user, "boundary"),
        "AGT-031": lambda: _parallel(tenant_a_user, "failure"),
        "AGT-032": lambda: _metadata(tenant_a_user, "core"),
        "AGT-033": lambda: _metadata(tenant_a_user, "boundary"),
        "AGT-034": lambda: _metadata(tenant_a_user, "failure"),
        "AGT-035": lambda: _tool_params(tenant_a_user, True),
        "AGT-036": lambda: _tool_params(tenant_a_user, False),
        "AGT-037": lambda: _attachments(tenant_a_user, "core"),
        "AGT-038": lambda: _attachments(tenant_a_user, "boundary"),
        "AGT-039": lambda: _attachments(tenant_a_user, "failure"),
    }
    await handlers[case_id]()
