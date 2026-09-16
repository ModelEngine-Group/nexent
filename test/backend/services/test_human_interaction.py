"""Real PostgreSQL and real CoreAgent/executor tests against an isolated database.

Set HITL_TEST_DATABASE_FILE to a file containing the test SQLAlchemy DSN.
The database must be named hitl_test: these tests recreate its nexent schema.
"""

import asyncio
import json
import os
import sys
import time
import types
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path
from threading import Thread

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import create_engine, insert
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker
from sqlalchemy.schema import CreateSchema, DropSchema


def test_clarification_mode_does_not_force_tool_approval():
    from services.human_interaction.application import _allowed_tool_names

    tools = [
        types.SimpleNamespace(name="read_skill_md", source="local", class_name="ReadSkillTool"),
        types.SimpleNamespace(name="search", source="mcp", class_name="McpTool"),
    ]

    assert _allowed_tool_names(tools, approval_enabled=False) == {
        "final_answer",
        "read_skill_md",
        "search",
    }


def test_action_approval_mode_only_trusts_control_tools():
    from services.human_interaction.application import _allowed_tool_names

    tools = [
        types.SimpleNamespace(name="read_skill_md", source="local", class_name="ReadSkillTool"),
        types.SimpleNamespace(name="create_plan", source="local", class_name="CreatePlanTool"),
        types.SimpleNamespace(name="remote_plan", source="mcp", class_name="CreatePlanTool"),
    ]

    assert _allowed_tool_names(tools, approval_enabled=True) == {"final_answer", "create_plan"}


def test_interaction_answer_accepts_explicit_other_value():
    from services.human_interaction.service import validate_interaction_answer

    validate_interaction_answer({"options": ["A"], "allow_other": True}, "B")


@pytest.mark.parametrize("text", ["", "  ", "B"])
def test_interaction_answer_preserves_strict_legacy_contract(text):
    from services.human_interaction.models import InteractionError
    from services.human_interaction.service import validate_interaction_answer

    with pytest.raises(InteractionError):
        validate_interaction_answer({"options": ["A"]}, text)


def test_clarification_signature_normalizes_defaults_and_outer_whitespace():
    from services.human_interaction.service import clarification_signature

    assert clarification_signature({"question": " Where? ", "options": ["A"]}) == clarification_signature({
        "question": "Where?", "options": ["A"], "allow_other": True,
    })


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
    from database.db_models import (
        ConversationRecord,
        HumanEvent,
        HumanExecution,
        HumanRequest,
        HumanRun,
        TableBase,
    )
    from database.human_interaction_db import HumanInteractionRepository
    from services.human_interaction.crypto import PayloadCipher
    from services.human_interaction.service import HumanInteractionService

    with engine.begin() as connection:
        connection.execute(DropSchema("nexent", cascade=True, if_exists=True))
        connection.execute(CreateSchema("nexent"))
        TableBase.metadata.create_all(connection, tables=[
            model.__table__ for model in (ConversationRecord, HumanRun, HumanRequest, HumanExecution, HumanEvent)
        ])
        connection.execute(insert(ConversationRecord).values(
            conversation_id=7, created_by="owner", updated_by="owner", delete_flag="N",
        ))
    value = HumanInteractionService(HumanInteractionRepository(session_scope), PayloadCipher(Fernet.generate_key().decode()))
    yield value
    engine.dispose()



FORM = [
    {"id": "goal", "type": "text", "title": "What should be produced?"},
    {"id": "audience", "type": "single_choice", "title": "Who is it for?", "allow_other": True,
     "options": [{"id": "team", "label": "Internal team"}, {"id": "client", "label": "Clients"}]},
    {"id": "constraints", "type": "multiple_choice", "title": "Which constraints matter?", "allow_other": True,
     "options": [{"id": "short", "label": "Brief"}, {"id": "formal", "label": "Formal"}]},
]


def form_answers(value):
    return [{"question_id": "goal", "value": value},
            {"question_id": "audience", "value": "client", "other_text": "Partners too"},
            {"question_id": "constraints", "value": ["short", "formal"], "other_text": "Due tomorrow"}]


def form_result(value):
    from nexent.core.human_interaction.clarification import (
        ClarificationAnswer,
        format_clarification_answers,
    )
    return format_clarification_answers({"questions": FORM}, [
        ClarificationAnswer.model_validate(item) for item in form_answers(value)
    ])

def create_run(service):
    return service.create("tenant-a", "owner", 7, {"query": "test"})


def port_for(service, run_id, *, allowed=(), authorize=lambda: None, live_resume=False):
    from services.human_interaction.runtime_port import RuntimeInteractionPort
    job = service.repository.claim("worker", 1, 120)[0]
    assert job["run_id"] == run_id
    port = RuntimeInteractionPort(
        service, job, "worker", authorize, allowed_tools=allowed, live_resume=live_resume,
    )
    port.bind_catalog({"tool-version": "1"})
    return port


def decide_pending(service, run_id, decision="approve", answer=None, key="test-key-0001"):
    from services.human_interaction.models import DecisionCommand
    item = service.snapshot(run_id, "tenant-a", "owner")["requests"][0]
    return service.decide(run_id, item["request_id"], "tenant-a", "owner", DecisionCommand(
        version=item["version"], digest=item["digest"], idempotency_key=key, decision=decision,
        text=None if item["payload"].get("questions") else answer,
        answers=form_answers(answer) if item["payload"].get("questions") else None,
    ))


