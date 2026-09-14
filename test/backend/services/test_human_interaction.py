"""Real PostgreSQL and real CoreAgent/executor tests against an isolated database.

Set HITL_TEST_DATABASE_FILE to a file containing the test SQLAlchemy DSN.
The database must be named hitl_test: these tests recreate its nexent schema.
"""

import asyncio
import os
import sys
import types
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker


@pytest.fixture
def service(monkeypatch):
    dsn_file = os.environ.get("HITL_TEST_DATABASE_FILE")
    if not dsn_file:
        pytest.skip("An isolated PostgreSQL database is required")
    url = Path(dsn_file).read_text().strip()
    if make_url(url).database != "hitl_test":
        pytest.fail("Refusing to modify a database not named hitl_test")
    engine = create_engine(url, hide_parameters=True)
    session_factory = sessionmaker(bind=engine)

    @contextmanager
    def session_scope():
        with session_factory() as session:
            with session.begin():
                yield session

    client = types.ModuleType("database.client")
    client.get_db_session = session_scope
    monkeypatch.setitem(sys.modules, "database.client", client)
    from database.human_interaction_db import HumanInteractionRepository
    from services.human_interaction.crypto import PayloadCipher
    from services.human_interaction.service import HumanInteractionService

    migration = Path(__file__).resolve().parents[3] / "deploy/sql/migrations/v2.5.1_001_human_interaction.sql"
    with engine.begin() as connection:
        connection.execute(text("DROP SCHEMA IF EXISTS nexent CASCADE"))
        connection.execute(text("CREATE SCHEMA nexent"))
        connection.exec_driver_sql(migration.read_text())
        connection.exec_driver_sql(migration.read_text())
    value = HumanInteractionService(HumanInteractionRepository(session_scope), PayloadCipher(Fernet.generate_key().decode()))
    yield value
    engine.dispose()


def create_run(service):
    return service.create("tenant-a", "owner", 7, {"query": "test"})


def port_for(service, run_id, *, allowed=(), authorize=lambda: None):
    from services.human_interaction.runtime_port import RuntimeInteractionPort
    job = service.repository.claim("worker", 1, 120)[0]
    assert job["run_id"] == run_id
    port = RuntimeInteractionPort(service, job, "worker", authorize, allowed_tools=allowed)
    port.bind_catalog({"tool-version": "1"})
    return port


def decide_pending(service, run_id, decision="approve", answer=None, key="test-key-0001"):
    from services.human_interaction.models import DecisionCommand
    item = service.snapshot(run_id, "tenant-a", "owner")["requests"][0]
    return service.decide(run_id, item["request_id"], "tenant-a", "owner", DecisionCommand(
        version=item["version"], digest=item["digest"], idempotency_key=key, decision=decision, text=answer,
    ))


def build_agent(port, model, effects, *, planning=False, on_effect=None):
    from smolagents import Tool
    from smolagents.memory import SystemPromptStep
    from nexent.core.agents.core_agent import CoreAgent
    from nexent.core.context_runtime.contracts import FinalContext, UnconfiguredContextRuntime
    from nexent.core.human_interaction.runtime import HumanInteractionRuntime
    from nexent.core.utils.observer import MessageObserver

    class EffectTool(Tool):
        name = "send"
        description = "Record a counted external effect"
        inputs = {"value": {"type": "string", "description": "Value to send"}}
        output_type = "string"

        def forward(self, value: str) -> str:
            effects.append(value)
            if on_effect:
                on_effect()
            return "sent:" + value

    class Context(UnconfiguredContextRuntime):
        def prepare_run(self, *, memory, fallback_system_prompt):
            memory.system_prompt = SystemPromptStep(fallback_system_prompt)

        def prepare_step(self, *, memory, **kwargs):
            return FinalContext(messages=memory.system_prompt.to_messages() + [
                message for step in memory.steps for message in step.to_messages()
            ])

        def finalize_evidence(self, *, status):
            return None

    tools = [EffectTool()]
    if planning:
        from nexent.core.tools.plan_tools import CreatePlanTool, UpdatePlanStepTool
        tools.extend([CreatePlanTool(), UpdatePlanStepTool()])
    agent = CoreAgent(observer=MessageObserver(), model=model, tools=tools, max_steps=5,
                      context_runtime=Context(), enable_planning=planning, verbosity_level=0)
    HumanInteractionRuntime(port).attach(agent)
    if planning:
        for name, callback in [("create_plan", agent._on_plan_created), ("update_plan_step", agent._on_step_updated)]:
            tool = agent.tools[name]
            tool.observer = agent.observer
            tool.plan_repo = agent.plan_repo
            tool._get_conversation_id = lambda: 7
            tool._get_user_id = lambda: "owner"
            if name == "create_plan":
                tool._on_plan_created = callback
            else:
                tool._on_step_updated = callback
    return agent


