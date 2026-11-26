# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Traditional UT for section validation and partial configuration merges."""

from copy import deepcopy

import pytest
from pydantic import ValidationError

from contracts.tag import AuthenticatedCaller
from services import nl2agent_configuration as service


@pytest.fixture
def collaboration_boundary(mocker):
    current = {2: 1, 3: None}
    mocker.patch.object(service, "_relations", return_value=current)
    visible = mocker.patch.object(service, "_visible_collaborators", return_value=[{"agent_id": 2}, {"agent_id": 4}])
    validate = mocker.patch.object(service, "_validate_agent_relationships", side_effect=lambda request, tenant: [
        item.model_dump() for item in request.related_agents
    ])
    persist = mocker.patch.object(service, "update_related_agents", return_value=True)
    return current, visible, validate, persist


def test_remove_only_collaboration_skips_candidate_directory(collaboration_boundary):
    current, visible, validate, persist = collaboration_boundary
    visible.side_effect = ConnectionError("Candidate directory must not be needed for removal")
    service._update_collaboration(AuthenticatedCaller("user", "tenant"), 1, {"remove": [2]})
    visible.assert_not_called()
    validate.assert_called_once()
    assert validate.call_args.args[1] == "tenant"
    persist.assert_called_once_with(1, "tenant", "user", related_agents=[{"agent_id": 3, "version_no": None}],
                                    expected_relations=current)
    assert current == {2: 1, 3: None}


@pytest.mark.parametrize("changes,expected", [
    ({"add": [{"agent_id": 4}]}, [{"agent_id": 2, "version_no": 1}, {"agent_id": 3, "version_no": None},
                                  {"agent_id": 4, "version_no": None}]),
    ({"add": [{"agent_id": 2, "version_no": 5}]}, [{"agent_id": 2, "version_no": 5},
                                                   {"agent_id": 3, "version_no": None}]),
    ({"add": [{"agent_id": 4}], "remove": [2]}, [{"agent_id": 3, "version_no": None},
                                                  {"agent_id": 4, "version_no": None}]),
])
def test_added_or_replaced_collaboration_checks_visibility(collaboration_boundary, changes, expected):
    current, visible, validate, persist = collaboration_boundary
    caller = AuthenticatedCaller("user", "tenant")
    service._update_collaboration(caller, 1, changes)
    visible.assert_called_once_with(caller, 1)
    validate.assert_called_once()
    persist.assert_called_once_with(1, "tenant", "user", related_agents=expected, expected_relations=current)


def test_invisible_collaboration_is_rejected_before_validation_or_write(collaboration_boundary):
    _, visible, validate, persist = collaboration_boundary
    with pytest.raises(service.ConfigurationError, match="invalid_collaborators"):
        service._update_collaboration(AuthenticatedCaller("user", "tenant"), 1, {"add": [{"agent_id": 6}]})
    visible.assert_called_once()
    validate.assert_not_called()
    persist.assert_not_called()


@pytest.mark.parametrize("changes", [{}, {"add": [], "remove": []},
    {"add": [{"agent_id": 2}, {"agent_id": 2}]}, {"add": [{"agent_id": 2}], "remove": [2]},
])
def test_invalid_collaboration_changes_do_not_write(collaboration_boundary, changes):
    _, _, validate, persist = collaboration_boundary
    with pytest.raises(service.ConfigurationError, match="invalid_collaborators"):
        service._update_collaboration(AuthenticatedCaller("user", "tenant"), 1, changes)
    validate.assert_not_called()
    persist.assert_not_called()


def test_remove_only_collaboration_keeps_relation_validation(collaboration_boundary):
    _, _, validate, persist = collaboration_boundary
    validate.side_effect = ValueError("Invalid remaining relationship")
    with pytest.raises(ValueError, match="Invalid remaining relationship"):
        service._update_collaboration(AuthenticatedCaller("user", "tenant"), 1, {"remove": [2]})
    persist.assert_not_called()


def test_remove_only_collaboration_keeps_optimistic_consistency_check(collaboration_boundary):
    current, _, validate, persist = collaboration_boundary
    persist.return_value = False
    with pytest.raises(service.ConfigurationError, match="configuration_changed"):
        service._update_collaboration(AuthenticatedCaller("user", "tenant"), 1, {"remove": [2]})
    validate.assert_called_once()
    assert persist.call_args.kwargs["expected_relations"] == current


