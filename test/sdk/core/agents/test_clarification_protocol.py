# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Terminal clarification parsing rejects the complete block before execution."""
import pytest
from nexent.core.agents.clarification import (
    choose_clarification_tool_name,
    render_question_text,
)
from nexent.core.agents.output_protocol import (
    ModelOutputProtocolError,
    extract_clarification_form,
)

QUESTIONS = "[{'id': 'scope', 'type': 'text', 'title': 'Which region?'}]"


def test_static_form_and_full_text_fallback():
    form = extract_clarification_form(f"ask_user(questions={QUESTIONS})", "ask_user")
    assert form.questions[0].id == "scope"
    assert render_question_text(form) == "1. Which region?"


@pytest.mark.parametrize("tool_name", ["ask_user", "nexent_ask_user_2"])
@pytest.mark.parametrize("suffix", ["", "\nprint(answer)", "; print(answer)"])
def test_literal_assignment_is_a_terminal_form_without_execution(tool_name, suffix):
    form = extract_clarification_form(f"answer = {tool_name}(questions={QUESTIONS}){suffix}", tool_name)
    assert form.questions[0].id == "scope"
    assert render_question_text(form) == "1. Which region?"


@pytest.mark.parametrize("code", [
    f"answer = ask_user(questions={QUESTIONS}); print(other)",
    f"answer = ask_user(questions={QUESTIONS}); print(answer, 'extra')",
    f"answer = ask_user(questions={QUESTIONS}); print(answer, flush=True)",
    f"answer = ask_user(questions={QUESTIONS}); print(str(answer))",
    f"answer = ask_user(questions={QUESTIONS}); record()",
    f"answer = ask_user(questions={QUESTIONS}); print(answer); record()",
    f"print = ask_user(questions={QUESTIONS}); print(print)",
    f"ask_user = ask_user(questions={QUESTIONS})",
    f"a = b = ask_user(questions={QUESTIONS})",
    f"a, b = ask_user(questions={QUESTIONS})",
    f"obj.value = ask_user(questions={QUESTIONS})",
    f"items[0] = ask_user(questions={QUESTIONS})",
    f"answer: str = ask_user(questions={QUESTIONS})",
    f"record(); ask_user(questions={QUESTIONS})",
    f"ask_user(questions={QUESTIONS}); record()",
    f"if True:\n    ask_user(questions={QUESTIONS})",
    f"print(ask_user(questions={QUESTIONS}))",
    "alias = ask_user",
    "def ask_user(): pass",
    "from tools import ask_user as alias",
    "getattr(ask_user, '__call__')()",
    "x.ask_user(questions=[])",
    "ask_user(questions=data)",
    "ask_user(questions=build_questions())",
    "ask_user(questions=[question for question in source])",
    f"ask_user({QUESTIONS})",
    f"ask_user(**{{'questions': {QUESTIONS}}})",
    f"ask_user(questions={QUESTIONS}, other=True)",
    "ask_user(questions=[{'id': 'a', 'id': 'b', 'type': 'text', 'title': 'Q'}])",
    "ask_user(questions=[{**data}])",
    "ask_user(",
])
def test_invalid_form_is_a_repairable_protocol_error(code):
    with pytest.raises(ModelOutputProtocolError) as error:
        extract_clarification_form(code, "ask_user")
    assert error.value.reason.value == "malformed_action"


def test_schema_failure_teaches_yaml_option_contract_without_echoing_rejected_values():
    question = {
        "id": "scope", "type": "single_choice", "title": "Which scope?",
        "options": [{"id": f"option_{index}", "label": "private label"} for index in range(13)],
        "allow_other": True,
    }
    with pytest.raises(ModelOutputProtocolError) as error:
        extract_clarification_form(f"ask_user(questions={[question]!r})", "ask_user")
    assert error.value.reason.value == "invalid_clarification_form"
    assert "questions.0.options: too_long" in error.value.repair_instruction
    assert "2-12 options" in error.value.repair_instruction
    assert "allow_other" in error.value.repair_instruction
    assert "private label" not in error.value.repair_instruction


def test_empty_form_has_schema_repair_feedback():
    with pytest.raises(ModelOutputProtocolError) as error:
        extract_clarification_form("ask_user(questions=[])", "ask_user")
    assert error.value.reason.value == "invalid_clarification_form"
    assert "questions: too_short" in error.value.repair_instruction


def test_oversized_clarification_keeps_the_existing_action_size_limit():
    code = f"# {'x' * 131072}\nanswer = ask_user(questions={QUESTIONS})"
    with pytest.raises(ModelOutputProtocolError) as error:
        extract_clarification_form(code, "ask_user")
    assert error.value.reason.value == "malformed_action"


def test_ordinary_code_and_string_mentions_remain_executable():
    assert extract_clarification_form("record(); print('ask_user')", "ask_user") is None
    assert extract_clarification_form("ask_user()", "nexent_ask_user") is None


def test_business_name_collision_never_replaces_tools():
    assert choose_clarification_tool_name(set()) == "ask_user"
    assert choose_clarification_tool_name({"ask_user"}) == "nexent_ask_user"
    assert choose_clarification_tool_name({"ask_user", "nexent_ask_user", "nexent_ask_user_1"}) == "nexent_ask_user_2"
