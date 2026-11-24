# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""AC-OBS-STOP-001: exported stop parameters match the actual provider body."""

import json

import httpx
import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from test_model_service import Sender, complete, frame
from test_model_service import setup as setup  # noqa: PLC0414

from nexent.core.model_service.sse import SSEEvent
from nexent.core.models.openai_llm import OpenAIModel
from nexent.core.utils.observer import MessageObserver
from nexent.monitor.monitoring import MonitoringConfig, MonitoringManager
from nexent.monitor.span_processor import MonitoringSpanProcessor


@pytest.fixture
def monitoring():
    provider = TracerProvider(shutdown_on_exit=False)
    exported = InMemorySpanExporter()
    provider.add_span_processor(MonitoringSpanProcessor(SimpleSpanProcessor(exported)))
    manager = object.__new__(MonitoringManager)
    manager.__init__()
    manager._config = MonitoringConfig(enable_telemetry=True, provider="phoenix", export_metrics=False)
    manager._tracer = provider.get_tracer("stop-parameters-test")
    try:
        yield manager, exported
    finally:
        provider.shutdown()


def assert_exported_stop(exported, body):
    spans = [s for s in exported.get_finished_spans() if s.attributes.get("openinference.span.kind") == "LLM"]
    assert len(spans) == 1
    parameters = json.loads(spans[0].attributes["llm.invocation_parameters"])
    if body.get("stop") is None:
        assert "stop" not in parameters
    else:
        assert parameters["stop"] == body["stop"]
    assert not {"headers", "authorization", "api_key"}.intersection(parameters)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["invoke", "ainvoke", "stream", "astream"])
@pytest.mark.parametrize("stop", [None, ["END"], ["<RESULT>", "</code>"]])
async def test_model_service_exports_final_body_stop(setup, monitoring, mode, stop):
    profile, request, limiter, factory = setup
    manager, exported = monitoring
    data = profile.model_dump()
    if stop is not None:
        data["parameter_values"]["stop"] = stop
    profile = type(profile).model_validate(data)
    streaming = mode in {"stream", "astream"}
    request = request.model_copy(update={"stream": streaming})
    response = [frame({"content": "answer"}), frame(finish="stop"), SSEEvent("[DONE]")] if streaming else complete()
    sender = Sender([response])
    service = factory(sender, monitoring=manager)
    if mode == "astream":
        async with service.astream(request, profile) as events:
            result = [event async for event in events][-1].message
    elif mode == "stream":
        with service.stream(request, profile) as events:
            result = list(events)[-1].message
    else:
        result = await service.ainvoke(request, profile) if mode == "ainvoke" else service.invoke(request, profile)
    assert result.content_parts[0]["text"] == "answer"
    assert len(sender.calls) == 1 and not limiter._entries
    body = json.loads(sender.calls[0].body_bytes)
    assert body.get("stop") == stop
    assert_exported_stop(exported, body)


@pytest.mark.parametrize("case", [
    "normal", "absent", "unsupported", "constructor_override", "extra_body_override", "extra_body_null",
])
def test_legacy_exports_prepared_stop_without_changing_dispatch(monitoring, case):
    manager, exported = monitoring
    bodies = []

    def provider(request):
        bodies.append(json.loads(request.content))
        chunk = {"id": "fixture", "model": "fixture", "object": "chat.completion.chunk", "created": 0,
                 "choices": [{"index": 0, "delta": {"role": "assistant", "content": "answer"},
                              "finish_reason": "stop"}]}
        return httpx.Response(200, headers={"content-type": "text/event-stream"},
                              text="data: " + json.dumps(chunk) + "\n\ndata: [DONE]\n\n")

    options = {"stop": ["CONSTRUCTOR"]} if case == "constructor_override" else {}
    if case == "extra_body_override":
        options["extra_body"] = {"stop": "WIRE_OVERRIDE"}
    elif case == "extra_body_null":
        options["extra_body"] = {"stop": None}
    stop = None if case == "absent" else ["<RESULT>", "</code>"]
    with httpx.Client(transport=httpx.MockTransport(provider)) as transport:
        model = OpenAIModel(observer=MessageObserver(), model_id="o3" if case == "unsupported" else "fixture",
                            api_key="fixture-only", api_base="http://fixture.invalid/v1",
                            client_kwargs={"http_client": transport}, **options)
        model._monitoring = manager
        try:
            result = model([{"role": "user", "content": "question"}], stop_sequences=stop)
        finally:
            model.client.close()
    assert result.content == "answer" and len(bodies) == 1
    expected = {"normal": stop, "absent": None, "unsupported": None,
                "constructor_override": ["CONSTRUCTOR"], "extra_body_override": "WIRE_OVERRIDE",
                "extra_body_null": None}[case]
    assert bodies[0].get("stop") == expected
    assert_exported_stop(exported, bodies[0])
