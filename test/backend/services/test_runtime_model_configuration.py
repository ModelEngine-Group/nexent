# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Runtime legacy commands keep the same resolved outlet format and revision rules."""

from unittest.mock import Mock

import pytest

from contracts.errors.exceptions import ModelOutletValidationError
from infrastructure.rdb import model_records, outlets
from nexent.core.model_service.compatibility.legacy_outlet import build_legacy_outlet_snapshot
from nexent.core.model_service.profiles.outlet_storage import encode_resolved_model_profile
from nexent.core.model_service.registry import model_service_references
from runtime.model import configuration


def row(**changes):
    return {"model_id": 42, "tenant_id": "tenant", "model_type": "llm", "model_name": "custom-model",
            "model_factory": "custom", "base_url": "https://custom.invalid/v1", "display_name": "chosen",
            "temperature": 0, "extra_params": {"enable_thinking": False}, "max_output_tokens": 8192, **changes}


def test_runtime_create_persists_resolved_llm_without_legacy_row(monkeypatch):
    create = Mock(return_value=43)
    old = Mock(side_effect=AssertionError("LLM must not use legacy storage"))
    monkeypatch.setattr(outlets, "create_resolved_model_record", create)
    monkeypatch.setattr(configuration, "create_model_record", old)
    monkeypatch.setattr("configs.model_catalog_loader.resolve_reasoning_capability", Mock(return_value=None))
    assert configuration.create_model_configuration(row(api_key="runtime-secret"), "owner", "tenant") == 43
    profile, user_id, tenant_id = create.call_args.args
    assert (user_id, tenant_id) == ("owner", "tenant")
    assert profile.outlet_id is None and profile.identity.tenant_id == "tenant"
    assert profile.parameter_values["temperature"] == 0 and profile.parameter_values["enable_thinking"] is False
    assert "migration" not in profile.provenance.provider_metadata
    assert "runtime-secret" not in profile.model_dump_json()
    assert create.call_args.kwargs["api_key"] == "runtime-secret"
    old.assert_not_called()


def test_runtime_update_uses_saved_rules_and_revision_without_replacing_credentials(monkeypatch):
    profile = build_legacy_outlet_snapshot(row(), legacy_capability=None, migrated_at="controlled-time")
    record = encode_resolved_model_profile(profile, registered_references=model_service_references())
    record.update(api_key="keep-secret", http_headers={"X-Workspace": "workspace"})
    lookup = Mock(return_value=record)
    update = Mock(return_value=2)
    monkeypatch.setattr(configuration, "get_model_by_model_id", lookup)
    monkeypatch.setattr(model_records, "get_model_by_model_id", lookup)
    monkeypatch.setattr(outlets, "get_resolved_model_record", Mock(return_value=profile))
    monkeypatch.setattr(outlets, "update_resolved_model_record", update)
    monkeypatch.setattr(outlets, "has_model_outlet_credential", Mock(return_value=True))
    result = configuration.update_model_configuration(42, {"temperature": 0.3}, "owner", "tenant")
    proposed, expected_revision, user_id, tenant_id = update.call_args.args
    assert (expected_revision, user_id, tenant_id) == (1, "owner", "tenant")
    assert proposed.parameter_values["temperature"] == 0.3
    assert "api_key" not in update.call_args.kwargs and "http_headers" not in update.call_args.kwargs
    assert result["config_revision"] == 2 and result["http_header_names"] == ["X-Workspace"]


def test_runtime_update_missing_tenant_model_cannot_write(monkeypatch):
    lookup = Mock(return_value=None)
    old = Mock()
    monkeypatch.setattr(configuration, "get_model_by_model_id", lookup)
    monkeypatch.setattr(configuration, "update_model_record", old)
    with pytest.raises(LookupError, match="MODEL_OUTLET_NOT_FOUND"):
        configuration.update_model_configuration(42, {"display_name": "renamed"}, "owner", "tenant")
    lookup.assert_called_once_with(42, tenant_id="tenant")
    old.assert_not_called()


def test_runtime_non_llm_configuration_keeps_existing_storage(monkeypatch):
    create, update = Mock(return_value=True), Mock(return_value=True)
    monkeypatch.setattr(configuration, "create_model_record", create)
    monkeypatch.setattr(configuration, "update_model_record", update)
    monkeypatch.setattr(configuration, "get_model_by_model_id", Mock(return_value={"model_type": "embedding"}))
    data = {"model_type": "embedding", "display_name": "vectors"}
    assert configuration.create_model_configuration(data, "owner", "tenant") is True
    assert configuration.update_model_configuration(42, {"display_name": "renamed"}, "owner", "tenant") is True
    create.assert_called_once_with(data, "owner", "tenant")
    update.assert_called_once_with(42, {"display_name": "renamed"}, "owner", "tenant")
