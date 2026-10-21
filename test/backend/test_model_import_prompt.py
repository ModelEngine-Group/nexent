# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Import-model prompt normalization branches and validation boundaries."""

from collections import UserDict
from copy import deepcopy

import pytest
from pydantic import ValidationError

from backend.consts import model as model_consts


@pytest.fixture
def agent_payload():
    return {
        "agent_id": 1,
        "name": "test-agent",
        "description": "Test agent",
        "max_steps": 5,
        "provide_run_summary": False,
        "enabled": True,
        "tools": [],
        "managed_agents": [],
    }


@pytest.mark.parametrize("values", [{}, {"duty_prompt": "Purpose"}])
def test_dictionary_input_returns_import_normalizer_result(mocker, values):
    normalized = {"duty_prompt": "Normalized prompt"}
    normalize = mocker.patch.object(
        model_consts, "normalize_imported_agent_prompt", return_value=normalized,
    )

    result = model_consts.ExportAndImportAgentInfo.normalize_business_prompt(values)

    normalize.assert_called_once_with(values)
    assert normalize.call_args.args[0] is values
    assert result is normalized


@pytest.mark.parametrize(
    "values",
    [None, "prompt", 0, [], (), UserDict({"duty_prompt": "Purpose"}), object()],
    ids=["null", "string", "integer", "list", "tuple", "mapping", "object"],
)
def test_non_dictionary_input_is_returned_unchanged(mocker, values):
    normalize = mocker.patch.object(model_consts, "normalize_imported_agent_prompt")

    result = model_consts.ExportAndImportAgentInfo.normalize_business_prompt(values)

    assert result is values
    normalize.assert_not_called()


@pytest.mark.parametrize(
    ("fields", "expected"),
    [
        ({}, None),
        ({"duty_prompt": None}, None),
        ({"duty_prompt": ""}, ""),
        ({"duty_prompt": " exact\n  prompt "}, " exact\n  prompt "),
        (
            {"duty_prompt": "Purpose", "constraint_prompt": "Rule", "few_shots_prompt": "Example"},
            "# Responsibilities\nPurpose\n\n# Constraints\nRule\n\n# Examples\nExample",
        ),
        ({"constraint_prompt": "Rule"}, "# Constraints\nRule"),
        ({"few_shots_prompt": "Example"}, "# Examples\nExample"),
        (
            {"duty_prompt": "Purpose", "constraint_prompt": " \n", "few_shots_prompt": None},
            "Purpose",
        ),
    ],
)
def test_model_validation_normalizes_prompt_without_mutating_input(agent_payload, fields, expected):
    agent_payload.update(fields)
    original = deepcopy(agent_payload)

    agent = model_consts.ExportAndImportAgentInfo.model_validate(agent_payload)

    assert agent.duty_prompt == expected
    assert agent.name == original["name"]
    assert agent_payload == original
    exported = agent.model_dump()
    assert "constraint_prompt" not in exported
    assert "few_shots_prompt" not in exported
    assert model_consts.ExportAndImportAgentInfo.model_validate(exported).model_dump() == exported


@pytest.mark.parametrize("values", [None, "prompt", 0, [], ()])
def test_model_validation_rejects_invalid_non_dictionary_input(values):
    with pytest.raises(ValidationError) as error:
        model_consts.ExportAndImportAgentInfo.model_validate(values)

    assert error.value.errors()[0]["type"] == "model_type"


def test_normalizer_preserves_existing_model_instance(mocker, agent_payload):
    agent = model_consts.ExportAndImportAgentInfo.model_validate(agent_payload)
    normalize = mocker.patch.object(model_consts, "normalize_imported_agent_prompt")

    assert model_consts.ExportAndImportAgentInfo.normalize_business_prompt(agent) is agent
    assert model_consts.ExportAndImportAgentInfo.model_validate(agent) is agent
    normalize.assert_not_called()
