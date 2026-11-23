# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Rejected maintenance must preserve business success and recover outside its lane."""

import asyncio
import json
from threading import Event
from types import SimpleNamespace

import pytest
from test_jiuwen_context import make_bridge
from test_jiuwen_model_service import saved_profile as saved_profile

from nexent.core.concurrency import LanePolicy, ManagedTaskSpec, ThreadManager
from nexent.core.concurrency.cancellation import RunTerminated
from nexent.core.model_service.service import ModelServiceError


def accept(bridge, tool):
    call = SimpleNamespace(id="provider-call", name="lookup", arguments="{}")
    bridge.accepted_response(SimpleNamespace(
        usage=SimpleNamespace(origin="provider", input_tokens=100),
        content_parts=[{"type": "text", "text": "actual answer"}],
    ), SimpleNamespace(tool_calls=[call] if tool else []))
    if tool:
        bridge.completed_tool("lookup", "actual result", "local-call", provider_call_id=call.id)


@pytest.mark.asyncio
@pytest.mark.parametrize("tool", [False, True], ids=["answer", "tool"])
async def test_successful_callback_in_full_lane_is_maintained_once_after_release(tool, caplog):
    bridge, info = make_bridge()
    manager = ThreadManager("maintenance-test", {
        "model-tool-io": LanePolicy(name="model-tool-io", max_workers=1, max_queue_size=0),
    })
    manager.start()
    bridge.manager = manager
    bridge.summary_model.model.run_id = "run"
    bridge._assemble([{"role": "user", "content": info.query}], [])
    calls = []

    def business():
        calls.append("once")
        accept(bridge, tool)
        return "business success"

    execution = manager.submit("model-tool-io", ManagedTaskSpec(task_name="business", owner=__name__), business)
    try:
        assert await asyncio.wrap_future(execution.future) == "business success"
        prompt = [{"role": "user", "content": info.query}] + [
            message for item in bridge._current_items for message in item.content.get("messages", [])]
        messages = await bridge.prepare_messages(prompt, [])
        assert info.query in str(messages)
        assert ("actual result" if tool else "actual answer") in str(messages)
        assert calls == ["once"]
        assert caplog.text.count("event=jiuwen_context_maintenance_deferred") == 1
        assert bridge.usage_baseline.actual_input_tokens == 100
        assert sum(e.spec.task_name == "jiuwen-context-maintenance" for e in bridge.executions) == 1
    finally:
        bridge.close()
        assert not (await manager.shutdown(timeout=2)).stuck_execution_ids


@pytest.mark.asyncio
@pytest.mark.parametrize("ending", ["timeout", "cancel"])
async def test_running_maintenance_is_cancelled_without_committing_after_wait_ends(monkeypatch, ending):
    from nexent.core.agents.cores.jiuwen import context

    bridge, info = make_bridge()
    manager = ThreadManager("maintenance-running-test", {
        "model-tool-io": LanePolicy(name="model-tool-io", max_workers=1, max_queue_size=0),
    })
    manager.start()
    bridge.manager = manager
    bridge.summary_model.model.run_id = "run"
    bridge.context_timeout = 0.05 if ending == "timeout" else 2
    bridge._assemble([{"role": "user", "content": info.query}], [])
    started, release = Event(), Event()
    original = context.complete_context

    def maintenance(**kwargs):
        started.set()
        release.wait(2)
        return original(**kwargs)

    monkeypatch.setattr(context, "complete_context", maintenance)
    try:
        accept(bridge, False)
        execution = bridge._maintenance_execution
        assert started.wait(1)
        task = asyncio.create_task(bridge.prepare_messages([{"role": "user", "content": info.query}], []))
        if ending == "cancel":
            await asyncio.sleep(0)
            bridge.scope.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            with pytest.raises(TimeoutError):
                await task
        assert bridge.scope.cancelled
        release.set()
        await asyncio.wrap_future(execution.future)
        assert bridge.last_evidence.maintenance_phase != "post_response"
        assert bridge.usage_baseline.actual_input_tokens is None
        assert len(bridge.executions) == 1
    finally:
        release.set()
        bridge.close()
        assert not (await manager.shutdown(timeout=2)).stuck_execution_ids


