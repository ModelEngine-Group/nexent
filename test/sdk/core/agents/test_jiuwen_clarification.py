# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Terminal ordinary-chat clarification never dispatches resource actions."""

import asyncio
import json
from threading import Event
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from nexent.core.agents.contracts.config import AgentConfig
from nexent.core.agents.cores.jiuwen.adapter import JiuwenAdapter
from nexent.core.agents.cores.jiuwen.model import JiuwenServiceModel
from nexent.core.agents.cores.jiuwen.protocol import EXECUTION_TOOL, JiuwenProtocolError
from nexent.core.concurrency import LanePolicy, RunCancellationScope, ThreadManager
from nexent.core.model_service.contracts import ToolCall
from nexent.core.utils.observer import MessageObserver, ProcessType
from test_jiuwen_model_service import message
from test_jiuwen_model_service import saved_profile as _saved_profile

saved_profile = _saved_profile

FORM = {"questions": [{"id": "birth", "type": "text", "title": "Please provide your birth date", "required": True}]}


def test_ordinary_human_interaction_is_an_advertised_core_capability():
    assert "human_interaction" in JiuwenAdapter.capabilities()


def control(names=()):
    from nexent.core.agents.cores.jiuwen.clarification import JiuwenClarification

    return JiuwenClarification(set(names))


def call(name, arguments):
    return SimpleNamespace(name=name, arguments=json.dumps(arguments))


@pytest.mark.parametrize("text", [False, True])
def test_exclusive_complete_literal_form_is_valid(text):
    c = control()
    calls = [call(EXECUTION_TOOL, {"code": "ask_user(questions=" + repr(FORM["questions"]) + ")"})] if text else [
        call(c.name, FORM)]
    assert c.form_for(calls, text_protocol=text).model_dump(mode="json", exclude_none=True) == {
        "questions": [{**FORM["questions"][0], "options": [], "allow_other": False, "placeholder": ""}]}


@pytest.mark.parametrize("suffix", ["", "\nprint(answer)"])
def test_text_form_accepts_inert_assignment_without_executing_it(suffix):
    code = f"answer = ask_user(questions={FORM['questions']!r}){suffix}"
    form = control().form_for([call(EXECUTION_TOOL, {"code": code})], text_protocol=True)
    assert form.questions[0].id == "birth"


@pytest.mark.parametrize("text", [False, True])
def test_creation_confirmation_keeps_the_request_in_both_protocols(text):
    form = {"questions": [{"id": "workbench_creation_mode", "type": "single_choice",
        "title": "Create an Agent?", "creation_request": "Summarize the supplied report.",
        "options": [{"id": "agent_create", "label": "Create"},
                    {"id": "continue_chat", "label": "Continue chat"}]}]}
    calls = [call(EXECUTION_TOOL, {"code": f"ask_user(questions={form['questions']!r})"})] if text else [
        call("ask_user", form)]
    result = control().form_for(calls, text_protocol=text)
    assert result.questions[0].creation_request == "Summarize the supplied report."
    assert [option.id for option in result.questions[0].options] == ["agent_create", "continue_chat"]


@pytest.mark.parametrize("code", [
    "record(); ask_user(questions=[])", "ask_user(questions=load())", "x = ask_user(questions=[])",
    "ask_user(questions=[])", "alias = ask_user", "ask_user(questions=[{'id':'x','id':'y'}])",
])
def test_text_clarification_rejects_mixed_dynamic_and_invalid_actions(code):
    with pytest.raises(JiuwenProtocolError):
        control().form_for([call(EXECUTION_TOOL, {"code": code})], text_protocol=True)


@pytest.mark.parametrize("calls", [
    [call("ask_user", FORM), call("add", {"a": 1})],
    [call("ask_user", FORM), call("ask_user", FORM)],
    [call("ask_user", {"questions": []})],
])
def test_native_mixed_or_invalid_forms_are_rejected(calls):
    with pytest.raises(JiuwenProtocolError):
        control().form_for(calls, text_protocol=False)