class ScriptModel:
    model_id = "counted-test-model"
    last_finish_reason = "stop"
    last_input_token_count = 3
    last_output_token_count = 4

    def __init__(self, outputs, callback=None):
        self.outputs = iter(outputs)
        self.calls = 0
        self.callback = callback

    def __call__(self, messages, **kwargs):
        from smolagents.models import ChatMessage, MessageRole
        from smolagents.monitoring import TokenUsage
        self.calls += 1
        if self.callback:
            self.callback()
        return ChatMessage(role=MessageRole.ASSISTANT, content=next(self.outputs), token_usage=TokenUsage(3, 4))


@pytest.mark.parametrize("planning", [False, True])
def test_same_run_rebuilds_worker_without_repeating_effects_or_model(service, planning):
    from nexent.core.human_interaction.contracts import AttemptSuspended
    run_id = create_run(service)
    prefix = ''
    if planning:
        prefix = 'p = create_plan(title="work", steps=[{"id":"step-1","title":"send","description":"send once"}, {"id":"step-2","title":"ask","description":"ask"}, {"id":"step-3","title":"finish","description":"finish"}])\n'
    model = ScriptModel([f'<code>{prefix}first = send(value="first")\nanswer = ask_user(question="Where?")\n'
                         'second = send(value=answer)\nfinal_answer(second)</code>'])
    effects = []
    allowed = {"final_answer", "create_plan", "update_plan_step"}
    for decision, answer, expected in [("approve", None, []), ("answer", "second", ["first"]),
                                        ("approve", None, ["first"])]:
        port = port_for(service, run_id, allowed=allowed)
        agent = build_agent(port, model, effects, planning=planning)
        with pytest.raises(AttemptSuspended):
            list(agent.run("test", stream=True))
        assert effects == expected
        assert service.snapshot(run_id, "tenant-a", "owner")["status"] == "WAITING_HUMAN"
        assert port.checkpoint is not None
        service.repository.release(run_id, "worker")
        decide_pending(service, run_id, decision, answer)
    port = port_for(service, run_id, allowed=allowed)
    agent = build_agent(port, model, effects, planning=planning)
    results = list(agent.run("test", stream=True))
    assert str(results[-1].output) == "sent:second"
    assert effects == ["first", "second"]
    assert model.calls == 1
    if planning:
        assert agent.current_plan.plan_id == port.load_plan()["plan_id"]
    action_steps = [item for item in agent.memory.steps if hasattr(item, "step_number")]
    assert len(action_steps) == 1
    assert action_steps[0].token_usage.input_tokens == 3


def test_unsafe_suffix_is_rejected_before_any_prefix_tool(service):
    from nexent.core.human_interaction.executor import UnsupportedResumableExecution
    run_id = create_run(service)
    port = port_for(service, run_id, allowed={"send"})
    effects = []
    agent = build_agent(port, ScriptModel([]), effects)
    agent.python_executor.send_tools(agent.tools)
    with pytest.raises(UnsupportedResumableExecution):
        agent.python_executor('send(value="must-not-send")\nimport os')
    assert effects == []


