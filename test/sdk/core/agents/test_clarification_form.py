import json
from copy import deepcopy

import pytest
from nexent.core.human_interaction.clarification import (
    ClarificationAnswer,
    ClarificationForm,
    format_clarification_answers,
)


@pytest.fixture
def form():
    return {
        "questions": [
            {"id": "goal", "type": "text", "title": "Desired outcome?"},
            {
                "id": "audience",
                "type": "single_choice",
                "title": "Audience?",
                "allow_other": True,
                "options": [
                    {"id": "a", "label": "Team"},
                    {"id": "b", "label": "Customers"},
                ],
            },
            {
                "id": "constraints",
                "type": "multiple_choice",
                "title": "Constraints?",
                "allow_other": True,
                "options": [
                    {"id": "short", "label": "Brief"},
                    {"id": "formal", "label": "Formal"},
                ],
            },
        ]
    }


@pytest.fixture
def answers():
    return [
        {"question_id": "goal", "value": "Meeting notice"},
        {"question_id": "audience", "value": "a", "other_text": "Partners"},
        {
            "question_id": "constraints",
            "value": ["short", "formal"],
            "other_text": "Due tomorrow",
        },
    ]


def submit(form, answers):
    return json.loads(
        format_clarification_answers(
            form, [ClarificationAnswer.model_validate(a) for a in answers]
        )
    )


def test_all_answers_and_other_fields_are_preserved_with_labels(form, answers):
    result = submit(form, list(reversed(answers)))["answers"]
    assert [item["question_id"] for item in result] == [
        "goal",
        "audience",
        "constraints",
    ]
    assert result[1]["answer"] == "Team"
    assert result[1]["other_text"] == "Partners"
    assert result[2]["answer"] == ["Brief", "Formal"]
    assert result[2]["value"] == ["short", "formal"]
    assert result[2]["other_text"] == "Due tomorrow"


@pytest.mark.parametrize(
    "change",
    [
        lambda a: a.pop(),
        lambda a: a.append(deepcopy(a[0])),
        lambda a: a[0].update(question_id="unknown"),
        lambda a: a[0].update(value="  "),
        lambda a: a[0].update(other_text="forged"),
        lambda a: a[1].update(value="forged"),
        lambda a: a[1].update(value=["a"]),
        lambda a: a[2].update(value="short"),
        lambda a: a[2].update(value=["short", "short"]),
        lambda a: a[2].update(value=["forged"]),
    ],
)
def test_answers_are_checked_against_the_frozen_form(form, answers, change):
    change(answers)
    with pytest.raises(ValueError):
        submit(form, answers)


def test_optional_question_can_be_omitted_and_other_can_be_the_only_choice(
    form, answers
):
    form["questions"][0]["required"] = False
    answers.pop(0)
    answers[0]["value"] = ""
    answers[1]["value"] = []
    result = submit(form, answers)["answers"]
    assert len(result) == 2
    assert result[0]["other_text"] == "Partners"


@pytest.mark.parametrize(
    "change",
    [
        lambda q: q[1].update(id="goal"),
        lambda q: q[1].update(title="Desired outcome?"),
        lambda q: q[1].update(options=[{"id": "a", "label": "Only choice"}]),
        lambda q: q[1]["options"][1].update(id="a"),
        lambda q: q[0].update(allow_other=True),
        lambda q: q[0].update(type="executable_script"),
        lambda q: q[0].update(on_submit="run_code()"),
        lambda q: q[0].update(title="  "),
    ],
)
def test_invalid_or_executable_form_definitions_are_rejected(form, change):
    change(form["questions"])
    with pytest.raises(ValueError):
        ClarificationForm.model_validate(form)


def test_nested_declarative_choices_are_normalized(form, answers):
    for item in form["questions"][1:]:
        item["choices"] = {"options": item.pop("options"), "allow_other": item.pop("allow_other")}
    normalized = ClarificationForm.model_validate(form).model_dump(mode="json")
    assert "choices" not in normalized["questions"][1]
    assert normalized["questions"][1]["allow_other"] is True
    assert submit(form, answers)["answers"][1]["answer"] == "Team"


def test_choices_array_alias_preserves_option_labels(form, answers):
    form["questions"][1]["choices"] = form["questions"][1].pop("options")
    assert submit(form, answers)["answers"][1]["answer"] == "Team"


@pytest.mark.parametrize("choices", [
    {"options": [], "on_submit": "run_code()"},
    {"options": [{"id": "x", "label": "Conflicting"}]},
])
def test_choice_normalization_rejects_executable_or_conflicting_fields(form, choices):
    form["questions"][1]["choices"] = choices
    with pytest.raises(ValueError):
        ClarificationForm.model_validate(form)