def build_agent(port, model, effects, *, planning=False, on_effect=None, native=False):
    from nexent.core.agents.core_agent import CoreAgent
    from nexent.core.context_runtime.contracts import (
        FinalContext,
        UnconfiguredContextRuntime,
    )
    from nexent.core.human_interaction.runtime import HumanInteractionRuntime
    from nexent.core.utils.observer import MessageObserver
    from smolagents import Tool
    from smolagents.memory import SystemPromptStep

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
    if native:
        from nexent.core.human_interaction.live_runtime import LiveHumanInteractionRuntime
        original_executor = agent.python_executor
        LiveHumanInteractionRuntime(port).attach(agent)
        assert agent.python_executor is original_executor
    else:
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
    model = ScriptModel([f'<code>{prefix}first = send(value="first")\nanswer = ask_user(questions={FORM!r})\n'
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
        snapshot = service.snapshot(run_id, "tenant-a", "owner")
        assert snapshot["status"] == "WAITING_HUMAN"
        if decision == "answer":
            assert len(snapshot["requests"][0]["payload"]["questions"]) == 3
        assert port.checkpoint is not None
        service.repository.release(run_id, "worker")
        decide_pending(service, run_id, decision, answer)
    port = port_for(service, run_id, allowed=allowed)
    agent = build_agent(port, model, effects, planning=planning)
    results = list(agent.run("test", stream=True))
    assert str(results[-1].output) == "sent:" + form_result("second")
    assert effects == ["first", form_result("second")]
    assert model.calls == 1
    if planning:
        assert agent.current_plan.plan_id == port.load_plan()["plan_id"]
    action_steps = [item for item in agent.memory.steps if hasattr(item, "step_number")]
    assert len(action_steps) == 1
    assert action_steps[0].token_usage.input_tokens == 3


def test_live_resume_continues_the_same_agent_loop_and_python_stack(service):
    run_id = create_run(service)
    model = ScriptModel([
        '<code>first = send(value="first")\n'
        f'answer = ask_user(questions={FORM!r})\n'
        'second = send(value=answer)\nfinal_answer(second)</code>'
    ])
    effects = []
    port = port_for(service, run_id, allowed={"final_answer"}, live_resume=True)
    agent = build_agent(port, model, effects)
    outcome = {}

    def run_agent():
        try:
            outcome["steps"] = list(agent.run("test", stream=True))
        except BaseException as exc:  # noqa: BLE001 - HITL control signals inherit BaseException.
            outcome["error"] = exc

    thread = Thread(target=run_agent, daemon=True)
    thread.start()

    seen = set()
    decisions = [("approve", None), ("answer", "other-place"), ("approve", None)]
    for index, (decision, answer) in enumerate(decisions):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            requests = service.snapshot(run_id, "tenant-a", "owner")["requests"]
            if requests and requests[0]["request_id"] not in seen:
                seen.add(requests[0]["request_id"])
                break
            time.sleep(0.02)
        else:
            pytest.fail(f"Timed out waiting for interaction {index + 1}")
        decide_pending(service, run_id, decision, answer, key=f"live-key-{index:04d}")

    thread.join(timeout=5)
    assert not thread.is_alive()
    assert "error" not in outcome
    assert str(outcome["steps"][-1].output) == "sent:" + form_result("other-place")
    assert effects == ["first", form_result("other-place")]
    assert model.calls == 1


def test_identical_clarification_reuses_the_answer_without_a_second_card(service):
    from nexent.core.human_interaction.contracts import AttemptSuspended

    run_id = create_run(service)
    interaction = {
        "kind": "CLARIFICATION", "question": "Where?", "options": ["A"], "allow_other": True,
    }
    port = port_for(service, run_id)
    with pytest.raises(AttemptSuspended):
        port.dispatch("1:0", "ask_user", {"question": "Where?"}, interaction=interaction)
    decide_pending(service, run_id, "answer", "B")
    service.repository.release(run_id, "worker")

    port = port_for(service, run_id)
    result = port.dispatch("2:0", "ask_user", {"question": "Where?"}, interaction=interaction)

    assert result == {"status": "replay", "result": "B"}
    with service.repository.transaction(run_id) as tx:
        assert len(tx.requests()) == 1
        assert tx.execution("2:0").status == "SUCCEEDED"


@pytest.mark.parametrize("when", ["model", "tool"])
def test_live_pause_discards_the_old_suffix_and_continues_the_outer_loop(service, when):
    run_id = create_run(service)

    def pause():
        return service.control(run_id, "tenant-a", "owner", "pause")

    model = ScriptModel(
        [
            '<code>send(value="first")\nsend(value="obsolete")</code>',
            '<code>final_answer("followed-new-feedback")</code>',
        ],
        callback=pause if when == "model" else None,
    )
    effects = []
    port = port_for(service, run_id, allowed={"send", "final_answer"}, live_resume=True)
    agent = build_agent(port, model, effects, on_effect=pause if when == "tool" else None)
    outcome = {}

    def run_agent():
        try:
            outcome["steps"] = list(agent.run("test", stream=True))
        except BaseException as exc:  # noqa: BLE001 - HITL control signals inherit BaseException.
            outcome["error"] = exc

    thread = Thread(target=run_agent, daemon=True)
    thread.start()
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        requests = service.snapshot(run_id, "tenant-a", "owner")["requests"]
        if requests and requests[0]["kind"] == "USER_STEERING":
            break
        time.sleep(0.02)
    else:
        pytest.fail("Timed out waiting for user steering")

    model.callback = None
    decide_pending(service, run_id, "steer", "Do not send anything else", key="live-steer-0001")
    thread.join(timeout=5)

    assert not thread.is_alive()
    assert "error" not in outcome
    assert str(outcome["steps"][-1].output) == "followed-new-feedback"
    assert effects == ([] if when == "model" else ["first"])
    assert model.calls == 2
    assert any("Do not send anything else" in getattr(step, "task", "") for step in agent.memory.steps)


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
    from nexent.core.human_interaction.contracts import AttemptSuspended
    from services.human_interaction.models import DecisionCommand, InteractionError
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
    from nexent.core.human_interaction.contracts import AttemptSuspended
    from services.human_interaction.models import DecisionCommand, InteractionError
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
    from nexent.core.human_interaction.contracts import (
        AttemptSuspended,
        RecoveryRequired,
    )
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
    def pause():
        return service.control(run_id, "tenant-a", "owner", "pause")

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
        # Exercise the durable fallback coordinator; live continuation is
        # covered separately with one retained Agent instance.
        info.human_interaction.port.live_resume = False
        with pytest.raises(AttemptSuspended):
            await asyncio.to_thread(info.human_interaction.port.dispatch, "1:0", "send", {"value": "once"})
        info.attempt_outcome = "waiting_human"
        if early_decision:
            await asyncio.to_thread(decide_pending, service, run_id)
        yield 'data: {"type":"model_output","content":"review"}\n\n'

    adapter = types.ModuleType("management.services.agent.run")
    adapter.prepare_agent_run = prepare
    adapter._stream_agent_chunks = stream
    adapter._unregister_agent_run_after_execution = lambda *_, **__: None
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


@pytest.mark.parametrize("legacy", [False, True])
def test_structured_form_resumes_the_original_code_stack_without_database(legacy):
    """Exercise the real Agent/executor against an in-memory human delivery port."""
    from copy import deepcopy
    from threading import Event

    from nexent.core.human_interaction.contracts import AttemptSuspended

    class DeliveryPort:
        checkpoint = None

        def __init__(self):
            self.pending = Event()
            self.answered = Event()
            self.interaction = None
            self.receipts = {}
            self.suspend = legacy

        def bind_executor(self, identity):
            pass

        def save_checkpoint(self, value):
            self.checkpoint = deepcopy(value)

        def boundary(self, checkpoint):
            return None

        def load_plan(self):
            return None

        def dispatch(self, slot, name, arguments, *, interaction=None):
            if slot in self.receipts:
                return {"status": "replay", "result": self.receipts[slot]}
            if interaction:
                self.interaction = interaction
                self.pending.set()
                if self.suspend:
                    raise AttemptSuspended()
                assert self.answered.wait(5), "No human answer was delivered"
                return {"status": "replay", "result": "legacy answer" if legacy else form_result("Meeting notice")}
            return {"status": "execute", "arguments": arguments}

        def receipt(self, slot, result, **kwargs):
            self.receipts[slot] = result

    port = DeliveryPort()
    # First persist a valid new checkpoint; then simulate a pre-upgrade frozen call.
    code = f'first = send(value="first")\nanswer = ask_user(questions={FORM!r})\n'
    code += 'second = send(value=answer)\nfinal_answer(second)'
    model = ScriptModel([f'<code>{code}</code>'])
    effects = []
    agent = build_agent(port, model, effects)
    if legacy:
        with pytest.raises(AttemptSuspended):
            list(agent.run("test", stream=True))
        frozen = port.checkpoint["pending_step"]
        # The codec keeps the full model response and the code action as scalar fields.
        def replace_code(value):
            if isinstance(value, str):
                return value.replace(f"ask_user(questions={FORM!r})", 'ask_user(question="Where?")')
            if isinstance(value, dict):
                return {k: replace_code(v) for k, v in value.items()}
            if isinstance(value, list):
                return [replace_code(v) for v in value]
            return value
        port.checkpoint["pending_step"] = replace_code(frozen)
        port.checkpoint.pop("clarification_schema_version")
        port.suspend = False
        port.pending.clear()
        agent = build_agent(port, model, effects)

    outcome = {}

    def run():
        try:
            outcome["steps"] = list(agent.run("test", stream=True))
        except BaseException as exc:  # noqa: BLE001 - Control signals also need to be asserted.
            outcome["error"] = exc

    thread = Thread(target=run, daemon=True)
    thread.start()
    try:
        assert port.pending.wait(5), outcome
        assert thread.is_alive()
        assert effects == ["first"]
        assert model.calls == 1
        if not legacy:
            assert len(port.interaction["questions"]) == 3
        port.answered.set()
        thread.join(5)
        assert not thread.is_alive()
        assert "error" not in outcome, outcome
        expected = "legacy answer" if legacy else form_result("Meeting notice")
        assert effects == ["first", expected]
        assert str(outcome["steps"][-1].output) == "sent:" + expected
        assert model.calls == 1
    finally:
        port.answered.set()
        thread.join(5)


def test_structured_decision_validation_and_idempotent_reuse(service):
    from nexent.core.human_interaction.contracts import AttemptSuspended
    from services.human_interaction.models import DecisionCommand, InteractionError

    run_id = create_run(service)
    interaction = {"kind": "CLARIFICATION", "schema_version": 2, "questions": FORM}
    port = port_for(service, run_id)
    with pytest.raises(AttemptSuspended):
        port.dispatch("1:0", "ask_user", {"questions": FORM}, interaction=interaction)
    request = service.snapshot(run_id, "tenant-a", "owner")["requests"][0]
    fields = {"version": request["version"], "digest": request["digest"], "decision": "answer",
              "idempotency_key": "structured-key-0001"}
    for invalid in [{"text": "Only the first answer"}, {"answers": form_answers("Notice")[:1]},
                    {"answers": [*form_answers("Notice")[:2], {"question_id": "constraints", "value": ["forged"]}]}]:
        with pytest.raises(InteractionError) as error:
            service.decide(run_id, request["request_id"], "tenant-a", "owner", DecisionCommand(**fields, **invalid))
        assert error.value.status_code == 422
        assert service.snapshot(run_id, "tenant-a", "owner")["status"] == "WAITING_HUMAN"
    command = DecisionCommand(**fields, answers=form_answers("Notice"))
    for _ in range(2):
        assert service.decide(run_id, request["request_id"], "tenant-a", "owner", command)["accepted"]
    service.repository.release(run_id, "worker")
    port = port_for(service, run_id)
    result = port.dispatch("2:0", "ask_user", {"questions": FORM}, interaction=interaction)
    assert json.loads(result["result"])["answers"][2]["answer"] == ["Brief", "Formal"]
    with service.repository.transaction(run_id) as tx:
        assert len(tx.requests()) == 1


def test_different_structured_forms_do_not_share_an_answer_signature():
    from services.human_interaction.service import clarification_signature

    different = [{**question, "title": question["title"] + " Another task?"} for question in FORM]
    assert clarification_signature({"questions": FORM}) != clarification_signature({"questions": different})


def test_structured_decision_boundary_without_database():
    """Validate decision semantics with real encrypted payloads and an in-memory transaction."""
    from database.human_interaction_db import utcnow
    from database.human_interaction_models import HumanRequest
    from services.human_interaction.crypto import PayloadCipher
    from services.human_interaction.models import (
        DecisionCommand,
        InteractionError,
        digest,
    )
    from services.human_interaction.service import HumanInteractionService

    cipher = PayloadCipher(Fernet.generate_key().decode())
    payload = {"schema_version": 2, "questions": FORM}
    item = HumanRequest(
        request_id="request", run_record_id=1, kind="CLARIFICATION", status="PENDING", version=1,
        digest=digest(payload), payload=cipher.seal(payload), create_time=utcnow().replace(tzinfo=None),
        expires_at=utcnow() + timedelta(minutes=5),
    )
    events = []
    tx = types.SimpleNamespace(run=types.SimpleNamespace(status="WAITING_HUMAN", run_id="run"),
                               requests=lambda: [item], emit=events.append)

    @contextmanager
    def transaction(*args):
        yield tx

    service = HumanInteractionService(types.SimpleNamespace(transaction=transaction), cipher)
    fields = {"version": 1, "digest": item.digest, "decision": "answer", "idempotency_key": "structured-unit-001"}
    for invalid in [{"text": "Plain answer"}, {"answers": form_answers("Notice")[:1]},
                    {"answers": form_answers("Notice"), "text": "Mixed response"}]:
        with pytest.raises(InteractionError) as error:
            service.decide("run", "request", "tenant", "owner", DecisionCommand(**fields, **invalid))
        assert error.value.status_code == 422
        assert item.status == "PENDING"
        assert tx.run.status == "WAITING_HUMAN"
        assert not events

    command = DecisionCommand(**fields, answers=form_answers("Notice"))
    service.decide("run", "request", "tenant", "owner", command)
    service.decide("run", "request", "tenant", "owner", command)
    assert item.status == "DECIDED"
    assert tx.run.status == "READY"
    assert len(events) == 1
    assert service.clarification_result(item, cipher.open(item.decision)) == form_result("Notice")
    assert service.reusable_clarification_answer(tx, payload) == form_result("Notice")
    with pytest.raises(InteractionError, match="Idempotency"):
        service.decide("run", "request", "tenant", "owner", DecisionCommand(**fields, answers=form_answers("Changed")))


def test_legacy_decision_retry_keeps_the_existing_digest():
    from database.human_interaction_models import HumanRequest
    from services.human_interaction.crypto import PayloadCipher
    from services.human_interaction.models import DecisionCommand, digest
    from services.human_interaction.service import HumanInteractionService

    old = {"version": 1, "digest": "0" * 64, "decision": "answer", "text": "Original answer",
           "idempotency_key": "pre-upgrade-key"}
    item = HumanRequest(request_id="request", status="DECIDED", idempotency_key=old["idempotency_key"],
                        decision_digest=digest(old))

    @contextmanager
    def transaction(*args):
        yield types.SimpleNamespace(run=types.SimpleNamespace(status="READY"), requests=lambda: [item])

    service = HumanInteractionService(types.SimpleNamespace(transaction=transaction),
                                      PayloadCipher(Fernet.generate_key().decode()))
    assert service.decide("run", "request", "tenant", "owner", DecisionCommand(**old))["accepted"]


@pytest.mark.parametrize("when", ["model", "tool", "finalization"])
def test_composer_guidance_resumes_same_loop_without_another_input_card(service, when):
    from services.human_interaction.models import SteeringCommand

    run_id = create_run(service)
    command = SteeringCommand(message_id="composer-message-0001", text="Use the revised direction")
    submitted = []

    def guide():
        if submitted:
            return
        submitted.append(service.steer(run_id, "tenant-a", "owner", command))

    first_code = 'final_answer("obsolete-final")' if when == "finalization" else 'send(value="first")\nsend(value="obsolete")'
    model = ScriptModel([f'<code>{first_code}</code>', '<code>final_answer("revised-result")</code>'],
                        callback=guide if when == "model" else None)
    effects = []
    port = port_for(service, run_id, allowed={"send", "final_answer"}, live_resume=True)
    agent = build_agent(port, model, effects, on_effect=guide if when == "tool" else None)
    if when == "finalization":
        close = port.close_steering

        def close_with_racing_guidance(checkpoint):
            guide()
            return close(checkpoint)

        port.close_steering = close_with_racing_guidance
    steps = list(agent.run("test", stream=True))
    assert str(steps[-1].output) == "revised-result"
    assert effects == (["first"] if when == "tool" else [])
    assert model.calls == 2
    assert any("Use the revised direction" in getattr(step, "task", "") for step in agent.memory.steps)
    assert service.snapshot(run_id, "tenant-a", "owner")["requests"] == []
    assert service.steer(run_id, "tenant-a", "owner", command) == submitted[0]
    with service.repository.transaction(run_id) as tx:
        assert len(tx.requests()) == 1
        assert tx.requests()[0].status == "DECIDED"


def test_composer_guidance_replaces_pending_clarification_but_never_approves_it(service):
    from nexent.core.human_interaction.contracts import AttemptSuspended
    from services.human_interaction.models import SteeringCommand

    run_id = create_run(service)
    port = port_for(service, run_id)
    with pytest.raises(AttemptSuspended):
        port.dispatch("1:0", "send", {"value": "obsolete"})
    service.steer(run_id, "tenant-a", "owner", SteeringCommand(
        message_id="composer-message-0001", text="Do not send; revise the task",
    ))
    assert service.snapshot(run_id, "tenant-a", "owner")["status"] == "READY"
    feedback = port.boundary({"steering_ids": []})
    assert feedback["text"] == "Do not send; revise the task"
    with service.repository.transaction(run_id) as tx:
        assert tx.execution("1:0").status == "REJECTED"
        assert all(item.status != "PENDING" for item in tx.requests())


def test_composer_guidance_is_owner_scoped_repeatable_and_closed_at_completion(service):
    from services.human_interaction.models import InteractionError, SteeringCommand

    run_id = create_run(service)
    port = port_for(service, run_id)
    command = SteeringCommand(message_id="composer-message-0001", text="My guidance")
    with pytest.raises(InteractionError):
        service.steer(run_id, "other-tenant", "owner", command)
    with pytest.raises(InteractionError):
        service.steer(run_id, "tenant-a", "other-user", command)
    result = service.steer(run_id, "tenant-a", "owner", command)
    assert service.steer(run_id, "tenant-a", "owner", command) == result
    second = service.steer(run_id, "tenant-a", "owner", SteeringCommand(
        message_id="second-message-0001", text="Second",
    ))
    assert second["request_id"] != result["request_id"]
    displayed = port.visible_guidance()
    assert [item["request_id"] for item in displayed] == [result["request_id"], second["request_id"]]
    assert [item["text"] for item in displayed] == [command.text, "Second"]
    with pytest.raises(InteractionError):
        service.steer(run_id, "tenant-a", "owner", SteeringCommand(message_id=command.message_id, text="Changed"))
    assert port.close_steering({"steering_ids": []}) is False
    assert port.close_steering({"steering_ids": [result["request_id"]]}) is False
    assert port.close_steering({"steering_ids": [result["request_id"], second["request_id"]]}) is True
    assert service.steer(run_id, "tenant-a", "owner", command)["accepted"]


@pytest.mark.parametrize("native", [False, True])
@pytest.mark.parametrize("batched", [False, True])
def test_successive_guidance_is_consumed_in_order_without_repeating_actions(service, native, batched):
    from services.human_interaction.models import SteeringCommand

    run_id = create_run(service)
    port = port_for(service, run_id, allowed={"send", "final_answer"}, live_resume=True)
    submitted = []
    texts = ["Use a formal tone", "Change the tone to casual"]

    def guide():
        if len(submitted) == 2:
            return
        for index in range(len(submitted), 2 if batched else len(submitted) + 1):
            command = SteeringCommand(message_id=f"repeat-guide-000{index}", text=texts[index])
            result = service.steer(run_id, "tenant-a", "owner", command)
            assert service.steer(run_id, "tenant-a", "owner", command) == result
            submitted.append(result["request_id"])

    obsolete = '<code>send(value="obsolete")</code>'
    model = ScriptModel(
        [obsolete] * (1 if batched else 2) + ['<code>send(value="revised")\nfinal_answer("done")</code>'],
        callback=guide,
    )
    effects = []
    agent = build_agent(port, model, effects, native=native)
    steps = list(agent.run("test", stream=True))
    assert str(steps[-1].output) == "done"
    assert effects == ["revised"]
    assert model.calls == (2 if batched else 3)
    assert agent.human_interaction.steering_ids == submitted
    tasks = "\n".join(getattr(step, "task", "") for step in agent.memory.steps)
    assert tasks.count(texts[0]) == tasks.count(texts[1]) == 1
    assert tasks.index(texts[0]) < tasks.index(texts[1])
    assert port.boundary(agent.human_interaction.capture()) is None
    with service.repository.transaction(run_id) as tx:
        assert len(tx.requests()) == 2


def test_late_composer_guidance_is_rejected_instead_of_silently_lost(service):
    from services.human_interaction.models import InteractionError, SteeringCommand

    run_id = create_run(service)
    port = port_for(service, run_id)
    assert port.close_steering({"steering_ids": []})
    with pytest.raises(InteractionError, match="finished accepting"):
        service.steer(run_id, "tenant-a", "owner", SteeringCommand(message_id="late-message-0001", text="Too late"))
    with service.repository.transaction(run_id) as tx:
        assert not tx.requests()


def test_native_executor_keeps_python_and_clear_requests_do_not_ask(service):
    run_id = create_run(service)
    port = port_for(service, run_id, live_resume=True)
    model = ScriptModel(['<code>values = [i * 2 for i in range(3)]\nfinal_answer(str(values))</code>'])
    agent = build_agent(port, model, [], native=True)
    steps = list(agent.run("Compute doubled numbers from 0 to 2", stream=True))
    assert str(steps[-1].output) == "[0, 2, 4]"
    assert model.calls == 1
    assert service.snapshot(run_id, "tenant-a", "owner")["requests"] == []


@pytest.mark.parametrize("native", [False, True])
def test_clarification_then_work_finishes_without_reinjected_tasks(service, native):
    from nexent.core.agents.context import ContextManager
    from nexent.core.agents.context.runtime import ManagedContextRuntime

    class InspectingModel(ScriptModel):
        def __init__(self):
            super().__init__([
                f'<code>answer = ask_user(questions={FORM!r})</code>',
                '<code>result = send(value="draft ready")</code>',
                '<code>print(result)</code>',
                '<code>final_answer(result)</code>',
            ])
            self.inputs = []

        def __call__(self, messages, **kwargs):
            self.inputs.append(json.dumps(messages, default=str))
            return super().__call__(messages, **kwargs)

    run_id = create_run(service)
    port = port_for(service, run_id, allowed={"send", "final_answer"}, live_resume=True)
    model = InspectingModel()
    effects = []
    agent = build_agent(port, model, effects, native=native)
    agent.context_runtime = ManagedContextRuntime(ContextManager())
    with ThreadPoolExecutor(max_workers=1) as pool:
        result = pool.submit(lambda: list(agent.run("Draft a notice", stream=True)))
        try:
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                if service.snapshot(run_id, "tenant-a", "owner")["requests"]:
                    break
                time.sleep(0.02)
            else:
                pytest.fail("No clarification card")
            decide_pending(service, run_id, decision="answer", answer="Team meeting")
            steps = result.result(timeout=10)
        finally:
            service.control(run_id, "tenant-a", "owner", "terminate")
    assert str(steps[-1].output) == "sent:draft ready"
    assert effects == ["draft ready"]
    assert model.calls == 4
    with service.repository.transaction(run_id) as tx:
        assert len(tx.requests()) == 1
    for messages in model.inputs[1:]:
        assert messages.count("Current-run human clarification (authoritative user input):") == 1
    assert model.inputs[-1].index("Current-run human clarification") < model.inputs[-1].index("sent:draft ready")


def test_native_clarification_continues_same_python_state_and_suppresses_rewording(service):
    run_id = create_run(service)
    port = port_for(service, run_id, live_resume=True)
    second_form = [{"id": "extra", "type": "text", "title": "Another preference?"}]
    model = ScriptModel([
        '<code>values = [i * 2 for i in range(3)]\n'
        f'answer = ask_user(questions={FORM!r})\n'
        'send(value=str(values))\n'
        f'repeated = ask_user(questions={second_form!r})\n'
        'final_answer(answer)</code>'
    ])
    effects = []
    agent = build_agent(port, model, effects, native=True)
    outcome = {}

    def run():
        try:
            outcome["steps"] = list(agent.run("test", stream=True))
        except BaseException as exc:
            outcome["error"] = exc

    thread = Thread(target=run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        snapshot = service.snapshot(run_id, "tenant-a", "owner")
        if snapshot["requests"]:
            break
        time.sleep(0.02)
    else:
        pytest.fail("No native clarification card")
    assert thread.is_alive()
    assert effects == []
    assert model.calls == 1
    decide_pending(service, run_id, "answer", "Notice")
    thread.join(timeout=5)
    assert not thread.is_alive()
    assert "error" not in outcome
    assert str(outcome["steps"][-1].output) == form_result("Notice")
    assert effects == ["[0, 2, 4]"]
    assert model.calls == 1
    assert json.loads(agent.python_executor.state["repeated"])["status"] == "clarification_limit_reached"
    with service.repository.transaction(run_id) as tx:
        assert len(tx.requests()) == 1


@pytest.mark.parametrize("when", ["model", "tool", "finalization"])
def test_native_steering_keeps_completed_observations_and_same_loop(service, when):
    from services.human_interaction.models import SteeringCommand

    run_id = create_run(service)
    submitted = []

    def guide():
        if not submitted:
            submitted.append(service.steer(run_id, "tenant-a", "owner", SteeringCommand(
                message_id="native-guide-0001", text="Use the revised direction",
            )))

    model = ScriptModel([
        '<code>print(send(value="once"))\nfinal_answer("old answer")</code>',
        '<code>final_answer("revised answer")</code>',
    ], callback=guide if when == "model" else None)
    effects = []
    port = port_for(service, run_id, live_resume=True)
    agent = build_agent(port, model, effects, native=True, on_effect=guide if when == "tool" else None)
    if when == "finalization":
        close = port.close_steering

        def close_with_guidance(checkpoint):
            guide()
            return close(checkpoint)

        port.close_steering = close_with_guidance
    steps = list(agent.run("test", stream=True))
    assert str(steps[-1].output) == "revised answer"
    assert effects == ([] if when == "model" else ["once"])
    assert model.calls == 2
    if when != "model":
        assert any("sent:once" in str(getattr(step, "observations", "")) for step in agent.memory.steps)


def test_native_continuation_never_replays_after_worker_loss(service):
    from database.human_interaction_db import utcnow
    from nexent.core.human_interaction.contracts import RecoveryRequired

    run_id = create_run(service)
    port = port_for(service, run_id, live_resume=True)
    agent = build_agent(port, ScriptModel(['<code>final_answer("done")</code>']), [], native=True)
    list(agent.run("test", stream=True))
    with service.repository.transaction(run_id) as tx:
        tx.run.lock_until = utcnow() - timedelta(seconds=1)
    resumed_port = port_for(service, run_id, live_resume=True)
    model = ScriptModel([])
    resumed = build_agent(resumed_port, model, [], native=True)
    with pytest.raises(RecoveryRequired):
        list(resumed.run("test", stream=True))
    assert model.calls == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("skip_user_save", [False, True])
async def test_attachment_request_starts_native_run_without_losing_files(service, monkeypatch, skip_user_save):
    from consts.model import AgentRequest
    from services.human_interaction import application

    request = AgentRequest(agent_id=1, conversation_id=7, query="Analyze the uploaded report", enable_hitl=True,
                           minio_files=[{"object_name": "report.pdf", "bucket": "test"}])
    saved_messages = []
    adapter = types.ModuleType("management.services.agent.run")
    adapter.save_messages = lambda request, *_: saved_messages.append(request)
    manager_module = types.ModuleType("agents.agent_run_manager")
    manager_module.agent_run_manager = types.SimpleNamespace(
        reserve_agent_run=lambda *_: "reserved", release_agent_run_reservation=lambda *_: None,
    )
    monkeypatch.setitem(sys.modules, "management.services.agent.run", adapter)
    monkeypatch.setitem(sys.modules, "agents.agent_run_manager", manager_module)
    monkeypatch.setattr(application, "require_enabled", lambda: service)
    monkeypatch.setattr(application, "HITL_ENABLED", True)
    monkeypatch.setattr(application, "HITL_ACCEPT_NEW_RUNS", True)
    monkeypatch.setattr(application, "HITL_TOOL_APPROVAL_ENABLED", False)

    async def authorize(*_):
        return None

    async def stream(run_id, tenant, user):
        return service.snapshot(run_id, tenant, user)

    monkeypatch.setattr(application, "authorize_run", authorize)
    monkeypatch.setattr(application, "stream_run", stream)
    result = await application.start_run(request, "tenant-a", "owner", "en", skip_user_save=skip_user_save)
    assert result["status"] == "READY"
    assert saved_messages == ([] if skip_user_save else [request])
    with service.repository.transaction(result["run_id"]) as tx:
        saved = service.cipher.open(tx.run.request_payload)
        assert saved["runtime_mode"] == "native-live-v1"
        assert saved["request"]["minio_files"] == request.minio_files


@pytest.mark.asyncio
@pytest.mark.parametrize("cancelled", [False, True])
async def test_native_attempt_preserves_sandbox_workspace_and_subagents(service, monkeypatch, cancelled):
    from consts.model import AgentRequest
    from nexent.core.agents.context_input import ContextInput
    from nexent.core.human_interaction.live_runtime import LiveHumanInteractionRuntime
    from nexent.scheduler import ClaimedJob
    from services.human_interaction import application

    request = AgentRequest(agent_id=1, conversation_id=7, query="Analyze", minio_files=[{"object_name": "report.pdf"}])
    run_id = service.create("tenant-a", "owner", 7, {
        "request": request.model_dump(mode="json"), "runtime_mode": "native-live-v1", "language": "en",
        "runtime_metadata": {}, "runtime_metadata_version": 1,
    })
    identity = service.repository.claim("worker", 1, 120)[0]
    config = types.SimpleNamespace(managed_agents=[object()], external_a2a_agents=[object()], tools=[],
                                   model_dump=lambda: {})
    cancellations = []
    unregisters = []
    sandbox = object()
    info = types.SimpleNamespace(agent_config=config, context_input=ContextInput(), model_config_list=[],
                                 runtime_metadata={}, sandbox_config=sandbox, workspace_path="/workspace/test",
                                 minio_files=request.minio_files, attempt_outcome=None,
                                 cancellation_scope=types.SimpleNamespace(cancel=lambda: cancellations.append(True)))

    async def authorize(*_):
        pass

    async def prepare(**kwargs):
        assert kwargs["agent_request"].minio_files == request.minio_files
        return info, None

    async def stream(**_):
        assert isinstance(info.human_interaction, LiveHumanInteractionRuntime)
        assert info.sandbox_config is sandbox
        assert info.workspace_path == "/workspace/test"
        assert info.minio_files == request.minio_files
        assert info.agent_config is config
        if cancelled:
            raise asyncio.CancelledError
        info.attempt_outcome = "completed"
        yield 'data: {"type":"final_answer","content":"Analyzed"}\n\n'

    adapter = types.ModuleType("management.services.agent.run")
    adapter.prepare_agent_run = prepare
    adapter._stream_agent_chunks = stream
    adapter._unregister_agent_run_after_execution = lambda *args, **kwargs: unregisters.append((args, kwargs))
    manager_module = types.ModuleType("agents.agent_run_manager")
    manager_module.agent_run_manager = types.SimpleNamespace(unregister_agent_run=lambda *_, **__: None)
    monkeypatch.setitem(sys.modules, "management.services.agent.run", adapter)
    monkeypatch.setitem(sys.modules, "agents.agent_run_manager", manager_module)
    monkeypatch.setattr(application, "get_service", lambda: service)
    monkeypatch.setattr(application, "authorize_run", authorize)
    attempt = application.execute_attempt(ClaimedJob(job_id=run_id, payload=identity),
                                          types.SimpleNamespace(owner_id="worker"))
    if cancelled:
        with pytest.raises(asyncio.CancelledError):
            await attempt
        assert cancellations == [True]
    else:
        await attempt
        assert cancellations == []
        assert service.snapshot(run_id, "tenant-a", "owner")["status"] == "COMPLETED"
    assert len(unregisters) == 1
    assert unregisters[0][0][:2] == (7, "owner")
    assert unregisters[0][1]["agent_run_info"] is info


def test_native_guidance_interrupts_the_waiting_code_suffix(service):
    from services.human_interaction.models import SteeringCommand

    run_id = create_run(service)
    port = port_for(service, run_id, live_resume=True)
    model = ScriptModel([
        f'<code>answer = ask_user(questions={FORM!r})\nsend(value="obsolete")\nfinal_answer(answer)</code>',
        '<code>final_answer("guided")</code>',
    ])
    effects = []
    agent = build_agent(port, model, effects, native=True)
    outcome = {}

    def run():
        try:
            outcome["steps"] = list(agent.run("test", stream=True))
        except BaseException as exc:
            outcome["error"] = exc

    thread = Thread(target=run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if service.snapshot(run_id, "tenant-a", "owner")["requests"]:
            break
        time.sleep(0.02)
    else:
        pytest.fail("No pending clarification")
    service.steer(run_id, "tenant-a", "owner", SteeringCommand(
        message_id="native-wait-guide", text="Finish with the revised direction",
    ))
    thread.join(timeout=5)
    assert not thread.is_alive()
    assert "error" not in outcome
    assert str(outcome["steps"][-1].output) == "guided"
    assert effects == []
    assert model.calls == 2


def test_northbound_card_decision_and_replay_through_runtime_http(service, monkeypatch):
    """Exercise both HTTP boundaries and real PostgreSQL lifecycle with internal JWTs."""
    from unittest.mock import MagicMock

    import httpx
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from nexent.core.human_interaction.contracts import AttemptSuspended
    from services.human_interaction import application

    with monkeypatch.context() as imports:
        # Load HTTP dependencies against the complete client module; the HITL
        # repository already retains the isolated fixture's session factory.
        imports.delitem(sys.modules, "database.client")
        imports.setitem(sys.modules, "management.services.agent.service", MagicMock())
        from utils import auth_utils
        from apps import northbound_app, northbound_human_interaction_app, human_interaction_app
    from services import runtime_proxy_service

    monkeypatch.setattr(application, "require_enabled", lambda: service)
    monkeypatch.setattr(human_interaction_app, "require_enabled", lambda: service)
    monkeypatch.setattr(auth_utils, "SUPABASE_JWT_SECRET", "test-only-internal-signing-key-for-hitl")
    identities = {
        "owner-key": {"user_id": "owner", "tenant_id": "tenant-a", "token_id": 0},
        "other-user-key": {"user_id": "other", "tenant_id": "tenant-a", "token_id": 0},
        "other-tenant-key": {"user_id": "owner", "tenant_id": "tenant-b", "token_id": 0},
    }
    monkeypatch.setattr(northbound_app, "validate_bearer_token", lambda header: (
        bool(header and header.removeprefix("Bearer ") in identities), {"valid": True},
    ))
    monkeypatch.setattr(northbound_app, "get_user_and_tenant_by_access_key", lambda key: identities[key])
    runtime = FastAPI(root_path="/api")
    runtime.include_router(human_interaction_app.internal_router)
    monkeypatch.setattr(runtime_proxy_service, "create_httpx_client", lambda **kwargs: httpx.AsyncClient(
        transport=httpx.ASGITransport(app=runtime), headers=kwargs["headers"],
    ))
    northbound = FastAPI()
    northbound.include_router(northbound_human_interaction_app.router)
    client = TestClient(northbound)
    headers = {"Authorization": "Bearer owner-key"}
    base = "/nb/v1/chat/human-interactions"

    run_id = create_run(service)
    port = port_for(service, run_id)
    interaction = {"kind": "CLARIFICATION", "schema_version": 2, "questions": FORM}
    arguments = {"questions": FORM}
    with pytest.raises(AttemptSuspended):
        port.dispatch("ask:0", "ask_user", arguments, interaction=interaction)
    service.repository.release(run_id, "worker")
    snapshot = client.get(base + "/conversation/7", headers=headers).json()["data"]
    assert snapshot["status"] == "WAITING_HUMAN"
    card = snapshot["requests"][0]
    stream = client.get(base + f"/{run_id}/events", headers=headers)
    assert stream.status_code == 200
    assert '"type": "human_interaction"' in stream.text
    assert f'id: {snapshot["event_seq"]}\n' in stream.text
    decision_url = base + f'/{run_id}/requests/{card["request_id"]}/decisions'
    command = {
        "version": card["version"], "digest": card["digest"], "idempotency_key": "northbound-answer-0001",
        "decision": "answer", "answers": form_answers("Prepare a notice"),
    }
    for key in ("other-user-key", "other-tenant-key"):
        unauthorized_headers = {"Authorization": f"Bearer {key}"}
        assert client.get(base + f"/{run_id}", headers=unauthorized_headers).status_code == 404
        assert client.get(base + f"/{run_id}/events", headers=unauthorized_headers).status_code == 404
        assert client.post(decision_url, json=command, headers=unauthorized_headers).status_code == 404
    accepted = client.post(decision_url, json=command, headers=headers)
    assert accepted.status_code == 200 and accepted.json()["data"]["accepted"] is True
    decided = service.snapshot(run_id, "tenant-a", "owner")
    assert decided["status"] == "READY"
    assert client.post(decision_url, json=command, headers=headers).status_code == 200
    assert service.snapshot(run_id, "tenant-a", "owner")["event_seq"] == decided["event_seq"]
    changed = {**command, "answers": form_answers("Different request")}
    assert client.post(decision_url, json=changed, headers=headers).status_code == 409

    resumed = port_for(service, run_id)
    result = resumed.dispatch("ask:0", "ask_user", arguments, interaction=interaction)
    assert "Prepare a notice" in result["result"]
    resumed.emit_chunk('data: {"type":"final_answer","content":"Notice prepared"}\n\n')
    resumed.finish("completed")
    service.repository.release(run_id, "worker")
    continuation = client.get(
        base + f"/{run_id}/events", headers={**headers, "Last-Event-ID": str(snapshot["event_seq"])},
    )
    assert continuation.status_code == 200
    assert '"type": "human_decision"' in continuation.text
    assert '"type":"final_answer"' in continuation.text
    assert '"type": "human_interaction"' not in continuation.text
    assert '"status": "COMPLETED"' in continuation.text
    assert service.snapshot(run_id, "tenant-a", "owner")["conversation_id"] == 7


@pytest.mark.parametrize("ready", [False, True])
def test_managed_cancellation_exits_live_wait_without_executing_pending_action(service, ready):
    from threading import Event
    from nexent.core.human_interaction.contracts import AttemptSuspended, RunTerminated

    run_id = create_run(service)
    port = port_for(service, run_id)
    with pytest.raises(AttemptSuspended):
        port.dispatch("1:0", "send", {"value": "must-not-run"})
    if ready:
        decide_pending(service, run_id)
    port.live_resume = True
    port.stop_event = Event()
    port.stop_event.set()
    with pytest.raises(RunTerminated, match="managed execution was cancelled"):
        port._wait_until_ready()
    with service.repository.transaction(run_id) as tx:
        assert tx.execution("1:0").status == "PREPARED"