def test_literal_prose_or_an_unrelated_call_does_not_become_a_form():
    assert control().form_for([], text_protocol=False) is None
    assert control().form_for([call(EXECUTION_TOOL, {"code": "print('ask_user')"})], text_protocol=True) is None


def test_collision_uses_a_distinct_virtual_name():
    c = control({"ask_user", "nexent_ask_user"})
    assert c.name == "nexent_ask_user_1"
    assert c.form_for([call(c.name, FORM)], text_protocol=False) is not None
    assert c.form_for([call("ask_user", FORM)], text_protocol=False) is None


@pytest.mark.parametrize("language", ["zh", "en"])
@pytest.mark.parametrize("text", [False, True])
def test_protocol_only_changes_shared_policy_wire_example(language, text):
    instructions = control().instructions(language, text_protocol=text)
    assert "ask_user" in instructions
    assert ("<code>" in instructions) == text


@pytest.mark.parametrize("mode,enabled", [("chat", True), ("artifact", False), ("python_workflow", False)])
def test_creator_protocols_keep_their_own_card_boundaries(mode, enabled):
    info = SimpleNamespace(agent_config=AgentConfig(name="fixture", description="Fixture", model_name="fixture", tools=[], response_mode=mode), observer=MessageObserver())
    adapter = JiuwenAdapter(info)
    assert (adapter.clarification is not None) == enabled


@pytest.mark.asyncio
async def test_model_finishes_observation_then_pauses_before_native_dispatch(saved_profile):
    from nexent.core.agents.cores.jiuwen.clarification import ClarificationRequested

    c = control()
    response = message("", tool_calls=[ToolCall(name=c.name, provider_call_id="ask-1", index=0,
        raw_arguments=json.dumps(FORM), parsed_arguments=FORM)])
    response = response.model_copy(update={"finish_reason": "tool_calls"})
    service = SimpleNamespace(ainvoke=AsyncMock(return_value=response))
    observed = []
    model = JiuwenServiceModel(service, saved_profile, RunCancellationScope(), clarification=c,
        on_event=lambda event: observed.append(event.type))
    with pytest.raises(ClarificationRequested) as error:
        await model.invoke([{"role": "user", "content": "Need missing information"}], tools=[{
            "name": c.name, "description": "Clarify", "parameters": c.schema}])
    assert error.value.form.questions[0].id == "birth"
    assert observed == ["message_completed"]
    assert service.ainvoke.await_count == 1
    assert not model.scope.cancelled


@pytest.fixture
def loop_manager():
    manager = ThreadManager("clarification-loop", {
        "background-service": LanePolicy(name="background-service", max_workers=1, max_queue_size=0)})
    manager.start()
    yield manager
    assert not asyncio.run(manager.shutdown(timeout=5)).stuck_execution_ids


def test_adapter_publishes_one_public_card_without_a_fake_final_or_cancel(loop_manager):
    from nexent.core.agents.contracts.clarification import ClarificationForm
    from nexent.core.agents.cores.jiuwen.clarification import ClarificationRequested

    observer = MessageObserver(lang="en")
    info = SimpleNamespace(agent_config=AgentConfig(name="fixture", description="Fixture", model_name="fixture", tools=[]), observer=observer)
    adapter = JiuwenAdapter(info)
    adapter.manager = loop_manager
    adapter.scope = RunCancellationScope(Event())
    adapter._run_async = AsyncMock(side_effect=ClarificationRequested(ClarificationForm.model_validate(FORM)))
    assert "birth date" in adapter.run()
    result = adapter.events.finish()
    assert result.status == "completed" and result.end_reason == "awaiting_input"
    assert not result.final_block_ids and not result.final_content
    events = [json.loads(item) for item in observer.message_query]
    assert sum(e["type"] == ProcessType.HUMAN_INTERACTION.value for e in events) == 1
    assert not any(e["type"] in {"error", "final_answer", "tool"} for e in events)
    card = next(e for e in events if e["type"] == "human_interaction")
    assert isinstance(card["content"], str)
    assert json.loads(card["content"])["questions"][0]["id"] == "birth"
    assert "creation_request" not in json.loads(card["content"])["questions"][0]
