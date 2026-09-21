"""Real tracing and managed workers; isolate persistence and model services."""

import asyncio
import importlib
import sys
from types import ModuleType, SimpleNamespace

import pytest
from cryptography.fernet import Fernet
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from pytest_mock import MockerFixture

from consts.model import AgentRequest
from nexent.core.concurrency import (
    LanePolicy,
    ManagedTaskSpec,
    RunCancellationScope,
    ThreadManager,
)
from nexent.monitor import (
    MonitoringConfig,
    get_agent_monitoring_context,
    get_monitoring_manager,
)
from services.human_interaction import application
from services.human_interaction.crypto import PayloadCipher


@pytest.fixture
def mocker(pytestconfig):
    fixture = MockerFixture(pytestconfig)
    yield fixture
    fixture.stopall()


@pytest.fixture
def spans(monkeypatch):
    provider = TracerProvider()
    exporter = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    tracer = provider.get_tracer("hitl-test")
    manager = get_monitoring_manager()
    monkeypatch.setattr(manager, "_config", MonitoringConfig(enable_telemetry=True))
    monkeypatch.setattr(manager, "_tracer", tracer)
    yield SimpleNamespace(tracer=tracer, exporter=exporter, manager=manager)
    provider.shutdown()


@pytest.fixture
def runtime(monkeypatch, mocker, spans):
    threads = ThreadManager("hitl-traces", {"agent-run": LanePolicy("agent-run", 4, 4)})
    threads.start()
    cipher = PayloadCipher(Fernet.generate_key().decode())
    stored, ports, infos, seen, cleanups = {}, {}, {}, {}, []
    service = mocker.Mock()
    service.repository.latest.return_value = None
    service.repository.events.return_value = []

    def create(tenant, user, conversation, payload, **_kwargs):
        run_id = f"run-{conversation}"
        stored[run_id] = cipher.seal(payload)
        return run_id

    service.create.side_effect = create
    service.light_snapshot.side_effect = lambda run_id, *_args: {
        "run_id": run_id, "conversation_id": int(run_id.split("-")[1]),
        "event_seq": 0, "status": "COMPLETED",
    }
    service.cipher = cipher
    monkeypatch.setattr(application, "get_service", lambda: service)
    monkeypatch.setattr(application, "HITL_ENABLED", True)
    monkeypatch.setattr(application, "HITL_ACCEPT_NEW_RUNS", True)
    monkeypatch.setattr(application, "authorize_run", mocker.AsyncMock())
    monkeypatch.setattr(application, "resolve_monitoring_user_email",
                        lambda user, tenant: f"{user}@example.com", raising=False)

    async def blocking(_name, fn, *args, lane=None, owner=None, **kwargs):
        return fn(*args, **kwargs)

    monkeypatch.setattr(application, "run_blocking", blocking)

    def port_factory(_service, identity, *_args, **_kwargs):
        port = mocker.Mock()
        chunks = []

        def take_chunks():
            buffered = list(chunks)
            chunks.clear()
            return buffered

        def drain_and_emit():
            buffered = take_chunks()
            if buffered:
                port.emit_chunks(buffered)

        port.add_chunk.side_effect = chunks.append
        port.peek_chunks.side_effect = lambda: len(chunks)
        port.take_chunks.side_effect = take_chunks
        port.drain_and_emit.side_effect = drain_and_emit
        port.request_payload = cipher.open(stored[identity["run_id"]])
        port.checkpoint = None
        port.context_snapshot.side_effect = lambda items: items
        ports[identity["run_id"]] = port
        return port

    monkeypatch.setattr(application, "RuntimeInteractionPort", port_factory)
    run_module = ModuleType("management.services.agent.run")

    async def prepare(agent_request, **_kwargs):
        with spans.tracer.start_as_current_span("prepare"):
            await asyncio.sleep(0)
        scope = RunCancellationScope()
        info = SimpleNamespace(
            query=agent_request.query,
            conversation_id=agent_request.conversation_id,
            agent_config=SimpleNamespace(
                name="test-agent", display_name="测试助手", tools=[], managed_agents=[], external_a2a_agents=[],
                model_dump=dict,
            ),
            context_input=SimpleNamespace(items=[]), model_config_list=[], runtime_metadata={},
            attempt_outcome="completed", cancellation_scope=scope, stop_event=scope.stop_event,
        )
        infos[agent_request.conversation_id] = info
        return info, SimpleNamespace(user_config=SimpleNamespace(memory_switch=False))

    sdk_run = importlib.import_module("nexent.core.agents.run_agent")

    def worker(info):
        seen[info.conversation_id] = get_agent_monitoring_context()
        with spans.tracer.start_as_current_span("model.generate"):
            pass

    monkeypatch.setattr(sdk_run, "_agent_run_thread", worker)

    async def stream(agent_run_info, **_kwargs):
        await threads.run(
            "agent-run", ManagedTaskSpec("test-agent", "test"), sdk_run.agent_run_thread, agent_run_info,
        )
        yield 'data: {"type":"final_answer","content":"done"}\n\n'

    def cleanup(*_args, **_kwargs):
        cleanups.append((trace.get_current_span().get_span_context(), get_agent_monitoring_context()))

    run_module.prepare_agent_run = mocker.AsyncMock(side_effect=prepare)
    run_module._stream_agent_chunks = stream
    run_module._unregister_agent_run_after_execution = mocker.Mock(side_effect=cleanup)
    run_module.save_messages = mocker.Mock()
    monkeypatch.setitem(sys.modules, run_module.__name__, run_module)
    registry = ModuleType("agents.agent_run_manager")
    registry.agent_run_manager = mocker.Mock()
    monkeypatch.setitem(sys.modules, registry.__name__, registry)

    async def submit(conversation=1):
        request = AgentRequest(query="Return done", agent_id=10 + conversation,
                               conversation_id=conversation, enable_hitl=True)
        await application.start_run(request, f"tenant-{conversation}", f"user-{conversation}", "en")
        return SimpleNamespace(job_id=f"run-{conversation}", payload={
            "run_id": f"run-{conversation}", "tenant_id": f"tenant-{conversation}",
            "user_id": f"user-{conversation}", "conversation_id": conversation, "fence": 1,
        })

    yield SimpleNamespace(
        submit=submit, stored=stored, cipher=cipher, ports=ports, infos=infos, seen=seen,
        cleanups=cleanups, module=run_module, service=service,
    )
    asyncio.run(threads.shutdown(timeout=2))