@pytest.mark.asyncio
@pytest.mark.parametrize("ending", ["busy", "cancel", "over_window"])
async def test_pending_maintenance_wait_is_bounded_cancellable_and_preserves_results(ending):
    bridge, info = make_bridge()
    manager = ThreadManager("maintenance-wait-test", {
        "model-tool-io": LanePolicy(name="model-tool-io", max_workers=1, max_queue_size=0),
    })
    manager.start()
    bridge.manager = manager
    bridge.summary_model.model.run_id = "run"
    bridge.context_timeout = 0.05 if ending == "busy" else 2
    bridge._assemble([{"role": "user", "content": info.query}], [])
    release = Event()
    blocker = manager.submit("model-tool-io", ManagedTaskSpec(task_name="blocker", owner=__name__), release.wait, 2)
    try:
        accept(bridge, True)
        prompt = [{"role": "user", "content": info.query}] + [
            message for item in bridge._current_items for message in item.content.get("messages", [])]
        task = asyncio.create_task(bridge.prepare_messages(prompt, []))
        await asyncio.sleep(0)
        if ending == "cancel":
            bridge.scope.cancel()
            with pytest.raises(RunTerminated):
                await task
        elif ending == "busy":
            with pytest.raises(ModelServiceError) as caught:
                await task
            assert caught.value.error.category == "JIUWEN_CONTEXT_BUSY"
            assert "资源繁忙" in caught.value.error.safe_message
        else:
            bridge.context_manager.config.effective_input_limit_tokens = 1
            release.set()
            prepared = await task
            assert "actual result" in str(prepared)
            assert bridge.usage_baseline.pending_estimate > 1
        assert "actual result" in str(bridge._current_items)
        assert sum(e.spec.task_name == "jiuwen-context-maintenance" for e in bridge.executions) <= 1
    finally:
        release.set()
        await asyncio.wrap_future(blocker.future)
        bridge.close()
        assert not (await manager.shutdown(timeout=2)).stuck_execution_ids


@pytest.mark.asyncio
async def test_over_window_estimate_reaches_http_sender_and_keeps_provider_usage(saved_profile):
    from nexent.core.agents.cores.jiuwen.context import SummaryModel
    from nexent.core.agents.cores.jiuwen.model import JiuwenServiceModel
    from nexent.core.model_service.http_contracts import RawHttpResponse
    from nexent.core.model_service.service import ModelService
    from test.sdk.core.model_service.test_model_service import Sender, complete

    bridge, info = make_bridge()
    bridge.context_manager.config.effective_input_limit_tokens = 1000
    info.query = "ESTIMATED_INPUT " + "x" * 3000
    manager = ThreadManager("estimate-send-test", {
        "model-tool-io": LanePolicy(name="model-tool-io", max_workers=1, max_queue_size=0),
    })
    manager.start()
    bridge.manager = manager
    payload = json.loads(complete().body)
    payload["usage"] = {"prompt_tokens": 128, "completion_tokens": 3, "total_tokens": 131}
    sender = Sender([RawHttpResponse(200, {}, json.dumps(payload).encode())])
    model = JiuwenServiceModel(ModelService(lambda _profile: sender), saved_profile, bridge.scope,
        prepare_messages=bridge.prepare_messages,
        on_event=lambda event: bridge.accepted_response(event.message, model.last_native_message))
    bridge.summary_model = SummaryModel(model)
    bridge.context_manager._request_token_estimator = bridge._estimate_wire
    try:
        response = await model.invoke([{"role": "user", "content": info.query}])
        assert response.content == "answer"
        assert len(sender.calls) == 1
        assert info.query in json.dumps(json.loads(sender.calls[0].body_bytes))
        await asyncio.wrap_future(bridge._maintenance_execution.future)
        assert bridge.usage_baseline.request_estimate > 1000
        assert bridge.usage_baseline.actual_input_tokens == 128
        assert bridge.usage_baseline.source == "provider_calibrated"
        assert bridge.usage_baseline.pending_estimate is None
        assert sum(e.spec.task_name == "jiuwen-context-maintenance" for e in bridge.executions) == 1
    finally:
        bridge.close()
        assert not (await manager.shutdown(timeout=2)).stuck_execution_ids
