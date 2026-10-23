"""Real tracing and worker contexts with isolated external dependencies."""

import asyncio
import importlib
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from pytest_mock import MockerFixture

from nexent.core.concurrency import (
    LanePolicy,
    ThreadManager,
    clear_default_thread_manager,
    get_default_thread_manager,
    set_default_thread_manager,
)
from nexent.monitor import MonitoringConfig, get_monitoring_manager


@pytest.fixture
def mocker(pytestconfig):
    fixture = MockerFixture(pytestconfig)
    yield fixture
    fixture.stopall()


@pytest.fixture
def service(mocker):
    mocker.patch("nexent.storage.storage_client_factory.create_storage_client_from_config")
    mocker.patch("nexent.storage.minio_config.MinIOStorageConfig.validate")
    mocker.patch("elasticsearch.Elasticsearch")
    return importlib.import_module("services.conversation_management_service")


@pytest.fixture
def runtime(service, monkeypatch, mocker):
    provider = TracerProvider()
    exporter = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    tracer = provider.get_tracer("title-tracing-test")
    manager = get_monitoring_manager()
    example = Path(__file__).resolve().parents[4] / "deploy/env/monitoring.env.example"
    included = next(line.split("=", 1)[1] for line in example.read_text().splitlines()
                    if line.startswith("MONITORING_FASTAPI_INCLUDED_URLS="))
    monkeypatch.setattr(manager, "_config", MonitoringConfig(
        enable_telemetry=True, fastapi_included_urls=included,
        fastapi_exclude_spans=["receive", "send"],
    ))
    monkeypatch.setattr(manager, "_tracer", tracer)
    monkeypatch.setattr(trace, "get_tracer_provider", lambda: provider)
    threads = ThreadManager("title-tests", {"model-tool-io": LanePolicy("model-tool-io", 2, 4)})
    previous = get_default_thread_manager()
    threads.start()
    set_default_thread_manager(threads)

    def prompt(**_kwargs):
        with tracer.start_as_current_span("title.prepare"):
            return {"SYSTEM_PROMPT": "Generate a title", "USER_PROMPT": "{{ question }}"}

    def model(messages):
        with tracer.start_as_current_span("model.generate"):
            return SimpleNamespace(content="Title: " + messages[-1]["content"])

    def persist(*_args):
        with tracer.start_as_current_span("title.persist"):
            return True

    prepare = mocker.patch.object(service, "get_generate_title_prompt_template", side_effect=prompt)
    mocker.patch.object(service.tenant_config_manager, "get_model_config", return_value={
        "display_name": "test-model", "model_factory": "openai",
    })
    adapter = mocker.Mock(side_effect=model)
    mocker.patch.object(service, "get_llm_adapter_from_config", return_value=adapter)
    save = mocker.patch.object(service, "rename_conversation", side_effect=persist)

    def app():
        application = FastAPI()

        async def generate(conversation_id: int = 1, question: str = "hello"):
            title = await service.generate_conversation_title_service(
                conversation_id, question, "test-user", "test-tenant",
            )
            return {"code": 0, "message": "success", "data": title}

        application.post("/conversation/generate_title")(generate)
        application.post("/nb/v1/generate_title")(generate)
        assert manager.setup_fastapi_app(application)
        return application

    yield SimpleNamespace(
        service=service, tracer=tracer, exporter=exporter, manager=manager,
        app=app, prepare=prepare, adapter=adapter, save=save, model=model,
    )
    asyncio.run(threads.shutdown(timeout=2))
    clear_default_thread_manager(threads)
    if previous is not None:
        set_default_thread_manager(previous)
    provider.shutdown()