def test_decision_idempotency_scope_and_concurrent_cas(service):
    from services.human_interaction.models import DecisionCommand, InteractionError
    from nexent.core.human_interaction.contracts import AttemptSuspended
    run_id = create_run(service)
    port = port_for(service, run_id)
    with pytest.raises(AttemptSuspended):
        port.dispatch("1:0", "send", {"value": "hello"})
    item = service.snapshot(run_id, "tenant-a", "owner")["requests"][0]
    command = DecisionCommand(version=1, digest=item["digest"], decision="approve", idempotency_key="same-key-0001")
    with pytest.raises(InteractionError) as denied:
        service.decide(run_id, item["request_id"], "other-tenant", "owner", command)
    assert denied.value.status_code == 404
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda _: service.decide(run_id, item["request_id"], "tenant-a", "owner", command), range(2)))
    assert results[0] == results[1]
    with pytest.raises(InteractionError):
        service.decide(run_id, item["request_id"], "tenant-a", "owner", command.model_copy(update={"decision": "reject"}))
    service.repository.release(run_id, "worker")
    port = port_for(service, run_id)
    assert port.dispatch("1:0", "send", {"value": "hello"})["status"] == "execute"
    port.receipt("1:0", "sent")
    assert port.dispatch("1:0", "send", {"value": "hello"}) == {"status": "replay", "result": "sent"}


@pytest.mark.parametrize("control", ["terminate", "pause"])
def test_control_invalidates_pending_approval(service, control):
    from services.human_interaction.models import DecisionCommand, InteractionError
    from nexent.core.human_interaction.contracts import AttemptSuspended
    run_id = create_run(service)
    port = port_for(service, run_id)
    with pytest.raises(AttemptSuspended):
        port.dispatch("1:0", "send", {"value": "hello"})
    item = service.snapshot(run_id, "tenant-a", "owner")["requests"][0]
    service.control(run_id, "tenant-a", "owner", control)
    with pytest.raises(InteractionError):
        service.decide(run_id, item["request_id"], "tenant-a", "owner", DecisionCommand(
            version=1, digest=item["digest"], decision="approve", idempotency_key="old-key-0001"))


def test_expiry_and_argument_drift_never_dispatch(service):
    from database.human_interaction_db import utcnow
    from nexent.core.human_interaction.contracts import AttemptSuspended, RecoveryRequired
    from services.human_interaction.models import InteractionError
    run_id = create_run(service)
    port = port_for(service, run_id)
    with pytest.raises(AttemptSuspended):
        port.dispatch("1:0", "send", {"value": "hello"})
    decide_pending(service, run_id)
    service.repository.release(run_id, "worker")
    port = port_for(service, run_id)
    with pytest.raises(RecoveryRequired):
        port.dispatch("1:0", "send", {"value": "changed"})
    with service.repository.transaction(run_id) as tx:
        tx.requests()[0].status = "PENDING"
        tx.requests()[0].expires_at = utcnow() - timedelta(seconds=1)
        tx.run.status = "WAITING_HUMAN"
    assert service.snapshot(run_id, "tenant-a", "owner")["status"] == "EXPIRED"


@pytest.mark.parametrize("when", ["model", "tool"])
@pytest.mark.parametrize("planning", [False, True])
def test_steering_continues_without_dispatching_old_suffix(service, when, planning):
    from nexent.core.human_interaction.contracts import AttemptSuspended
    run_id = create_run(service)
    effects = []
    pause = lambda: service.control(run_id, "tenant-a", "owner", "pause")
    steps = '[{"id":"one","title":"review"},{"id":"two","title":"act"},{"id":"three","title":"answer"}]'
    initial_plan = f'create_plan(title="original", steps={steps})\n' if planning else ''
    revised_plan = f'create_plan(title="revised", steps={steps})\n' if planning else ''
    model = ScriptModel([f'<code>{initial_plan}send(value="first")\nsend(value="obsolete")</code>',
                         f'<code>{revised_plan}final_answer("followed-new-feedback")</code>'],
                        callback=pause if when == "model" else None)
    allowed = {"send", "final_answer", "create_plan", "update_plan_step"}
    port = port_for(service, run_id, allowed=allowed)
    agent = build_agent(port, model, effects, planning=planning, on_effect=pause if when == "tool" else None)
    with pytest.raises(AttemptSuspended):
        list(agent.run("test", stream=True))
    assert effects == ([] if when == "model" else ["first"])
    service.repository.release(run_id, "worker")
    decide_pending(service, run_id, "steer", "Do not send anything else")
    model.callback = None
    port = port_for(service, run_id, allowed=allowed)
    resumed = build_agent(port, model, effects, planning=planning)
    result = list(resumed.run("test", stream=True))
    assert str(result[-1].output) == "followed-new-feedback"
    assert effects == ([] if when == "model" else ["first"])
    assert any("Do not send anything else" in getattr(step, "task", "") for step in resumed.memory.steps)
    if planning:
        assert resumed.current_plan.title == "revised"
        assert port.load_plan()["title"] == "revised"


