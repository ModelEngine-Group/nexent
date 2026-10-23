"""SDK-UT-013: sandbox warm-up duration, identity and parentage."""

import threading
import time
from types import SimpleNamespace

import pytest
from opentelemetry import trace
from opentelemetry.trace import StatusCode

from nexent.core.agents.agent_model import AgentConfig
from nexent.core.agents.nexent_agent import NexentAgent
from nexent.core.agents.sandbox import SandboxConfig, SandboxLevel, SandboxScope
from nexent.core.concurrency import ManagedTaskSpec
from nexent.core.utils.observer import MessageObserver
from nexent.monitor import AgentRunMetadata, get_agent_monitoring_context

from .conftest import assert_child, by_name


def config(name="root", display_name="主智能体", children=()):
    return AgentConfig(
        name=name, display_name=display_name, description="Warm-up test", model_name="test-model",
        tools=[], managed_agents=list(children),
    )


@pytest.fixture
def factory(mocker):
    runtime = NexentAgent(
        observer=MessageObserver(), model_config_list=[], stop_event=threading.Event(),
        sandbox_config=SandboxConfig(level=SandboxLevel.DOCKER, scope=SandboxScope.SYSTEM),
    )
    mocker.patch.object(runtime, "create_model", return_value=mocker.Mock())
    mocker.patch("nexent.core.agents.nexent_agent.CoreAgent", side_effect=lambda **kwargs: SimpleNamespace(**kwargs))
    mocker.patch("nexent.core.agents.sandbox.SandboxSkillScriptRunner")
    return runtime


def warmups(spans):
    return [s for s in spans.exporter.get_finished_spans() if s.name == "agent.sandbox.warmup"]


def test_sdk_ut_013_01_agent_tree_warmups_are_timed_children_of_run(spans, mocker, factory):
    intervals = []

    def execute(code):
        assert code == "[0, None]"
        start = time.time_ns()
        with spans.tracer.start_as_current_span("warmup-probe"):
            pass
        intervals.append((start, time.time_ns()))

    executors = [mocker.Mock(_nexent_backend="docker", side_effect=execute) for _ in range(2)]
    mocker.patch("nexent.core.agents.sandbox.build_python_executor", side_effect=executors)
    child = config("child", "子智能体")
    child._sub_agent_id = 23
    metadata = AgentRunMetadata(
        agent_id=7, agent_name="root", agent_display_name="主智能体", conversation_id=42,
        user_id="internal-user", user_email="warmup@example.test",
    )
    with spans.tracer.start_as_current_span("request"), spans.manager.start_agent_run(metadata):
        parent = trace.get_current_span()
        factory.create_single_agent(config(children=[child]))
        assert trace.get_current_span() is parent
        assert get_agent_monitoring_context() is metadata

    observations = warmups(spans)
    assert len(observations) == 2
    tree = by_name(spans)
    assert_child(tree["agent.run"], tree["request"])
    assert tree["agent.run"].attributes["langfuse.trace.name"] == "主智能体"
    assert sum(s.name == "agent.run" for s in spans.exporter.get_finished_spans()) == 1
    assert not any(s.name.startswith("agent.subagent.") for s in spans.exporter.get_finished_spans())
    for span, interval, executor, name, display, agent_id in zip(
        observations, intervals, executors, ("child", "root"), ("子智能体", "主智能体"), (23, 7), strict=True,
    ):
        assert_child(span, tree["agent.run"])
        assert span.start_time <= interval[0] <= interval[1] <= span.end_time
        assert span.attributes["openinference.span.kind"] == "CHAIN"
        assert span.attributes["agent.step.type"] == "sandbox_warmup"
        assert span.attributes["agent.name"] == name
        assert span.attributes["agent.display_name"] == display
        assert span.attributes["agent.id"] == agent_id
        assert span.attributes["user.id"] == "warmup@example.test"
        assert span.attributes["session.id"] == "42"
        assert "langfuse.trace.name" not in span.attributes
        assert "input.value" not in span.attributes
        executor.assert_called_once_with("[0, None]")
    probes = [s for s in spans.exporter.get_finished_spans() if s.name == "warmup-probe"]
    for probe, span in zip(probes, observations, strict=True):
        assert_child(probe, span)
    assert get_agent_monitoring_context() is None


@pytest.mark.parametrize("level,backend", [(SandboxLevel.DOCKER, "docker"), (SandboxLevel.WASM, "wasm"),
                                         (SandboxLevel.DOCKER, "local")])
