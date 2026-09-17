"""BE-UT-012: verify full title lifecycle, ancestry and request isolation."""

import asyncio
import threading

import httpx
import pytest
from opentelemetry import trace
from opentelemetry.trace import StatusCode


def assert_child(child, parent):
    assert child.context.trace_id == parent.context.trace_id
    assert child.parent.span_id == parent.context.span_id
    assert parent.start_time <= child.start_time <= child.end_time <= parent.end_time


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/conversation/generate_title", "/nb/v1/generate_title"])
async def test_http_title_lifecycle(runtime, path):
    """BE-UT-012-01: entry, preparation, model and persistence share one trace."""
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=runtime.app()), base_url="http://test") as client:
        response = await client.post(path, params={"conversation_id": 42, "question": "hello"})
    assert response.json() == {"code": 0, "message": "success", "data": "Title: hello"}
    spans = {span.name: span for span in runtime.exporter.get_finished_spans()}
    http = spans[f"POST {path}"]
    operation = spans["conversation.generate_title"]
    assert_child(operation, http)
    for name in ("title.prepare", "model.generate", "title.persist"):
        assert_child(spans[name], operation)
    assert operation.attributes["openinference.span.kind"] == "CHAIN"
    assert operation.attributes["langfuse.trace.name"] == "生成会话标题"
    assert operation.attributes["session.id"] == "42"
    assert operation.attributes["input.value"] == "hello"
    assert operation.attributes["output.value"] == "Title: hello"
    runtime.save.assert_called_once_with(42, "Title: hello", "test-user")
    assert not trace.get_current_span().get_span_context().is_valid


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["prepare", "adapter", "save"])
async def test_errors_remain_in_request_trace(runtime, stage):
    """BE-UT-012-02: failures before/after the model retain operation context."""
    getattr(runtime, stage).side_effect = ValueError("controlled title failure")
    transport = httpx.ASGITransport(app=runtime.app(), raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/conversation/generate_title")
    assert response.status_code == 500
    spans = {span.name: span for span in runtime.exporter.get_finished_spans()}
    operation = spans["conversation.generate_title"]
    assert_child(operation, spans["POST /conversation/generate_title"])
    assert operation.status.status_code == StatusCode.ERROR
    assert "controlled title failure" in operation.status.description
    assert "output.value" not in operation.attributes
    if stage == "prepare":
        runtime.adapter.assert_not_called()
    if stage != "save":
        runtime.save.assert_not_called()
    assert not trace.get_current_span().get_span_context().is_valid


@pytest.mark.asyncio
async def test_concurrent_title_requests_are_isolated(runtime):
    """BE-UT-012-03: simultaneously executing workers keep their own parents."""
    barrier = threading.Barrier(2)

    def overlapping_model(messages):
        barrier.wait(timeout=5)
        return runtime.model(messages)

    runtime.adapter.side_effect = overlapping_model
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=runtime.app()), base_url="http://test") as client:
        responses = await asyncio.gather(*[
            client.post("/conversation/generate_title", params={"conversation_id": cid, "question": str(cid)})
            for cid in (1, 2)
        ])
    assert [response.json()["data"] for response in responses] == ["Title: 1", "Title: 2"]
    spans = runtime.exporter.get_finished_spans()
    operations = [span for span in spans if span.name == "conversation.generate_title"]
    assert len(operations) == 2
    assert len({span.context.trace_id for span in operations}) == 2
    for operation in operations:
        same_trace = {span.name: span for span in spans if span.context.trace_id == operation.context.trace_id}
        assert_child(operation, same_trace["POST /conversation/generate_title"])
        assert_child(same_trace["model.generate"], operation)
        assert_child(same_trace["title.persist"], operation)
        assert operation.attributes["output.value"] == "Title: " + operation.attributes["session.id"]


@pytest.mark.asyncio
async def test_disabled_monitoring_preserves_behavior(runtime):
    """BE-UT-012-04: telemetry never becomes a requirement for title generation."""
    runtime.manager._config.enable_telemetry = False
    runtime.prepare.side_effect = None
    runtime.prepare.return_value = {"SYSTEM_PROMPT": "Title", "USER_PROMPT": "{{ question }}"}
    runtime.adapter.side_effect = None
    runtime.adapter.return_value.content = "A title"
    runtime.save.side_effect = None
    title = await runtime.service.generate_conversation_title_service(1, "hello", "user", "tenant")
    assert title == "A title"
    runtime.save.assert_called_once_with(1, "A title", "user")
    assert runtime.exporter.get_finished_spans() == ()


@pytest.mark.asyncio
async def test_explicit_http_exclusion_is_preserved(runtime):
    """BE-UT-012-04: operator exclusions override deployment defaults."""
    runtime.manager._config.fastapi_excluded_urls = "/conversation/generate_title"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=runtime.app()), base_url="http://test") as client:
        response = await client.post("/conversation/generate_title")
    assert response.status_code == 200
    spans = {span.name: span for span in runtime.exporter.get_finished_spans()}
    assert not any(name.startswith("POST ") for name in spans)
    operation = spans["conversation.generate_title"]
    assert operation.parent is None
    assert_child(spans["model.generate"], operation)


@pytest.mark.asyncio
async def test_direct_service_call_has_full_lifecycle(runtime):
    """BE-UT-012-05: non-HTTP callers get the same service lifecycle."""
    assert await runtime.service.generate_conversation_title_service(1, "hello", "user", "tenant") == "Title: hello"
    spans = {span.name: span for span in runtime.exporter.get_finished_spans()}
    operation = spans["conversation.generate_title"]
    assert operation.parent is None
    for name in ("title.prepare", "model.generate", "title.persist"):
        assert_child(spans[name], operation)


@pytest.mark.asyncio
async def test_cancelled_title_does_not_persist_late_result(runtime):
    """BE-UT-012-05: cancellation closes the service span and restores context."""
    started, release, finished = threading.Event(), threading.Event(), threading.Event()

    def slow_model(messages):
        started.set()
        try:
            assert release.wait(timeout=5)
            return runtime.model(messages)
        finally:
            finished.set()

    runtime.adapter.side_effect = slow_model
    task = asyncio.create_task(runtime.service.generate_conversation_title_service(1, "hello", "user", "tenant"))
    try:
        for _ in range(200):
            if started.is_set():
                break
            await asyncio.sleep(0.01)
        assert started.is_set()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        release.set()
    for _ in range(200):
        if finished.is_set():
            break
        await asyncio.sleep(0.01)
    assert finished.is_set()
    runtime.save.assert_not_called()
    operations = [span for span in runtime.exporter.get_finished_spans() if span.name == "conversation.generate_title"]
    assert len(operations) == 1
    assert not trace.get_current_span().get_span_context().is_valid