def test_started_crash_is_reconciliation_and_stale_worker_is_fenced(service):
    from database.human_interaction_db import utcnow
    from nexent.core.human_interaction.contracts import RunTerminated
    run_id = create_run(service)
    port = port_for(service, run_id, allowed={"send"})
    port.dispatch("1:0", "send", {"value": "hello"})
    with service.repository.transaction(run_id) as tx:
        tx.run.lock_until = utcnow() - timedelta(seconds=1)
    assert service.repository.claim("next-worker", 1, 120) == []
    assert service.snapshot(run_id, "tenant-a", "owner")["status"] == "RECOVERY_REQUIRED"
    with pytest.raises(RunTerminated):
        port.receipt("1:0", "stale-result")


def test_secret_projection_and_ciphertext(service):
    from nexent.core.human_interaction.contracts import AttemptSuspended
    run_id = create_run(service)
    port = port_for(service, run_id)
    with pytest.raises(AttemptSuspended):
        port.dispatch("1:0", "send", {"authorization": "synthetic-secret", "nested": {"api_key": "synthetic-key"}})
    projected = service.snapshot(run_id, "tenant-a", "owner")
    assert "synthetic-secret" not in str(projected)
    with service.repository.transaction(run_id) as tx:
        assert "synthetic-secret" not in tx.execution("1:0").arguments
    assert "synthetic-secret" not in str(service.repository.events(run_id))


def test_initializing_reservation_blocks_duplicate_and_never_dispatches(service):
    from services.human_interaction.models import InteractionError
    run_id = service.create("tenant-a", "owner", 7, {}, ready=False)
    with pytest.raises(InteractionError):
        create_run(service)
    assert service.repository.claim("worker", 1, 120) == []
    service.initialized(run_id, "tenant-a", "owner", succeeded=True)
    assert service.repository.claim("worker", 1, 120)[0]["run_id"] == run_id


def test_catalog_and_executor_replacement_fail_closed(service):
    from nexent.core.human_interaction.contracts import RecoveryRequired
    port = port_for(service, create_run(service))
    port.bind_executor({"send": "version-one"})
    with pytest.raises(RecoveryRequired):
        port.bind_executor({"send": "version-two"})
    with pytest.raises(RecoveryRequired):
        port.bind_catalog({"tool-version": "2"})


def test_authorization_revocation_before_dispatch(service):
    from nexent.core.human_interaction.contracts import RunTerminated
    active = [True]

    def authorize():
        if not active[0]:
            raise RunTerminated("revoked")
    port = port_for(service, create_run(service), allowed={"send"}, authorize=authorize)
    active[0] = False
    with pytest.raises(RunTerminated):
        port.dispatch("1:0", "send", {"value": "must not execute"})
    with service.repository.transaction(port.run_id) as tx:
        assert tx.executions() == []


def test_rejected_action_is_never_executed(service):
    from nexent.core.human_interaction.contracts import AttemptSuspended
    run_id = create_run(service)
    port = port_for(service, run_id)
    with pytest.raises(AttemptSuspended):
        port.dispatch("1:0", "send", {"value": "hello"})
    decide_pending(service, run_id, "reject", "Use a preview instead")
    service.repository.release(run_id, "worker")
    port = port_for(service, run_id)
    result = port.dispatch("1:0", "send", {"value": "hello"})
    assert result["status"] == "replay"
    assert result["result"]["reason"] == "human_rejected"
    assert result["result"]["feedback"] == "Use a preview instead"


