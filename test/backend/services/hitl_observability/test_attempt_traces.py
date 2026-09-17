"""UT-BE-TRACE-009..012: persist the HTTP parent across durable HITL attempts."""

import asyncio
from types import SimpleNamespace

import pytest
from opentelemetry import baggage, context, trace

from nexent.monitor import (
    AgentRunMetadata,
    agent_monitoring_context,
    get_agent_monitoring_context,
)
from nexent.scheduler import LeaseScheduler, SchedulerConfig
from services.human_interaction import application

LEASE = SimpleNamespace(owner_id="test-scheduler")


def agent_spans(spans):
    return [s for s in spans.exporter.get_finished_spans() if s.name == "agent.run"]


def assert_parent(span, parent):
    expected = parent.get_span_context()
    assert span.context.trace_id == expected.trace_id
    assert span.parent.span_id == expected.span_id


@pytest.mark.asyncio
async def test_ut_be_trace_009_persisted_parent_survives_request_completion(runtime, spans):
    token = context.attach(baggage.set_baggage("private", "must-not-persist"))
    try:
        with spans.tracer.start_as_current_span("POST /agent/run") as parent:
            job = await runtime.submit()
    finally:
        context.detach(token)
    saved = runtime.cipher.open(runtime.stored[job.job_id])
    carrier = saved.get("telemetry_context")
    assert carrier and set(carrier) <= {"traceparent", "tracestate"}
    assert "private" not in str(carrier)

    previous = AgentRunMetadata(tenant_id="scheduler")
    with spans.tracer.start_as_current_span("scheduler") as unrelated, agent_monitoring_context(previous):
        await application.execute_attempt(job, LEASE)
        assert trace.get_current_span() is unrelated
        assert get_agent_monitoring_context() is previous
    run, = agent_spans(spans)
    assert_parent(run, parent)
    assert run.attributes["user.id"] == "user-1@example.com"
    assert run.attributes["langfuse.trace.name"] == "测试助手"
    model = next(s for s in spans.exporter.get_finished_spans() if s.name == "model.generate")
    assert model.parent.span_id == run.context.span_id
    preparation = next(s for s in spans.exporter.get_finished_spans() if s.name == "prepare")
    assert_parent(preparation, parent)
    metadata = runtime.seen[1]
    assert (metadata.tenant_id, metadata.user_id, metadata.agent_id, metadata.conversation_id) == (
        "tenant-1", "user-1", 11, 1,
    )
    assert metadata.extra_metadata["run_id"] == job.job_id
    assert metadata.extra_metadata["attempt_id"]
    assert runtime.cleanups[0][0].span_id == parent.get_span_context().span_id
    assert runtime.ports[job.job_id].finish.call_args.args == ("completed",)


@pytest.mark.asyncio
async def test_ut_be_trace_010_scheduler_isolates_jobs_and_reconnect(runtime, spans):
    ready = asyncio.Event()
    jobs = []
    done = asyncio.Event()
    completed = []

    class Store:
        async def recover(self):
            pass

        async def claim_due(self, *_args):
            if not ready.is_set():
                return []
            claimed = list(jobs)
            jobs.clear()
            return claimed

        async def renew(self, *_args):
            return True

        async def release(self, job_id, *_args):
            completed.append(job_id)
            if len(completed) == 2:
                done.set()
            return True

    scheduler = LeaseScheduler(Store(), application.execute_attempt, SchedulerConfig(
        poll_interval_seconds=0.01, lease_seconds=10, max_concurrency=2,
    ))
    await scheduler.start()
    try:
        parents = []
        for conversation in (1, 2):
            with spans.tracer.start_as_current_span("POST /agent/run") as parent:
                parents.append(parent)
                jobs.append(await runtime.submit(conversation))
        before = dict(runtime.stored)
        with spans.tracer.start_as_current_span("reconnect"):
            response = await application.stream_run("run-1", "tenant-1", "user-1")
            assert [chunk async for chunk in response.body_iterator]
        ready.set()
        await asyncio.wait_for(done.wait(), 3)
        assert runtime.stored == before
        runs = agent_spans(spans)
        assert len(runs) == 2
        for parent in parents:
            run, = [s for s in runs if s.context.trace_id == parent.get_span_context().trace_id]
            assert_parent(run, parent)
        assert runtime.seen[1].tenant_id == "tenant-1"
        assert runtime.seen[2].tenant_id == "tenant-2"
    finally:
        await scheduler.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("carrier", ["missing", None, {}, [], "invalid", {"traceparent": "bad"}, {"traceparent": 123}])
async def test_ut_be_trace_011_legacy_carrier_does_not_inherit_scheduler(runtime, spans, carrier):
    job = await runtime.submit()
    saved = runtime.cipher.open(runtime.stored[job.job_id])
    if carrier == "missing":
        saved.pop("telemetry_context", None)
    else:
        saved["telemetry_context"] = carrier
    runtime.stored[job.job_id] = runtime.cipher.seal(saved)
    with spans.tracer.start_as_current_span("scheduler") as unrelated:
        await application.execute_attempt(job, LEASE)
        assert trace.get_current_span() is unrelated
    run, = agent_spans(spans)
    assert run.parent is None
    assert run.context.trace_id != unrelated.get_span_context().trace_id


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["prepare", "stream", "cancel", "cleanup"])
async def test_ut_be_trace_012_failures_restore_context(runtime, spans, monkeypatch, phase):
    with spans.tracer.start_as_current_span("POST /agent/run") as parent:
        job = await runtime.submit()
    if phase == "prepare":
        runtime.module.prepare_agent_run.side_effect = RuntimeError("prepare failed")
    elif phase in {"stream", "cancel"}:
        async def stream(**_kwargs):
            if phase == "cancel":
                raise asyncio.CancelledError()
            raise RuntimeError("stream failed")
            yield "unreachable"
        monkeypatch.setattr(runtime.module, "_stream_agent_chunks", stream)
    else:
        runtime.module._unregister_agent_run_after_execution.side_effect = RuntimeError("cleanup failed")

    previous = AgentRunMetadata(tenant_id="previous")
    expected_error = asyncio.CancelledError if phase == "cancel" else RuntimeError
    with spans.tracer.start_as_current_span("scheduler") as unrelated, agent_monitoring_context(previous):
        with pytest.raises(expected_error):
            await application.execute_attempt(job, LEASE)
        assert trace.get_current_span() is unrelated
        assert get_agent_monitoring_context() is previous
    if phase == "cancel":
        assert runtime.infos[1].cancellation_scope.cancelled
    if phase in {"stream", "cancel"}:
        assert runtime.cleanups[0][0].span_id == parent.get_span_context().span_id


@pytest.mark.asyncio
async def test_ut_be_trace_012_disabled_monitoring_preserves_execution(runtime, spans, monkeypatch):
    monkeypatch.setattr(spans.manager._config, "enable_telemetry", False)
    job = await runtime.submit()
    await application.execute_attempt(job, LEASE)
    assert not agent_spans(spans)
    assert runtime.ports[job.job_id].finish.call_args.args == ("completed",)
    assert get_agent_monitoring_context() is None
