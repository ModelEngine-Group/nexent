from types import SimpleNamespace

import pytest
from nexent.core.human_interaction.contracts import StepSteered
from nexent.core.human_interaction.executor import LinearToolExecutor
from nexent.core.human_interaction.runtime import AskUserTool, HumanInteractionRuntime


class RecordingPort:
    def __init__(self):
        self.interaction = None

    def dispatch(self, _slot, _name, _arguments, *, interaction=None):
        self.interaction = interaction
        return {"status": "replay", "result": "custom answer"}

    def load_plan(self):
        return None


def call_ask_user(*, legacy=False, **arguments):
    port = RecordingPort()
    runtime = HumanInteractionRuntime(port)
    runtime.agent = SimpleNamespace(
        step_number=1,
        verification_controller=None,
    )
    if legacy:
        runtime.legacy_replay_step = 1
    result = runtime.call("0", "ask_user", [], arguments, AskUserTool())
    return result, port.interaction


def test_ask_user_allows_an_other_answer_by_default():
    result, interaction = call_ask_user(legacy=True, question="Choose", options=["A", "B"])

    assert result == "custom answer"
    assert interaction == {
        "kind": "CLARIFICATION",
        "question": "Choose",
        "options": ["A", "B"],
        "allow_other": True,
    }


def test_ask_user_can_require_a_registered_option():
    _, interaction = call_ask_user(
        legacy=True,
        question="Choose",
        options=["A", "B"],
        allow_other=False,
    )

    assert interaction["allow_other"] is False


def test_answer_is_reinjected_as_authoritative_context_for_later_steps():
    port = RecordingPort()
    runtime = HumanInteractionRuntime(port)
    runtime.agent = SimpleNamespace(
        step_number=2,
        verification_controller=None,
        memory=SimpleNamespace(steps=[]),
        python_executor=SimpleNamespace(state={}),
    )
    questions = [{"id": str(i), "type": "text", "title": title}
                 for i, title in enumerate(["Where?", "For whom?", "What format?"])]
    runtime.call("0", "ask_user", [], {"questions": questions}, AskUserTool())
    runtime._inject_clarification_context()

    context = runtime.agent.memory.steps[-1].task
    assert "Question: Where?" in context
    assert "Answer: custom answer" in context
    assert "Do not call ask_user again" in context


@pytest.mark.parametrize("native", [False, True])
def test_clarification_is_added_once_not_as_a_new_task_every_step(native):
    from nexent.core.human_interaction.live_runtime import LiveHumanInteractionRuntime

    runtime = (LiveHumanInteractionRuntime if native else HumanInteractionRuntime)(RecordingPort())
    runtime.agent = SimpleNamespace(step_number=1, memory=SimpleNamespace(steps=[]))
    runtime._record_clarification("Which topic?", "Team meeting")
    for number in range(2, 16):
        runtime.agent.step_number = number
        runtime._inject_clarification_context()
    assert len(runtime.agent.memory.steps) == 1

    runtime._record_clarification("Which topic?", "Team meeting")
    runtime._inject_clarification_context()
    assert len(runtime.agent.memory.steps) == 1

    runtime._record_clarification("Which topic?", "Project review")
    runtime._inject_clarification_context()
    assert len(runtime.agent.memory.steps) == 2
    assert "Project review" in runtime.agent.memory.steps[-1].task
    assert "Team meeting" not in runtime.agent.memory.steps[-1].task


@pytest.mark.parametrize("native", [False, True])
def test_pending_answer_precedes_newer_guidance(native):
    from nexent.core.human_interaction.live_runtime import LiveHumanInteractionRuntime

    port = RecordingPort()
    port.boundary = lambda _: {"request_id": "guide-1", "text": "Use a friendly tone instead"}
    port.save_checkpoint = lambda _: None
    runtime = (LiveHumanInteractionRuntime if native else HumanInteractionRuntime)(port)
    runtime.capture = dict
    runtime.agent = SimpleNamespace(step_number=2, memory=SimpleNamespace(steps=[]))
    runtime._record_clarification("Which tone?", "Formal")
    runtime.safe_boundary()
    runtime.agent.step_number = 3
    runtime._inject_clarification_context()
    tasks = [step.task for step in runtime.agent.memory.steps]
    assert len(tasks) == 2
    assert "Formal" in tasks[0]
    assert "friendly tone instead" in tasks[1]