def test_executed_effect_stays_succeeded_after_post_validation_failure(service):
    from nexent.core.human_interaction.contracts import RecoveryRequired
    port = port_for(service, create_run(service), allowed={"send", "final_answer"})
    effects = []
    model = ScriptModel(['<code>send(value="once")</code>'])
    agent = build_agent(port, model, effects)
    agent.verification_controller.verify_after_tool_call = lambda **_: types.SimpleNamespace(
        passed=False, severity="blocking", repair_instruction="invalid result", user_visible_note="", phase="blocked",
    )
    agent.verification_controller.build_feedback_observation = lambda _: "result was blocked"
    with pytest.raises(RecoveryRequired):
        list(agent.run("test", stream=True))
    assert effects == ["once"]
    with service.repository.transaction(port.run_id) as tx:
        assert tx.execution("1:0").status == "SUCCEEDED"


def test_expression_error_after_effect_cannot_restart_the_block(service):
    from nexent.core.human_interaction.contracts import RecoveryRequired
    port = port_for(service, create_run(service), allowed={"send"})
    effects = []
    model = ScriptModel(['<code>send(value="once")\nmissing_value</code>'])
    agent = build_agent(port, model, effects)
    with pytest.raises(RecoveryRequired):
        list(agent.run("test", stream=True))
    assert effects == ["once"]
    assert model.calls == 1


def test_crash_after_final_checkpoint_does_not_restart_completed_model(service):
    from database.human_interaction_db import utcnow
    run_id = create_run(service)
    port = port_for(service, run_id, allowed={"send", "final_answer"})
    effects = []
    model = ScriptModel(['<code>send(value="once")\nfinal_answer("done")</code>'])
    original = build_agent(port, model, effects)
    assert str(list(original.run("test", stream=True))[-1].output) == "done"
    with service.repository.transaction(run_id) as tx:
        tx.run.lock_until = utcnow() - timedelta(seconds=1)
    recovered = build_agent(port_for(service, run_id, allowed={"send", "final_answer"}), model, effects)
    assert str(list(recovered.run("test", stream=True))[-1].output) == "done"
    assert effects == ["once"]
    assert model.calls == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("early_decision", [False, True])
async def test_attempt_coordinator_keeps_waiting_or_queued_decision(service, monkeypatch, early_decision):
    from consts.model import AgentRequest
    from nexent.core.agents.context_input import ContextInput
    from nexent.core.human_interaction.contracts import AttemptSuspended
    from nexent.scheduler import ClaimedJob
    from services.human_interaction import application

    request = AgentRequest(agent_id=1, conversation_id=7, query="test", enable_hitl=True)
    run_id = service.create("tenant-a", "owner", 7, {
        "request": request.model_dump(mode="json"), "language": "en", "runtime_metadata": {},
        "runtime_metadata_version": 1,
    })
    identity = service.repository.claim("worker", 1, 120)[0]
    config = types.SimpleNamespace(managed_agents=[], external_a2a_agents=[], tools=[], model_dump=lambda: {})
    info = types.SimpleNamespace(agent_config=config, context_input=ContextInput(),
                                 model_config_list=[], runtime_metadata={}, attempt_outcome=None)

    async def authorize(*_):
        return None

    async def prepare(**_):
        return info, None

    async def stream(**_):
        with pytest.raises(AttemptSuspended):
            await asyncio.to_thread(info.human_interaction.port.dispatch, "1:0", "send", {"value": "once"})
        info.attempt_outcome = "waiting_human"
        if early_decision:
            await asyncio.to_thread(decide_pending, service, run_id)
        yield 'data: {"type":"model_output","content":"review"}\n\n'

    adapter = types.ModuleType("management.services.agent.run")
    adapter.prepare_agent_run = prepare
    adapter._stream_agent_chunks = stream
    manager_module = types.ModuleType("agents.agent_run_manager")
    manager_module.agent_run_manager = types.SimpleNamespace(unregister_agent_run=lambda *_, **__: None)
    monkeypatch.setitem(sys.modules, "management.services.agent.run", adapter)
    monkeypatch.setitem(sys.modules, "agents.agent_run_manager", manager_module)
    monkeypatch.setattr(application, "get_service", lambda: service)
    monkeypatch.setattr(application, "authorize_run", authorize)
    await application.execute_attempt(ClaimedJob(job_id=run_id, payload=identity),
                                      types.SimpleNamespace(owner_id="worker"))
    snapshot = service.snapshot(run_id, "tenant-a", "owner")
    assert snapshot["status"] == ("READY" if early_decision else "WAITING_HUMAN")
    assert snapshot["attempt_active"]
    service.repository.release(run_id, "worker")
    assert not service.snapshot(run_id, "tenant-a", "owner")["attempt_active"]
    assert any("chunk_cipher" in row["payload"] for row in service.repository.events(run_id))


