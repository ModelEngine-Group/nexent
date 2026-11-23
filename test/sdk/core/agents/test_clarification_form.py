import json
from copy import deepcopy

import pytest
from nexent.core.agents.clarification import ClarificationForm


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


def test_nested_declarative_choices_are_normalized(form):
    for item in form["questions"][1:]:
        item["choices"] = {"options": item.pop("options"), "allow_other": item.pop("allow_other")}
    normalized = ClarificationForm.model_validate(form).model_dump(mode="json")
    assert "choices" not in normalized["questions"][1]
    assert normalized["questions"][1]["allow_other"] is True
    assert ClarificationForm.model_validate(form).questions[1].options[0].label == "Team"


def test_choices_array_alias_preserves_option_labels(form):
    form["questions"][1]["choices"] = form["questions"][1].pop("options")
    assert ClarificationForm.model_validate(form).questions[1].options[0].label == "Team"


@pytest.mark.parametrize("choices", [
    {"options": [], "on_submit": "run_code()"},
    {"options": [{"id": "x", "label": "Conflicting"}]},
])
def test_choice_normalization_rejects_executable_or_conflicting_fields(form, choices):
    form["questions"][1]["choices"] = choices
    with pytest.raises(ValueError):
        ClarificationForm.model_validate(form)