@pytest.mark.parametrize("legacy", [False, True])
@pytest.mark.parametrize("pending", [False, True])
def test_checkpoint_restores_delivered_and_pending_clarification(legacy, pending):
    port = RecordingPort()

    def make_runtime():
        runtime = HumanInteractionRuntime(port)
        runtime.agent = SimpleNamespace(
            step_number=2, memory=SimpleNamespace(steps=[]), task="Draft", _history_step_count=0,
            state={}, python_executor=SimpleNamespace(state={}), logger=None,
        )
        return runtime

    original = make_runtime()
    original._record_clarification("Topic?", "Team meeting")
    if not pending:
        original._inject_clarification_context()
    port.checkpoint = original.capture()
    if legacy:
        port.checkpoint.pop("clarification_context")
    resumed = make_runtime()
    assert resumed.restore()
    for number in range(3, 6):
        resumed.agent.step_number = number
        resumed._inject_clarification_context()
    assert len(resumed.agent.memory.steps) == 1
    assert "Team meeting" in resumed.agent.memory.steps[0].task


@pytest.mark.parametrize("native", [False, True])
def test_interrupted_action_stays_before_the_guidance_it_preceded(native):
    from nexent.core.human_interaction.live_runtime import LiveHumanInteractionRuntime

    port = RecordingPort()
    port.boundary = lambda _: {"request_id": "guide", "text": "Revise draft", "completed_actions": "Saved draft"}
    port.save_checkpoint = lambda _: None
    runtime = (LiveHumanInteractionRuntime if native else HumanInteractionRuntime)(port)
    runtime.capture = dict
    runtime.agent = SimpleNamespace(
        step_number=2, memory=SimpleNamespace(steps=[]), python_executor=SimpleNamespace(state={}),
    )
    action = SimpleNamespace(observations="Saved draft", code_action="old suffix")
    runtime.pending_step = action
    assert runtime.safe_boundary()
    assert runtime.agent.memory.steps[0] is action
    assert "Revise draft" in runtime.agent.memory.steps[1].task
    assert runtime.pending_step is None


def test_additional_answer_does_not_reassert_previously_delivered_answers():
    runtime = HumanInteractionRuntime(RecordingPort())
    runtime.agent = SimpleNamespace(step_number=1, memory=SimpleNamespace(steps=[]))
    runtime._record_clarification("Tone?", "Formal")
    runtime._inject_clarification_context()
    runtime._record_clarification("Topic?", "Team meeting")
    runtime._inject_clarification_context()
    assert "Formal" not in runtime.agent.memory.steps[-1].task
    assert "Team meeting" in runtime.agent.memory.steps[-1].task


def test_steering_abandons_the_current_code_suffix_at_the_loop_boundary():
    port = RecordingPort()
    port.dispatch = lambda *_args, **_kwargs: {"status": "steered"}
    runtime = HumanInteractionRuntime(port)
    runtime.agent = SimpleNamespace(step_number=1, verification_controller=None)
    boundary_calls = []
    runtime.safe_boundary = lambda: boundary_calls.append(True)

    with pytest.raises(StepSteered):
        runtime.call("0", "ask_user", [], {"questions": [
            {"id": str(i), "type": "text", "title": f"Intent {i}?"} for i in range(3)
        ]}, AskUserTool())

    assert boundary_calls == [True]


def test_linear_executor_never_dispatches_an_old_suffix_after_steering():
    runtime = SimpleNamespace(
        safe_boundary=lambda: True,
        call=lambda *_args, **_kwargs: pytest.fail("old suffix was dispatched"),
    )
    executor = LinearToolExecutor(runtime)
    executor.send_tools({"send": object()})

    with pytest.raises(StepSteered):
        executor('send("obsolete")')


def test_new_calls_require_structured_questions():
    with pytest.raises(ValueError, match="registered schema"):
        call_ask_user(question="Where?")


@pytest.mark.parametrize("count", [0, 6])
def test_invalid_question_count_never_dispatches(count):
    with pytest.raises(ValueError):
        call_ask_user(questions=[{"id": str(i), "type": "text", "title": f"Intent {i}?"} for i in range(count)])


@pytest.mark.parametrize("count", [3, 4, 5])
def test_ask_user_emits_a_versioned_structured_form(count):
    result, interaction = call_ask_user(
        questions=[{"id": str(i), "type": "text", "title": f"Intent {i}?"} for i in range(count)]
    )
    assert result == "custom answer"
    assert interaction["schema_version"] == 2
    assert len(interaction["questions"]) == count
    assert all(item["required"] for item in interaction["questions"])
    assert set(AskUserTool.inputs) == {"questions"}


@pytest.mark.parametrize("count", [1, 2, 3, 4, 5])
def test_only_missing_questions_are_required(count):
    _, interaction = call_ask_user(questions=[
        {"id": str(i), "type": "text", "title": f"Missing fact {i}?"} for i in range(count)
    ])
    assert len(interaction["questions"]) == count


def test_invalid_native_form_is_model_feedback_and_does_not_dispatch():
    import json

    from nexent.core.human_interaction.live_runtime import LiveHumanInteractionRuntime

    port = RecordingPort()
    runtime = LiveHumanInteractionRuntime(port)
    result = runtime.ask([{"id": "bad", "type": "execute", "on_submit": "run_code()"}])
    assert json.loads(result)["status"] == "invalid_clarification"
    assert port.interaction is None