@pytest.mark.asyncio
async def test_remove_only_collaboration_still_requires_draft_edit(mocker):
    async def blocking(_task, function, *args, **kwargs):
        kwargs.pop("lane", None)
        return function(*args, **kwargs)
    mocker.patch.object(service, "run_blocking", blocking)
    authorize = mocker.patch.object(service, "require_agent_draft_edit", side_effect=PermissionError("read only"))
    visible = mocker.patch.object(service, "_visible_collaborators")
    persist = mocker.patch.object(service, "update_related_agents")
    with pytest.raises(PermissionError, match="read only"):
        await service.save_configuration(AuthenticatedCaller("user", "tenant"), 1, "collaborators", {"remove": [2]})
    authorize.assert_called_once_with(agent_id=1, tenant_id="tenant", user_id="user")
    visible.assert_not_called()
    persist.assert_not_called()


@pytest.mark.parametrize("unrelated", [
    {"guardrail_config": {"rules": [{"name": "old", "pattern": "secret", "severity": "error"}]}},
    {"max_final_rounds": 0},
    {"critical_events": ["unknown-event"]},
])
def test_advanced_read_ignores_unrelated_verification_errors(unrelated):
    caller = AuthenticatedCaller("user", "tenant")
    draft = {
        "max_steps": 12, "provide_run_summary": True, "allow_chat_metadata": False,
        "enable_protocol_repair_retry": True, "verification_config": {"enabled": True, **unrelated},
    }
    before = deepcopy(draft)
    assert service._read_section(caller, 1, "advanced", draft) == {
        "max_steps": 12, "provide_run_summary": True, "allow_chat_metadata": False,
        "enable_protocol_repair_retry": True, "self_verification_enabled": True,
    }
    assert draft == before


@pytest.mark.parametrize("verification,expected", [
    (None, False), ({}, False), ({"enabled": False}, False), ({"enabled": True}, True),
    ({"enabled": "true"}, True), ({"enabled": "false"}, False),
])
def test_advanced_read_preserves_enabled_defaults_and_boolean_conversion(verification, expected):
    result = service._read_section(AuthenticatedCaller("user", "tenant"), 1, "advanced",
                                   {"verification_config": verification})
    assert result["self_verification_enabled"] is expected


def test_advanced_read_still_rejects_invalid_requested_enabled_value():
    with pytest.raises(ValidationError):
        service._read_section(AuthenticatedCaller("user", "tenant"), 1, "advanced",
                              {"verification_config": {"enabled": "not-a-boolean"}})


def test_guardrail_read_still_validates_complete_guardrail_rules():
    with pytest.raises(ValidationError):
        service._read_section(AuthenticatedCaller("user", "tenant"), 1, "guardrails", {
            "verification_config": {"guardrail_config": {
                "rules": [{"name": "old", "pattern": "secret", "severity": "error"}],
            }},
        })


@pytest.mark.parametrize("section,changes", [
    ("advanced", {"max_steps": 0}),
    ("advanced", {"max_steps": 5, "prompt": "unrequested"}),
    ("advanced", {"self_verification_enabled": "true"}),
    ("guardrails", {"upsert_rules": [{"name": "bad", "pattern": "["}]}),
    ("model", {"model_ids": [1], "model_params_override": {}}),
])
async def test_configuration_rejects_invalid_inputs_before_read_or_write(mocker, section, changes):
    draft = mocker.patch.object(service, "_draft")
    update = mocker.patch.object(service, "update_agent_draft_fields")
    with pytest.raises(ValidationError):
        await service.save_configuration(AuthenticatedCaller("user", "tenant"), 1, section, changes)
    draft.assert_not_called()
    update.assert_not_called()


def test_guardrail_and_self_verification_updates_preserve_one_another(mocker):
    caller = AuthenticatedCaller("user", "tenant")
    draft = {"verification_config": {"enabled": True, "max_final_rounds": 4}, "group_ids": "[]"}
    save = mocker.patch.object(service, "update_agent_draft_fields", return_value=1)
    assert service._apply(caller, 1, "guardrails", {"enabled": True}, draft) == ["verification_config"]
    first = save.call_args.args[2]["verification_config"]
    assert first["enabled"] and first["max_final_rounds"] == 4 and first["guardrail_config"]["enabled"]
    assert service._apply(caller, 1, "advanced", {"self_verification_enabled": False},
                          {**draft, "verification_config": first}) == ["verification_config"]
    second = save.call_args.args[2]["verification_config"]
    assert second == {**first, "enabled": False}
    assert save.call_args.kwargs["expected_fields"]["verification_config"] == first
