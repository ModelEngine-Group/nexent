# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Old LLM payloads use frozen outlet storage; no alternate request/configuration format."""

from types import ModuleType
from unittest.mock import Mock

import pytest
from contracts.errors.exceptions import ModelOutletValidationError
from nexent.core.model_service.profiles.outlet_storage import encode_resolved_model_profile
from nexent.core.model_service.registry import model_service_references
from management.services.model import outlet_legacy as service
from management.services.model.outlet_migration import build_legacy_outlet_snapshot


def legacy_row(**changes):
    return {"model_id": 42, "tenant_id": "tenant", "model_type": "llm", "model_name": "custom-model",
        "model_factory": "custom", "base_url": "https://custom.invalid/v1", "display_name": "chosen",
        "temperature": 0, "extra_params": {"enable_thinking": False}, "max_output_tokens": 8192, **changes}


@pytest.fixture
def saved_row():
    profile = build_legacy_outlet_snapshot(legacy_row(), legacy_capability=None, migrated_at="controlled-time")
    return encode_resolved_model_profile(profile, registered_references=model_service_references())


def test_create_saves_complete_outlet_without_migration_badge(monkeypatch):
    database = ModuleType("management.db.model.outlets")
    database.create_resolved_model_record = Mock(return_value=43)
    catalog = ModuleType("configs.model_catalog_loader")
    catalog.resolve_reasoning_capability = Mock(return_value=None)
    monkeypatch.setitem(__import__("sys").modules, "management.db.model.outlets", database)
    monkeypatch.setitem(__import__("sys").modules, "configs.model_catalog_loader", catalog)
    assert service.create_legacy_llm_outlet(legacy_row(api_key="controlled-key"), "user", "tenant") == 43
    profile = database.create_resolved_model_record.call_args.args[0]
    assert profile.outlet_id is None and profile.connection.credential_ref.model_id is None
    assert profile.identity.tenant_id == "tenant"
    assert profile.parameter_values["temperature"] == 0
    assert profile.parameter_values["enable_thinking"] is False
    assert "migration" not in profile.provenance.provider_metadata
    assert "controlled-key" not in repr(profile.model_dump())


def test_old_partial_update_uses_saved_rules_and_preserves_key_omission(monkeypatch, saved_row):
    import management.services.model.profiles as profiles

    update = Mock(return_value={"config_revision": 2})
    monkeypatch.setattr(profiles, "update_model_outlet", update)
    monkeypatch.setattr(profiles, "get_model_profile_catalog", lambda: pytest.fail("Must not recompose saved outlet"))
    service.update_legacy_llm_outlet(saved_row, {"temperature": 0, "extra_params": {"enable_thinking": False}}, "user", "tenant")
    patch = update.call_args.args[1]
    assert patch.expected_revision == 1
    assert patch.parameter_values == {"temperature": 0, "enable_thinking": False}
    assert "api_key" not in patch.model_fields_set and "connection" not in patch.model_fields_set


def test_old_output_cap_update_keeps_distinct_request_default_and_context(monkeypatch, saved_row):
    import management.services.model.profiles as profiles

    update = Mock()
    monkeypatch.setattr(profiles, "update_model_outlet", update)
    service.update_legacy_llm_outlet(saved_row, {"max_output_tokens": 65536, "config_revision": 3}, "user", "tenant")
    patch = update.call_args.args[1]
    assert patch.context_limits.output_limit == 65536
    assert patch.parameter_values["max_output_tokens"] == 65536
    assert patch.expected_revision == 3


@pytest.mark.parametrize("change", [{"model_name": "another"}, {"model_factory": "another"}])
def test_old_identity_replacement_is_rejected(saved_row, change):
    with pytest.raises(ModelOutletValidationError) as error:
        service.update_legacy_llm_outlet(saved_row, change, "user", "tenant")
    assert error.value.category == "OUTLET_IDENTITY_IMMUTABLE"


def test_explicit_extra_false_zero_and_credential_clear_are_preserved(monkeypatch, saved_row):
    import management.services.model.profiles as profiles

    update = Mock()
    monkeypatch.setattr(profiles, "update_model_outlet", update)
    service.update_legacy_llm_outlet(saved_row, {"api_key": None,
        "extra_params": {"__custom__": {"options": {"flag": False, "count": 0}}}}, "user", "tenant")
    patch = update.call_args.args[1]
    assert patch.api_key is None and "api_key" in patch.model_fields_set
    assert patch.extra_api_parameters == [{"path": "/options/flag", "value": False}, {"path": "/options/count", "value": 0}]


def test_repair_keeps_record_identity_and_filters_foreign_tenant_fields(monkeypatch):
    import sys
    from copy import deepcopy

    database = ModuleType('management.db.model.outlets')
    captured = {}

    def repair(model_id, tenant_id, user_id, revision, construct, **kwargs):
        captured.update(model_id=model_id, tenant_id=tenant_id, user_id=user_id, revision=revision)
        return construct(deepcopy(original))

    database.repair_legacy_model_record = Mock(side_effect=repair)
    catalog = ModuleType('configs.model_catalog_loader')
    catalog.resolve_reasoning_capability = Mock(return_value=None)
    monkeypatch.setitem(sys.modules, database.__name__, database)
    monkeypatch.setitem(sys.modules, catalog.__name__, catalog)
    original = legacy_row(base_url='invalid', config_revision=3)
    before = deepcopy(original)
    profile, credential = service.update_legacy_llm_outlet(original, {
        'model_name': 'replacement', 'model_repo': 'private', 'base_url': 'https://fixed.invalid/v1',
        'api_key': 'controlled-key', 'tenant_id': 'foreign', 'model_id': 99,
    }, 'user', 'tenant')
    assert captured == {'model_id': 42, 'tenant_id': 'tenant', 'user_id': 'user', 'revision': 3}
    assert profile.outlet_id == 42 and profile.identity.tenant_id == 'tenant'
    assert profile.identity.request_model_id == 'private/replacement'
    assert profile.connection.base_url == 'https://fixed.invalid/v1'
    assert credential == 'controlled-key' and original == before
    catalog.resolve_reasoning_capability.assert_called_once_with('private/replacement', 'https://fixed.invalid/v1', 'custom')


@pytest.mark.parametrize('value', ['invalid', {'__custom__': []}])
def test_legacy_extra_parameter_shape_is_rejected_without_write(monkeypatch, saved_row, value):
    from management.services.model import profiles as model_profile_service

    update = Mock()
    monkeypatch.setattr(model_profile_service, 'update_model_outlet', update)
    with pytest.raises(ModelOutletValidationError):
        service.update_legacy_llm_outlet(saved_row, {'extra_params': value}, 'user', 'tenant')
    update.assert_not_called()