def test_failed_teardown_blocks_already_queued_decision(service):
    from nexent.core.human_interaction.contracts import AttemptSuspended
    run_id = create_run(service)
    port = port_for(service, run_id)
    with pytest.raises(AttemptSuspended):
        port.dispatch("1:0", "send", {"value": "once"})
    decide_pending(service, run_id)
    port.finish("recovery_required")
    service.repository.release(run_id, "worker")
    assert service.snapshot(run_id, "tenant-a", "owner")["status"] == "RECOVERY_REQUIRED"
    assert service.repository.claim("next-worker", 1, 120) == []


@pytest.mark.asyncio
async def test_waiting_stream_is_durable_and_releases_subscription(service, monkeypatch):
    from nexent.core.human_interaction.contracts import AttemptSuspended
    from services.human_interaction import application
    monkeypatch.setattr(application, "require_enabled", lambda: service)
    run_id = create_run(service)
    port = port_for(service, run_id)
    with pytest.raises(AttemptSuspended):
        port.dispatch("1:0", "send", {"value": "hello"})
    service.repository.release(run_id, "worker")
    response = await application.stream_run(run_id, "tenant-a", "owner")
    chunks = [chunk async for chunk in response.body_iterator]
    assert "human_interaction" in "".join(chunks)
    assert '"status": "WAITING_HUMAN"' in chunks[-1]
    assert response.headers["run_id"] == run_id
    assert response.headers["conversation_id"] == "7"


def test_api_rejects_other_tenant_and_untrusted_command_fields(service, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    auth = types.ModuleType("utils.auth_utils")
    auth.get_current_user_id = lambda _: ("owner", "tenant-a")
    monkeypatch.setitem(sys.modules, "utils.auth_utils", auth)
    from apps import human_interaction_app
    from nexent.core.human_interaction.contracts import AttemptSuspended
    monkeypatch.setattr(human_interaction_app, "require_enabled", lambda: service)
    monkeypatch.setattr(human_interaction_app, "get_current_user_id", lambda _: ("owner", "tenant-a"))
    app = FastAPI()
    app.include_router(human_interaction_app.router)
    client = TestClient(app)
    run_id = create_run(service)
    port = port_for(service, run_id)
    with pytest.raises(AttemptSuspended):
        port.dispatch("1:0", "send", {"value": "hello"})
    item = service.snapshot(run_id, "tenant-a", "owner")["requests"][0]
    base = f"/agent/human-interactions/{run_id}"
    command = {"version": 1, "digest": item["digest"], "decision": "approve", "idempotency_key": "api-test-0001"}
    assert client.post(f"{base}/requests/{item['request_id']}/decisions", json={**command, "tenant_id": "forged"}).status_code == 422
    monkeypatch.setattr(human_interaction_app, "get_current_user_id", lambda _: ("owner", "other-tenant"))
    assert client.get(base).status_code == 404
    assert client.post(f"{base}/pause").status_code == 404
    assert client.post(f"{base}/requests/{item['request_id']}/decisions", json=command).status_code == 404