def test_sdk_ut_013_02_backend_and_fallback(spans, mocker, factory, level, backend):
    factory.sandbox_config.level = level
    executor = mocker.Mock(_nexent_backend=backend)
    mocker.patch("nexent.core.agents.sandbox.build_python_executor", return_value=executor)
    with spans.manager.start_agent_run():
        factory.create_single_agent(config())
    span, = warmups(spans)
    assert span.attributes["sandbox.level"] == level.value
    assert span.attributes["sandbox.scope"] == "system"
    assert span.attributes["sandbox.backend"] == backend
    assert span.status.status_code == StatusCode.OK
    executor.assert_called_once_with("[0, None]")


def test_sdk_ut_013_03_failure_is_recorded_without_changing_continue_behavior(spans, mocker, factory, caplog):
    executor = mocker.Mock(_nexent_backend="docker", side_effect=RuntimeError("warm-up unavailable"))
    mocker.patch("nexent.core.agents.sandbox.build_python_executor", return_value=executor)
    with spans.manager.start_agent_run():
        parent = trace.get_current_span()
        result = factory.create_single_agent(config())
        assert trace.get_current_span() is parent
        with spans.tracer.start_as_current_span("after-failure"):
            pass
    assert result.name == "root"
    assert "Sandbox warm-up failed" in caplog.text
    span, = warmups(spans)
    assert span.status.status_code == StatusCode.ERROR
    assert span.attributes["error.type"] == "RuntimeError"
    assert span.attributes["sandbox.backend"] == "docker"
    assert any(event.name == "exception" for event in span.events)
    tree = by_name(spans)
    assert tree["agent.run"].status.status_code == StatusCode.OK
    assert_child(tree["after-failure"], tree["agent.run"])
    executor.assert_called_once_with("[0, None]")


@pytest.mark.parametrize("mode", ["local", "absent", "disabled"])
def test_sdk_ut_013_04_no_spurious_warmups(spans, mocker, factory, mode):
    if mode == "absent":
        factory.sandbox_config = None
    elif mode == "local":
        factory.sandbox_config.level = SandboxLevel.LOCAL
    else:
        spans.manager._config.enable_telemetry = False
    executor = mocker.Mock(_nexent_backend="docker")
    build = mocker.patch("nexent.core.agents.sandbox.build_python_executor", return_value=executor)
    factory.create_single_agent(config())
    assert not warmups(spans)
    if mode == "disabled":
        executor.assert_called_once_with("[0, None]")
    else:
        executor.assert_not_called()
    assert build.call_count == (0 if mode == "absent" else 1)


def test_sdk_ut_013_05_concurrent_runs_keep_warmup_contexts_isolated(spans, threads, mocker, factory):
    barrier = threading.Barrier(2)

    def execute(_code):
        barrier.wait(timeout=3)
        with spans.tracer.start_as_current_span("concurrent-probe"):
            pass

    mocker.patch(
        "nexent.core.agents.sandbox.build_python_executor",
        side_effect=lambda **kwargs: mocker.Mock(_nexent_backend="docker", side_effect=execute),
    )

    def build(index):
        metadata = AgentRunMetadata(agent_name=f"agent-{index}", conversation_id=index, user_email=f"u{index}@test.dev")
        with spans.tracer.start_as_current_span(f"request-{index}"), spans.manager.start_agent_run(metadata):
            factory.create_single_agent(config(f"agent-{index}"))

    executions = [threads.submit("agent-run", ManagedTaskSpec("warmup-test", "test"), build, i) for i in (1, 2)]
    for execution in executions:
        execution.future.result(timeout=5)
    observations = warmups(spans)
    assert len(observations) == 2
    exported = {s.context.span_id: s for s in spans.exporter.get_finished_spans()}
    for span in observations:
        run = exported[span.parent.span_id]
        assert run.name == "agent.run"
        assert_child(span, run)
        assert span.attributes["agent.name"] == run.attributes["agent.name"]
        assert span.attributes["session.id"] == run.attributes["session.id"]
        assert span.attributes["user.id"] == run.attributes["user.id"]
    assert len({s.context.trace_id for s in observations}) == 2
    for probe in (s for s in exported.values() if s.name == "concurrent-probe"):
        assert exported[probe.parent.span_id] in observations
    assert get_agent_monitoring_context() is None
