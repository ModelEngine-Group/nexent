# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Explicit and inherited controls share the same preflight before writes."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from contracts.errors.exceptions import ModelOutletValidationError, RunModelControlsError
from management.services.model import run_controls


def request(**changes):
    values = dict(model_id=None, model_parameter_preferences={}, agent_id=7,
                  entrypoint=None, is_debug=False, version_no=None)
    values.update(changes)
    return SimpleNamespace(**values)


@pytest.mark.parametrize("explicit,current,expected", [(3, 9, 3), (None, 9, 9), (None, None, 0)])
def test_agent_lookup_uses_explicit_or_current_version(monkeypatch, explicit, current, expected):
    from management.db.agent import repository
    version = Mock(return_value=current)
    monkeypatch.setattr(repository, "query_current_version_no", version)
    lookup = Mock(return_value={"model_ids": [42]})
    assert run_controls._agent_record_for_run(request(version_no=explicit), "tenant", lookup) == {"model_ids": [42]}
    lookup.assert_called_once_with(agent_id=7, tenant_id="tenant", version_no=expected)
    assert version.call_count == (1 if explicit is None else 0)


def test_absent_selection_and_preferences_do_not_resolve_models(monkeypatch):
    selected = Mock(side_effect=AssertionError("No explicit model"))
    preflight = Mock(side_effect=AssertionError("No controls"))
    monkeypatch.setattr(run_controls, "validate_selected_model", selected)
    monkeypatch.setattr(run_controls, "preflight_turn_controls", preflight)
    run_controls.validate_agent_model_selection(request(), "tenant", Mock())
    run_controls.preflight_agent_turn_controls(request(), "tenant", Mock())
    selected.assert_not_called()
    preflight.assert_not_called()


@pytest.mark.parametrize("workbench", [False, True])
def test_preflight_resolves_native_agent_only_when_needed(monkeypatch, workbench):
    record = {"model_ids": [42]}
    lookup = Mock(return_value=record)
    check = Mock()
    monkeypatch.setattr(run_controls, "_agent_record_for_run", lookup)
    monkeypatch.setattr(run_controls, "preflight_turn_controls", check)
    value = request(model_id=42, entrypoint="workbench" if workbench else None)
    run_controls.preflight_agent_turn_controls(value, "tenant", Mock())
    check.assert_called_once_with(value, "tenant", None if workbench else record)
    assert lookup.call_count == (0 if workbench else 1)


@pytest.mark.parametrize("configured", [[], [42]])
def test_saved_preferences_inherit_agent_or_tenant_selection(monkeypatch, configured):
    from management.services.conversation import model_preferences
    from management.services.configuration.tenant.settings import tenant_config_manager
    value = request(_runtime_model_parameter_preferences={"42": {"temperature": 0}})
    default = Mock(return_value={"model_id": 42})
    monkeypatch.setattr(tenant_config_manager, "get_model_config", default)
    selected, validate = Mock(), Mock()
    monkeypatch.setattr(run_controls, "validate_selected_model", selected)
    monkeypatch.setattr(model_preferences, "validate_model_preferences", validate)
    run_controls.preflight_turn_controls(value, "tenant", {"model_ids": configured})
    selected.assert_called_once_with(42, "tenant")
    validate.assert_called_once_with({"42": {"temperature": 0}}, "tenant", allowed_model_ids=configured or None)
    assert default.call_count == (0 if configured else 1)
    assert value.model_parameter_preferences == {} and value.model_id is None
    validate.side_effect = ModelOutletValidationError("PARAMETER_UNKNOWN", "/retired")
    with pytest.raises(RunModelControlsError) as failure:
        run_controls.preflight_turn_controls(value, "tenant", {"model_ids": configured})
    assert failure.value.code == "model_controls_invalid"


@pytest.mark.parametrize("selected", [None, 42])
def test_creator_selection_copies_model_and_preserves_other_roots(monkeypatch, selected):
    from management.services.agent.preparation import run
    from management.services.model import run_bindings
    record = {"model_id": 42}
    source = Mock()
    root = SimpleNamespace(cite_name="creator_root_model")
    source.model_copy.return_value = root
    monkeypatch.setattr(run_controls, "validate_selected_model", Mock(return_value=record))
    factory, merge = Mock(return_value=source), Mock()
    monkeypatch.setattr(run_bindings, "create_model_config_from_record", factory)
    monkeypatch.setattr(run, "apply_root_model_preferences", merge)
    original = SimpleNamespace(cite_name="business")
    models, agent = [original], SimpleNamespace(model_name="business")
    preferences = {"42": {"temperature": 0}}
    assert run_controls.resolve_creator_model(models, agent, "tenant", selected, preferences, record) is record
    source.model_copy.assert_called_once_with(deep=True, update={"cite_name": "creator_root_model"})
    assert models == [original, root] and agent.model_name == "creator_root_model"
    merge.assert_called_once_with(models, agent, preferences)


def test_creator_without_new_record_requires_existing_root(monkeypatch):
    from management.services.agent.preparation import run
    merge = Mock()
    monkeypatch.setattr(run, "apply_root_model_preferences", merge)
    agent = SimpleNamespace(model_name="existing")
    models = [SimpleNamespace(cite_name="existing")]
    assert run_controls.resolve_creator_model(models, agent, "tenant", None, {}, None) == {}
    merge.assert_called_once_with(models, agent, {})
    with pytest.raises(RunModelControlsError) as failure:
        run_controls.resolve_creator_model([], agent, "tenant", None, {}, None)
    assert failure.value.code == "model_not_available"
